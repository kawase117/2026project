from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _make_row(
    date: str,
    machine_number: int,
    machine_name: str,
    payout_rate: float,
    *,
    games: int = 1000,
    n_active: int = 6,
) -> dict[str, object]:
    diff = games * 3 * (payout_rate / 100.0 - 1.0)
    rank = 1
    if machine_name == "steady":
        rank = 3
    elif machine_name == "volatile":
        rank = 2
    elif machine_name == "event_boost":
        rank = 1 if date.endswith(("01", "02", "03")) else 4
    elif machine_name == "retired":
        rank = 5
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "games": games,
        "diff": diff,
        "payout_rate": payout_rate,
        "hit104": int(payout_rate >= 104.0),
        "rank": rank,
        "n_active": n_active,
        "top3_flag": int(rank <= 3),
        "bottom3_flag": int(rank > (n_active - 3)),
        "is_any_event": int(date.endswith(("01", "02", "03"))),
        "is_x_day": int(date.endswith(("01", "03"))),
        "is_weekend": int(date.endswith(("02", "03"))),
    }


def _make_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [
        "20260701",
        "20260702",
        "20260703",
        "20260710",
        "20260711",
        "20260712",
        "20260720",
        "20260721",
        "20260722",
        "20260730",
    ]
    for date in dates:
        rows.extend(
            [
                _make_row(date, 101, "steady", 100.0, n_active=6),
                _make_row(date, 102, "volatile", 100.0 if date.endswith(("01", "11", "21")) else 114.0, n_active=6),
                _make_row(date, 103, "event_boost", 116.0 if date.endswith(("01", "02", "03")) else 98.0, n_active=6),
            ]
        )
    rows.append(_make_row("20260625", 104, "retired", 108.0, n_active=6))
    return pd.DataFrame(rows)


def test_build_hall_outputs_forces_reference_machine_into_event_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_volatility_event_gap_scan as analysis

    raw = _make_frame()
    monkeypatch.setattr(analysis, "_resolve_tokyo_ghoul_name", lambda hall: "steady")
    ranking, event_gap, summary = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        currently_installed_grace_days=30,
        min_machine_days_volatility=3,
        min_group_days=2,
        volatility_top_pct=0.25,
        min_active_machines=3,
    )

    assert "steady" not in set(ranking.head(1)["machine_name"].astype(str))
    assert "steady" in set(event_gap["machine_name"].astype(str))
    assert summary["tokyo_ghoul_machine_name"] == "steady"
    assert pd.notna(summary["tokyo_ghoul_hit104_gap_any_event"])


def test_build_hall_outputs_filters_retired_machine_and_orders_by_volatility() -> None:
    from eda import machine_volatility_event_gap_scan as analysis

    raw = _make_frame()
    ranking, event_gap, summary = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        currently_installed_grace_days=30,
        min_machine_days_volatility=3,
        min_group_days=2,
        volatility_top_pct=0.25,
        min_active_machines=3,
    )

    assert "retired" not in set(ranking["machine_name"].astype(str))
    assert "retired" not in set(event_gap["machine_name"].astype(str))
    assert ranking["volatility_score"].is_monotonic_decreasing
    assert (
        ranking.loc[ranking["machine_name"].eq("volatile"), "volatility_score"].iloc[0]
        > ranking.loc[ranking["machine_name"].eq("steady"), "volatility_score"].iloc[0]
    )
    assert summary["n_volatile_machines_tested"] == 1


def test_build_hall_outputs_reports_event_gaps_and_notes_for_small_groups() -> None:
    from eda import machine_volatility_event_gap_scan as analysis

    raw = _make_frame()
    ranking, event_gap, _ = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        currently_installed_grace_days=30,
        min_machine_days_volatility=3,
        min_group_days=20,
        volatility_top_pct=1.0,
        min_active_machines=3,
    )

    row = event_gap.loc[
        (event_gap["machine_name"].astype(str) == "event_boost")
        & (event_gap["event_type"].astype(str) == "is_any_event")
    ].iloc[0]
    assert row["hit104_gap"] > 0
    assert row["bottom3_gap"] >= 0
    assert str(row["note"]).startswith("skip:")
    assert not ranking.empty


def test_build_hall_outputs_keeps_event_type_rows_separate() -> None:
    from eda import machine_volatility_event_gap_scan as analysis

    raw = _make_frame()
    _, event_gap, _ = analysis.build_hall_outputs(
        "蒲田1",
        raw,
        currently_installed_grace_days=30,
        min_machine_days_volatility=3,
        min_group_days=2,
        volatility_top_pct=1.0,
        min_active_machines=3,
    )

    event_boost = event_gap.loc[event_gap["machine_name"].astype(str).eq("event_boost")]
    assert set(event_boost["event_type"].astype(str)) == {"is_any_event", "is_x_day", "is_weekend"}


def test_main_writes_requested_csvs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eda import machine_volatility_event_gap_scan as analysis

    monkeypatch.setattr(analysis, "HALL_DBS", {"蒲田1": "fake.db"})
    monkeypatch.setattr(analysis, "load_hall_df", lambda hall: _make_frame())
    monkeypatch.setattr(analysis, "DEFAULT_MIN_ACTIVE_MACHINES", 3)

    exit_code = analysis.main(
        [
            "--halls",
            "蒲田1",
            "--output-dir",
            str(tmp_path),
            "--currently-installed-grace-days",
            "30",
            "--min-machine-days-volatility",
            "3",
            "--min-group-days",
            "2",
            "--volatility-top-pct",
            "0.5",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "蒲田1_volatility_ranking.csv").exists()
    assert (tmp_path / "蒲田1_event_gap.csv").exists()
    assert (tmp_path / "summary_report.csv").exists()
