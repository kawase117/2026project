from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard.utils import kamata7_theory as theory


def test_infer_floor_from_kamata7_machine_number():
    assert theory.infer_floor(2001) == "2F"
    assert theory.infer_floor(3135) == "3F"
    assert theory.infer_floor(711) == "不明"


def test_infer_lr_uses_section_median_and_vertical_fallback():
    layout = pd.DataFrame(
        {
            "machine_number": [2001, 2002, 3001, 3002],
            "section": ["A", "A", "B", "B"],
            "x": [1, 3, 5, 5],
        }
    )

    assert theory.infer_lr(layout).tolist() == ["L", "R", "R", "R"]


def test_attach_theory_axes_builds_segment_event_and_cooling_flags():
    machines = pd.DataFrame(
        {
            "date": ["20260730", "20260715", "20260715"],
            "machine_number": [2001, 3065, 3135],
            "machine_name": ["normal", "normal", "normal"],
            "games_normalized": [1200, 1300, 1400],
            "diff_coins_normalized": [300, -100, 500],
        }
    )
    layout = pd.DataFrame(
        {
            "machine_number": [2001, 3065, 3135],
            "section": ["A", "B", "C"],
            "x": [1, 1, 2],
            "section_min": [2001, 3061, 3131],
            "section_max": [2010, 3070, 3140],
            "rank_from_min": [1, 5, 5],
            "rank_from_max": [10, 6, 6],
        }
    )

    out = theory.attach_theory_axes(machines, layout)

    assert "2F_L_N" in set(out["segment"])
    assert out.loc[out["machine_number"].eq(2001), "is_event_day"].iloc[0]
    assert out.loc[out["machine_number"].eq(3065), "cooling_zone"].iloc[0] == "variable"
    assert out.loc[out["machine_number"].eq(3135), "cooling_zone"].iloc[0] == "structural"
    assert out.loc[out["machine_number"].eq(2001), "segment"].iloc[0] == "2F_L_N"


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
