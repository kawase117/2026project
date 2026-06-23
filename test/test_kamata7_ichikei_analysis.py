from __future__ import annotations

import pandas as pd

from eda import kamata7_ichikei_analysis as ichikei


def _make_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "20260101", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 10, "games_normalized": 1200},
            {"date": "20260107", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 20, "games_normalized": 1200},
            {"date": "20260111", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 30, "games_normalized": 1200},
            {"date": "20260117", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 40, "games_normalized": 1200},
            {"date": "20260121", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 50, "games_normalized": 1200},
            {"date": "20260127", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 60, "games_normalized": 1200},
            {"date": "20260131", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 70, "games_normalized": 1200},
            {"date": "20260201", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 15, "games_normalized": 1200},
            {"date": "20260211", "machine_number": 2001, "machine_name": "A", "diff_coins_normalized": 25, "games_normalized": 1200},
            {"date": "20260217", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 35, "games_normalized": 1200},
            {"date": "20260221", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 45, "games_normalized": 1200},
            {"date": "20260227", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 55, "games_normalized": 1200},
            {"date": "20260228", "machine_number": 3001, "machine_name": "B", "diff_coins_normalized": 65, "games_normalized": 1200},
        ]
    )


def test_load_data_marks_ichikei_and_floor(monkeypatch) -> None:
    monkeypatch.setattr(ichikei, "base_load_data", lambda _db_path: _make_raw_frame())

    loaded = ichikei.load_data(ichikei.DB_PATH)

    assert "is_ichikei" in loaded.columns
    assert loaded.loc[loaded["date"] == pd.Timestamp("2026-01-11"), "is_ichikei"].eq(True).all()
    assert loaded.loc[loaded["machine_number"] == 2001, "floor"].eq("2F").all()
    assert loaded.loc[loaded["machine_number"] == 3001, "floor"].eq("3F").all()


def test_report_mentions_ichikei_and_sample_note(monkeypatch) -> None:
    machinename_summary = pd.DataFrame(
        [
            {"day_type": "通常日", "quintile": 1, "avg_diff": 1.0, "excess": 1.0, "baseline": 0.0, "n_machine_days": 40, "n_dates": 10, "n_periods": 3, "note": ""},
            {"day_type": "通常日", "quintile": 5, "avg_diff": 5.0, "excess": 5.0, "baseline": 0.0, "n_machine_days": 40, "n_dates": 10, "n_periods": 3, "note": ""},
            {"day_type": "7系日", "quintile": 1, "avg_diff": 2.0, "excess": 2.0, "baseline": 0.0, "n_machine_days": 35, "n_dates": 9, "n_periods": 3, "note": ""},
            {"day_type": "7系日", "quintile": 5, "avg_diff": 6.0, "excess": 6.0, "baseline": 0.0, "n_machine_days": 35, "n_dates": 9, "n_periods": 3, "note": ""},
            {"day_type": "1系日", "quintile": 1, "avg_diff": 3.0, "excess": 3.0, "baseline": 0.0, "n_machine_days": 20, "n_dates": 4, "n_periods": 2, "note": "サンプル少（参考値）"},
            {"day_type": "1系日", "quintile": 5, "avg_diff": 7.0, "excess": 7.0, "baseline": 0.0, "n_machine_days": 20, "n_dates": 4, "n_periods": 2, "note": "サンプル少（参考値）"},
            {"day_type": "週末", "quintile": 1, "avg_diff": 4.0, "excess": 4.0, "baseline": 0.0, "n_machine_days": 33, "n_dates": 8, "n_periods": 3, "note": ""},
            {"day_type": "週末", "quintile": 5, "avg_diff": 8.0, "excess": 8.0, "baseline": 0.0, "n_machine_days": 33, "n_dates": 8, "n_periods": 3, "note": ""},
        ]
    )
    floor_summary = pd.DataFrame(
        [
            {"day_type": "通常日", "floor": "2F", "avg_diff": 1.0, "excess": 1.0, "baseline": 0.0, "n_machine_days": 45, "n_dates": 10, "n_periods": 3, "note": ""},
            {"day_type": "通常日", "floor": "3F", "avg_diff": 2.0, "excess": 2.0, "baseline": 0.0, "n_machine_days": 45, "n_dates": 10, "n_periods": 3, "note": ""},
            {"day_type": "7系日", "floor": "2F", "avg_diff": 3.0, "excess": 3.0, "baseline": 0.0, "n_machine_days": 40, "n_dates": 9, "n_periods": 3, "note": ""},
            {"day_type": "7系日", "floor": "3F", "avg_diff": 4.0, "excess": 4.0, "baseline": 0.0, "n_machine_days": 40, "n_dates": 9, "n_periods": 3, "note": ""},
            {"day_type": "1系日", "floor": "2F", "avg_diff": 5.0, "excess": 5.0, "baseline": 0.0, "n_machine_days": 20, "n_dates": 4, "n_periods": 2, "note": "サンプル少（参考値）"},
            {"day_type": "1系日", "floor": "3F", "avg_diff": 6.0, "excess": 6.0, "baseline": 0.0, "n_machine_days": 20, "n_dates": 4, "n_periods": 2, "note": "サンプル少（参考値）"},
            {"day_type": "週末", "floor": "2F", "avg_diff": 7.0, "excess": 7.0, "baseline": 0.0, "n_machine_days": 33, "n_dates": 8, "n_periods": 3, "note": ""},
            {"day_type": "週末", "floor": "3F", "avg_diff": 8.0, "excess": 8.0, "baseline": 0.0, "n_machine_days": 33, "n_dates": 8, "n_periods": 3, "note": ""},
        ]
    )
    report = ichikei.build_report(machinename_summary, floor_summary)

    assert "1系日" in report
    assert "n_dates" in report
    assert "サンプル少（参考値）" in report
