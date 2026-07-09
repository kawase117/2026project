from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def test_build_hall_matrix_returns_expected_rows_for_dd_group() -> None:
    import eda.dd_group_weekday_interaction_3halls as analysis

    frame = analysis.load_hall_df("蒲田7")
    result = analysis.build_hall_matrix("蒲田7", matrix_kind="dd_group", df=frame, exclude_anniversary=False)

    assert set(result["dd_group"].astype(str)) == {"4系", "7系", "その他"}
    assert set(result["day_of_week"].astype(str)) == {"月", "火", "水", "木", "金", "土", "日"}
    row = result.loc[(result["dd_group"].astype(str) == "7系") & (result["day_of_week"].astype(str) == "月")].iloc[0]
    assert row["avg_diff"] == pytest.approx(807.0, abs=1.0)
    assert row["ci_low"] == pytest.approx(692.0, abs=2.0)
    assert row["ci_high"] == pytest.approx(930.0, abs=2.0)


def test_build_hall_matrix_returns_expected_rows_for_mitoya_dd_group() -> None:
    import eda.dd_group_weekday_interaction_3halls as analysis

    frame = analysis.load_hall_df("みとや")
    result = analysis.build_hall_matrix("みとや", matrix_kind="dd_group", df=frame, exclude_anniversary=False)

    assert set(result["dd_group"].astype(str)) == {"4系", "7系", "その他"}
    assert set(result["day_of_week"].astype(str)) == {"月", "火", "水", "木", "金", "土", "日"}
    row = result.loc[(result["dd_group"].astype(str) == "4系") & (result["day_of_week"].astype(str) == "土")].iloc[0]
    assert row["avg_diff"] == pytest.approx(356.0, abs=1.0)
    assert row["ci_low"] == pytest.approx(217.0, abs=2.0)
    assert row["ci_high"] == pytest.approx(493.0, abs=2.0)


def test_build_hall_matrix_returns_x_day_structure() -> None:
    import eda.dd_group_weekday_interaction_3halls as analysis

    frame = analysis.load_hall_df("蒲田1")
    result = analysis.build_hall_matrix("蒲田1", matrix_kind="is_x_day", df=frame, exclude_anniversary=False)

    assert set(result["dd_group"].astype(str)) == {"非イベント", "X_DDS"}
    assert set(result["day_of_week"].astype(str)) == {"月", "火", "水", "木", "金", "土", "日"}
    assert result["avg_diff"].notna().all()


def test_main_writes_requested_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import eda.dd_group_weekday_interaction_3halls as analysis

    def fake_load_hall_df(hall_name: str) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        dd_groups = {
            "4系": [4, 14, 24],
            "7系": [7, 17, 27],
            "その他": [1, 2, 3],
        }
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        for group_idx, (dd_group, days) in enumerate(dd_groups.items(), start=1):
            for day_idx, day in enumerate(weekdays, start=1):
                for dd in days:
                    for repeat in range(5):
                        rows.append(
                            {
                                "date": f"202606{dd:02d}",
                                "machine_name": f"{hall_name}-{dd_group}-{day}-{repeat}",
                                "machine_number": 1000 + dd * 10 + repeat,
                                "machine_digit": dd % 10,
                                "diff": float(group_idx * 100 + day_idx * 10 + dd),
                                "games": 2000,
                                "machine_zorome": 0,
                                "dd": dd,
                                "plus": 1,
                                "year_month": "202606",
                                "dd_mod10": dd % 10,
                                "date_digit": dd % 10,
                                "dd_group": dd_group,
                                "day_of_week": day,
                                "weekday_nth": "Mon1",
                                "is_weekend": int(day in {"土", "日"}),
                                "is_mmdd_zorome": 0,
                                "is_month_start": 0,
                                "is_month_end": 0,
                                "is_x_day": 1 if dd in {4, 7, 14, 17, 24, 27} else 0,
                                "is_any_event": 1,
                                "hall": hall_name,
                            }
                        )
        return pd.DataFrame(rows)

    monkeypatch.setattr(analysis, "load_hall_df", fake_load_hall_df)

    exit_code = analysis.main(["--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "dd_group_weekday_3halls.csv").exists()
    out = pd.read_csv(tmp_path / "dd_group_weekday_3halls.csv")
    assert {
        "hall",
        "dd_group",
        "day_of_week",
        "avg_diff",
        "plus_rate",
        "hit104_rate",
        "n",
        "ci_low",
        "ci_high",
        "tier",
    } <= set(out.columns)
