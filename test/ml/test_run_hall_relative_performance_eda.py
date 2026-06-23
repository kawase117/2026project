from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.machine_type import machine_type_common as common
from ml.machine_type.exploratory import run_hall_relative_performance_eda as hall_eda


def _make_hall_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hall_id": ["hall_a"] * 4 + ["hall_b"] * 4,
            "machine_name": ["m1", "m2", "m1", "m2", "m1", "m2", "m1", "m2"],
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-02",
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-02",
                ]
            ),
            "machine_count": [2] * 8,
            "total_games": [100, 200, 120, 220, 110, 210, 130, 230],
            "avg_games": [50, 100, 60, 110, 55, 105, 65, 115],
            "total_diff_coins": [10, 30, 12, 32, 20, 10, 22, 12],
            "avg_diff_coins": [5, 15, 6, 16, 10, 5, 11, 6],
            "win_rate": [0.5, 0.75, 0.6, 0.7, 0.4, 0.8, 0.55, 0.65],
            "hall_win_rate": [0.62, 0.62, 0.68, 0.68, 0.58, 0.58, 0.61, 0.61],
            "avg_diff_per_machine": [12, 12, 14, 14, 10, 10, 11, 11],
            "efficiency": [0.10, 0.15, 0.10, 0.1454545455, 0.1818181818, 0.0476190476, 0.1692307692, 0.052173913],
            "is_top_3": [0, 1, 0, 1, 1, 0, 1, 0],
        }
    )


def test_load_daily_hall_summary_slim_selects_expected_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeConn:
        def close(self) -> None:
            return None

    def fake_connect(_db_path):
        return FakeConn()

    def fake_read_sql_query(sql, con):
        captured["sql"] = sql
        captured["con"] = con
        return pd.DataFrame({"date": ["20260101"], "win_rate": [55], "avg_diff_per_machine": [12]})

    monkeypatch.setattr(common, "_table_columns", lambda _con, _table: ["date", "win_rate", "avg_diff_per_machine"])
    monkeypatch.setattr(common.sqlite3, "connect", fake_connect)
    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql_query)

    out = common.load_daily_hall_summary_slim(Path("db/demo.db"))

    assert list(out.columns) == ["date", "win_rate", "avg_diff_per_machine"]
    assert "SELECT" in str(captured["sql"])
    assert "daily_hall_summary" in str(captured["sql"])


def test_add_hall_relative_features_computes_hall_average_gap_and_quartiles() -> None:
    frame = _make_hall_frame()

    out = hall_eda.add_hall_relative_features(frame)

    hall_a_day1 = out.loc[(out["hall_id"] == "hall_a") & (out["date"] == pd.Timestamp("2026-01-01"))].iloc[0]
    expected_hall_mean = frame.loc[(frame["hall_id"] == "hall_a") & (frame["date"] == pd.Timestamp("2026-01-01")), "efficiency"].mean()

    assert hall_a_day1["hall_win_rate"] == pytest.approx(0.62)
    assert hall_a_day1["efficiency_minus_hall_avg"] == pytest.approx(hall_a_day1["efficiency"] - expected_hall_mean)
    assert set(out["hall_win_rate_quartile"].dropna().unique()) <= {"Q1", "Q2", "Q3", "Q4"}
