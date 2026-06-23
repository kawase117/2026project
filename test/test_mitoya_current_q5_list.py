from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda import mitoya_current_q5_list as mitoya  # noqa: E402


def _make_overall_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "machine_name": "A",
                "period": 0,
                "diff_sum": 10,
                "games_sum": 3000,
                "payout_rate": (3000 * 3 + 10) / (3000 * 3) * 100,
                "n_dates": 3,
                "n_machines": 1,
                "last_date": pd.Timestamp("2026-05-01"),
                "quintile": 1,
            },
            {
                "machine_name": "B",
                "period": 0,
                "diff_sum": 20,
                "games_sum": 3000,
                "payout_rate": (3000 * 3 + 20) / (3000 * 3) * 100,
                "n_dates": 4,
                "n_machines": 1,
                "last_date": pd.Timestamp("2026-05-15"),
                "quintile": 2,
            },
            {
                "machine_name": "C",
                "period": 0,
                "diff_sum": 30,
                "games_sum": 3000,
                "payout_rate": (3000 * 3 + 30) / (3000 * 3) * 100,
                "n_dates": 5,
                "n_machines": 2,
                "last_date": pd.Timestamp("2026-05-20"),
                "quintile": 3,
            },
            {
                "machine_name": "D",
                "period": 0,
                "diff_sum": 40,
                "games_sum": 3000,
                "payout_rate": (3000 * 3 + 40) / (3000 * 3) * 100,
                "n_dates": 6,
                "n_machines": 2,
                "last_date": pd.Timestamp("2026-05-31"),
                "quintile": 4,
            },
            {
                "machine_name": "E",
                "period": 0,
                "diff_sum": 50,
                "games_sum": 3000,
                "payout_rate": (3000 * 3 + 50) / (3000 * 3) * 100,
                "n_dates": 7,
                "n_machines": 3,
                "last_date": pd.Timestamp("2026-06-10"),
                "quintile": 5,
            },
            {
                "machine_name": "F",
                "period": 0,
                "diff_sum": 55,
                "games_sum": 3000,
                "payout_rate": (3000 * 3 + 55) / (3000 * 3) * 100,
                "n_dates": 8,
                "n_machines": 3,
                "last_date": pd.Timestamp("2026-05-01"),
                "quintile": 5,
            },
        ]
    )


def test_build_current_q5_table_returns_q5_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mitoya, "aggregate_machine_overall", lambda df: _make_overall_frame())

    result = mitoya.build_current_q5_table(pd.DataFrame(), pd.Timestamp("2026-06-15"))

    assert set(result["machine_name"]) == {"E", "F"}
    assert set(result["quintile"]) == {5}
    assert len(result) == 2


def test_active_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mitoya, "aggregate_machine_overall", lambda df: _make_overall_frame())

    result = mitoya.build_current_q5_table(pd.DataFrame(), pd.Timestamp("2026-06-15"))

    active = dict(zip(result["machine_name"], result["active"], strict=True))
    assert active["E"] is True
    assert active["F"] is False


def test_build_checklist_markdown_contains_machine_name() -> None:
    q5_current = pd.DataFrame(
        [
            {
                "machine_name": "みとやQ5",
                "quintile": 5,
                "payout_rate": 105.23,
                "diff_sum": 12345,
                "n_dates": 12,
                "n_machines": 4,
                "last_date": "2026-06-10",
                "active": True,
            }
        ]
    )

    markdown = mitoya.build_checklist_markdown(
        q5_current,
        window_start=pd.Timestamp("2026-03-01"),
        max_date=pd.Timestamp("2026-06-15"),
    )

    assert "みとやQ5" in markdown
    assert "| 機種名 | 台数 | 機械割 | 最終登場 | active |" in markdown
