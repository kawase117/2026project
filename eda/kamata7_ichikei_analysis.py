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


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "db" / "マルハンメガシティ2000-蒲田7.db"
OUTPUT_DIR = BASE_DIR / "tmp" / "kamata7_ichikei_analysis"
MIN_GAMES = 1000
RECENT_PERIODS = 3
SAMPLE_NOTE_THRESHOLD = 30
DAY_TYPES = ["通常日", "7系日", "1系日", "週末"]


def load_data(db_path: Path, min_games: int = MIN_GAMES) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["floor"] = df["machine_number"].apply(lambda x: "2F" if x < 3000 else "3F")
    df["day_of_month"] = df["date"].dt.day
    df["is_weekend"] = df["date"].dt.dayofweek.isin([4, 5, 6])
    df["is_ichikei"] = df["day_of_month"].isin({1, 11, 21, 31})
    df["is_7kei"] = df["day_of_month"].isin({7, 17, 27})
    return df


def _note_for_count(n_machine_days: int) -> str:
    return "サンプル少（参考値）" if n_machine_days < SAMPLE_NOTE_THRESHOLD else ""


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{value:.{digits}f}"


def _day_type_mask(df: pd.DataFrame, day_type: str) -> pd.Series:
    if day_type == "通常日":
        return ~df["is_ichikei"] & ~df["is_7kei"] & ~df["is_weekend"]
    if day_type == "7系日":
        return df["is_7kei"]
    if day_type == "1系日":
        return df["is_ichikei"]
    if day_type == "週末":
        return df["is_weekend"]
    raise ValueError(f"unknown day_type: {day_type}")


