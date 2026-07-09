from __future__ import annotations

from pathlib import Path

import pandas as pd


def test_build_theory_document_reads_report_files(tmp_path: Path) -> None:
    from eda import mitoya_phase5b_theory as phase5b

    phase3 = tmp_path / "phase3.md"
    phase4 = tmp_path / "phase4.md"
    phase5a_weekday = tmp_path / "phase5a_weekday.md"
    phase5a_interactions = tmp_path / "phase5a_interactions.md"
    phase6 = tmp_path / "phase6.md"
    phase7 = tmp_path / "phase7.md"
    output = tmp_path / "mitoya_theory.md"

    phase3.write_text("# phase3\nsummary", encoding="utf-8")
    phase4.write_text("# phase4\nsummary", encoding="utf-8")
    phase5a_weekday.write_text("# weekday\nsummary", encoding="utf-8")
    phase5a_interactions.write_text("# interactions\nsummary", encoding="utf-8")
    phase6.write_text("# phase6\nsummary", encoding="utf-8")
    phase7.write_text("# phase7\nsummary", encoding="utf-8")
    monkey_phase8 = pd.DataFrame(
        [
            {
                "section": "557-573",
                "reversed": 0,
                "corner_bucket": "corner1",
                "avg_diff": 100,
                "plus_rate": 50.0,
                "n": 10,
            },
            {
                "section": "557-573",
                "reversed": 1,
                "corner_bucket": "corner1",
                "avg_diff": -50,
                "plus_rate": 30.0,
                "n": 10,
            },
        ]
    )
    monkey_vertical = pd.DataFrame(
        [
            {"section": "712-722", "avg_diff": 200, "plus_rate": 55.0, "n": 20},
        ]
    )
    monkey_strategy = pd.DataFrame(
        [
            {
                "scope": "全体",
                "Target_avg_diff": 1.0,
                "Shortlist_avg_diff": 2.0,
                "CornerRule_avg_diff": 3.0,
                "MachineCorner_avg_diff": 4.0,
                "Shortlist_vs_Target_diff": 1.0,
                "CornerRule_vs_Target_diff": 2.0,
                "MachineCorner_vs_Target_diff": 3.0,
            },
        ]
    )
    monkey_stability = pd.DataFrame(
        [
            {
                "period_train": 0.0,
                "period_test": 1.0,
                "scope": "全体",
                "Target_avg_diff": 1.0,
                "Shortlist_avg_diff": 2.0,
                "CornerRule_avg_diff": 3.0,
                "MachineCorner_avg_diff": 4.0,
                "Shortlist_vs_Target_diff": 1.0,
                "CornerRule_vs_Target_diff": 2.0,
                "MachineCorner_vs_Target_diff": 3.0,
            },
        ]
    )

    phase5b._phase8_horizontal_corner_table = lambda: monkey_phase8
    phase5b._phase8_vertical_island_table = lambda: monkey_vertical
    phase5b._phase8_strategy_table = lambda: monkey_strategy
    phase5b._phase8_stability_table = lambda: monkey_stability

    phase5b.build_theory_document(
        phase3_path=phase3,
        phase4_path=phase4,
        phase5a_weekday_path=phase5a_weekday,
        phase5a_interactions_path=phase5a_interactions,
        phase6_path=phase6,
        phase7_path=phase7,
        output_path=output,
    )

    text = output.read_text(encoding="utf-8")
    assert "Mitoya 作業順" in text
    assert "セクション優先度" in text
    assert "phase7" in text
    assert "phase6" in text
    assert "phase3" in text
    assert "phase4" in text
    assert "weekday" in text
    assert "Phase 8" in text
    assert "Phase 3-5 のデータは旧セクション定義" in text
    assert "mitoya-section-was-two-rows-merged" in text
    assert "mitoya-corner-effect-reversed0-strong" in text
    assert "corner1 avg_diff=+542" in text
    assert text.count("このPhaseのデータは旧セクション定義") >= 2
