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


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "db" / "マルハンメガシティ2000-蒲田7.db"
COORD_2F = BASE_DIR / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORD_3F = BASE_DIR / "Heatmap" / "3F_floor_coordinates_kamata7.csv"
OUTPUT_DIR = BASE_DIR / "tmp" / "kamata7_machine_band_analysis"
MIN_GAMES = 1000
LOW_SAMPLE_THRESHOLD = 50
ICHIKEI_DAYS: frozenset[int] = frozenset({1, 11, 21, 31})

# 確定設定6（鉄台）。section ranking から除外する
TETSU_MACHINES: set[int] = {2026}
TETSU_START_DATE = "20260101"


def load_section_coords() -> pd.DataFrame:
    coords = pd.concat(
        [
            pd.read_csv(COORD_2F)[["machine_number", "section", "floor"]],
            pd.read_csv(COORD_3F)[["machine_number", "section", "floor"]],
        ],
        ignore_index=True,
    )
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords["section"] = coords["section"].astype(str)
    coords["floor"] = coords["floor"].astype(str)
    return coords


def attach_section_info(df: pd.DataFrame, coords: pd.DataFrame | None = None) -> pd.DataFrame:
    base = df.drop(columns=["floor", "section"], errors="ignore").copy()
    coords_df = load_section_coords() if coords is None else coords.copy()
    coords_df["machine_number"] = coords_df["machine_number"].astype(int)
    coords_df["section"] = coords_df["section"].astype(str)
    coords_df["floor"] = coords_df["floor"].astype(str)
    merged = base.merge(
        coords_df[["machine_number", "section", "floor"]],
        on="machine_number",
        how="left",
        validate="m:1",
    )
    merged = merged.dropna(subset=["section"]).copy()
    merged["section"] = merged["section"].astype(str)
    merged["floor"] = merged["floor"].astype(str)
    assert merged["section"].notna().all()
    return merged


def apply_tetsu_filter(df: pd.DataFrame, *, exclude_tetsu: bool) -> pd.DataFrame:
    if not exclude_tetsu:
        return df.copy()
    cutoff = pd.Timestamp(TETSU_START_DATE)
    mask = ~(df["machine_number"].isin(TETSU_MACHINES) & (df["date"] >= cutoff))
    return df[mask].copy()


def load_data(
    db_path: Path,
    min_games: int = MIN_GAMES,
    *,
    exclude_tetsu: bool = True,
) -> pd.DataFrame:
    df = base_load_data(db_path)
    df = df[df["games_normalized"] >= min_games].copy()
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = apply_tetsu_filter(df, exclude_tetsu=exclude_tetsu)
    df = attach_section_info(df)
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)
    df["dow"] = df["date"].dt.dayofweek
    df["day_of_month"] = df["date"].dt.day
    df["is_weekend"] = df["dow"].isin([4, 5, 6])
    df["is_ichikei"] = df["day_of_month"].isin(ICHIKEI_DAYS)
    df["is_7kei"] = df["day_of_month"].isin([7, 17, 27])
    df["day_type"] = "通常日"
    df.loc[df["is_weekend"], "day_type"] = "週末"
    df.loc[df["is_ichikei"], "day_type"] = "1系日"
    df.loc[df["is_7kei"], "day_type"] = "7系日"
    return df


def _note_for_count(n_machine_days: int) -> str:
    return "サンプル少（参考値）" if n_machine_days < LOW_SAMPLE_THRESHOLD else ""


def _day_type_order(day_type: str) -> int:
    return {"通常日": 0, "7系日": 1, "1系日": 2, "週末": 3}.get(day_type, 99)


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    return f"{value:.{digits}f}"


def build_section_detail(df: pd.DataFrame) -> pd.DataFrame:
    baseline = df.groupby("period")["diff_coins_normalized"].mean().rename("baseline")
    detail = (
        df.groupby(["period", "day_type", "floor", "section"], as_index=False)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_machine_days=("diff_coins_normalized", "size"),
            n_dates=("date", "nunique"),
        )
        .merge(baseline, on="period", how="left")
    )
    detail["excess"] = detail["avg_diff"] - detail["baseline"]
    detail["note"] = detail["n_machine_days"].astype(int).apply(_note_for_count)
    detail["_day_type_order"] = detail["day_type"].map(_day_type_order)
    detail = detail.sort_values(["period", "_day_type_order", "floor", "section"]).drop(columns="_day_type_order")
    return detail[
        [
            "period",
            "day_type",
            "floor",
            "section",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "note",
        ]
    ]