def _build_machinename_detail(df: pd.DataFrame, day_type: str) -> pd.DataFrame:
    subset = df[_day_type_mask(df, day_type)].copy()
    columns = [
        "period",
        "day_type",
        "quintile",
        "avg_diff",
        "baseline",
        "excess",
        "n_machine_days",
        "n_dates",
        "note",
    ]
    if subset.empty:
        return pd.DataFrame(columns=columns)

    baseline = subset.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    training = (
        subset.groupby(["period", "machine_name"], as_index=False)
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
    )
    training["quintile"] = quintile(training, "diff_sum")
    detailed = subset.merge(training[["period", "machine_name", "quintile"]], on=["period", "machine_name"], how="left")
    detail = (
        detailed.groupby(["period", "quintile"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["day_type"] = day_type
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    return detail[columns].sort_values(["period", "quintile"], ascending=[True, True])


def _build_floor_detail(df: pd.DataFrame, day_type: str) -> pd.DataFrame:
    subset = df[_day_type_mask(df, day_type)].copy()
    columns = [
        "period",
        "day_type",
        "floor",
        "avg_diff",
        "baseline",
        "excess",
        "n_machine_days",
        "n_dates",
        "note",
    ]
    if subset.empty:
        return pd.DataFrame(columns=columns)

    baseline = subset.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    detail = (
        subset.groupby(["period", "floor"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["day_type"] = day_type
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    return detail[columns].sort_values(["period", "floor"], ascending=[True, True])


def build_machinename_detail(df: pd.DataFrame) -> pd.DataFrame:
    frames = [_build_machinename_detail(df, day_type) for day_type in DAY_TYPES]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_floor_detail(df: pd.DataFrame) -> pd.DataFrame:
    frames = [_build_floor_detail(df, day_type) for day_type in DAY_TYPES]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _recent_periods(detail: pd.DataFrame) -> list[int]:
    periods = sorted(detail["period"].unique())
    return periods[-RECENT_PERIODS:] if len(periods) > RECENT_PERIODS else periods


def build_machinename_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=[
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
        )
    recent = detail[detail["period"].isin(_recent_periods(detail))].copy()
    summary = (
        recent.groupby(["day_type", "quintile"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["day_type", "quintile"], ascending=[True, True])
    )
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


def build_floor_summary(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame(
            columns=[
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
        )
    recent = detail[detail["period"].isin(_recent_periods(detail))].copy()
    summary = (
        recent.groupby(["day_type", "floor"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            excess=("excess", "mean"),
            baseline=("baseline", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
        .sort_values(["day_type", "floor"], ascending=[True, True])
    )
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


def _summary_note(summary: pd.DataFrame, *, day_type: str, key_col: str, key_value: str | int) -> str:
    row = summary[(summary["day_type"] == day_type) & (summary[key_col] == key_value)]
    if row.empty:
        return ""
    return str(row.iloc[0]["note"])


def _report_table_rows(
    machinename_summary: pd.DataFrame,
    floor_summary: pd.DataFrame,
) -> tuple[list[str], list[str]]:
    q5_rows: list[str] = []
    floor_rows: list[str] = []
    for day_type in DAY_TYPES:
        q5_rows.append(
            "| "
            + " | ".join(
                [
                    day_type,
                    _fmt(_summary_value_by_quintile(machinename_summary, day_type, 5, "excess")),
                    _fmt(_summary_value_by_quintile(machinename_summary, day_type, 1, "excess")),
                    str(int(_summary_value_by_quintile(machinename_summary, day_type, 5, "n_machine_days")))
                    if not pd.isna(_summary_value_by_quintile(machinename_summary, day_type, 5, "n_machine_days"))
                    else "NaN",
                    str(int(_summary_value_by_quintile(machinename_summary, day_type, 5, "n_dates")))
                    if not pd.isna(_summary_value_by_quintile(machinename_summary, day_type, 5, "n_dates"))
                    else "NaN",
                    _summary_note(machinename_summary, day_type=day_type, key_col="quintile", key_value=5),
                ]
            )
            + " |"
        )
        n2 = _summary_value_by_floor(floor_summary, day_type, "2F", "n_machine_days")
        n3 = _summary_value_by_floor(floor_summary, day_type, "3F", "n_machine_days")
        n2_dates = _summary_value_by_floor(floor_summary, day_type, "2F", "n_dates")
        n3_dates = _summary_value_by_floor(floor_summary, day_type, "3F", "n_dates")
        note_2f = _summary_note(floor_summary, day_type=day_type, key_col="floor", key_value="2F")
        note_3f = _summary_note(floor_summary, day_type=day_type, key_col="floor", key_value="3F")
        floor_rows.append(
            "| "
            + " | ".join(
                [
                    day_type,
                    _fmt(_summary_value_by_floor(floor_summary, day_type, "2F", "excess")),
                    _fmt(_summary_value_by_floor(floor_summary, day_type, "3F", "excess")),
                    _fmt(
                        _summary_value_by_floor(floor_summary, day_type, "2F", "excess")
                        - _summary_value_by_floor(floor_summary, day_type, "3F", "excess")
                    ),
                    str(int(max([v for v in [n2, n3] if not pd.isna(v)]))) if not pd.isna(n2) or not pd.isna(n3) else "NaN",
                    str(int(max([v for v in [n2_dates, n3_dates] if not pd.isna(v)]))) if not pd.isna(n2_dates) or not pd.isna(n3_dates) else "NaN",
                    note_2f if note_2f else note_3f,
                ]
            )
            + " |"
        )
    return q5_rows, floor_rows


def build_report(machinename_summary: pd.DataFrame, floor_summary: pd.DataFrame) -> str:
    q5_rows, floor_rows = _report_table_rows(machinename_summary, floor_summary)

    normal_q5 = _summary_value_by_quintile(machinename_summary, "通常日", 5, "excess")
    xday_q5 = _summary_value_by_quintile(machinename_summary, "7系日", 5, "excess")
    ichi_q5 = _summary_value_by_quintile(machinename_summary, "1系日", 5, "excess")
    weekend_q5 = _summary_value_by_quintile(machinename_summary, "週末", 5, "excess")

    normal_gap = _summary_value_by_floor(floor_summary, "通常日", "2F", "excess") - _summary_value_by_floor(
        floor_summary, "通常日", "3F", "excess"
    )
    xday_gap = _summary_value_by_floor(floor_summary, "7系日", "2F", "excess") - _summary_value_by_floor(
        floor_summary, "7系日", "3F", "excess"
    )
    ichi_gap = _summary_value_by_floor(floor_summary, "1系日", "2F", "excess") - _summary_value_by_floor(
        floor_summary, "1系日", "3F", "excess"
    )
    weekend_gap = _summary_value_by_floor(floor_summary, "週末", "2F", "excess") - _summary_value_by_floor(
        floor_summary, "週末", "3F", "excess"
    )

    same_pattern = (
        not pd.isna(ichi_q5)
        and not pd.isna(xday_q5)
        and not pd.isna(normal_q5)
        and not pd.isna(ichi_gap)
        and not pd.isna(xday_gap)
        and not pd.isna(normal_gap)
        and abs(ichi_q5 - xday_q5) <= abs(ichi_q5 - normal_q5)
        and abs(ichi_gap - xday_gap) <= abs(ichi_gap - normal_gap)
    )
    verdict = "7系日と同パターン" if same_pattern else "別パターン"

    lines = [
        "# Kamata7 1系日 × 機種名・フロア別差枚パターン検証",
        "",
        "## 機種名 × 1系日 4way 比較",
        "| day_type | Q5 excess | Q1 excess | n_machine_days | n_dates | note |",
        "|---|---:|---:|---:|---:|---|",
        *q5_rows,
        "",
        "## フロア × 1系日 4way 比較",
        "| day_type | 2F excess | 3F excess | gap | n_machine_days | n_dates | note |",
        "|---|---:|---:|---:|---:|---:|---|",
        *floor_rows,
        "",
        "## 比較メモ",
        f"- 1系日 Q5 excess: {_fmt(ichi_q5)}",
        f"- 7系日 Q5 excess: {_fmt(xday_q5)}",
        f"- 通常日 Q5 excess: {_fmt(normal_q5)}",
        f"- 週末 Q5 excess: {_fmt(weekend_q5)}",
        f"- 1系日 2F/3F gap: {_fmt(ichi_gap)}",
        f"- 7系日 2F/3F gap: {_fmt(xday_gap)}",
        f"- 通常日 2F/3F gap: {_fmt(normal_gap)}",
        f"- 週末 2F/3F gap: {_fmt(weekend_gap)}",
        "",
        "## 仮説判定",
        f"- 判定: {verdict}",
        "- 1系日が 7系日 に近いほど「7系日と同パターン」、通常日寄りなら「別パターン」と判定しています。",
    ]
    return "\n".join(lines) + "\n"


def _output_paths(output_dir: Path) -> tuple[Path, Path, Path]:
    return (
        output_dir / "machinename_summary.csv",
        output_dir / "floor_summary.csv",
        output_dir / "report.md",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games)
    machinename_detail = build_machinename_detail(df)
    floor_detail = build_floor_detail(df)
    machinename_summary = build_machinename_summary(machinename_detail)
    floor_summary = build_floor_summary(floor_detail)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    machinename_path, floor_path, report_path = _output_paths(args.output_dir)
    machinename_summary.to_csv(machinename_path, index=False, encoding="utf-8-sig")
    floor_summary.to_csv(floor_path, index=False, encoding="utf-8-sig")
    report_path.write_text(build_report(machinename_summary, floor_summary), encoding="utf-8")
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date()}")
    print(f"periods={df['period'].nunique()}")


if __name__ == "__main__":
    main()
