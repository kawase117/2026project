from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import mannwhitneyu

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import COINS_PER_GAME, load_data as base_load_data

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_machine_category_axis_deepdive"
X_DDS = {4, 7, 14, 17, 24, 27}
MIN_GAMES = 500
MIN_N_XDDS = 20


def _calc_payout_rate(games_sum: pd.Series, diff_sum: pd.Series) -> pd.Series:
    return (games_sum * COINS_PER_GAME + diff_sum) / (games_sum * COINS_PER_GAME) * 100


def load_data_with_category(db_path: Path) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= MIN_GAMES].copy()
    if df.empty:
        return df

    with sqlite3.connect(db_path) as conn:
        master = pd.read_sql_query(
            """
            SELECT
                machine_name_normalized AS machine_name,
                COALESCE(jug_flag, 0) AS jug_flag,
                COALESCE(hana_flag, 0) AS hana_flag,
                COALESCE(oki_flag, 0) AS oki_flag,
                COALESCE(bt_flag, 0) AS bt_flag
            FROM machine_master
            """,
            conn,
        )

    df = df.merge(master, on="machine_name", how="left")
    for col in ["jug_flag", "hana_flag", "oki_flag", "bt_flag"]:
        df[col] = df[col].fillna(0).astype(int)

    def categorize(row: pd.Series) -> str:
        if row.get("jug_flag", 0) == 1:
            return "jug"
        if row.get("hana_flag", 0) == 1:
            return "hana"
        if row.get("oki_flag", 0) == 1:
            return "oki"
        if row.get("bt_flag", 0) == 1:
            return "bt"
        return "other"

    df["category"] = df.apply(categorize, axis=1)
    df["dd"] = df["date"].dt.day
    df["is_xdds"] = df["dd"].isin(X_DDS)
    df["payout"] = _calc_payout_rate(df["games_normalized"], df["diff_coins_normalized"])
    return df


