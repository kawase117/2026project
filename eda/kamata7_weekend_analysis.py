from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.cross_hall_pattern_verification import load_data as base_load_data
from eda.kamata7_machinename_q5_backtest import WINDOW_MONTHS, assign_period, quintile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DB_PATH = Path(__file__).resolve().parents[1] / "db" / "マルハンメガシティ2000-蒲田7.db"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "kamata7_weekend_analysis"
MIN_GAMES = 1000
RECENT_PERIODS = 3


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < 3000 else "3F")
    df["dow"] = df["date"].dt.dayofweek
    df["is_weekend"] = df["dow"].isin([4, 5, 6])
    return df


def _note_for_count(n_machine_days: int) -> str:
    return "サンプル少（参考値）" if n_machine_days < 30 else ""


def _day_type_label(is_weekend: bool) -> str:
    return "週末" if is_weekend else "通常日"


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{value:.{digits}f}"


def _summary_value_by_quintile(summary: pd.DataFrame, is_weekend: bool, quintile_value: int, column: str) -> float:
    row = summary[(summary["is_weekend"] == is_weekend) & (summary["quintile"] == quintile_value)]
    if row.empty:
        return float("nan")
    return float(row.iloc[0][column])


def _summary_value_by_floor(summary: pd.DataFrame, is_weekend: bool, floor: str, column: str) -> float:
    row = summary[(summary["is_weekend"] == is_weekend) & (summary["floor"] == floor)]
    if row.empty:
        return float("nan")
    return float(row.iloc[0][column])


