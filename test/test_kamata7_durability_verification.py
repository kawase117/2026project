from __future__ import annotations

from pathlib import Path

import pandas as pd

from eda import kamata7_machine_specificity as specificity
from eda import kamata7_refutation_eda as refutation
from eda import kamata7_regime_change_ledger as ledger


def test_extract_machine_change_events_detects_name_switches() -> None:
    frame = pd.DataFrame(
        [
            {"date": "20251220", "machine_number": 2101, "machine_name": "A", "section": "S1"},
            {"date": "20251221", "machine_number": 2101, "machine_name": "A", "section": "S1"},
            {"date": "20251222", "machine_number": 2101, "machine_name": "B", "section": "S1"},
            {"date": "20251223", "machine_number": 2101, "machine_name": "B", "section": "S1"},
            {"date": "20251220", "machine_number": 2102, "machine_name": "C", "section": "S1"},
            {"date": "20251221", "machine_number": 2102, "machine_name": "D", "section": "S1"},
        ]
    )

    events = ledger.extract_machine_change_events(frame)

    assert events[["machine_number", "date_from", "date_to", "old_machine", "new_machine"]].to_dict("records") == [
        {
            "machine_number": 2101,
            "date_from": "20251221",
            "date_to": "20251222",
            "old_machine": "A",
            "new_machine": "B",
        },
        {
            "machine_number": 2102,
            "date_from": "20251220",
            "date_to": "20251221",
            "old_machine": "C",
            "new_machine": "D",
        },
    ]


def test_recommend_split_date_prefers_balanced_high_change_day() -> None:
    candidates = pd.DataFrame(
        [
            {"date": "20251210", "n_changed_machines": 8, "before_days": 10, "after_days": 80},
            {"date": "20251222", "n_changed_machines": 7, "before_days": 40, "after_days": 38},
            {"date": "20260115", "n_changed_machines": 9, "before_days": 70, "after_days": 5},
        ]
    )

    picked = ledger.recommend_split_date(candidates)

    assert picked == "20251222"


def test_top_machine_share_returns_nan_when_total_diff_non_positive() -> None:
    frame = pd.DataFrame(
        [
            {"machine_number": 2101, "diff": -100},
            {"machine_number": 2101, "diff": 50},
            {"machine_number": 2102, "diff": -30},
            {"machine_number": 2102, "diff": 20},
        ]
    )

    share = specificity.compute_top_machine_share(frame, top_n=1)

    assert pd.isna(share)


def test_resolve_regime_split_date_uses_fallback_on_missing_report(tmp_path: Path) -> None:
    missing = tmp_path / "missing_report.md"

    split_date = refutation.resolve_regime_split_date(missing)

    assert split_date == "20251222"


def test_select_games_column_falls_back_to_games_normalized() -> None:
    frame = pd.DataFrame({"games_normalized": [1000, 1200], "diff": [10, -20]})

    assert refutation.select_games_column(frame) == "games_normalized"