def branch_e_category_xdds(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "category",
                "xdds_payout",
                "non_xdds_payout",
                "delta",
                "n_xdds_dates",
                "n_non_xdds_dates",
                "first_half_delta",
                "second_half_delta",
                "same_direction",
                "stable",
            ]
        )

    all_dates = sorted(pd.to_datetime(df["date"]).unique())
    cutoff = all_dates[len(all_dates) // 2]

    rows: list[dict[str, object]] = []
    for cat in ["jug", "bt", "other", "hana", "oki"]:
        sub = df[df["category"] == cat].copy()
        if sub.empty:
            continue

        daily = sub.groupby(["date", "is_xdds"], as_index=False)["payout"].mean()
        xdds_mean = daily.loc[daily["is_xdds"], "payout"].mean()
        non_mean = daily.loc[~daily["is_xdds"], "payout"].mean()
        delta = xdds_mean - non_mean

        first = sub[sub["date"] < cutoff].copy()
        second = sub[sub["date"] >= cutoff].copy()
        first_daily = first.groupby(["date", "is_xdds"], as_index=False)["payout"].mean()
        second_daily = second.groupby(["date", "is_xdds"], as_index=False)["payout"].mean()

        first_delta = first_daily.loc[first_daily["is_xdds"], "payout"].mean() - first_daily.loc[
            ~first_daily["is_xdds"], "payout"
        ].mean()
        second_delta = second_daily.loc[second_daily["is_xdds"], "payout"].mean() - second_daily.loc[
            ~second_daily["is_xdds"], "payout"
        ].mean()
        same_direction = (
            not pd.isna(first_delta)
            and not pd.isna(second_delta)
            and float(first_delta) * float(second_delta) > 0
        )
        stable = same_direction and abs(float(delta)) > 0.5

        rows.append(
            {
                "category": cat,
                "xdds_payout": float(xdds_mean) if pd.notna(xdds_mean) else float("nan"),
                "non_xdds_payout": float(non_mean) if pd.notna(non_mean) else float("nan"),
                "delta": float(delta) if pd.notna(delta) else float("nan"),
                "n_xdds_dates": int(daily["is_xdds"].sum()),
                "n_non_xdds_dates": int((~daily["is_xdds"]).sum()),
                "first_half_delta": float(first_delta) if pd.notna(first_delta) else float("nan"),
                "second_half_delta": float(second_delta) if pd.notna(second_delta) else float("nan"),
                "same_direction": same_direction,
                "stable": stable,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "category",
            "xdds_payout",
            "non_xdds_payout",
            "delta",
            "n_xdds_dates",
            "n_non_xdds_dates",
            "first_half_delta",
            "second_half_delta",
            "same_direction",
            "stable",
        ],
    ).sort_values("delta", ascending=False).reset_index(drop=True)


def branch_f_other_machine_xdds(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "n_xdds",
                "n_non_xdds",
                "xdds_payout",
                "non_xdds_payout",
                "delta",
                "p_value",
                "direction",
                "significant",
                "first_half_delta",
                "second_half_delta",
                "same_direction",
                "stable",
            ]
        )

    other_df = df[df["category"] == "other"].copy()
    all_dates = sorted(pd.to_datetime(df["date"]).unique())
    cutoff = all_dates[len(all_dates) // 2]

    rows: list[dict[str, object]] = []
    for machine_name, sub in other_df.groupby("machine_name", sort=True):
        xdds_vals = sub.loc[sub["is_xdds"], "payout"].to_numpy()
        non_vals = sub.loc[~sub["is_xdds"], "payout"].to_numpy()
        if len(xdds_vals) < MIN_N_XDDS or len(non_vals) < 10:
            continue

        _, p_value = mannwhitneyu(xdds_vals, non_vals, alternative="two-sided")
        xdds_mean = float(xdds_vals.mean())
        non_mean = float(non_vals.mean())
        delta = xdds_mean - non_mean
        direction = "xdds_higher" if delta > 0 else "non_higher"

        first = sub[sub["date"] < cutoff].copy()
        second = sub[sub["date"] >= cutoff].copy()
        first_delta = float("nan")
        second_delta = float("nan")
        if len(first) > 10:
            first_x = first.loc[first["is_xdds"], "payout"]
            first_n = first.loc[~first["is_xdds"], "payout"]
            if not first_x.empty and not first_n.empty:
                first_delta = float(first_x.mean() - first_n.mean())
        if len(second) > 10:
            second_x = second.loc[second["is_xdds"], "payout"]
            second_n = second.loc[~second["is_xdds"], "payout"]
            if not second_x.empty and not second_n.empty:
                second_delta = float(second_x.mean() - second_n.mean())

        same_direction = (
            not pd.isna(first_delta)
            and not pd.isna(second_delta)
            and first_delta * second_delta > 0
        )
        stable = same_direction and p_value < 0.05

        rows.append(
            {
                "machine_name": machine_name,
                "n_xdds": int(len(xdds_vals)),
                "n_non_xdds": int(len(non_vals)),
                "xdds_payout": xdds_mean,
                "non_xdds_payout": non_mean,
                "delta": delta,
                "p_value": float(p_value),
                "direction": direction,
                "significant": bool(p_value < 0.05),
                "first_half_delta": first_delta,
                "second_half_delta": second_delta,
                "same_direction": same_direction,
                "stable": stable,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "machine_name",
            "n_xdds",
            "n_non_xdds",
            "xdds_payout",
            "non_xdds_payout",
            "delta",
            "p_value",
            "direction",
            "significant",
            "first_half_delta",
            "second_half_delta",
            "same_direction",
            "stable",
        ],
    ).sort_values(["delta", "xdds_payout"], ascending=[False, False]).reset_index(drop=True)


def _fmt(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        if isinstance(value, int):
            return str(value)
        return f"{value:.{digits}f}"
    return str(value)


def build_report(branch_e: pd.DataFrame, branch_f: pd.DataFrame) -> str:
    lines = [
        "# みとや machine_category 軸 DEEPDIVE",
        "",
        "Branch E は `jug / hana / oki / bt / other` の5分類で集計し、",
        "`other` は `jug/hana/oki/bt` のいずれにも該当しない機種群を表す。",
        "AT機の多くは `other` に入るため、`other = AT機` ではない点に注意。",
        "",
        "## Branch E: カテゴリ × X_DDS 効果",
        "| category | xdds_payout | non_xdds_payout | delta | stable |",
        "|---|---:|---:|---:|---|",
    ]
    if branch_e.empty:
        lines.append("該当なし")
    else:
        for _, row in branch_e.iterrows():
            lines.append(
                f"| {row['category']} | {_fmt(row['xdds_payout'])} | {_fmt(row['non_xdds_payout'])} | "
                f"{_fmt(row['delta'])} | {_fmt(bool(row['stable']))} |"
            )

    stable = branch_f[branch_f["stable"]].copy() if not branch_f.empty else branch_f
    lines.extend(
        [
            "",
            "## Branch F: other群 機種別 X_DDS 効果 (stable のみ)",
            "| machine_name | xdds_payout | non_xdds_payout | delta | p_value | stable |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    if stable.empty:
        lines.append("該当なし")
    else:
        for _, row in stable.iterrows():
            lines.append(
                f"| {row['machine_name']} | {_fmt(row['xdds_payout'])} | {_fmt(row['non_xdds_payout'])} | "
                f"{_fmt(row['delta'])} | {_fmt(row['p_value'], 4)} | {_fmt(bool(row['stable']))} |"
            )

    lines.extend(["", "## Branch F 全件サマリ"])
    total = len(branch_f)
    significant = int(branch_f["significant"].sum()) if not branch_f.empty else 0
    stable_count = int(branch_f["stable"].sum()) if not branch_f.empty else 0
    top5 = branch_f[(branch_f["stable"]) & (branch_f["direction"] == "xdds_higher")].head(5)
    lines.extend(
        [
            f"- total: {total} 機種",
            f"- significant (p<0.05): {significant} 機種",
            f"- stable (sig + same_direction): {stable_count} 機種",
            "- xdds_higher かつ stable: "
            + (", ".join(top5["machine_name"].tolist()) if not top5.empty else "該当なし"),
        ]
    )
    return "\n".join(lines) + "\n"


def save_outputs(branch_e: pd.DataFrame, branch_f: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    branch_e.to_csv(output_dir / "branch_e.csv", index=False, encoding="utf-8-sig")
    branch_f.to_csv(output_dir / "branch_f.csv", index=False, encoding="utf-8-sig")
    branch_f[branch_f["stable"]].to_csv(output_dir / "branch_f_stable.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(build_report(branch_e, branch_f), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data_with_category(args.db_path)
    branch_e = branch_e_category_xdds(df)
    branch_f = branch_f_other_machine_xdds(df)
    save_outputs(branch_e, branch_f, args.output_dir)
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date() if not df.empty else 'NaT'}")
    print(f"branch_f_rows={len(branch_f)}")


if __name__ == "__main__":
    main()
