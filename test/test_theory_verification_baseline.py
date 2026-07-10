from __future__ import annotations

import pandas as pd

from dashboard.pages import page_20_theory_verification as page


def _make_frame() -> pd.DataFrame:
    # Family A has a structurally lower hit104 rate than family N regardless of
    # event day, mirroring the real kamata7 data. A naive "hall_all" baseline
    # would make the A/event_day claim look negative even though A improves on
    # event days relative to its own non-event baseline.
    rows = [
        {"family": "A", "is_event_day": False, "hit104": 0.20},
        {"family": "A", "is_event_day": False, "hit104": 0.20},
        {"family": "A", "is_event_day": True, "hit104": 0.30},
        {"family": "A", "is_event_day": True, "hit104": 0.30},
        {"family": "N", "is_event_day": False, "hit104": 0.60},
        {"family": "N", "is_event_day": False, "hit104": 0.60},
        {"family": "N", "is_event_day": True, "hit104": 0.62},
        {"family": "N", "is_event_day": True, "hit104": 0.62},
    ]
    frame = pd.DataFrame(rows)
    frame["date_dt"] = pd.Timestamp("2026-07-01")
    return frame


def test_segment_non_event_baseline_compares_within_family():
    frame = _make_frame()
    claim_segment = {"family": "A", "event_day": True}

    mask = page._baseline_mask(frame, "segment_non_event", claim_segment)
    baseline = frame.loc[mask]

    assert set(baseline["family"]) == {"A"}
    assert baseline["is_event_day"].eq(False).all()
    assert baseline["hit104"].mean() == 0.20


def test_hall_all_baseline_would_mix_families_and_invert_the_sign():
    frame = _make_frame()
    claim = {
        "segment": {"family": "A", "event_day": True},
        "baseline": "hall_all",
        "metric": "hit104_rate",
    }
    claim_fixed = {**claim, "baseline": "segment_non_event"}

    _, hall_all_comparison = page._summarize_claim(frame, claim)
    _, fixed_comparison = page._summarize_claim(frame, claim_fixed)

    hall_all_delta = hall_all_comparison.full_value - hall_all_comparison.full_baseline_value
    fixed_delta = fixed_comparison.full_value - fixed_comparison.full_baseline_value

    # hall_all mixes in family N (much higher hit104), pulling the baseline up
    # and making the A/event effect look negative even though it is positive
    # within family A.
    assert hall_all_delta < 0
    assert fixed_delta > 0
