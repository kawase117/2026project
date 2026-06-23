from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import (  # noqa: E402
    COINS_PER_GAME,
    WINDOW_MONTHS,
    assign_period,
    load_data as base_load_data,
)
from eda.mitoya_machinename_q5_backtest import build_training_table  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_machinename_axis_eda"
X_DDS = {4, 7, 14, 17, 24, 27}
MIN_GAMES = 1000
MIN_N_XDDS = 20


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    if df.empty:
        return df
    if "period" not in df.columns:
        df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["is_xdds"] = df["date"].dt.day.isin(X_DDS)
    return df


def load_machine_master(db_path: Path) -> pd.DataFrame:
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
    return master


def _calc_payout_rate(games_sum: pd.Series, diff_sum: pd.Series) -> pd.Series:
    return (games_sum * COINS_PER_GAME + diff_sum) / (games_sum * COINS_PER_GAME) * 100


def _classify_category_frame(machine_master: pd.DataFrame) -> pd.DataFrame:
    out = machine_master.copy()

    def _cat(row: pd.Series) -> str:
        if int(row.get("jug_flag", 0) or 0) == 1:
            return "jug"
        if int(row.get("hana_flag", 0) or 0) == 1:
            return "hana"
        if int(row.get("oki_flag", 0) or 0) == 1:
            return "oki"
        if int(row.get("bt_flag", 0) or 0) == 1:
            return "bt"
        return "other"

    out["category"] = out.apply(_cat, axis=1)
    return out[["machine_name", "category"]].drop_duplicates()


def branch_a_q5_persistence(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "period_train",
                "period_test",
                "q5_payout_mean",
                "q1_payout_mean",
                "all_payout_mean",
                "q5_beat_all_rate",
            ]
        )
    if "period" not in work.columns:
        if not pd.api.types.is_datetime64_any_dtype(work["date"]):
            work["date"] = pd.to_datetime(work["date"])
        work["period"] = assign_period(work["date"], WINDOW_MONTHS)
    training_table = build_training_table(work)
    periods = sorted(training_table["period"].unique())
    rows: list[dict[str, object]] = []

    for period_train, period_test in zip(periods[:-1], periods[1:], strict=True):
        train = training_table[training_table["period"] == period_train].copy()
        test = training_table[training_table["period"] == period_test].copy()
        qmax = train["quintile"].max()
        qmin = train["quintile"].min()
        q5_names = set(train.loc[train["quintile"] == qmax, "machine_name"])
        q1_names = set(train.loc[train["quintile"] == qmin, "machine_name"])

        q5_df = test[test["machine_name"].isin(q5_names)].copy()
        q1_df = test[test["machine_name"].isin(q1_names)].copy()
        all_mean = test["payout_rate"].mean() if not test.empty else float("nan")
        q5_beat_all_rate = float("nan")
        if not q5_df.empty and pd.notna(all_mean):
            q5_beat_all_rate = (q5_df["payout_rate"] > all_mean).mean()

        rows.append(
            {
                "period_train": period_train,
                "period_test": period_test,
                "q5_payout_mean": q5_df["payout_rate"].mean(),
                "q1_payout_mean": q1_df["payout_rate"].mean(),
                "all_payout_mean": all_mean,
                "q5_beat_all_rate": q5_beat_all_rate,
                "q5_n_machines": int(len(q5_df)),
                "q1_n_machines": int(len(q1_df)),
                "all_n_machines": int(len(test)),
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "period_train",
            "period_test",
            "q5_payout_mean",
            "q1_payout_mean",
            "all_payout_mean",
            "q5_beat_all_rate",
            "q5_n_machines",
            "q1_n_machines",
            "all_n_machines",
        ],
    )


