"""MM/DD末尾×カテゴリの探索済み候補を日付偶奇インターリーブで split-half 検証する。"""

from __future__ import annotations

import pandas as pd

from eda.briefing_common import use_utf8_stdout
from eda.lastdigit_mm_dd_category_scan import daily_gaps, prepare_hall, summarize_gaps


TARGETS = (
    ("ヒロキ", "JUG", "hit_dd"),
    ("蒲田7", "HANA", "hit_mm"),
    ("蒲田7", "OKI", "both"),
    ("ARROW", "HANA", "both"),
)
MIN_GROUP_SIZE = 1


def split_category_frame(category_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """カテゴリ自身の営業日を、ソート順の偶奇で A/B にインターリーブ分割する。"""
    days = sorted(category_frame["date"].unique())
    half_a_dates = {date for index, date in enumerate(days) if index % 2 == 0}
    half_b_dates = {date for index, date in enumerate(days) if index % 2 == 1}
    return (
        category_frame[category_frame["date"].isin(half_a_dates)].copy(),
        category_frame[category_frame["date"].isin(half_b_dates)].copy(),
    )


def evaluate_target(hall: str, category: str, hypothesis: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    """対象セルを A/B に分け、既存の日次gap・要約関数で評価する。"""
    frame = prepare_hall(hall)
    category_frame = frame[frame["category"] == category]
    half_a, half_b = split_category_frame(category_frame)

    rows: list[dict[str, object]] = []
    summaries: dict[str, dict[str, float | int | str]] = {}
    for half_name, half_frame in (("A", half_a), ("B", half_b)):
        summary = summarize_gaps(daily_gaps(half_frame, hypothesis, min_group_size=MIN_GROUP_SIZE))
        summaries[half_name] = summary
        row: dict[str, object] = {
            "hall": hall,
            "category": category,
            "hypothesis": hypothesis,
            "half": half_name,
        }
        row.update(summary)
        rows.append(row)

    gap_a = summaries["A"]["gap_pp"]
    gap_b = summaries["B"]["gap_pp"]
    if pd.isna(gap_a) or pd.isna(gap_b):
        sign_match: bool | str = "insufficient"
    else:
        sign_match = bool(float(gap_a) * float(gap_b) > 0)
    return rows, {
        "hall": hall,
        "category": category,
        "hypothesis": hypothesis,
        "sign_match": sign_match,
        "gap_a": gap_a,
        "gap_b": gap_b,
    }


def build_results() -> tuple[pd.DataFrame, pd.DataFrame]:
    """指定4セルの8行の半分別結果と4行の符号要約を返す。"""
    detail_rows: list[dict[str, object]] = []
    sign_rows: list[dict[str, object]] = []
    for hall, category, hypothesis in TARGETS:
        rows, sign_row = evaluate_target(hall, category, hypothesis)
        detail_rows.extend(rows)
        sign_rows.append(sign_row)
    return pd.DataFrame(detail_rows), pd.DataFrame(sign_rows)


def _format_numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    display = frame.copy()
    for column in columns:
        display[column] = display[column].map(lambda value: f"{value:.3f}" if pd.notna(value) else "NaN")
    return display


def main() -> None:
    use_utf8_stdout()
    details, signs = build_results()
    print("MM/DD末尾×カテゴリ 候補セル split-half 検証")
    print("カテゴリ自身の日付集合をソート順偶奇で A/B 分割; min_group_size=1")
    print("探索済み候補の頑健性確認であり、独立ホールドアウトではない")
    print(_format_numeric(details, ("gap_pp", "ci_low", "ci_high", "positive_rate")).to_string(index=False))
    print("\n符号再現要約")
    print(_format_numeric(signs, ("gap_a", "gap_b")).to_string(index=False))


if __name__ == "__main__":
    main()
