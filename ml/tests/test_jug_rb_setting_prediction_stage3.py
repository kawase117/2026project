from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


def _make_stage2_frame() -> pd.DataFrame:
    rows = [
        {
            "date": "20260630",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.20,
            "e_setting": 2.0,
            "e_payout": 98.0,
        },
        {
            "date": "20260701",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 3,
            "bb": 1,
            "p_high": 0.80,
            "e_setting": 5.0,
            "e_payout": 105.0,
        },
        {
            "date": "20260702",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.40,
            "e_setting": 3.0,
            "e_payout": 100.0,
        },
        {
            "date": "20260703",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 3,
            "bb": 1,
            "p_high": 0.60,
            "e_setting": 4.0,
            "e_payout": 102.0,
        },
        {
            "date": "20260704",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.20,
            "e_setting": 2.0,
            "e_payout": 98.0,
        },
        {
            "date": "20260705",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.30,
            "e_setting": 2.0,
            "e_payout": 98.5,
        },
        {
            "date": "20260706",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.50,
            "e_setting": 3.0,
            "e_payout": 100.0,
        },
        {
            "date": "20260707",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.40,
            "e_setting": 3.0,
            "e_payout": 100.0,
        },
        {
            "date": "20260708",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.10,
            "e_setting": 1.0,
            "e_payout": 96.0,
        },
        {
            "date": "20260711",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 4,
            "bb": 1,
            "p_high": 0.90,
            "e_setting": 6.0,
            "e_payout": 108.0,
        },
        {
            "date": "20260730",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.20,
            "e_setting": 2.0,
            "e_payout": 98.0,
        },
        {
            "date": "20260731",
            "machine_number": 1001,
            "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
            "G": 1000,
            "rb": 2,
            "bb": 1,
            "p_high": 0.20,
            "e_setting": 2.0,
            "e_payout": 98.0,
        },
        {
            "date": "20260630",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.10,
            "e_setting": 1.0,
            "e_payout": 96.0,
        },
        {
            "date": "20260701",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.20,
            "e_setting": 2.0,
            "e_payout": 98.0,
        },
        {
            "date": "20260702",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.30,
            "e_setting": 2.0,
            "e_payout": 99.0,
        },
        {
            "date": "20260703",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.40,
            "e_setting": 3.0,
            "e_payout": 100.0,
        },
        {
            "date": "20260704",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.50,
            "e_setting": 3.0,
            "e_payout": 100.0,
        },
        {
            "date": "20260705",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.60,
            "e_setting": 4.0,
            "e_payout": 102.0,
        },
        {
            "date": "20260706",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.70,
            "e_setting": 5.0,
            "e_payout": 104.0,
        },
        {
            "date": "20260707",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.80,
            "e_setting": 6.0,
            "e_payout": 106.0,
        },
        {
            "date": "20260708",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.60,
            "e_setting": 4.0,
            "e_payout": 102.0,
        },
        {
            "date": "20260711",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.70,
            "e_setting": 5.0,
            "e_payout": 104.0,
        },
        {
            "date": "20260731",
            "machine_number": 1002,
            "machine_name": "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
            "G": 1000,
            "rb": 1,
            "bb": 1,
            "p_high": 0.30,
            "e_setting": 2.0,
            "e_payout": 99.0,
        },
    ]
    return pd.DataFrame(rows)


def _make_layout_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "machine_number": 1001,
                "section": "2001-2010",
                "kakuban_rank_min": 1,
                "kakuban_rank_max": 2,
                "section_size": 2,
                "is_corner1": 1,
                "side_lr": "L",
            },
            {
                "machine_number": 1002,
                "section": "2001-2010",
                "kakuban_rank_min": 2,
                "kakuban_rank_max": 1,
                "section_size": 2,
                "is_corner1": 1,
                "side_lr": "R",
            },
        ]
    )