def build_branch_a_detail(df: pd.DataFrame) -> pd.DataFrame:
    baseline = df.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    training = (
        df.groupby(["period", "machine_name"], as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
    )
    training["quintile"] = quintile(training, "diff_sum")
    detailed = df.merge(training[["period", "machine_name", "quintile"]], on=["period", "machine_name"], how="left")
    detail = (
        detailed.groupby(["period", "is_weekend", "quintile"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["day_type"] = detail["is_weekend"].map({_v: _day_type_label(_v) for _v in [True, False]})
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    return detail[
        [
            "period",
            "is_weekend",
            "day_type",
            "quintile",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "note",
        ]
    ].sort_values(["period", "is_weekend", "quintile"], ascending=[True, False, True])


def build_branch_b_detail(df: pd.DataFrame) -> pd.DataFrame:
    baseline = df.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    detail = (
        df.groupby(["period", "is_weekend", "floor"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["day_type"] = detail["is_weekend"].map({_v: _day_type_label(_v) for _v in [True, False]})
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    return detail[
        [
            "period",
            "is_weekend",
            "day_type",
            "floor",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "note",
        ]
    ].sort_values(["period", "is_weekend", "floor"], ascending=[True, False, True])


def build_branch_a_summary(detail: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-RECENT_PERIODS:] if len(periods) > RECENT_PERIODS else periods
    recent = detail[detail["period"].isin(selected_periods)].copy()
    summary = (
        recent.groupby(["is_weekend", "quintile"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["is_weekend", "quintile"], ascending=[False, True])
    )
    summary["day_type"] = summary["is_weekend"].map({_v: _day_type_label(_v) for _v in [True, False]})
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    return summary[
        [
            "is_weekend",
            "day_type",
            "quintile",
            "avg_diff",
            "excess",
            "baseline",
            "n_machine_days",
            "n_dates",
            "n_periods",
            "note",
        ]
    ], selected_periods


def build_branch_b_summary(detail: pd.DataFrame) -> tuple[pd.DataFrame, list[int]]:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-RECENT_PERIODS:] if len(periods) > RECENT_PERIODS else periods
    recent = detail[detail["period"].isin(selected_periods)].copy()
    summary = (
        recent.groupby(["is_weekend", "floor"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["is_weekend", "floor"], ascending=[False, True])
    )
    summary["day_type"] = summary["is_weekend"].map({_v: _day_type_label(_v) for _v in [True, False]})
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    return summary[
        [
            "is_weekend",
            "day_type",
            "floor",
            "avg_diff",
            "excess",
            "baseline",
            "n_machine_days",
            "n_dates",
            "n_periods",
            "note",
        ]
    ], selected_periods


def build_report(
    machinename_summary: pd.DataFrame,
    floor_summary: pd.DataFrame,
    machinename_periods: list[int],
    floor_periods: list[int],
) -> str:
    q5_weekend_excess = _summary_value_by_quintile(machinename_summary, True, 5, "excess")
    q5_normal_excess = _summary_value_by_quintile(machinename_summary, False, 5, "excess")
    q5_delta = q5_weekend_excess - q5_normal_excess

    weekend_2f_excess = _summary_value_by_floor(floor_summary, True, "2F", "excess")
    weekend_3f_excess = _summary_value_by_floor(floor_summary, True, "3F", "excess")
    normal_2f_excess = _summary_value_by_floor(floor_summary, False, "2F", "excess")
    normal_3f_excess = _summary_value_by_floor(floor_summary, False, "3F", "excess")
    weekend_gap = weekend_2f_excess - weekend_3f_excess
    normal_gap = normal_2f_excess - normal_3f_excess

    if q5_delta > 10:
        verdict = "強化"
    elif q5_delta < -10:
        verdict = "減衰"
    else:
        verdict = "維持"

    machinename_rows = []
    for is_weekend in [True, False]:
        for quintile_value in range(1, 6):
            machinename_rows.append(
                "| "
                + " | ".join(
                    [
                        _day_type_label(is_weekend),
                        str(quintile_value),
                        _fmt(_summary_value_by_quintile(machinename_summary, is_weekend, quintile_value, "avg_diff")),
                        _fmt(_summary_value_by_quintile(machinename_summary, is_weekend, quintile_value, "excess")),
                        str(
                            machinename_summary[
                                (machinename_summary["is_weekend"] == is_weekend)
                                & (machinename_summary["quintile"] == quintile_value)
                            ]["note"].iloc[0]
                            if not machinename_summary[
                                (machinename_summary["is_weekend"] == is_weekend)
                                & (machinename_summary["quintile"] == quintile_value)
                            ].empty
                            else ""
                        ),
                    ]
                )
                + " |"
            )

    floor_rows = []
    for is_weekend in [True, False]:
        for floor in ["2F", "3F"]:
            floor_rows.append(
                "| "
                + " | ".join(
                    [
                        _day_type_label(is_weekend),
                        floor,
                        _fmt(_summary_value_by_floor(floor_summary, is_weekend, floor, "avg_diff")),
                        _fmt(_summary_value_by_floor(floor_summary, is_weekend, floor, "excess")),
                        str(
                            floor_summary[
                                (floor_summary["is_weekend"] == is_weekend)
                                & (floor_summary["floor"] == floor)
                            ]["note"].iloc[0]
                            if not floor_summary[
                                (floor_summary["is_weekend"] == is_weekend)
                                & (floor_summary["floor"] == floor)
                            ].empty
                            else ""
                        ),
                    ]
                )
                + " |"
            )

    lines = [
        "# Kamata7 週末×機種名・フロア別差枚パターン検証",
        "",
        f"## 直近{len(machinename_periods)}ペアの機種名×週末集計対象期間",
        ", ".join(str(p) for p in machinename_periods),
        "",
        "| day_type | quintile | avg_diff | excess | note |",
        "|---|---:|---:|---:|---|",
        *machinename_rows,
        "",
        f"## 直近{len(floor_periods)}ペアのフロア×週末集計対象期間",
        ", ".join(str(p) for p in floor_periods),
        "",
        "| day_type | floor | avg_diff | excess | note |",
        "|---|---|---:|---:|---|",
        *floor_rows,
        "",
        "## 比較",
        f"- 週末 Q5 excess: {_fmt(q5_weekend_excess)}",
        f"- 通常日 Q5 excess: {_fmt(q5_normal_excess)}",
        f"- 差分（週末 - 通常日）: {_fmt(q5_delta)}",
        f"- 週末 2F excess: {_fmt(weekend_2f_excess)}",
        f"- 週末 3F excess: {_fmt(weekend_3f_excess)}",
        f"- 通常日 2F excess: {_fmt(normal_2f_excess)}",
        f"- 通常日 3F excess: {_fmt(normal_3f_excess)}",
        f"- 週末 2F/3F gap: {_fmt(weekend_gap)}",
        f"- 通常日 2F/3F gap: {_fmt(normal_gap)}",
        "",
        "## 総評",
        f"- 判定: {verdict}",
        "- 判定基準: 週末 Q5 excess が通常日より 10 coins 以上大きければ「強化」、10 coins 以上小さければ「減衰」、それ以外は「維持」",
        "- 週末フロア差は 2F/3F gap の符号と大きさで併記した",
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
    machinename_detail = build_branch_a_detail(df)
    floor_detail = build_branch_b_detail(df)
    machinename_summary, machinename_periods = build_branch_a_summary(machinename_detail)
    floor_summary, floor_periods = build_branch_b_summary(floor_detail)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    machinename_summary.to_csv(args.output_dir / "machinename_summary.csv", index=False, encoding="utf-8-sig")
    floor_summary.to_csv(args.output_dir / "floor_summary.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "report.md").write_text(
        build_report(machinename_summary, floor_summary, machinename_periods, floor_periods),
        encoding="utf-8",
    )
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date()}")
    print(f"periods={df['period'].nunique()}")


if __name__ == "__main__":
    main()
