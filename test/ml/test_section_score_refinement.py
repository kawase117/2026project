from __future__ import annotations

import pandas as pd
import pytest

from eda import section_score_refinement as ssr


def test_candidate_hit_flag_uses_segment_specific_thresholds() -> None:
    frame = pd.DataFrame(
        {
            "seg": ["A", "A", "N", "N"],
            "payout_rate": [101.0, 99.9, 105.5, 103.9],
        }
    )

    result = ssr.build_candidate_hit_flag(frame, threshold_a=100.0, threshold_n=105.0)

    assert result.tolist() == [True, False, True, False]


def test_section_adjustments_zero_when_subset_has_fewer_than_three_dates() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1", "S1", "S1", "S1", "S2", "S2", "S2", "S2", "S2", "S2"],
            "date_dt": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                    "2026-06-05",
                    "2026-06-06",
                ]
            ),
            "dd": [1, 1, 2, 2, 1, 1, 1, 2, 2, 2],
            "dow": [0, 0, 0, 0, 1, 1, 1, 1, 1, 1],
            "hit_flag": [1, 0, 1, 0, 1, 0, 0, 1, 1, 1],
        }
    )

    adjustments = ssr.build_section_adjustments(frame, target_dd=1, target_dow=0)

    assert adjustments.loc["S1", "dd_adjustment"] == pytest.approx(0.0)
    assert adjustments.loc["S1", "dow_adjustment"] == pytest.approx(0.0)
    assert adjustments.loc["S2", "dd_adjustment"] != pytest.approx(0.0)


def test_blend_scores_adds_adjustments_linearly() -> None:
    base = pd.Series({"S1": 0.10, "S2": 0.20})
    dd = pd.Series({"S1": 0.05, "S2": -0.02})
    dow = pd.Series({"S1": -0.01, "S2": 0.03})

    blended = ssr.blend_section_scores(base, dd, dow, alpha=0.2, beta=0.5)

    assert blended.loc["S1"] == pytest.approx(0.10 + 0.2 * 0.05 + 0.5 * -0.01)
    assert blended.loc["S2"] == pytest.approx(0.20 + 0.2 * -0.02 + 0.5 * 0.03)


def test_dd_only_score_mode_falls_back_and_blends_as_expected() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 6 + ["S2"] * 6,
            "machine_number": [1, 2, 3, 1, 2, 3, 10, 11, 12, 13, 14, 15],
            "date_dt": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-03",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                    "2026-06-05",
                    "2026-06-06",
                ]
            ),
            "dd": [1, 1, 2, 2, 1, 1, 1, 2, 1, 2, 1, 2],
            "dow": [0, 0, 1, 1, 2, 2, 0, 1, 2, 3, 4, 5],
            "seg": ["A"] * 12,
            "payout_rate": [101.0, 99.0, 103.0, 101.0, 100.0, 104.0, 104.0, 103.0, 99.0, 102.0, 105.0, 106.0],
        }
    )

    base_scores, _, adjustments = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="base",
    )
    dd_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="dd_only",
    )
    blended_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="blend_dd",
        gamma=0.3,
    )

    assert dd_scores.loc["S1"] == pytest.approx(adjustments.loc["S1", "base_rate"])
    assert dd_scores.loc["S2"] == pytest.approx(
        adjustments.loc["S2", "base_rate"] + adjustments.loc["S2", "dd_adjustment"]
    )
    assert blended_scores.loc["S2"] == pytest.approx(0.3 * base_scores.loc["S2"] + 0.7 * dd_scores.loc["S2"])


def test_restrict_to_current_machines_keeps_latest_day_roster() -> None:
    frame = pd.DataFrame(
        {
            "machine_number": [1, 2, 1, 2, 3, 2, 3],
            "date_dt": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-03",
                ]
            ),
        }
    )

    filtered, current_machine_count = ssr._restrict_to_current_machines(frame)

    assert current_machine_count == 2
    assert set(filtered["machine_number"].tolist()) == {2, 3}


def test_event_modes_switch_scores_by_target_day_type() -> None:
    frame = pd.DataFrame(
        {
            "section": ["S1"] * 10 + ["S2"] * 10,
            "machine_number": [1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 10, 11, 12, 10, 11, 12, 10, 11, 12, 10],
            "date_dt": pd.to_datetime(
                [
                    "2026-06-01",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-03",
                    "2026-06-04",
                    "2026-06-04",
                    "2026-06-05",
                    "2026-06-05",
                    "2026-06-01",
                    "2026-06-01",
                    "2026-06-02",
                    "2026-06-02",
                    "2026-06-03",
                    "2026-06-04",
                    "2026-06-04",
                    "2026-06-05",
                    "2026-06-05",
                    "2026-06-06",
                ]
            ),
            "dd": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6],
            "dow": [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 0, 0, 1, 1, 2, 3, 3, 4, 4, 5],
            "is_event": [
                True,
                True,
                False,
                False,
                True,
                True,
                False,
                False,
                True,
                True,
                True,
                True,
                False,
                False,
                True,
                False,
                False,
                True,
                True,
                False,
            ],
            "seg": ["A"] * 20,
            "payout_rate": [
                105.0,
                104.0,
                99.0,
                100.0,
                106.0,
                103.0,
                101.0,
                102.0,
                107.0,
                105.0,
                99.0,
                98.0,
                106.0,
                105.0,
                100.0,
                101.0,
                102.0,
                103.0,
                104.0,
                100.0,
            ],
        }
    )

    base_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="base",
    )
    event_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="event_only",
    )
    nonevent_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="nonevent_only",
    )
    adaptive_event_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="adaptive",
        target_is_event=True,
    )
    adaptive_nonevent_scores, _, _ = ssr._build_section_score_bundle(
        frame,
        threshold_a=100.0,
        threshold_n=105.0,
        target_dd=1,
        target_dow=0,
        score_mode="adaptive",
        target_is_event=False,
    )

    assert event_scores.loc["S1"] != pytest.approx(event_scores.loc["S2"])
    assert nonevent_scores.loc["S1"] != pytest.approx(nonevent_scores.loc["S2"])
    assert adaptive_event_scores.loc["S1"] == pytest.approx(0.5 * base_scores.loc["S1"] + 0.5 * event_scores.loc["S1"])
    assert adaptive_nonevent_scores.loc["S2"] == pytest.approx(
        0.5 * base_scores.loc["S2"] + 0.5 * nonevent_scores.loc["S2"]
    )
