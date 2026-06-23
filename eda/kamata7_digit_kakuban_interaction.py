"""
蒲田7 台番号末尾 × 角番位置 交互作用分析

目的:
- 角2がイベント日に強い既知知見を前提に、末尾0-9の効き方が角番位置で変わるかを検証する
- A機 × 角2 × 末尾dX のような3軸ターゲティングの候補を抽出する

出力:
- eda/reports/kamata7_digit_kakuban_interaction_report.md
- eda/reports/kamata7_3axis_top_combinations.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.kamata7_dd_internal_structure import (  # noqa: E402
    DIGIT_ORDER,
    KAKUBAN_ORDER,
    _agg_metrics,
    _prepare_frame,
    _table_to_markdown,
)

HALL = "蒲田7"
REPORT_PATH = Path(__file__).resolve().parent / "reports" / "kamata7_digit_kakuban_interaction_report.md"
CSV_PATH = Path(__file__).resolve().parent / "reports" / "kamata7_3axis_top_combinations.csv"

DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
DD_MOD10_ORDER = list(range(10))

MIN_N_SECTION2 = 30
MIN_N_SECTION3 = 100
MIN_N_SECTION4 = 15
MIN_N_SECTION5 = 20


def _prepare_working_frame() -> pd.DataFrame:
    df = _prepare_frame().copy()
    df["plus"] = (df["diff"] > 0).astype(int)
    df["segment"] = df["segment"].astype("string")
    df["kakuban"] = df["kakuban_rank"].astype("string")
    df["digit"] = df["machine_digit"].astype("string")
    df["day_of_week"] = df["day_of_week"].astype("string")
    df["dd_mod10"] = pd.to_numeric(df["dd_mod10"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["segment", "kakuban", "digit", "day_of_week", "dd_mod10"]).copy()
    df["dd_mod10"] = df["dd_mod10"].astype(int)
    return df


def _aggregate_metrics(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if len(group_cols) == 1:
        return _agg_metrics(df, group_cols)
    if df.empty:
        cols = group_cols + ["n", "avg_diff", "plus_rate", "hit104_rate"]
        return pd.DataFrame(columns=cols)
    stats = (
        df.groupby(group_cols, observed=True)
        .agg(
            n=("diff", "count"),
            avg_diff=("diff", "mean"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    stats["avg_diff"] = stats["avg_diff"].round(0)
    stats["plus_rate"] = (stats["plus_rate"] * 100).round(1)
    stats["hit104_rate"] = (stats["hit104_rate"] * 100).round(1)
    return stats


def _ranked_metrics(
    df: pd.DataFrame,
    group_cols: list[str],
    sort_cols: list[str],
    *,
    min_n: int = 1,
    rank_cols: list[str] | None = None,
) -> pd.DataFrame:
    stats = _aggregate_metrics(df, group_cols)
    if stats.empty:
        return stats
    stats = stats[stats["n"] >= min_n].copy()
    if stats.empty:
        return stats
    if rank_cols is None:
        rank_cols = group_cols
    ascending = [True] * len(rank_cols) + [False] * len(sort_cols)
    stats = stats.sort_values(rank_cols + sort_cols, ascending=ascending).reset_index(drop=True)
    stats["rank"] = stats.groupby(rank_cols, observed=True).cumcount() + 1
    return stats


def _best_combination_by_slice(
    stats: pd.DataFrame,
    slice_cols: list[str],
    *,
    min_n: int,
) -> pd.DataFrame:
    if stats.empty:
        return stats
    work = stats[stats["n"] >= min_n].copy()
    if work.empty:
        return work
    work = work.sort_values(slice_cols + ["avg_diff", "n", "digit"], ascending=[True] * len(slice_cols) + [False, False, True])
    work["rank"] = work.groupby(slice_cols, observed=True).cumcount() + 1
    return work[work["rank"] == 1].reset_index(drop=True)


def _format_section_title(title: str) -> str:
    return f"## {title}\n"


def _markdown_block(title: str, df: pd.DataFrame) -> str:
    return "\n".join([f"**{title}**", _table_to_markdown(df), ""])


def _print_table(title: str, df: pd.DataFrame) -> None:
    print(f"\n{title}")
    if df.empty:
        print("  (no rows)")
    else:
        print(df.to_string(index=False))


def _build_section1(df: pd.DataFrame) -> tuple[str, str]:
    kak_stats = _ranked_metrics(df, ["kakuban", "digit"], ["avg_diff", "n", "digit"], min_n=1, rank_cols=["kakuban"])
    overall_digit_stats = _aggregate_metrics(df, ["digit"])

    kak_stats["kakuban"] = pd.Categorical(kak_stats["kakuban"], categories=KAKUBAN_ORDER, ordered=True)
    kak_stats["digit"] = pd.Categorical(kak_stats["digit"], categories=DIGIT_ORDER, ordered=True)
    kak_stats = kak_stats.sort_values(["kakuban", "rank", "digit"], ascending=[True, True, True]).reset_index(drop=True)

    overall_digit_stats["digit"] = pd.Categorical(overall_digit_stats["digit"], categories=DIGIT_ORDER, ordered=True)
    overall_digit_stats = overall_digit_stats.sort_values(["digit"], ascending=[True]).reset_index(drop=True)

    console_lines = [
        f"rows={len(df):,}, days={df['date'].nunique()}, date_range={df['date'].min()}..{df['date'].max()}",
        "",
        "角番×末尾 baseline (ranked by avg_diff within kakuban):",
        kak_stats.to_string(index=False),
        "",
        "末尾 overall baseline:",
        overall_digit_stats.to_string(index=False),
    ]

    report = "\n".join(
        [
            _format_section_title("Section 1: 角番位置別 末尾ベースライン"),
            "- 各角番位置で、末尾0-9の avg_diff, plus_rate, hit104_rate を確認する",
            "- rank は各角番位置内での末尾順位",
            "",
            _markdown_block("角番位置別の末尾ランキング", kak_stats[["kakuban", "rank", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]]),
            _markdown_block("末尾 overall baseline", overall_digit_stats[["digit", "n", "avg_diff", "plus_rate", "hit104_rate"]]),
        ]
    )
    return "\n".join(console_lines), report


def _build_section2(df: pd.DataFrame) -> tuple[list[str], str]:
    console_blocks: list[str] = []
    report_parts: list[str] = [
        _format_section_title("Section 2: 角番 × 末尾 × dd_mod10 マトリクス"),
        "- dd_mod10 ごとに、角番位置別の末尾ランキングを確認する",
        "- 角2に限定した末尾 Top3 / Bottom2 を各 dd_mod10 で抽出する",
        f"- n < {MIN_N_SECTION2} のセルは除外する",
        "",
    ]

    for dd_mod10 in DD_MOD10_ORDER:
        sub = df[df["dd_mod10"] == dd_mod10].copy()
        stats = _ranked_metrics(
            sub,
            ["kakuban", "digit"],
            ["avg_diff", "n", "digit"],
            min_n=MIN_N_SECTION2,
            rank_cols=["kakuban"],
        )
        stats["kakuban"] = pd.Categorical(stats["kakuban"], categories=KAKUBAN_ORDER, ordered=True)
        stats["digit"] = pd.Categorical(stats["digit"], categories=DIGIT_ORDER, ordered=True)
        stats = stats.sort_values(["kakuban", "rank", "digit"], ascending=[True, True, True]).reset_index(drop=True)

        angle2 = stats[stats["kakuban"].astype(str) == "角2"].copy()
        angle2_top3 = angle2.head(3).copy()
        angle2_bottom2 = angle2.sort_values(["avg_diff", "n", "digit"], ascending=[True, False, True]).head(2).copy()

        console_blocks.extend(
            [
                f"dd_mod10={dd_mod10}",
                stats.to_string(index=False) if not stats.empty else "  (no rows)",
                "",
                f"角2 Top3 / Bottom2 for dd_mod10={dd_mod10}",
                f"Top3:\n{angle2_top3.to_string(index=False) if not angle2_top3.empty else '  (no rows)'}",
                f"Bottom2:\n{angle2_bottom2.to_string(index=False) if not angle2_bottom2.empty else '  (no rows)'}",
                "",
            ]
        )

        report_parts.extend(
            [
                f"### dd_mod10 = {dd_mod10}",
                _markdown_block(
                    "角番別末尾ランキング",
                    stats[["kakuban", "rank", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]],
                ),
                _markdown_block(
                    "角2限定 Top3",
                    angle2_top3[["kakuban", "rank", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]],
                ),
                _markdown_block(
                    "角2限定 Bottom2",
                    angle2_bottom2[["kakuban", "rank", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]],
                ),
            ]
        )

    return console_blocks, "\n".join(report_parts)


def _build_section3(df: pd.DataFrame) -> tuple[list[str], str]:
    combo_stats = _aggregate_metrics(df, ["kakuban", "digit"])
    combo_stats = combo_stats[combo_stats["n"] >= MIN_N_SECTION3].copy()
    combo_stats["kakuban"] = pd.Categorical(combo_stats["kakuban"], categories=KAKUBAN_ORDER, ordered=True)
    combo_stats["digit"] = pd.Categorical(combo_stats["digit"], categories=DIGIT_ORDER, ordered=True)
    combo_stats = combo_stats.sort_values(["avg_diff", "n", "kakuban", "digit"], ascending=[False, False, True, True]).reset_index(drop=True)

    seg_combo_stats = _aggregate_metrics(df, ["segment", "kakuban", "digit"])
    seg_combo_stats = seg_combo_stats[seg_combo_stats["n"] >= MIN_N_SECTION3].copy()
    seg_combo_stats["segment"] = pd.Categorical(seg_combo_stats["segment"], categories=["A", "N"], ordered=True)
    seg_combo_stats["kakuban"] = pd.Categorical(seg_combo_stats["kakuban"], categories=KAKUBAN_ORDER, ordered=True)
    seg_combo_stats["digit"] = pd.Categorical(seg_combo_stats["digit"], categories=DIGIT_ORDER, ordered=True)
    seg_combo_stats = seg_combo_stats.sort_values(["avg_diff", "n", "segment", "kakuban", "digit"], ascending=[False, False, True, True, True]).reset_index(drop=True)

    top20 = seg_combo_stats.head(20).copy()
    bottom20 = seg_combo_stats.sort_values(["avg_diff", "n", "segment", "kakuban", "digit"], ascending=[True, False, True, True, True]).head(20).copy()

    console_lines = [
        f"角番 × 末尾 combos (n>={MIN_N_SECTION3}):",
        combo_stats.to_string(index=False) if not combo_stats.empty else "  (no rows)",
        "",
        "segment × 角番 × 末尾 Top20:",
        top20.to_string(index=False) if not top20.empty else "  (no rows)",
        "",
        "segment × 角番 × 末尾 Bottom20:",
        bottom20.to_string(index=False) if not bottom20.empty else "  (no rows)",
    ]

    report = "\n".join(
        [
            _format_section_title("Section 3: 最強組み合わせ探索"),
            f"- 角番 × 末尾 の全組み合わせを avg_diff でランキングする (n >= {MIN_N_SECTION3})",
            f"- segment × 角番 × 末尾 の全組み合わせから Top20 / Bottom20 を出す (n >= {MIN_N_SECTION3})",
            "",
            _markdown_block("角番 × 末尾 ランキング", combo_stats[["kakuban", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]]),
            _markdown_block("segment × 角番 × 末尾 Top20", top20[["segment", "kakuban", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]]),
            _markdown_block("segment × 角番 × 末尾 Bottom20", bottom20[["segment", "kakuban", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]]),
        ]
    )
    return console_lines, report


def _build_section4(df: pd.DataFrame) -> tuple[list[str], str]:
    sub = df[df["day_of_week"].isin(["水", "土"])].copy()
    stats = _ranked_metrics(
        sub,
        ["day_of_week", "dd_mod10", "kakuban", "digit"],
        ["avg_diff", "n", "digit"],
        min_n=MIN_N_SECTION4,
        rank_cols=["day_of_week", "dd_mod10", "kakuban"],
    )
    stats["day_of_week"] = pd.Categorical(stats["day_of_week"], categories=["水", "土"], ordered=True)
    stats["kakuban"] = pd.Categorical(stats["kakuban"], categories=KAKUBAN_ORDER, ordered=True)
    stats["digit"] = pd.Categorical(stats["digit"], categories=DIGIT_ORDER, ordered=True)
    stats = stats.sort_values(["day_of_week", "dd_mod10", "kakuban", "rank", "digit"], ascending=[True, True, True, True, True]).reset_index(drop=True)

    console_lines = [
        f"水曜・土曜 subset (n>={MIN_N_SECTION4}):",
        stats.to_string(index=False) if not stats.empty else "  (no rows)",
    ]

    report = "\n".join(
        [
            _format_section_title("Section 4: 水曜・土曜限定 角番×末尾"),
            f"- 水曜と土曜に限定し、dd_mod10 別に角番別末尾 Top3 を出す (n >= {MIN_N_SECTION4})",
            "",
            _markdown_block(
                "水曜・土曜の角番別末尾ランキング",
                stats[["day_of_week", "dd_mod10", "kakuban", "rank", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]],
            ),
        ]
    )
    return console_lines, report


def _build_section5(df: pd.DataFrame) -> tuple[list[str], str, pd.DataFrame]:
    stats = _aggregate_metrics(df, ["dd_mod10", "day_of_week", "segment", "kakuban", "digit"])
    stats = stats[stats["n"] >= MIN_N_SECTION5].copy()
    stats["day_of_week"] = pd.Categorical(stats["day_of_week"], categories=DOW_ORDER, ordered=True)
    stats["segment"] = pd.Categorical(stats["segment"], categories=["A", "N"], ordered=True)
    stats["kakuban"] = pd.Categorical(stats["kakuban"], categories=KAKUBAN_ORDER, ordered=True)
    stats["digit"] = pd.Categorical(stats["digit"], categories=DIGIT_ORDER, ordered=True)
    top1 = _best_combination_by_slice(stats, ["dd_mod10", "day_of_week"], min_n=MIN_N_SECTION5)
    top1 = top1.sort_values(["dd_mod10", "day_of_week"], ascending=[True, True]).reset_index(drop=True)

    console_lines = [
        f"Top1 per dd_mod10 × weekday (n>={MIN_N_SECTION5}):",
        top1.to_string(index=False) if not top1.empty else "  (no rows)",
    ]

    report = "\n".join(
        [
            _format_section_title("Section 5: 三軸早見表（segment×角番×末尾 Top組み合わせ）"),
            f"- dd_mod10 × 曜日 ごとに、segment × kakuban × digit の Top1 を抽出する (n >= {MIN_N_SECTION5})",
            f"- CSV: {CSV_PATH.name} を UTF-8 BOM で出力する",
            "",
            _markdown_block(
                "dd_mod10 × 曜日ごとの Top1 組み合わせ",
                top1[["dd_mod10", "day_of_week", "segment", "kakuban", "digit", "n", "avg_diff", "plus_rate", "hit104_rate"]],
            ),
        ]
    )
    return console_lines, report, top1


def main() -> None:
    df = _prepare_working_frame()

    baseline = pd.DataFrame(
        [
            {
                "n": len(df),
                "avg_diff": round(df["diff"].mean(), 0),
                "plus_rate": round(df["plus"].mean() * 100, 1),
                "hit104_rate": round(df["hit104"].mean() * 100, 1),
            }
        ]
    )
    baseline["n"] = baseline["n"].astype(int)

    section1_console, section1_report = _build_section1(df)
    section2_console, section2_report = _build_section2(df)
    section3_console, section3_report = _build_section3(df)
    section4_console, section4_report = _build_section4(df)
    section5_console, section5_report, top1 = _build_section5(df)

    console_blocks = [
        f"=== {HALL} 台番号末尾 × 角番位置 交互作用分析 ===",
        f"baseline: n={baseline.loc[0, 'n']:,}, avg_diff={baseline.loc[0, 'avg_diff']:+.0f}, plus_rate={baseline.loc[0, 'plus_rate']:.1f}%, hit104_rate={baseline.loc[0, 'hit104_rate']:.1f}%",
        "",
        "Section 1",
        section1_console,
        "",
        "Section 2",
        "\n".join(section2_console),
        "",
        "Section 3",
        "\n".join(section3_console),
        "",
        "Section 4",
        "\n".join(section4_console),
        "",
        "Section 5",
        "\n".join(section5_console),
    ]
    print("\n".join(console_blocks))

    report_text = "\n".join(
        [
            f"# {HALL} 台番号末尾 × 角番位置 交互作用分析",
            "",
            f"- 対象: {HALL}",
            "- 前処理: `_prepare_frame()` で 7/7 を除外済み",
            "- 集計: n < 閾値のセルは除外し、空カテゴリは生成しない",
            "",
            "## 全体ベースライン",
            _table_to_markdown(baseline),
            "",
            section1_report,
            section2_report,
            section3_report,
            section4_report,
            section5_report,
        ]
    ).rstrip() + "\n"

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    top1.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

    print(f"\n[OK] report saved: {REPORT_PATH}")
    print(f"[OK] csv saved: {CSV_PATH}")


if __name__ == "__main__":
    main()