def build_section_summary(detail: pd.DataFrame) -> pd.DataFrame:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-3:] if len(periods) > 3 else periods
    recent = detail[detail["period"].isin(selected_periods)].copy()
    summary = (
        recent.groupby(["day_type", "floor", "section"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            baseline=("baseline", "mean"),
            excess=("excess", "mean"),
            n_machine_days=("n_machine_days", "sum"),
            n_dates=("n_dates", "sum"),
            n_periods=("period", "nunique"),
        )
    )
    summary["note"] = summary["n_machine_days"].astype(int).apply(_note_for_count)
    summary["_day_type_order"] = summary["day_type"].map(_day_type_order)
    summary = summary.sort_values(["_day_type_order", "floor", "section"]).drop(columns="_day_type_order")
    return summary[
        [
            "day_type",
            "floor",
            "section",
            "avg_diff",
            "baseline",
            "excess",
            "n_machine_days",
            "n_dates",
            "n_periods",
            "note",
        ]
    ]


def _table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "該当なし"
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in df.iterrows():
        values: list[str] = []
        for col in columns:
            value = row[col]
            if col in {"avg_diff", "baseline", "excess", "delta_excess"}:
                values.append(_fmt(value))
            elif col in {"n_machine_days", "n_dates", "n_periods"}:
                values.append("NaN" if pd.isna(value) else str(int(value)))
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def _normal_rows(summary: pd.DataFrame, floor: str) -> pd.DataFrame:
    rows = summary[(summary["day_type"] == "通常日") & (summary["floor"] == floor)].copy()
    if rows.empty:
        return rows
    return rows.sort_values(["excess", "section"], ascending=[False, True])


def _delta_rows(summary: pd.DataFrame, floor: str, day_type: str) -> pd.DataFrame:
    normal = summary[(summary["day_type"] == "通常日") & (summary["floor"] == floor)][
        ["section", "excess", "note", "n_machine_days"]
    ].rename(
        columns={
            "excess": "normal_excess",
            "note": "normal_note",
            "n_machine_days": "normal_n_machine_days",
        }
    )
    target = summary[(summary["day_type"] == day_type) & (summary["floor"] == floor)][
        ["section", "excess", "note", "n_machine_days"]
    ].rename(
        columns={
            "excess": "target_excess",
            "note": "target_note",
            "n_machine_days": "target_n_machine_days",
        }
    )
    merged = normal.merge(target, on="section", how="outer")
    merged["delta_excess"] = merged["target_excess"] - merged["normal_excess"]
    merged["_has_both"] = merged["normal_excess"].notna() & merged["target_excess"].notna()
    return merged.sort_values(["_has_both", "delta_excess", "section"], ascending=[False, False, True])


def _section_count(summary: pd.DataFrame, floor: str) -> int:
    return int(summary[summary["floor"] == floor]["section"].nunique())


def build_report(detail: pd.DataFrame, summary: pd.DataFrame, *, exclude_tetsu: bool) -> str:
    periods = sorted(detail["period"].unique())
    selected_periods = periods[-3:] if len(periods) > 3 else periods
    lines: list[str] = [
        "# Kamata7 section差枚パターン検証",
        "",
        "## 対象期間",
        f"- periods: {', '.join(str(p) for p in selected_periods)}",
        f"- 2F section数: {_section_count(summary, '2F')}",
        f"- 3F section数: {_section_count(summary, '3F')}",
        "",
        "## 通常日: 2F 全section / 3F 全section（excess 降順）",
    ]
    if exclude_tetsu:
        lines.extend(
            [
                "",
                "## 注記",
                "- machine_number=2026（確定設定6、20260101〜）は集計から除外しています。",
                "- 除外しない場合は --include-tetsu オプションで実行してください。",
            ]
        )

    for floor in ["2F", "3F"]:
        rows = _normal_rows(summary, floor)
        lines.extend(
            [
                f"### {floor} 全{len(rows)}section（excess 降順）",
                _table(
                    rows[["section", "avg_diff", "excess", "n_machine_days", "n_dates", "note"]],
                    ["section", "avg_diff", "excess", "n_machine_days", "n_dates", "note"],
                ),
                "",
            ]
        )

    for day_type in ["7系日", "1系日", "週末"]:
        lines.append(f"## {day_type}: delta_excess 全{_section_count(summary, '2F')}section（降順）")
        for floor in ["2F", "3F"]:
            rows = _delta_rows(summary, floor, day_type)
            lines.extend(
                [
                    f"### {floor}",
                    _table(
                        rows[
                            [
                                "section",
                                "normal_excess",
                                "target_excess",
                                "delta_excess",
                                "target_n_machine_days",
                                "target_note",
                            ]
                        ],
                        [
                            "section",
                            "normal_excess",
                            "target_excess",
                            "delta_excess",
                            "target_n_machine_days",
                            "target_note",
                        ],
                    ),
                    "",
                ]
            )

    lines.extend(
        [
            "## 総評",
            "- section名は座標CSVの定義をそのまま使用。",
            "- 3400-3401 も 3F の section として分析対象に含めています。",
            f"- `{_note_for_count(0)}` は `n_machine_days < {LOW_SAMPLE_THRESHOLD}` のセルに付与しています。",
            "",
            "## 注記",
            "- 通常日・7系日・1系日・週末ともに全sectionを excess 降順で表示しています。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    parser.add_argument(
        "--exclude-tetsu",
        action="store_true",
        default=True,
        help="鉄台（TETSU_MACHINES）を除外して集計する（デフォルト: True）",
    )
    parser.add_argument(
        "--include-tetsu",
        dest="exclude_tetsu",
        action="store_false",
        help="鉄台を除外せずに集計する",
    )
    return parser.parse_args()


def _output_paths(output_dir: Path, *, exclude_tetsu: bool) -> tuple[Path, Path, Path]:
    if exclude_tetsu:
        return (
            output_dir / "section_detail.csv",
            output_dir / "section_summary.csv",
            output_dir / "report.md",
        )
    return (
        output_dir / "section_detail_with_tetsu.csv",
        output_dir / "section_summary_with_tetsu.csv",
        output_dir / "report_with_tetsu.md",
    )


def main() -> None:
    args = parse_args()
    df = load_data(args.db_path, min_games=args.min_games, exclude_tetsu=args.exclude_tetsu)
    detail = build_section_detail(df)
    summary = build_section_summary(detail)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    detail_path, summary_path, report_path = _output_paths(args.output_dir, exclude_tetsu=args.exclude_tetsu)
    detail.to_csv(detail_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    report_path.write_text(build_report(detail, summary, exclude_tetsu=args.exclude_tetsu), encoding="utf-8")
    print(f"saved outputs to {args.output_dir}")
    print(f"source_latest_date={df['date'].max().date()}")
    print(f"periods={df['period'].nunique()}")


if __name__ == "__main__":
    main()
