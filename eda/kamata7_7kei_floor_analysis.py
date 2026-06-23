from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import load_data as base_load_data
from eda.kamata7_machinename_q5_backtest import WINDOW_MONTHS, assign_period

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path("db/マルハンメガシティ2000-蒲田7.db")
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "kamata7_7kei_floor_analysis"
MIN_GAMES = 1000
XDAY_DAYS = {7, 17, 27}


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < 3000 else "3F")
    df["day_of_month"] = df["date"].dt.day
    df["is_7kei"] = df["day_of_month"].isin(XDAY_DAYS)
    return df


def _note_for_count(n_machine_days: int) -> str:
    return "サンプル少（参考値）" if n_machine_days < 30 else ""


def build_period_detail(df: pd.DataFrame) -> pd.DataFrame:
    baseline = df.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    detail = (
        df.groupby(["period", "floor", "is_7kei"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["day_type"] = detail["is_7kei"].map({True: "7系日", False: "通常日"})
    detail["note"] = detail["n_machine_days"].apply(_note_for_count)
    return detail[
        [
            "period",
            "floor",
            "is_7kei",
            "day_type",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "note",
        ]
    ].sort_values(["period", "floor", "is_7kei"], ascending=[True, True, False])


def build_summary(detail: pd.DataFrame, df: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-3:] if len(periods) > 3 else periods
    detail_recent = detail[detail["period"].isin(selected_periods)].copy()
    df_recent = df[df["period"].isin(selected_periods)].copy()

    summary = (
        detail_recent.groupby(["floor", "is_7kei"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_periods=("period", "nunique"),
        )
    )
    dates = (
        df_recent.groupby(["floor", "is_7kei"], as_index=False)
        .agg(n_dates=("date", "nunique"))
    )
    summary = summary.merge(dates, on=["floor", "is_7kei"], how="left")
    summary["day_type"] = summary["is_7kei"].map({True: "7系日", False: "通常日"})
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    return (
        summary[
        [
            "floor",
            "is_7kei",
            "day_type",
            "avg_diff",
            "excess",
            "baseline",
            "n_machine_days",
            "n_dates",
            "n_periods",
            "note",
        ]
        ].sort_values(["floor", "is_7kei"], ascending=[True, False]),
        selected_periods,
    )


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    if isinstance(value, (int,)) or float(value).is_integer():
        return f"{float(value):.{digits}f}"
    return f"{value:.{digits}f}"


def _summary_value(summary: pd.DataFrame, floor: str, is_7kei: bool, column: str) -> float:
    row = summary[(summary["floor"] == floor) & (summary["is_7kei"] == is_7kei)]
    if row.empty:
        return float("nan")
    return float(row.iloc[0][column])


def _hypothesis_label(normal_gap: float, xday_gap: float, tol: float = 1e-6) -> str:
    if xday_gap < normal_gap - tol:
        return "H1"
    if xday_gap > normal_gap + tol:
        return "H3"
    return "H2"


def build_report(summary: pd.DataFrame, selected_periods: list[int]) -> str:
    rows = []
    for is_7kei in [True, False]:
        label = "7系日" if is_7kei else "通常日"
        for floor in ["2F", "3F"]:
            rows.append(
                "| "
                + " | ".join(
                    [
                        label,
                        floor,
                        _fmt(_summary_value(summary, floor, is_7kei, "avg_diff")),
                        _fmt(_summary_value(summary, floor, is_7kei, "excess")),
                        str(
                            summary[
                                (summary["floor"] == floor)
                                & (summary["is_7kei"] == is_7kei)
                            ]["note"].iloc[0]
                        ),
                    ]
                )
                + " |"
            )

    xday_2f_excess = _summary_value(summary, "2F", True, "excess")
    xday_3f_excess = _summary_value(summary, "3F", True, "excess")
    normal_2f_excess = _summary_value(summary, "2F", False, "excess")
    normal_3f_excess = _summary_value(summary, "3F", False, "excess")

    normal_gap = normal_2f_excess - normal_3f_excess
    xday_gap = xday_2f_excess - xday_3f_excess
    hypothesis = _hypothesis_label(normal_gap, xday_gap)

    if hypothesis == "H1":
        decision = "H1支持: 7系日で2F/3F差が縮小"
    elif hypothesis == "H2":
        decision = "H2支持: 7系日でも2F>3Fの順位を維持"
    else:
        decision = "H3支持: 7系日で2F優位が拡大"

    lines = [
        "# Kamata7 7系日×フロア別差枚パターン検証",
        "",
        f"## 3ペア平均（period {', '.join(str(p) for p in selected_periods)}）",
        "| day_type | floor | avg_diff | excess | note |",
        "|---|---|---:|---:|---|",
        *rows,
        "",
        "## 差分比較",
        f"- 通常日 2F excess: {_fmt(normal_2f_excess)}",
        f"- 通常日 3F excess: {_fmt(normal_3f_excess)}",
        f"- 7系日 2F excess: {_fmt(xday_2f_excess)}",
        f"- 7系日 3F excess: {_fmt(xday_3f_excess)}",
        f"- 通常日 2F/3F gap (excess): {_fmt(normal_gap)}",
        f"- 7系日 2F/3F gap (excess): {_fmt(xday_gap)}",
        "",
        "## 仮説判定",
        f"- {decision}",
        f"- 判定基準: 7系日の 2F/3F gap が通常日より小さければ H1、ほぼ同じなら H2、大きければ H3",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    detail = build_period_detail(df)
    summary, selected_periods = build_summary(detail, df)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(args.output_dir / "period_detail.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(args.output_dir / "summary.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "report.md").write_text(
        build_report(summary, selected_periods), encoding="utf-8"
    )
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date()}")
    print(f"periods={df['period'].nunique()}")


if __name__ == "__main__":
    main()