def branch_b_stability(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "period",
                "q5_diff_std_median",
                "q1_diff_std_median",
                "all_diff_std_median",
            ]
        )
    if "period" not in work.columns:
        if not pd.api.types.is_datetime64_any_dtype(work["date"]):
            work["date"] = pd.to_datetime(work["date"])
        work["period"] = assign_period(work["date"], WINDOW_MONTHS)

    period_machine = (
        work.groupby(["period", "machine_name"], as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            diff_std=("diff_coins_normalized", lambda s: s.std(ddof=0)),
        )
    )
    period_machine["payout_rate"] = _calc_payout_rate(period_machine["games_sum"], period_machine["diff_sum"])
    period_machine["quintile"] = period_machine.groupby("period")["diff_sum"].transform(
        lambda x: pd.qcut(x, 5, labels=False, duplicates="drop") + 1
    )

    rows: list[dict[str, object]] = []
    for period, group in period_machine.groupby("period", sort=True):
        qmax = group["quintile"].max()
        qmin = group["quintile"].min()
        q5_std = group.loc[group["quintile"] == qmax, "diff_std"].median()
        q1_std = group.loc[group["quintile"] == qmin, "diff_std"].median()
        all_std = group["diff_std"].median()
        rows.append(
            {
                "period": period,
                "q5_diff_std_median": q5_std,
                "q1_diff_std_median": q1_std,
                "all_diff_std_median": all_std,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "period",
            "q5_diff_std_median",
            "q1_diff_std_median",
            "all_diff_std_median",
        ],
    )


def branch_c_xdds_cross(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "xdds_payout",
                "non_xdds_payout",
                "lift",
                "n_xdds",
                "n_non_xdds",
            ]
        )
    if not pd.api.types.is_datetime64_any_dtype(work["date"]):
        work["date"] = pd.to_datetime(work["date"])
    work["is_xdds"] = work["date"].dt.day.isin(X_DDS)
    work["payout_rate"] = _calc_payout_rate(work["games_normalized"], work["diff_coins_normalized"])

    xdds = (
        work[work["is_xdds"]]
        .groupby("machine_name", as_index=False)
        .agg(
            xdds_payout=("payout_rate", "mean"),
            n_xdds=("date", "count"),
        )
    )
    non_xdds = (
        work[~work["is_xdds"]]
        .groupby("machine_name", as_index=False)
        .agg(
            non_xdds_payout=("payout_rate", "mean"),
            n_non_xdds=("date", "count"),
        )
    )
    out = xdds.merge(non_xdds, on="machine_name", how="outer")
    out["lift"] = out["xdds_payout"] - out["non_xdds_payout"]
    out = out[(out["n_xdds"].fillna(0) >= MIN_N_XDDS) & (out["n_non_xdds"].fillna(0) > 0)].copy()
    return out.sort_values(["lift", "xdds_payout"], ascending=[False, False]).reset_index(drop=True)


def branch_d_category(df: pd.DataFrame, machine_master: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "category",
                "n_machines",
                "q5_entry_rate",
                "avg_payout",
                "q5_avg_payout",
            ]
        )
    if "period" not in work.columns:
        if not pd.api.types.is_datetime64_any_dtype(work["date"]):
            work["date"] = pd.to_datetime(work["date"])
        work["period"] = assign_period(work["date"], WINDOW_MONTHS)

    training_table = build_training_table(work)
    category_map = _classify_category_frame(machine_master)
    table = training_table.merge(category_map, on="machine_name", how="left")
    table["category"] = table["category"].fillna("other")
    table["is_q5"] = table.groupby("period")["quintile"].transform(lambda x: x == x.max())

    rows: list[dict[str, object]] = []
    for category, group in table.groupby("category", sort=True):
        total_rows = len(group)
        q5_rows = group["is_q5"].sum()
        q5_group = group[group["is_q5"]]
        rows.append(
            {
                "category": category,
                "n_machines": int(group["machine_name"].nunique()),
                "q5_entry_rate": float(q5_rows / total_rows) if total_rows else float("nan"),
                "avg_payout": group["payout_rate"].mean(),
                "q5_avg_payout": q5_group["payout_rate"].mean(),
                "n_machine_periods": int(total_rows),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "category",
            "n_machines",
            "q5_entry_rate",
            "avg_payout",
            "q5_avg_payout",
            "n_machine_periods",
        ],
    ).sort_values(["q5_entry_rate", "avg_payout"], ascending=[False, False]).reset_index(drop=True)


