from __future__ import annotations

import pandas as pd
import pytest

from eda import stage2_machine_selection as sms


def test_safe_qcut_handles_ties_without_dropping_values() -> None:
    series = pd.Series([1, 1, 1, 2, 2, 3], dtype="float64")

    bins = sms._safe_qcut(series, q=5)

    assert bins.notna().all()
    assert bins.min() == 1
    assert bins.max() <= 5
    assert bins.iloc[-1] == bins.max()


def test_kakuban_edge_score_prefers_section_ends() -> None:
    left_edge = sms._kakuban_edge_score(1, 10)
    middle = sms._kakuban_edge_score(5, 10)
    right_edge = sms._kakuban_edge_score(10, 10)

    assert left_edge == pytest.approx(1.0)
    assert right_edge == pytest.approx(1.0)
    assert middle < left_edge
    assert middle < right_edge


def test_debut_phase_score_orders_newer_machines_higher() -> None:
    debut = sms._debut_phase_score(7, False)
    growth = sms._debut_phase_score(30, False)
    mature = sms._debut_phase_score(120, False)
    pre_existing = sms._debut_phase_score(None, True)

    assert debut > growth > mature > pre_existing
