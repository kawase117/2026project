from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_phase8_row_analysis import build_machine_layout_table
from eda.mitoya_prompt_common import (
    DB_PATH,
    MITOYA_ALL_SECTIONS,
    ensure_results_dir,
    load_machine_layout,
    load_mitoya_frame,
    render_markdown_table,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_PATH = Path(__file__).resolve().parents[1] / "document" / "mitoya_evidence_bundle.md"
PHASE8_BACKTEST_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase8_backtest"
PHASE8_ROW_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase8_row_analysis"

WORK_ORDER_ITEMS = [
    (
        "1",
        "debut_phase を台の年齢軸として固定する",
        "debut / growth / mature / pre_existing を先に分け、以降の交互作用をぶらさない。",
    ),
    ("2", "セクションの主従を確定する", "主力セクションと補助セクションを分け、見る場所を絞る。"),
    ("3", "セクション内の台選びを詰める", "同一セクション内で machine_name と rank_from_aisle を使って候補を絞る。"),
    ("4", "イベント条件との交互作用を確認する", "DD, weekday, last_digit, is_zorome は単独でなく補助軸として扱う。"),
    ("5", "TOP50 を台単位で再構成する", "セクション主導の塊を維持しつつ、台ごとの差分を追加する。"),
]

SECTION_PRIORITY = pd.DataFrame(
    [
        {"rank": 1, "section": "501-522", "position": "主力", "note": "成熟台の厚みが強い。"},
        {"rank": 2, "section": "523-539", "position": "主力", "note": "growth の寄りが強い。"},
        {"rank": 3, "section": "540-556", "position": "主力", "note": "growth の寄りが強い。"},
        {"rank": 4, "section": "557-573", "position": "主力", "note": "debut_phase が最も安定。"},
        {"rank": 5, "section": "574-590", "position": "主力", "note": "debut_phase が最も安定。"},
        {"rank": 6, "section": "591-607", "position": "主力", "note": "debut / growth の厚みがある。"},
        {"rank": 7, "section": "608-623", "position": "主力", "note": "debut / growth の厚みがある。"},
        {"rank": 8, "section": "658-674", "position": "準主力", "note": "成熟台ベースだが安定。"},
        {"rank": 9, "section": "675-691", "position": "準主力", "note": "成熟台ベースだが安定。"},
        {"rank": 10, "section": "712-722", "position": "準主力", "note": "成熟台中心で拾える。"},
        {"rank": 11, "section": "723-733", "position": "準主力", "note": "成熟台中心で拾える。"},
        {"rank": 12, "section": "805-815", "position": "準主力", "note": "台数は少ないが growth が強い。"},
        {"rank": 13, "section": "624-640", "position": "補助", "note": "reversed=1 で全面マイナス。"},
        {
            "rank": 14,
            "section": "641-657",
            "position": "主力",
            "note": "corner1 avg_diff=+542（全セクション最強）、勝率61.9%、n=535",
        },
        {"rank": 15, "section": "692-700", "position": "補助", "note": "バラエティ寄りで検証補助。"},
        {"rank": 16, "section": "701-711", "position": "補助", "note": "バラエティ寄りで検証補助。"},
        {"rank": 17, "section": "734-744", "position": "補助", "note": "本命台の履歴件数がさらに少ない。"},
        {"rank": 18, "section": "745-755", "position": "補助", "note": "本命台の履歴件数がさらに少ない。"},
    ]
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else "_missing_"


def _hall_overview() -> pd.DataFrame:
    import sqlite3

    with sqlite3.connect(DB_PATH) as conn:
        n_machines = pd.read_sql_query("SELECT COUNT(DISTINCT machine_number) AS n FROM machine_layout", conn).iloc[
            0, 0
        ]
        n_days = pd.read_sql_query("SELECT COUNT(DISTINCT date) AS n FROM machine_detailed_results", conn).iloc[0, 0]
        date_range = pd.read_sql_query(
            "SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM machine_detailed_results", conn
        ).iloc[0]
    return pd.DataFrame(
        [
            {
                "item": "台数",
                "value": int(n_machines),
            },
            {
                "item": "日数",
                "value": int(n_days),
            },
            {
                "item": "開始日",
                "value": str(date_range["min_date"]),
            },
            {
                "item": "終了日",
                "value": str(date_range["max_date"]),
            },
        ]
    )


def _work_order_markdown() -> str:
    lines = ["## Mitoya 作業順", ""]
    for order, title, note in WORK_ORDER_ITEMS:
        lines.append(f"{order}. {title}")
        lines.append(f"   - {note}")
    lines.extend(
        [
            "",
            "## セクション優先度",
            "",
            render_markdown_table(SECTION_PRIORITY),
            "",
            _source_line("mitoya-corner-effect-reversed0-strong"),
            "",
        ]
    )
    return "\n".join(lines)


def _source_line(*ids: str) -> str:
    return f"> source: {', '.join(f'[[{item}]]' for item in ids)}"


def _append_source(text: str, *ids: str) -> str:
    block = text.rstrip()
    if not block:
        return _source_line(*ids)
    return f"{block}\n\n{_source_line(*ids)}"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _phase8_horizontal_corner_table() -> pd.DataFrame:
    frame = load_mitoya_frame(join_layout=True).copy()
    layout = build_machine_layout_table(frame, sections=[str(section) for section in MITOYA_ALL_SECTIONS])
    if layout.empty:
        return pd.DataFrame()
    merged = frame.merge(
        layout[
            [
                "section",
                "machine_number",
                "row_corner_rank",
                "corner_bucket",
                "section_orientation",
            ]
        ],
        on=["section", "machine_number"],
        how="inner",
        validate="many_to_one",
    )
    horiz = merged.loc[merged["section_orientation"].eq("horizontal")].copy()
    if horiz.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for (section, reversed_flag, corner_bucket), grp in horiz.groupby(
        ["section", "is_reversed_section", "corner_bucket"], dropna=False
    ):
        rows.append(
            {
                "section": str(section),
                "reversed": int(reversed_flag),
                "corner_bucket": str(corner_bucket),
                "avg_diff": float(grp["diff"].mean()),
                "plus_rate": float((grp["diff"] > 0).mean() * 100),
                "n": int(len(grp)),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["section", "reversed", "corner_bucket"],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )


def _phase8_vertical_island_table() -> pd.DataFrame:
    frame = _read_csv(PHASE8_ROW_DIR / "row_corner_summary.csv")
    if frame.empty:
        return frame
    layout = build_machine_layout_table(
        load_mitoya_frame(join_layout=True), sections=[str(section) for section in MITOYA_ALL_SECTIONS]
    )
    if layout.empty:
        return frame
    sections = layout.loc[layout["section_orientation"].eq("vertical"), "section"].drop_duplicates().tolist()
    frame = frame.loc[frame["section"].astype(str).isin([str(section) for section in sections])].copy()
    if frame.empty:
        return frame
    return (
        frame.groupby("section", as_index=False, dropna=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            plus_rate=("plus_rate", "mean"),
            n=("n", "sum"),
        )
        .sort_values("avg_diff", ascending=False, kind="mergesort")
        .reset_index(drop=True)
    )


def _phase8_strategy_table() -> pd.DataFrame:
    frame = _read_csv(PHASE8_BACKTEST_DIR / "xdds_split_summary.csv")
    if frame.empty:
        return frame
    return frame.loc[
        :,
        [
            "scope",
            "Target_avg_diff",
            "Shortlist_avg_diff",
            "CornerRule_avg_diff",
            "MachineCorner_avg_diff",
            "Shortlist_vs_Target_diff",
            "CornerRule_vs_Target_diff",
            "MachineCorner_vs_Target_diff",
        ],
    ].copy()


def _phase8_stability_table() -> pd.DataFrame:
    frame = _read_csv(PHASE8_BACKTEST_DIR / "period_summary.csv")
    if frame.empty:
        return frame
    return frame.loc[
        :,
        [
            "period_train",
            "period_test",
            "scope",
            "Target_avg_diff",
            "Shortlist_avg_diff",
            "CornerRule_avg_diff",
            "MachineCorner_avg_diff",
            "Shortlist_vs_Target_diff",
            "CornerRule_vs_Target_diff",
            "MachineCorner_vs_Target_diff",
        ],
    ].copy()


def build_theory_document(
    *,
    phase3_path: Path,
    phase4_path: Path,
    phase5a_weekday_path: Path,
    phase5a_interactions_path: Path,
    phase6_path: Path | None = None,
    phase7_path: Path | None = None,
    output_path: Path = OUTPUT_PATH,
) -> Path:
    layout = load_machine_layout()
    section_table = (
        layout.groupby("section", dropna=False)
        .agg(
            n_machines=("machine_number", "count"),
            min_machine=("machine_number", "min"),
            max_machine=("machine_number", "max"),
        )
        .reset_index()
        .sort_values("section")
    )
    overview = _hall_overview()
    phase8_horizontal_corner = _phase8_horizontal_corner_table()
    phase8_vertical_island = _phase8_vertical_island_table()
    phase8_strategy = _phase8_strategy_table()
    phase8_stability = _phase8_stability_table()
    parts = [
        "# みとや大森町 theory",
        "",
        "## ホール概要",
        "",
        render_markdown_table(overview),
        "",
        "## セクション構成",
        "",
        render_markdown_table(section_table),
        "",
        _work_order_markdown(),
        "",
        "## Phase 3",
        "",
        "> ⚠️ このPhaseのデータは旧セクション定義（2列まとめ）時代のものです。列分割後の再検証は未実施。",
        _source_line("mitoya-section-was-two-rows-merged"),
        "",
        _append_source(_read_text(phase3_path), "mitoya-section-was-two-rows-merged"),
        "",
        "## Phase 4",
        "",
        _append_source(_read_text(phase4_path), "mitoya-section-was-two-rows-merged"),
        "",
        "## Phase 5a 曜日",
        "",
        "> ⚠️ このPhaseのデータは旧セクション定義（2列まとめ）時代のものです。列分割後の再検証は未実施。",
        _source_line("mitoya-section-was-two-rows-merged"),
        "",
        _append_source(_read_text(phase5a_weekday_path), "mitoya-section-was-two-rows-merged"),
        "",
        "## Phase 5a 交互作用",
        "",
        _append_source(_read_text(phase5a_interactions_path), "mitoya-section-was-two-rows-merged"),
        "",
        "> ⚠️ Phase 3-5 のデータは旧セクション定義（2列まとめ）時代のものです。列分割後の再検証は未実施。",
        _source_line("mitoya-section-was-two-rows-merged"),
        "",
        "## Phase 6",
        "",
        _append_source(
            _read_text(phase6_path) if phase6_path is not None else "_missing_",
            "mitoya-shortlist-min-n-and-existence-check",
        ),
        "",
        "## Phase 7",
        "",
        _append_source(
            _read_text(phase7_path) if phase7_path is not None else "_missing_",
            "mitoya-shortlist-min-n-and-existence-check",
            "mitoya-top-n-unnecessary-at-current-granularity",
        ),
        "",
        "## Phase 8",
        "",
        "### 横列 corner_bucket × avg_diff",
        "",
        render_markdown_table(phase8_horizontal_corner) if not phase8_horizontal_corner.empty else "_no rows_",
        "",
        "### 縦列 島レベル強弱",
        "",
        render_markdown_table(phase8_vertical_island) if not phase8_vertical_island.empty else "_no rows_",
        "",
        "### 戦略比較",
        "",
        render_markdown_table(phase8_strategy) if not phase8_strategy.empty else "_no rows_",
        "",
        "### ウィンドウ別の安定性",
        "",
        render_markdown_table(phase8_stability.head(20)) if not phase8_stability.empty else "_no rows_",
        "",
        _source_line(
            "mitoya-corner-effect-reversed0-strong",
            "mitoya-vertical-sections-island-level-alternation",
            "mitoya-corner-rule-xdds-strongest",
            "mitoya-machine-corner-best-overall-but-unstable",
            "mitoya-no-single-strategy-dominates-all-windows",
        ),
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    ensure_results_dir()
    build_theory_document(
        phase3_path=Path(__file__).resolve().parents[1] / "eda" / "results" / "mitoya_phase3_screening.md",
        phase4_path=Path(__file__).resolve().parents[1] / "eda" / "results" / "mitoya_phase4_durability.md",
        phase5a_weekday_path=Path(__file__).resolve().parents[1] / "eda" / "results" / "mitoya_phase5a_weekday.md",
        phase5a_interactions_path=Path(__file__).resolve().parents[1]
        / "eda"
        / "results"
        / "mitoya_phase5a_interactions.md",
        phase6_path=Path(__file__).resolve().parents[1] / "eda" / "results" / "mitoya_phase6_deepdive.md",
        phase7_path=Path(__file__).resolve().parents[1] / "eda" / "results" / "mitoya_phase7_shortlist.md",
    )
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
