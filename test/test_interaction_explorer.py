from __future__ import annotations

import pandas as pd

from dashboard.utils.interaction_analysis import (
    attach_interaction_axes,
    build_claim_draft,
    run_pairwise_axis_test,
    summarize_cells,
)


def _make_frame() -> pd.DataFrame:
    rows = []
    for dd, segment, effect in [
        (1, "A", 400),
        (1, "B", 10),
        (8, "A", 30),
        (8, "B", 20),
    ]:
        for idx in range(6):
            rows.append(
                {
                    "date": f"202607{dd:02d}",
                    "machine_number": 100 + idx,
                    "machine_name": f"machine-{idx}",
                    "segment": segment,
                    "dd": dd,
                    "kakuban": 1 if idx < 3 else 2,
                    "family": "A" if idx % 2 == 0 else "N",
                    "games_normalized": 1000,
                    "diff_coins_normalized": effect,
                    "hit104": 1 if effect > 100 else 0,
                    "is_event_day": dd == 1,
                }
            )
    return attach_interaction_axes(pd.DataFrame(rows))


def test_summarize_cells_and_pairwise_test_use_reused_stats() -> None:
    frame = _make_frame()

    summary = summarize_cells(frame, ["segment", "dd_bin"], metric="avg_diff")
    stats = run_pairwise_axis_test(frame, "segment", "dd_bin", metric="avg_diff", min_n=2)

    assert not summary.empty
    assert set(summary.columns) >= {"segment", "dd_bin", "n", "avg_diff", "win_rate", "hit104_rate"}
    assert stats.test == "kruskal"
    assert stats.effect_size > 0.1
    assert stats.n_obs > 0


def test_claim_draft_uses_selected_axes_and_segment_values() -> None:
    row = pd.Series(
        {
            "segment": "A",
            "dd_bin": "1-7",
            "axes": ("segment", "dd_bin"),
            "n": 12,
            "avg_diff": 400.0,
            "overall_metric": 40.0,
            "claim_id": "k7-a-1-7",
            "claim_title": "segment x dd_bin avg_diff",
            "min_n": 5,
        }
    )

    yaml_text = build_claim_draft(
        row,
        hall_key="kamata7",
        metric="avg_diff",
        source="document/plans/2026-07-10-dashboard-refactoring-plan.md#phase-3",
        last_reviewed="2026-07-10",
    )

    assert "status: watching" in yaml_text
    assert "metric: avg_diff" in yaml_text
    assert "dd:" in yaml_text
    assert "- 1" in yaml_text
    assert "- 7" in yaml_text


def test_attach_interaction_axes_adds_screening_columns() -> None:
    frame = pd.DataFrame(
        {
            "date": ["20260701"],
            "machine_number": [101],
            "machine_name": ["alpha"],
            "segment": ["A"],
            "dd": [1],
            "kakuban": [1],
            "family": ["A"],
            "games_normalized": [1000],
            "diff_coins_normalized": [100],
            "hit104": [1],
            "is_event_day": [True],
        }
    )

    out = attach_interaction_axes(frame)

    assert "dd_bin" in out.columns
    assert "machine_tail" in out.columns
    assert "event_day" in out.columns
    assert bool(out.loc[0, "event_day"]) is True
