from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.utils import theory_engine as theory


def test_hall_configs_and_registries_load_for_both_halls():
    kama7 = theory.load_hall_config("kamata7")
    kama1 = theory.load_hall_config("kamata1")
    reg7 = theory.load_theory_registry("kamata7")
    reg1 = theory.load_theory_registry("kamata1")

    assert kama7["segment_scheme"]["order"][0] == "2F_L_N"
    assert kama1["segment_scheme"]["order"] == ["2F_A", "2F_N"]
    assert len(reg7["claims"]) > 0
    assert len(reg1["claims"]) > 0
    assert any(claim["id"] == "k7-2f-l-n-corner" for claim in reg7["claims"])
    assert any(claim["id"] == "k1-a-dd30" for claim in reg1["claims"])


def test_attach_theory_axes_uses_hall_specific_segment_rules():
    layout7 = pd.DataFrame(
        {
            "machine_number": [2001, 3001],
            "section": ["A", "B"],
            "x": [1, 1],
            "section_min": [2001, 3001],
            "section_max": [2010, 3010],
            "rank_from_min": [1, 2],
            "rank_from_max": [10, 9],
        }
    )
    machines7 = pd.DataFrame(
        {
            "date": ["20260730", "20260730"],
            "machine_number": [2001, 3001],
            "machine_name": ["AT machine", "ジャグラー"],
            "games_normalized": [1200, 1300],
            "diff_coins_normalized": [300, 500],
        }
    )
    out7 = theory.attach_theory_axes(machines7, layout7, theory.load_hall_config("kamata7"))

    layout1 = pd.DataFrame(
        {
            "machine_number": [1631, 1632],
            "section": ["A", "A"],
            "x": [1, 2],
            "section_min": [1631, 1631],
            "section_max": [1640, 1640],
            "rank_from_min": [1, 2],
            "rank_from_max": [10, 9],
        }
    )
    machines1 = pd.DataFrame(
        {
            "date": ["20260730", "20260730"],
            "machine_number": [1631, 1632],
            "machine_name": ["ジャグラー", "AT machine"],
            "games_normalized": [1200, 1300],
            "diff_coins_normalized": [300, -100],
        }
    )
    out1 = theory.attach_theory_axes(machines1, layout1, theory.load_hall_config("kamata1"))

    assert set(out7["segment"]) == {"2F_L_N", "3F_L_A"}
    assert set(out1["segment"]) == {"2F_A", "2F_N"}
    assert out1["lr"].eq("不明").all()
    assert out1["kakuban"].tolist() == [1, 2]


def test_event_kind_summary_groups_dd_and_month_end_days():
    frame = pd.DataFrame(
        {
            "date_dt": pd.to_datetime(["2026-07-07", "2026-07-17", "2026-07-22", "2026-02-28", "2026-07-08"]),
            "is_event_day": [True, True, True, True, False],
            "machine_number": [1, 2, 3, 4, 5],
            "diff_coins_normalized": [100, 150, 200, 300, -50],
            "games_normalized": [1000, 1000, 1000, 1000, 1000],
            "hit104": [1, 0, 1, 1, 0],
        }
    )

    daily = theory.build_daily_event_summary(frame, min_n=1)
    summary = theory.build_event_kind_summary(frame, min_n=1)

    assert set(daily["event_kind"]) == {"DD7", "DD17", "DD22", "月末"}
    assert set(summary["event_kind"]) == {"DD7", "DD17", "DD22", "月末"}
    assert summary.loc[summary["event_kind"].eq("DD17"), "days"].iloc[0] == 1
    assert summary.loc[summary["event_kind"].eq("月末"), "total_diff"].iloc[0] == 300


def test_event_kind_summary_uses_machine_count_weighting():
    frame = pd.DataFrame(
        {
            "date_dt": pd.to_datetime(["2026-07-17", "2026-07-17", "2026-07-18", "2026-07-18"]),
            "is_event_day": [True, True, True, True],
            "machine_number": [1, 2, 3, 4],
            "diff_coins_normalized": [100, 100, 0, 0],
            "games_normalized": [1000, 1000, 1000, 1000],
            "hit104": [1, 1, 0, 0],
        }
    )

    summary = theory.build_event_kind_summary(frame, min_n=1)
    row = summary.loc[summary["event_kind"].eq("DD17")].iloc[0]

    assert row["machine_count"] == 2
    assert row["total_diff"] == 200
    assert row["avg_diff"] == 100
    assert row["avg_hit104_rate"] == 1


def test_event_bucket_summary_groups_calendar_families():
    frame = pd.DataFrame(
        {
            "date_dt": pd.to_datetime(
                [
                    "2026-07-01",
                    "2026-07-07",
                    "2026-07-11",
                    "2026-07-17",
                    "2026-07-22",
                    "2026-07-27",
                    "2026-04-30",
                    "2026-07-30",
                    "2026-07-31",
                    "2026-11-11",
                ]
            ),
            "is_event_day": [True] * 10,
            "machine_number": list(range(10)),
            "diff_coins_normalized": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            "games_normalized": [1000] * 10,
            "hit104": [0, 1, 0, 1, 0, 1, 1, 0, 1, 0],
        }
    )

    summary = theory.build_event_bucket_summary(frame, min_n=1)

    assert set(summary["event_bucket"]) == {
        "1のつく日",
        "7のつく日",
        "ゾロ目の日",
        "強ゾロ目の日",
        "月末",
        "30日",
    }
    assert summary.loc[summary["event_bucket"].eq("1のつく日"), "days"].iloc[0] == 4
    assert summary.loc[summary["event_bucket"].eq("7のつく日"), "days"].iloc[0] == 3
    assert summary.loc[summary["event_bucket"].eq("30日"), "days"].iloc[0] == 2


def test_real_kamata7_event_kind_summary_keeps_2026_dd17_counts():
    db_path = next(Path(r"C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db").glob("*蒲田7.db"))
    frame = theory.filter_theory_frame(
        theory.load_theory_frame(db_path),
        start_date=pd.Timestamp("2026-01-01"),
        min_games=1000,
    )

    summary = theory.build_event_kind_summary(frame, min_n=5)
    row = summary.loc[summary["event_kind"].eq("DD17")].iloc[0]

    assert row["days"] == 6
    assert row["machine_count"] == 4232
    assert row["total_diff"] == 723300


def test_dd_kakuban_matrix_hides_sparse_cells():
    frame = pd.DataFrame(
        {
            "dd": [7, 7, 7, 30],
            "rank_from_min": [1, 1, 2, 1],
            "machine_number": [1, 2, 3, 4],
            "diff_coins_normalized": [100, 300, 900, 500],
            "games_normalized": [1000, 1000, 1000, 1000],
            "hit104": [0, 1, 1, 1],
        }
    )

    matrix = theory.build_dd_kakuban_matrix(frame, metric="avg_diff", min_n=2)

    assert matrix.loc[7, 1] == 200
    assert 2 not in matrix.columns
