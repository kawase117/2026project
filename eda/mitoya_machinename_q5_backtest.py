from __future__ import annotations

import argparse
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
    quintile,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_machinename_q5_backtest"
MIN_GAMES = 1000
X_DDS = {4, 7, 14, 17, 24, 27}

SUMMARY_COLUMNS = [
    "period_train",
    "period_test",
    "Q5_avg_diff",
    "Q5_payout_rate",
    "Q5_win_rate",
    "Q5_n_machine_days",
    "Q1_avg_diff",
    "Q1_payout_rate",
    "Q1_win_rate",
    "Q1_n_machine_days",
    "All_avg_diff",
    "All_payout_rate",
    "All_win_rate",
    "All_n_machine_days",
    "Q5_vs_All_diff",
    "Q5_vs_Q1_diff",
]


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["is_xdds"] = df["date"].dt.day.isin(X_DDS)
    return df


def build_training_table(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby(["period", "machine_name"], as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
        )
    )
    if agg.empty:
        agg["payout_rate"] = pd.Series(dtype=float)
        agg["quintile"] = pd.Series(dtype=float)
        return agg
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    agg["quintile"] = quintile(agg, "diff_sum")
    return agg


def _empty_metrics(prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_avg_diff": float("nan"),
        f"{prefix}_payout_rate": float("nan"),
        f"{prefix}_win_rate": float("nan"),
        f"{prefix}_n_machine_days": float("nan"),
    }


def _summarize_group(df: pd.DataFrame, prefix: str) -> dict[str, float]:
    if df.empty:
        return _empty_metrics(prefix)
    total_games = df["games_normalized"].sum()
    payout_rate = float("nan")
    if total_games > 0:
        payout_rate = (
            (total_games * COINS_PER_GAME + df["diff_coins_normalized"].sum())
            / (total_games * COINS_PER_GAME)
            * 100
        )
    return {
        f"{prefix}_avg_diff": df["diff_coins_normalized"].mean(),
        f"{prefix}_payout_rate": payout_rate,
        f"{prefix}_win_rate": (df["diff_coins_normalized"] > 0).mean(),
        f"{prefix}_n_machine_days": float(len(df)),
    }


def _skip_row() -> dict[str, float]:
    row: dict[str, float] = {}
    for prefix in ("Q5", "Q1", "All"):
        row.update(_empty_metrics(prefix))
    row["Q5_vs_All_diff"] = float("nan")
    row["Q5_vs_Q1_diff"] = float("nan")
    return row


def summarize_pair(
    test_df: pd.DataFrame,
    q5_names: set[str],
    q1_names: set[str],
    *,
    skip_if_missing_q5: bool,
) -> dict[str, float]:
    if test_df.empty:
        return _skip_row()
    if skip_if_missing_q5 and not q5_names.intersection(set(test_df["machine_name"])):
        return _skip_row()

    q5_df = test_df[test_df["machine_name"].isin(q5_names)]
    q1_df = test_df[test_df["machine_name"].isin(q1_names)]
    all_df = test_df
    row: dict[str, float] = {}
    row.update(_summarize_group(q5_df, "Q5"))
    row.update(_summarize_group(q1_df, "Q1"))
    row.update(_summarize_group(all_df, "All"))
    row["Q5_vs_All_diff"] = row["Q5_avg_diff"] - row["All_avg_diff"]
    row["Q5_vs_Q1_diff"] = row["Q5_avg_diff"] - row["Q1_avg_diff"]
    return row


def build_period_summary(
    df: pd.DataFrame,
    training_table: pd.DataFrame,
    *,
    floor: str | None = None,
    xday_only: bool = False,
) -> pd.DataFrame:
    _ = floor
    periods = sorted(training_table["period"].unique())
    rows: list[dict[str, float]] = []
    for period_train, period_test in zip(periods[:-1], periods[1:], strict=True):
        train = training_table[training_table["period"] == period_train].copy()
        full_test = df[df["period"] == period_test].copy()
        test = full_test.copy()
        if xday_only:
            test = test[test["is_xdds"]].copy()

        qmax = train["quintile"].max()
        qmin = train["quintile"].min()
        q5_names = set(train.loc[train["quintile"] == qmax, "machine_name"])
        q1_names = set(train.loc[train["quintile"] == qmin, "machine_name"])

        row: dict[str, float] = {
            "period_train": float(period_train),
            "period_test": float(period_test),
        }
        if xday_only:
            row["n_xdds_dates"] = float(test["date"].nunique())
        row.update(
            summarize_pair(
                test,
                q5_names,
                q1_names,
                skip_if_missing_q5=not q5_names.intersection(set(full_test["machine_name"])),
            )
        )
        rows.append(row)

    columns = SUMMARY_COLUMNS.copy()
    if xday_only:
        columns = ["period_train", "period_test", "n_xdds_dates"] + columns[2:]
    return pd.DataFrame(rows, columns=columns)