def build_report(results: dict[str, pd.DataFrame]) -> str:
    def _fmt(value: object, digits: int = 2) -> str:
        if value is None or pd.isna(value):
            return ""
        if isinstance(value, (int, float)):
            return f"{value:.{digits}f}" if isinstance(value, float) else str(value)
        return str(value)

    branch_a = results["branch_a"]
    branch_b = results["branch_b"]
    branch_c = results["branch_c"]
    branch_d = results["branch_d"]

    lines = [
        "# みとや machine_name 軸 EDA",
        "",
        "Branch D の `other` は `jug/hana/oki/bt` のいずれにも該当しない機種をまとめたカテゴリで、"
        "AT機の多くを含む。`other = AT機` ではない点に注意。",
        "",
        "## Branch A: Q5継続率",
    ]
    if branch_a.empty:
        lines.append("該当なし")
    else:
        lines.extend(
            [
                "| period_train | period_test | q5_payout_mean | q1_payout_mean | all_payout_mean | q5_beat_all_rate |",
                "|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for _, row in branch_a.iterrows():
            lines.append(
                f"| {row['period_train']} | {row['period_test']} | {_fmt(row['q5_payout_mean'])} | "
                f"{_fmt(row['q1_payout_mean'])} | {_fmt(row['all_payout_mean'])} | {_fmt(row['q5_beat_all_rate'], 3)} |"
            )

    lines.extend(["", "## Branch B: 安定性"])
    if branch_b.empty:
        lines.append("該当なし")
    else:
        lines.extend(
            [
                "| period | q5_diff_std_median | q1_diff_std_median | all_diff_std_median |",
                "|---:|---:|---:|---:|",
            ]
        )
        for _, row in branch_b.iterrows():
            lines.append(
                f"| {row['period']} | {_fmt(row['q5_diff_std_median'])} | "
                f"{_fmt(row['q1_diff_std_median'])} | {_fmt(row['all_diff_std_median'])} |"
            )

    lines.extend(["", "## Branch C: X_DDS × 機種名 TOP10"])
    if branch_c.empty:
        lines.append("該当なし")
    else:
        lines.extend(
            [
                "| rank | machine_name | xdds_payout | non_xdds_payout | lift | n_xdds | n_non_xdds |",
                "|---:|---|---:|---:|---:|---:|---:|",
            ]
        )
        for idx, row in enumerate(branch_c.head(10).itertuples(index=False), start=1):
            lines.append(
                f"| {idx} | {row.machine_name} | {_fmt(row.xdds_payout)} | {_fmt(row.non_xdds_payout)} | "
                f"{_fmt(row.lift)} | {_fmt(row.n_xdds, 0)} | {_fmt(row.n_non_xdds, 0)} |"
            )

    lines.extend(["", "## Branch D: カテゴリ別 Q5傾向"])
    if branch_d.empty:
        lines.append("該当なし")
    else:
        lines.extend(
            [
                "| category | n_machines | q5_entry_rate | avg_payout | q5_avg_payout |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for _, row in branch_d.iterrows():
            lines.append(
                f"| {row['category']} | {row['n_machines']} | {_fmt(row['q5_entry_rate'], 3)} | "
                f"{_fmt(row['avg_payout'])} | {_fmt(row['q5_avg_payout'])} |"
            )

    return "\n".join(lines) + "\n"


def save_outputs(results: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, df in results.items():
        df.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(build_report(results), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    master = load_machine_master(args.db_path)
    results = {
        "branch_a": branch_a_q5_persistence(df),
        "branch_b": branch_b_stability(df),
        "branch_c": branch_c_xdds_cross(df),
        "branch_d": branch_d_category(df, master),
    }
    save_outputs(results, args.output_dir)
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date() if not df.empty else 'NaT'}")
    print(f"branch_c_rows={len(results['branch_c'])}")


if __name__ == "__main__":
    main()
