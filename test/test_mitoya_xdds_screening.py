from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from eda import mitoya_xdds_screening as mitoya  # noqa: E402


def _make_perf_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "machine_name": "Q5機種",
                "xdds_payout": 106.0,
                "norm_payout": 101.0,
                "lift_machine": 5.0,
                "n_xdds": 3,
            },
            {
                "machine_name": "非Q5機種",
                "xdds_payout": 102.0,
                "norm_payout": 100.0,
                "lift_machine": 2.0,
                "n_xdds": 3,
            },
        ]
    )


def test_x_dds_set() -> None:
    assert mitoya.X_DDS == {4, 7, 14, 17, 24, 27}


def test_score_q5_beats_non_q5(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    floor_csv = tmp_path / "layout.csv"
    pd.DataFrame(
        [
            {"machine_number": 101, "section": "501-522"},
            {"machine_number": 202, "section": "501-522"},
        ]
    ).to_csv(floor_csv, index=False, encoding="utf-8-sig")

    class DummyConn:
        def __enter__(self) -> "DummyConn":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_read_sql_query(query: str, conn: object) -> pd.DataFrame:
        _ = conn
        return pd.DataFrame(
            [
                {"machine_number": 101, "machine_name": "Q5機種"},
                {"machine_number": 202, "machine_name": "非Q5機種"},
            ]
        )

    monkeypatch.setattr(mitoya, "compute_current_q5_machines", lambda *args, **kwargs: {"Q5機種"})
    monkeypatch.setattr(mitoya, "compute_machine_xdds_perf", lambda *args, **kwargs: _make_perf_frame())
    monkeypatch.setattr(mitoya.sqlite3, "connect", lambda *args, **kwargs: DummyConn())
    monkeypatch.setattr(mitoya.pd, "read_sql_query", fake_read_sql_query)
    monkeypatch.setattr(
        mitoya.pd,
        "read_csv",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {"machine_number": 101, "section": "501-522"},
                {"machine_number": 202, "section": "501-522"},
            ]
        ),
    )

    table = mitoya.build_screening_table(Path("dummy.db"), floor_csv, target_dd=4)
    q5_score = table.loc[table["machine_name"].eq("Q5機種"), "score"].iloc[0]
    non_q5_score = table.loc[table["machine_name"].eq("非Q5機種"), "score"].iloc[0]
    assert q5_score > non_q5_score


def test_build_screening_table_columns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    floor_csv = tmp_path / "layout.csv"
    pd.DataFrame(
        [{"machine_number": 101, "section": "501-522"}]
    ).to_csv(floor_csv, index=False, encoding="utf-8-sig")

    class DummyConn:
        def __enter__(self) -> "DummyConn":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(mitoya, "compute_current_q5_machines", lambda *args, **kwargs: {"Q5機種"})
    monkeypatch.setattr(
        mitoya,
        "compute_machine_xdds_perf",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "machine_name": "Q5機種",
                    "xdds_payout": 106.0,
                    "norm_payout": 101.0,
                    "lift_machine": 5.0,
                    "n_xdds": 3,
                }
            ]
        ),
    )
    monkeypatch.setattr(mitoya.sqlite3, "connect", lambda *args, **kwargs: DummyConn())
    monkeypatch.setattr(
        mitoya.pd,
        "read_sql_query",
        lambda *args, **kwargs: pd.DataFrame(
            [{"machine_number": 101, "machine_name": "Q5機種"}]
        ),
    )
    monkeypatch.setattr(
        mitoya.pd,
        "read_csv",
        lambda *args, **kwargs: pd.DataFrame(
            [{"machine_number": 101, "section": "501-522"}]
        ),
    )

    table = mitoya.build_screening_table(Path("dummy.db"), floor_csv, target_dd=4)
    assert {"machine_name", "section", "score", "is_q5"} <= set(table.columns)
