from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


MODEL_FEATURES = [
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
]


def _make_stage3_frame() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=220, freq="D")
    rows = []
    for date_idx, date in enumerate(dates):
        is_event = int(
            date.day in {1, 7, 11, 17, 21, 27, 30} or date.day == 22 or date.day == date.month or date.is_month_end
        )
        weekday = int(date.weekday())
        for machine_number in range(1001, 1013):
            machine_offset = machine_number - 1001
            base = 0.2 + 0.02 * machine_offset + 0.001 * (date_idx % 30) + 0.15 * is_event
            p_high = min(max(base, 0.01), 0.99)
            rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_number": machine_number,
                    "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV"
                    if machine_number <= 1006
                    else "繧ｴ繝ｼ繧ｴ繝ｼ繧ｸ繝｣繧ｰ繝ｩ繝ｼ3",
                    "G": 1000 + machine_offset * 5,
                    "rb": int(round(1000 * p_high / 10)),
                    "bb": int(round(1000 * (0.3 + 0.01 * machine_offset) / 10)),
                    "p_high": p_high,
                    "e_setting": float(1 + 5 * p_high),
                    "e_payout": float(95 + 10 * p_high),
                    "kakuban_rank_min": machine_offset + 1,
                    "kakuban_rank_max": 12 - machine_offset,
                    "section_size": 12,
                    "is_corner1": int(machine_offset in {0, 11}),
                    "side_lr": "L" if machine_number <= 1006 else "R",
                    "b_machine_90d": p_high * 0.9,
                    "b_machine_180d": p_high * 0.95 if date_idx >= 195 else np.nan,
                    "p_high_lag1": p_high - 0.01,
                    "p_high_lag2": p_high - 0.02,
                    "p_high_lag1_event": p_high - 0.05 if is_event else p_high - 0.07,
                    "days_since_high": min(date_idx, 30),
                    "high_freq_same_weekday": p_high * 0.8,
                    "weekday": weekday,
                    "is_mon": int(weekday == 0),
                    "is_tue": int(weekday == 1),
                    "is_wed": int(weekday == 2),
                    "is_thu": int(weekday == 3),
                    "is_fri": int(weekday == 4),
                    "is_sat": int(weekday == 5),
                    "is_sun": int(weekday == 6),
                    "day_of_month": int(date.day),
                    "day_suffix": int(date.day % 10),
                    "is_zorome": int(date.day in {11, 22}),
                    "is_strong_zorome": int(date.day == date.month),
                    "is_month_end": int(date.is_month_end),
                    "is_month_start": int(date.is_month_start),
                    "is_event_day": is_event,
                }
            )
    return pd.DataFrame(rows)


def test_stage4_builds_outputs_and_uses_expected_feature_contract() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage4_walkforward as stage4

    outputs = stage4.build_stage4_outputs(frame=_make_stage3_frame(), hall="蒲田7")

    summary = outputs["summary"]
    selection_tables = outputs["selection_tables"]
    bootstrap_ci = outputs["bootstrap_ci"]
    daily_metrics = outputs["daily_metrics"]

    assert isinstance(summary, pd.DataFrame)
    assert {"method", "mean_p_high_top3", "mean_payout_lift_pp", "mean_spearman"} <= set(summary.columns)
    assert set(summary["method"]) >= {"B0", "B1", "B2", "M", "M2"}
    assert isinstance(selection_tables["M"], pd.DataFrame)
    assert isinstance(selection_tables["M2"], pd.DataFrame)
    assert {
        "date",
        "method",
        "selected_rank",
        "machine_number",
        "machine_name",
        "score",
        "p_high",
        "e_setting",
        "e_payout",
    } <= set(selection_tables["M"].columns)
    assert isinstance(bootstrap_ci, dict)
    assert {"M_minus_B1", "M2_minus_B1", "B1_minus_B0"} <= set(bootstrap_ci["comparisons"])
    assert isinstance(daily_metrics, pd.DataFrame)
    assert not daily_metrics.empty

    assert set(MODEL_FEATURES).issubset(stage4.MODEL_FEATURES)
    assert set(stage4.SIDE_LR_DUMMY_FEATURES) <= set(stage4.MODEL_FEATURES_M2)
    assert not any(column in stage4.MODEL_FEATURES for column in stage4.OUTCOME_COLUMNS)
    assert not any(column in stage4.B2_FEATURES for column in stage4.OUTCOME_COLUMNS)
    assert summary["n_eval_days"].gt(0).any()
    assert summary.loc[summary["method"].eq("B2"), "n_b2_nan_dropped"].iloc[0] >= 0


def test_stage4_main_writes_requested_artifacts(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage4_walkforward as stage4

    stage3_csv = tmp_path / "stage3_features.csv"
    _make_stage3_frame().to_csv(stage3_csv, index=False, encoding="utf-8-sig")
    output_dir = tmp_path / "out"

    exit_code = stage4.main(["--hall", "蒲田7", "--stage3-csv", str(stage3_csv), "--output-dir", str(output_dir)])

    assert exit_code == 0
    for method in ("B0", "B1", "B2", "M", "M2"):
        assert (output_dir / f"stage4_daily_selections_{method}.csv").exists()
    assert (output_dir / "stage4_summary.csv").exists()
    assert (output_dir / "stage4_bootstrap_ci.json").exists()


def test_stage4_layoutless_hall_skips_m2_with_note() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage4_walkforward as stage4

    frame = _make_stage3_frame().copy()
    for column in ("kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"):
        frame[column] = pd.NA

    outputs = stage4.build_stage4_outputs(frame=frame, hall="arrow")
    summary = outputs["summary"]

    assert isinstance(summary, pd.DataFrame)
    m2_row = summary.loc[summary["method"].eq("M2")].iloc[0]
    assert m2_row["note"] == "M2 not applicable (no layout data)"
    assert m2_row["n_eval_days"] == 0