def build_q5_machinename_table(training_table: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for _, group in training_table.groupby("period", sort=True):
        qmax = group["quintile"].max()
        qmin = group["quintile"].min()
        picked = group[group["quintile"].isin([qmin, qmax])].copy()
        frames.append(picked[["period", "machine_name", "quintile", "diff_sum", "payout_rate"]])
    if not frames:
        return pd.DataFrame(columns=["period", "machine_name", "quintile", "diff_sum", "payout_rate"])
    return pd.concat(frames, ignore_index=True)


def build_backtest_outputs(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    prepared = df.copy()
    if "period" not in prepared.columns:
        prepared["date"] = pd.to_datetime(prepared["date"], format="%Y%m%d")
        prepared["period"] = assign_period(prepared["date"], WINDOW_MONTHS)
    if "is_xdds" not in prepared.columns:
        if not pd.api.types.is_datetime64_any_dtype(prepared["date"]):
            prepared["date"] = pd.to_datetime(prepared["date"], format="%Y%m%d")
        prepared["is_xdds"] = prepared["date"].dt.day.isin(X_DDS)

    training_table = build_training_table(prepared)
    return {
        "period_summary": build_period_summary(prepared, training_table),
        "xdds_overlay": build_period_summary(prepared, training_table, xday_only=True),
        "q5_machinenames_per_period": build_q5_machinename_table(training_table),
    }


def _mean_metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {}
    numeric = df.select_dtypes(include="number")
    return numeric.mean(numeric_only=True, skipna=True).to_dict()


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{value:.{digits}f}"


def build_report(outputs: dict[str, pd.DataFrame]) -> str:
    scopes = [
        ("全体", outputs["period_summary"]),
        ("X_DDS日", outputs["xdds_overlay"]),
    ]
    header = [
        "| scope | pairs | Q5_avg_diff | Q1_avg_diff | All_avg_diff | Q5_vs_All_diff | Q5_vs_Q1_diff | Q5_payout | Q1_payout | All_payout | Q5_win | Q1_win | All_win |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows: list[str] = []
    means_by_scope: dict[str, dict[str, float]] = {}
    for name, df in scopes:
        means = _mean_metrics(df)
        means_by_scope[name] = means
        rows.append(
            "| "
            + " | ".join(
                [
                    name,
                    str(len(df)),
                    _fmt(means.get("Q5_avg_diff")),
                    _fmt(means.get("Q1_avg_diff")),
                    _fmt(means.get("All_avg_diff")),
                    _fmt(means.get("Q5_vs_All_diff")),
                    _fmt(means.get("Q5_vs_Q1_diff")),
                    _fmt(means.get("Q5_payout_rate")),
                    _fmt(means.get("Q1_payout_rate")),
                    _fmt(means.get("All_payout_rate")),
                    _fmt(means.get("Q5_win_rate")),
                    _fmt(means.get("Q1_win_rate")),
                    _fmt(means.get("All_win_rate")),
                ]
            )
            + " |"
        )

    overall = means_by_scope.get("全体", {})
    xdds = means_by_scope.get("X_DDS日", {})
    q5_boost = xdds.get("Q5_avg_diff", float("nan")) - overall.get("Q5_avg_diff", float("nan"))
    all_boost = xdds.get("All_avg_diff", float("nan")) - overall.get("All_avg_diff", float("nan"))
    excess_boost = xdds.get("Q5_vs_All_diff", float("nan")) - overall.get("Q5_vs_All_diff", float("nan"))

    report_lines = [
        "# みとや machine_name Q5継続バックテスト",
        "",
        "## 全ペア平均比較",
        *header,
        *rows,
        "",
        "## 主要差分",
        f"- 全体 Q5 vs All excess: {_fmt(overall.get('Q5_vs_All_diff'))}",
        f"- 全体 Q5 vs Q1 spread: {_fmt(overall.get('Q5_vs_Q1_diff'))}",
        f"- X_DDS日 Q5 boost vs 全体: {_fmt(q5_boost)}",
        f"- X_DDS日 All boost vs 全体: {_fmt(all_boost)}",
        f"- X_DDS日 excess boost vs 全体: {_fmt(excess_boost)}",
    ]
    if "n_xdds_dates" in outputs["xdds_overlay"].columns:
        report_lines.append(
            f"- X_DDS日の平均対象日数/ペア: {_fmt(_mean_metrics(outputs['xdds_overlay']).get('n_xdds_dates'))}"
        )
    return "\n".join(report_lines) + "\n"


def save_outputs(outputs: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs["period_summary"].to_csv(output_dir / "period_summary.csv", index=False, encoding="utf-8-sig")
    outputs["xdds_overlay"].to_csv(output_dir / "xdds_overlay.csv", index=False, encoding="utf-8-sig")
    outputs["q5_machinenames_per_period"].to_csv(
        output_dir / "q5_machinenames_per_period.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (output_dir / "report.md").write_text(build_report(outputs), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    outputs = build_backtest_outputs(df)
    save_outputs(outputs, args.output_dir)
    print(f"saved outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
