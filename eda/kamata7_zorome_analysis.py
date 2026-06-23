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
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "kamata7_zorome_analysis"
MIN_GAMES = 1000
RECENT_PERIODS = 3
DAY_OF_MONTH_7KEI = {7, 17, 27}
DAY_OF_MONTH_ZOROME = {11, 22}


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < 3000 else "3F")
    df["day_of_month"] = df["date"].dt.day
    df["is_7kei"] = df["day_of_month"].isin(DAY_OF_MONTH_7KEI)
    df["is_zorome"] = df["day_of_month"].isin(DAY_OF_MONTH_ZOROME)
    return df


def _note_for_count(n_machine_days: int) -> str:
    return "サンプル少（参考値）" if n_machine_days < 30 else ""


def _day_type_label(day_type: str) -> str:
    return {
        "normal": "通常日",
        "7kei": "7系日",
        "zorome": "ゾロ目日",
    }.get(day_type, day_type)


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{value:.{digits}f}"


def _summary_value_by_quintile(summary: pd.DataFrame, day_type: str, quintile_value: int, column: str) -> float:
    row = summary[(summary["day_type"] == day_type) & (summary["quintile"] == quintile_value)]
    if row.empty:
        return float("nan")
    return float(row.iloc[0][column])


def _summary_value_by_floor(summary: pd.DataFrame, day_type: str, floor: str, column: str) -> float:
    row = summary[(summary["day_type"] == day_type) & (summary["floor"] == floor)]
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
        detailed.groupby(["period", "is_zorome", "is_7kei", "quintile"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    return detail[
        [
            "period",
            "is_zorome",
            "is_7kei",
            "quintile",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "note",
        ]
    ].sort_values(["period", "is_zorome", "is_7kei", "quintile"], ascending=[True, False, False, True])


def build_branch_b_detail(df: pd.DataFrame) -> pd.DataFrame:
    baseline = df.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    detail = (
        df.groupby(["period", "is_zorome", "is_7kei", "floor"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    return detail[
        [
            "period",
            "is_zorome",
            "is_7kei",
            "floor",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "note",
        ]
    ].sort_values(["period", "is_zorome", "is_7kei", "floor"], ascending=[True, False, False, True])


def build_branch_a_summary(
    detail: pd.DataFrame,
    raw_df: pd.DataFrame,
    *,
    day_type: str,
    label_col: str,
) -> tuple[pd.DataFrame, list[int], bool]:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-RECENT_PERIODS:] if len(periods) > RECENT_PERIODS else periods
    recent = detail[detail["period"].isin(selected_periods)].copy()
    recent = recent[recent[label_col]].copy()
    summary = (
        recent.groupby(["quintile"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["quintile"], ascending=[True])
    )
    summary["day_type"] = day_type
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    period_detail = raw_df[raw_df[label_col]].groupby("period", as_index=False).agg(n_dates=("date", "nunique"))
    all_periods_sample_small = bool((period_detail["n_dates"] < 10).all()) if not period_detail.empty else True
    return (
        summary[
            [
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
        ],
        selected_periods,
        all_periods_sample_small,
    )


def build_branch_b_summary(
    detail: pd.DataFrame,
    raw_df: pd.DataFrame,
    *,
    day_type: str,
    label_col: str,
) -> tuple[pd.DataFrame, list[int], bool]:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-RECENT_PERIODS:] if len(periods) > RECENT_PERIODS else periods
    recent = detail[detail["period"].isin(selected_periods)].copy()
    recent = recent[recent[label_col]].copy()
    summary = (
        recent.groupby(["floor"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["floor"], ascending=[True])
    )
    summary["day_type"] = day_type
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    period_detail = raw_df[raw_df[label_col]].groupby("period", as_index=False).agg(n_dates=("date", "nunique"))
    all_periods_sample_small = bool((period_detail["n_dates"] < 10).all()) if not period_detail.empty else True
    return (
        summary[
            [
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
        ],
        selected_periods,
        all_periods_sample_small,
    )


def _combine_day_types(
    detail: pd.DataFrame,
    *,
    is_zorome: bool | None = None,
    is_7kei: bool | None = None,
) -> pd.DataFrame:
    subset = detail.copy()
    if is_zorome is True:
        subset = subset[subset["is_zorome"]].copy()
    elif is_zorome is False:
        subset = subset[~subset["is_zorome"]].copy()
    if is_7kei is True:
        subset = subset[subset["is_7kei"]].copy()
    elif is_7kei is False:
        subset = subset[~subset["is_7kei"]].copy()
    return subset


def _daytype_period_sample_small(detail: pd.DataFrame, mask: pd.Series) -> bool:
    subset = detail[mask].copy()
    if subset.empty:
        return True
    period_detail = subset.groupby("period", as_index=False).agg(n_dates=("n_dates", "sum"))
    return bool((period_detail["n_dates"] < 10).all())


def build_report(
    machinename_summary: pd.DataFrame,
    floor_summary: pd.DataFrame,
    q5_detail: pd.DataFrame,
    floor_detail: pd.DataFrame,
    machinename_periods: list[int],
    floor_periods: list[int],
    q5_all_periods_small: bool,
    floor_all_periods_small: bool,
) -> str:
    q5_sources = {
        "通常日": _build_daytype_compare_q5(q5_detail, "normal"),
        "7系日": _build_daytype_compare_q5(q5_detail, "7kei"),
        "ゾロ目日": machinename_summary,
    }
    floor_sources = {
        "通常日": _build_daytype_compare_floor(floor_detail, "normal"),
        "7系日": _build_daytype_compare_floor(floor_detail, "7kei"),
        "ゾロ目日": floor_summary,
    }

    normal_q5_excess = _summary_value_by_quintile(q5_sources["通常日"], "通常日", 5, "excess")
    xday_q5_excess = _summary_value_by_quintile(q5_sources["7系日"], "7系日", 5, "excess")
    zorome_q5_excess = _summary_value_by_quintile(q5_sources["ゾロ目日"], "ゾロ目日", 5, "excess")

    normal_2f_excess = _summary_value_by_floor(floor_sources["通常日"], "通常日", "2F", "excess")
    normal_3f_excess = _summary_value_by_floor(floor_sources["通常日"], "通常日", "3F", "excess")
    xday_2f_excess = _summary_value_by_floor(floor_sources["7系日"], "7系日", "2F", "excess")
    xday_3f_excess = _summary_value_by_floor(floor_sources["7系日"], "7系日", "3F", "excess")
    zorome_2f_excess = _summary_value_by_floor(floor_sources["ゾロ目日"], "ゾロ目日", "2F", "excess")
    zorome_3f_excess = _summary_value_by_floor(floor_sources["ゾロ目日"], "ゾロ目日", "3F", "excess")

    normal_gap = normal_2f_excess - normal_3f_excess
    zorome_gap = zorome_2f_excess - zorome_3f_excess
    xday_gap = xday_2f_excess - xday_3f_excess

    q5_vs_7kei = zorome_q5_excess - xday_q5_excess
    gap_vs_7kei = zorome_gap - xday_gap

    if q5_all_periods_small and floor_all_periods_small:
        verdict = "判定不能"
    else:
        if abs(q5_vs_7kei) <= 10 and abs(gap_vs_7kei) <= 10:
            verdict = "7系日と同パターン"
        else:
            verdict = "7系日と別パターン"

    q5_rows = []
    for day_type in ["通常日", "7系日", "ゾロ目日"]:
        for quintile_value in range(1, 6):
            source = q5_sources[day_type]
            q5_rows.append(
                "| "
                + " | ".join(
                    [
                        day_type,
                        str(quintile_value),
                        _fmt(_summary_value_by_quintile(source, day_type, quintile_value, "avg_diff")),
                        _fmt(_summary_value_by_quintile(source, day_type, quintile_value, "excess")),
                        str(
                            source[(source["day_type"] == day_type) & (source["quintile"] == quintile_value)]["note"].iloc[0]
                            if not source[(source["day_type"] == day_type) & (source["quintile"] == quintile_value)].empty
                            else ""
                        ),
                    ]
                )
                + " |"
            )

    floor_rows = []
    for day_type in ["通常日", "7系日", "ゾロ目日"]:
        for floor in ["2F", "3F"]:
            source = floor_sources[day_type]
            floor_rows.append(
                "| "
                + " | ".join(
                    [
                        day_type,
                        floor,
                        _fmt(_summary_value_by_floor(source, day_type, floor, "avg_diff")),
                        _fmt(_summary_value_by_floor(source, day_type, floor, "excess")),
                        str(
                            source[(source["day_type"] == day_type) & (source["floor"] == floor)]["note"].iloc[0]
                            if not source[(source["day_type"] == day_type) & (source["floor"] == floor)].empty
                            else ""
                        ),
                    ]
                )
                + " |"
            )

    lines = [
        "# Kamata7 ゾロ目日×機種名・フロア別差枚パターン検証",
        "",
        f"## 直近{len(machinename_periods)}ペアの機種名×ゾロ目集計対象期間",
        ", ".join(str(p) for p in machinename_periods),
        "",
        "| day_type | quintile | avg_diff | excess | note |",
        "|---|---:|---:|---:|---|",
        *q5_rows,
        "",
        f"## 直近{len(floor_periods)}ペアのフロア×ゾロ目集計対象期間",
        ", ".join(str(p) for p in floor_periods),
        "",
        "| day_type | floor | avg_diff | excess | note |",
        "|---|---|---:|---:|---|",
        *floor_rows,
        "",
        "## 比較",
        f"- 通常日 Q5 excess: {_fmt(normal_q5_excess)}",
        f"- 7系日 Q5 excess: {_fmt(xday_q5_excess)}",
        f"- ゾロ目日 Q5 excess: {_fmt(zorome_q5_excess)}",
        f"- ゾロ目日 - 7系日 Q5 excess差: {_fmt(q5_vs_7kei)}",
        f"- 通常日 2F excess: {_fmt(normal_2f_excess)}",
        f"- 通常日 3F excess: {_fmt(normal_3f_excess)}",
        f"- 7系日 2F excess: {_fmt(xday_2f_excess)}",
        f"- 7系日 3F excess: {_fmt(xday_3f_excess)}",
        f"- ゾロ目日 2F excess: {_fmt(zorome_2f_excess)}",
        f"- ゾロ目日 3F excess: {_fmt(zorome_3f_excess)}",
        f"- 通常日 2F/3F gap: {_fmt(normal_gap)}",
        f"- 7系日 2F/3F gap: {_fmt(xday_gap)}",
        f"- ゾロ目日 2F/3F gap: {_fmt(zorome_gap)}",
        f"- ゾロ目日 - 7系日 gap差: {_fmt(gap_vs_7kei)}",
        "",
        "## 仮説判定",
        f"- 判定: {verdict}",
        "- 参照: 7系日と同じく、ゾロ目日でも 2F/3F gap と Q5 excess の向きが通常日からどうズレるかを見た",
        "- サンプル少（参考値）は n_dates < 10 の period に付与した",
    ]
    if q5_all_periods_small or floor_all_periods_small:
        lines.extend(
            [
                "",
                "## 注意",
                "- 全 period が n_dates < 10 だったため、判定不能として扱う",
            ]
        )
    return "\n".join(lines) + "\n"


def _build_daytype_compare_q5(detail: pd.DataFrame, day_type: str) -> pd.DataFrame:
    if day_type == "normal":
        subset = detail[(~detail["is_zorome"]) & (~detail["is_7kei"])].copy()
    elif day_type == "7kei":
        subset = detail[detail["is_7kei"]].copy()
    else:
        subset = detail[detail["is_zorome"]].copy()
    if subset.empty:
        return pd.DataFrame(columns=["day_type", "quintile", "avg_diff", "excess", "baseline", "n_machine_days", "n_dates", "n_periods", "note"])
    summary = (
        subset.groupby(["quintile"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["quintile"], ascending=[True])
    )
    summary["day_type"] = _day_type_label(day_type)
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    return summary[
        [
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
    ]


def _build_daytype_compare_floor(detail: pd.DataFrame, day_type: str) -> pd.DataFrame:
    if day_type == "normal":
        subset = detail[(~detail["is_zorome"]) & (~detail["is_7kei"])].copy()
    elif day_type == "7kei":
        subset = detail[detail["is_7kei"]].copy()
    else:
        subset = detail[detail["is_zorome"]].copy()
    if subset.empty:
        return pd.DataFrame(columns=["day_type", "floor", "avg_diff", "excess", "baseline", "n_machine_days", "n_dates", "n_periods", "note"])
    summary = (
        subset.groupby(["floor"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["floor"], ascending=[True])
    )
    summary["day_type"] = _day_type_label(day_type)
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    return summary[
        [
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
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    q5_detail = build_branch_a_detail(df)
    floor_detail = build_branch_b_detail(df)

    machinename_summary, machinename_periods, q5_all_periods_small = build_branch_a_summary(
        q5_detail,
        df,
        day_type="ゾロ目日",
        label_col="is_zorome",
    )
    floor_summary, floor_periods, floor_all_periods_small = build_branch_b_summary(
        floor_detail,
        df,
        day_type="ゾロ目日",
        label_col="is_zorome",
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    machinename_summary.to_csv(args.output_dir / "machinename_summary.csv", index=False, encoding="utf-8-sig")
    floor_summary.to_csv(args.output_dir / "floor_summary.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "report.md").write_text(
        build_report(
            machinename_summary,
            floor_summary,
            q5_detail,
            floor_detail,
            machinename_periods,
            floor_periods,
            q5_all_periods_small,
            floor_all_periods_small,
        ),
        encoding="utf-8",
    )
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date()}")
    print(f"periods={df['period'].nunique()}")


if __name__ == "__main__":
    main()
