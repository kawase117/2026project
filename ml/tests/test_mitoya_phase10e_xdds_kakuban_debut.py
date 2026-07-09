from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [
        "20260101",
        "20260103",
        "20260104",
        "20260107",
        "20260111",
        "20260114",
    ]
    segment_specs = [
        ("h_jug", "501-522", "horizontal", True, 501, 1, 1),
        ("h_nonjug", "523-539", "horizontal", False, 523, 2, 1),
        ("v_jug", "624-640", "vertical", True, 624, 1, 1),
        ("v_nonjug", "641-657", "vertical", False, 641, 1, 2),
        ("mixed_805", "805-815", "horizontal", False, 805, 3, 1),
    ]
    for date_idx, date in enumerate(dates):
        dd = int(date[-2:])
        is_xdds_day = dd in {4, 7, 14}
        for segment_idx, (segment, section, orientation, is_jug, base_machine, x, y) in enumerate(segment_specs):
            for offset, rank in enumerate([1, 2, 3, 4], start=0):
                machine_number = base_machine + offset
                machine_name = "マイジャグラーV" if is_jug and rank <= 2 else "スマスロ北斗の拳"
                if segment == "h_nonjug" and machine_number == 524 and date >= "20260107":
                    machine_name = "L炎炎ノ消防隊"
                diff = 100 + segment_idx * 20 + rank * 10 + date_idx * 3
                if is_xdds_day and rank == 1:
                    diff += 80
                rows.append(
                    {
                        "date": date,
                        "machine_number": machine_number,
                        "machine_name": machine_name,
                        "diff": float(diff),
                        "games": 1500,
                        "section": section,
                        "x": x,
                        "y": y,
                        "rank_from_aisle": rank if segment != "v_jug" else rank + 1,
                        "dd": dd,
                    }
                )
    return pd.DataFrame(rows)


def test_build_all_artifacts_returns_expected_tables() -> None:
    import eda.mitoya_phase10e_xdds_kakuban_debut as phase10e

    artifacts = phase10e.build_all_artifacts(_make_frame())

    assert {
        "step1_cross_stats",
        "step2_anova_xdds_corner",
        "step3_interaction_summary",
        "step4_debut_phase_stats",
        "step5_debut_kw",
        "step6_anova_debut_event",
        "step7_debut_spearman",
        "report",
    } <= set(artifacts)

    step1 = artifacts["step1_cross_stats"]
    assert list(step1.columns) == ["segment", "scope", "corner_bucket", "n", "avg_diff", "plus_rate"]
    assert set(step1["scope"].astype(str)) <= {"X_DDS", "非イベント日"}
    assert set(step1["corner_bucket"].astype(str)) <= {"corner1", "corner2-4", "corner5-9", "corner10+"}

    step2 = artifacts["step2_anova_xdds_corner"]
    assert {"segment", "source", "df", "sum_sq", "F", "p_value", "note"} <= set(step2.columns)
    assert set(step2["segment"].astype(str)) == {"h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"}

    step4 = artifacts["step4_debut_phase_stats"]
    assert list(step4.columns) == ["segment", "debut_phase", "n", "avg_diff", "plus_rate"]
    assert "moved" not in set(step4["debut_phase"].astype(str))

    step5 = artifacts["step5_debut_kw"]
    assert list(step5.columns) == ["segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]

    step7 = artifacts["step7_debut_spearman"]
    assert list(step7.columns) == ["segment", "scope", "spearman_rho", "p_value", "n"]
    assert set(step7["scope"].astype(str)) == {"all", "X_DDS", "非イベント日"}

    report = artifacts["report"]
    assert "# Phase10e: X_DDS×角番 交互作用 & 経過日数×プレミアム検証" in report


def test_main_writes_requested_files(tmp_path: Path, monkeypatch) -> None:
    import eda.mitoya_phase10e_xdds_kakuban_debut as phase10e

    monkeypatch.setattr(phase10e, "load_mitoya_frame", lambda join_layout=True: _make_frame())

    exit_code = phase10e.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    for name in [
        "step1_cross_stats.csv",
        "step2_anova_xdds_corner.csv",
        "step3_interaction_summary.csv",
        "step4_debut_phase_stats.csv",
        "step5_debut_kw.csv",
        "step6_anova_debut_event.csv",
        "step7_debut_spearman.csv",
        "report.md",
    ]:
        assert (tmp_path / name).exists()
