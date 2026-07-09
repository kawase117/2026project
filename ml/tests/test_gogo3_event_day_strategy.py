from __future__ import annotations

import pandas as pd
import pytest


def _make_row(
    date: str,
    machine_number: int,
    machine_name: str,
    games_normalized: int,
    diff_coins_normalized: int,
) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "games_normalized": games_normalized,
        "diff_coins_normalized": diff_coins_normalized,
    }


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date in ["20260707", "20260711", "20260708", "20260709"]:
        if date in {"20260707", "20260711"}:
            gogo_diff = 300
            other_diff = 0
        else:
            gogo_diff = 0
            other_diff = 120

        rows.extend(
            [
                _make_row(date, 101, "ゴーゴージャグラー3", 1000, gogo_diff),
                _make_row(date, 102, "ゴーゴージャグラー3", 1000, gogo_diff),
                _make_row(date, 201, "other-a", 1000, other_diff),
                _make_row(date, 202, "other-b", 1000, other_diff),
            ]
        )

    return pd.DataFrame(rows)


def test_calendar_flags_are_derived_from_date_only() -> None:
    from ml.analysis import gogo3_event_day_strategy as strategy

    flags_7 = strategy._calendar_flags(pd.Timestamp("2026-07-07"))
    flags_11 = strategy._calendar_flags(pd.Timestamp("2026-07-11"))
    flags_31 = strategy._calendar_flags(pd.Timestamp("2026-07-31"))

    assert flags_7["is_any_event"] == 1
    assert flags_7["is_7suffix"] == 1
    assert flags_7["is_1suffix"] == 0
    assert flags_7["is_zorome"] == 0

    assert flags_11["is_any_event"] == 1
    assert flags_11["is_1suffix"] == 1
    assert flags_11["is_zorome"] == 1
    assert flags_11["is_strong_zorome"] == 0

    assert flags_31["is_any_event"] == 1
    assert flags_31["is_1suffix"] == 1
    assert flags_31["is_month_end"] == 1


def test_build_hall_result_computes_simple_diff_and_did_from_daily_payouts() -> None:
    from ml.analysis import gogo3_event_day_strategy as strategy

    result = strategy.build_hall_result("zashiti", _make_frame())

    assert result["simple_diff"]["mean"] == pytest.approx(10.0)
    assert result["simple_diff"]["n_event"] == 2
    assert result["simple_diff"]["n_non_event"] == 2
    assert result["did"]["mean"] == pytest.approx(7.0)
    assert result["simple_diff"]["ci_lower"] == pytest.approx(10.0)
    assert result["simple_diff"]["ci_upper"] == pytest.approx(10.0)
    assert result["did"]["ci_lower"] == pytest.approx(7.0)
    assert result["did"]["ci_upper"] == pytest.approx(7.0)
    assert result["by_category"] == {}