def test_stage3_features_are_past_only_and_include_calendar_flags() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage3_features as stage3

    layout = _make_layout_frame()
    full = stage3.build_stage3_features(_make_stage2_frame(), hall="蒲田7", layout_frame=layout)
    truncated = stage3.build_stage3_features(
        _make_stage2_frame().loc[lambda df: df["date"].le("20260708")].copy(),
        hall="蒲田7",
        layout_frame=layout,
    )

    target_full = full.loc[full["date"].eq("20260708") & full["machine_number"].eq(1001)].iloc[0]
    target_truncated = truncated.loc[truncated["date"].eq("20260708") & truncated["machine_number"].eq(1001)].iloc[0]
    compare_cols = [
        "b_machine_90d",
        "b_machine_180d",
        "p_high_lag1",
        "p_high_lag2",
        "p_high_lag1_event",
        "days_since_high",
        "high_freq_same_weekday",
        "weekday",
        "is_mon",
        "is_tue",
        "is_wed",
        "is_thu",
        "is_fri",
        "is_sat",
        "is_sun",
        "day_of_month",
        "day_suffix",
        "is_zorome",
        "is_strong_zorome",
        "is_month_end",
        "is_month_start",
        "is_event_day",
        "kakuban_rank_min",
        "kakuban_rank_max",
        "section_size",
        "is_corner1",
        "side_lr",
    ]

    for column in compare_cols:
        assert (
            target_full[column] == pytest.approx(target_truncated[column], rel=1e-12, abs=1e-12)
            if column != "side_lr"
            else target_full[column] == target_truncated[column]
        )

    assert target_full["b_machine_90d"] == pytest.approx(0.43392857142857144, rel=1e-12, abs=1e-12)
    assert target_full["b_machine_180d"] == pytest.approx(0.43392857142857144, rel=1e-12, abs=1e-12)
    assert target_full["p_high_lag1"] == pytest.approx(0.40, rel=1e-12, abs=1e-12)
    assert target_full["p_high_lag2"] == pytest.approx(0.50, rel=1e-12, abs=1e-12)
    assert target_full["p_high_lag1_event"] == pytest.approx(0.40, rel=1e-12, abs=1e-12)
    assert target_full["days_since_high"] == 5
    assert target_full["high_freq_same_weekday"] == pytest.approx(0.80, rel=1e-12, abs=1e-12)
    assert target_full["weekday"] == pd.Timestamp("20260708").weekday()
    assert target_full["is_wed"] == 1
    assert target_full["is_tue"] == 0
    assert target_full["day_of_month"] == 8
    assert target_full["day_suffix"] == 8
    assert target_full["is_zorome"] == 0
    assert target_full["is_strong_zorome"] == 0
    assert target_full["is_event_day"] == 0
    assert target_full["kakuban_rank_min"] == 1
    assert target_full["kakuban_rank_max"] == 2
    assert target_full["section_size"] == 2
    assert target_full["is_corner1"] == 1
    assert target_full["side_lr"] == "L"

    strong_row = full.loc[full["date"].eq("20260707") & full["machine_number"].eq(1001)].iloc[0]
    assert strong_row["is_strong_zorome"] == 1
    assert strong_row["is_event_day"] == 1

    event_row = full.loc[full["date"].eq("20260711") & full["machine_number"].eq(1001)].iloc[0]
    assert event_row["is_zorome"] == 1
    assert event_row["is_event_day"] == 1

    thirty_row = full.loc[full["date"].eq("20260730") & full["machine_number"].eq(1001)].iloc[0]
    assert thirty_row["is_event_day"] == 1

    assert {
        "b_machine_90d",
        "b_machine_180d",
        "p_high_lag1",
        "p_high_lag2",
        "p_high_lag1_event",
        "days_since_high",
        "high_freq_same_weekday",
        "weekday",
        "is_mon",
        "is_tue",
        "is_wed",
        "is_thu",
        "is_fri",
        "is_sat",
        "is_sun",
        "day_of_month",
        "day_suffix",
        "is_zorome",
        "is_strong_zorome",
        "is_month_end",
        "is_month_start",
        "is_event_day",
        "kakuban_rank_min",
        "kakuban_rank_max",
        "section_size",
        "is_corner1",
        "side_lr",
    } <= set(full.columns)


def test_main_writes_stage3_csv(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage3_features as stage3

    stage2_csv = tmp_path / "stage2_daily_posterior.csv"
    _make_stage2_frame().to_csv(stage2_csv, index=False, encoding="utf-8-sig")
    output_dir = tmp_path / "out"

    exit_code = stage3.main(["--hall", "蒲田7", "--stage2-csv", str(stage2_csv), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "stage3_features.csv").exists()


def test_stage3_features_leave_layout_columns_missing_when_layout_is_empty() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage3_features as stage3

    frame = _make_stage2_frame()
    empty_layout = pd.DataFrame(
        columns=["machine_number", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"]
    )

    out = stage3.build_stage3_features(frame, hall="arrow", layout_frame=empty_layout)

    assert len(out) == len(frame)
    assert out["kakuban_rank_min"].isna().all()
    assert out["section_size"].isna().all()
    assert out["side_lr"].isna().all()
