from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _build_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2026-01-01", periods=210, freq="D")
    stage3_rows = []
    stage5_rows = []
    for day_idx, date in enumerate(dates):
        weekday = int(date.weekday())
        is_event = int(date.day in {1, 7, 11, 17, 21, 27, 30} or date.day == date.month or date.is_month_end)
        for machine_number in range(1001, 1013):
            machine_offset = machine_number - 1001
            family_key = ["MYV", "IMEX", "GOGO3", "FUNKY2"][machine_offset % 4]
            section = "A" if machine_number <= 1004 else ("B" if machine_number <= 1008 else "C")
            pct_family = float(np.clip(0.18 + 0.035 * machine_offset + 0.0015 * day_idx, 0.01, 0.99))
            pct_section = float(np.clip(pct_family - 0.01 * (1 if section == "A" else -1), 0.01, 0.99))
            stage5_rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_number": machine_number,
                    "machine_name": f"Machine-{machine_number}",
                    "family_key": family_key,
                    "section": section,
                    "G": 1000 + machine_offset * 10,
                    "rb": 3 + (machine_offset % 4),
                    "bb": 1 + (machine_offset % 3),
                    "p_high": 0.12 + 0.01 * machine_offset,
                    "e_setting": 1.0 + 0.2 * machine_offset,
                    "e_payout": 96.0 + 0.1 * machine_offset,
                    "weekday": weekday,
                    "day_of_month": int(date.day),
                    "is_event_day": is_event,
                    "kakuban_rank_min": (machine_offset % 12) + 1,
                    "kakuban_rank_max": 12 - (machine_offset % 12),
                    "section_size": 4 if section == "A" else 3,
                    "is_corner1": int(machine_offset in {0, 11}),
                    "side_lr": "L" if machine_number <= 1006 else "R",
                    "pct_family": pct_family,
                    "pct_section": pct_section,
                }
            )
            stage3_rows.append(
                {
                    "date": date.strftime("%Y%m%d"),
                    "machine_number": machine_number,
                    "machine_name": f"Machine-{machine_number}",
                    "G": 1000 + machine_offset * 10,
                    "rb": 3 + (machine_offset % 4),
                    "bb": 1 + (machine_offset % 3),
                    "p_high": 0.12 + 0.01 * machine_offset,
                    "e_setting": 1.0 + 0.2 * machine_offset,
                    "e_payout": 96.0 + 0.1 * machine_offset,
                    "kakuban_rank_min": (machine_offset % 12) + 1,
                    "kakuban_rank_max": 12 - (machine_offset % 12),
                    "section_size": 4 if section == "A" else 3,
                    "is_corner1": int(machine_offset in {0, 11}),
                    "side_lr": "L" if machine_number <= 1006 else "R",
                    "b_machine_90d": 0.22 + 0.002 * machine_offset + 0.0005 * day_idx,
                    "b_machine_180d": 0.25 + 0.003 * machine_offset + 0.0007 * day_idx,
                    "p_high_lag1": 0.10 + 0.001 * machine_offset,
                    "p_high_lag2": 0.09 + 0.001 * machine_offset,
                    "p_high_lag1_event": 0.08 + 0.001 * machine_offset,
                    "days_since_high": min(day_idx, 30),
                    "high_freq_same_weekday": 0.18 + 0.01 * machine_offset,
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
    return pd.DataFrame(stage3_rows), pd.DataFrame(stage5_rows)


def _write_db(path: Path, stage3: pd.DataFrame, stage5: pd.DataFrame) -> None:
    merged = stage3.merge(
        stage5.loc[:, ["date", "machine_number", "machine_name", "pct_family"]],
        on=["date", "machine_number", "machine_name"],
        how="inner",
        validate="one_to_one",
    )
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                games_normalized INTEGER,
                diff_coins_normalized INTEGER,
                bb_count INTEGER,
                rb_count INTEGER
            )
            """
        )
        rows = []
        for idx, row in merged.reset_index(drop=True).iterrows():
            games = int(row["G"])
            diff = int(round((row["pct_family"] - 0.5) * 1200 + (idx % 7) * 3))
            rows.append(
                (
                    row["date"],
                    int(row["machine_number"]),
                    row["machine_name"],
                    games,
                    diff,
                    int(row["bb"]),
                    int(row["rb"]),
                )
            )
        conn.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()


def test_stage5_alloc_outputs_tables_and_summary(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_alloc_eda as stage5_alloc

    stage3, stage5 = _build_frames()
    stage3_csv = tmp_path / "stage3_features.csv"
    stage5_csv = tmp_path / "stage5_rank_daily.csv"
    output_dir = tmp_path / "alloc"
    stage3.to_csv(stage3_csv, index=False, encoding="utf-8-sig")
    stage5.to_csv(stage5_csv, index=False, encoding="utf-8-sig")

    outputs = stage5_alloc.build_stage5_alloc_outputs(
        hall="闥ｲ逕ｰ7", stage3_csv=stage3_csv, stage5_csv=stage5_csv, output_dir=output_dir
    )
    stage5_alloc.save_stage5_alloc_outputs(outputs, output_dir)

    assert isinstance(outputs["machine_weekday"], pd.DataFrame)
    assert {"machine_number", "weekday", "weekday_name", "n_rows", "mean_pct_family"} <= set(
        outputs["machine_weekday"].columns
    )
    assert isinstance(outputs["family_gap"], pd.DataFrame)
    assert {"family_key", "section", "n_rows", "mean_pct_gap", "mean_pct_family", "mean_pct_section"} <= set(
        outputs["family_gap"].columns
    )
    assert (output_dir / "stage5_alloc_machine_weekday.csv").exists()
    assert (output_dir / "stage5_alloc_machine_dd.csv").exists()
    assert (output_dir / "stage5_alloc_section_event_day.csv").exists()
    assert (output_dir / "stage5_alloc_kakuban_rank_min_section_size.csv").exists()
    assert (output_dir / "stage5_alloc_family_gap.csv").exists()
    assert (output_dir / "stage5_alloc_summary.md").exists()
    assert "Stage 5 Allocation EDA" in (output_dir / "stage5_alloc_summary.md").read_text(encoding="utf-8")


def test_stage5_alloc_outputs_layoutless_hall_as_partial_n_a(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_alloc_eda as stage5_alloc

    stage3, stage5 = _build_frames()
    stage3 = stage3.copy()
    stage5 = stage5.copy()
    for frame in (stage3, stage5):
        frame["section"] = pd.NA
        frame["kakuban_rank_min"] = pd.NA
        frame["section_size"] = pd.NA
    stage3_csv = tmp_path / "stage3_features.csv"
    stage5_csv = tmp_path / "stage5_rank_daily.csv"
    output_dir = tmp_path / "alloc_empty_layout"
    stage3.to_csv(stage3_csv, index=False, encoding="utf-8-sig")
    stage5.to_csv(stage5_csv, index=False, encoding="utf-8-sig")

    outputs = stage5_alloc.build_stage5_alloc_outputs(
        hall="arrow", stage3_csv=stage3_csv, stage5_csv=stage5_csv, output_dir=output_dir
    )
    stage5_alloc.save_stage5_alloc_outputs(outputs, output_dir)

    assert isinstance(outputs["machine_weekday"], pd.DataFrame)
    assert not outputs["machine_weekday"].empty
    assert outputs["section_event_day"].empty
    assert outputs["kakuban_rank_min_section_size"].empty
    assert outputs["family_gap"].empty
    assert "No rows." in (output_dir / "stage5_alloc_summary.md").read_text(encoding="utf-8")


def test_stage5_alloc_outputs_preserve_stage3_layout_columns(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_alloc_eda as stage5_alloc

    stage3, stage5 = _build_frames()
    stage5 = stage5.copy()
    stage5["kakuban_rank_min"] = pd.NA
    stage5["section_size"] = pd.NA
    stage3_csv = tmp_path / "stage3_features.csv"
    stage5_csv = tmp_path / "stage5_rank_daily.csv"
    output_dir = tmp_path / "alloc_layout_preserved"
    stage3.to_csv(stage3_csv, index=False, encoding="utf-8-sig")
    stage5.to_csv(stage5_csv, index=False, encoding="utf-8-sig")

    outputs = stage5_alloc.build_stage5_alloc_outputs(
        hall="kamata1", stage3_csv=stage3_csv, stage5_csv=stage5_csv, output_dir=output_dir
    )
    stage5_alloc.save_stage5_alloc_outputs(outputs, output_dir)

    kakuban = outputs["kakuban_rank_min_section_size"]
    assert isinstance(kakuban, pd.DataFrame)
    assert len(kakuban) > 1
    assert kakuban["kakuban_rank_min"].notna().all()
    assert kakuban["section_size"].notna().all()
    assert (output_dir / "stage5_alloc_kakuban_rank_min_section_size.csv").exists()


def test_stage4_real_money_outputs_b1r_and_bootstrap(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage4_real_money as stage4

    stage3, stage5 = _build_frames()
    db_path = tmp_path / "kamata7.db"
    stage3_csv = tmp_path / "stage3_features.csv"
    stage5_csv = tmp_path / "stage5_rank_daily.csv"
    output_dir = tmp_path / "real_money"
    stage3.to_csv(stage3_csv, index=False, encoding="utf-8-sig")
    stage5.to_csv(stage5_csv, index=False, encoding="utf-8-sig")
    _write_db(db_path, stage3, stage5)

    merged = stage3.merge(
        stage5.loc[:, ["date", "machine_number", "machine_name", "pct_family"]],
        on=["date", "machine_number", "machine_name"],
        how="inner",
        validate="one_to_one",
    )
    merged["date_dt"] = pd.to_datetime(merged["date"], format="%Y%m%d")
    ranked = stage4._add_b_rank_features(merged)
    first_machine = ranked.loc[ranked["machine_number"].eq(1001)].sort_values("date_dt")
    assert first_machine.iloc[0]["b_rank_180d"] == pytest.approx(0.5, abs=1e-12)
    assert first_machine.iloc[-1]["b_rank_180d"] != pytest.approx(0.5, abs=1e-12)

    outputs = stage4.build_stage4_real_money_outputs(
        hall="闥ｲ逕ｰ7",
        db_path=db_path,
        stage3_csv=stage3_csv,
        stage5_csv=stage5_csv,
        output_dir=output_dir,
    )
    stage4.save_stage4_real_money_outputs(outputs, output_dir)

    selection_tables = outputs["selection_tables"]
    assert set(selection_tables) >= {"B0", "B1", "B1R"}
    assert {
        "date",
        "method",
        "selected_rank",
        "machine_number",
        "machine_name",
        "score",
        "games_normalized",
        "diff_coins_normalized",
        "pay_rate_individual",
    } <= set(selection_tables["B1R"].columns)
    summary = outputs["summary"]
    assert isinstance(summary, pd.DataFrame)
    assert set(summary["method"]) == {"B0", "B1", "B1R"}
    assert summary["mean_lift_pp_weighted"].notna().any()
    bootstrap = outputs["bootstrap_json"]
    assert isinstance(bootstrap, dict)
    assert {"B1R_minus_B0", "B1R_minus_B1", "B1_minus_B0"} <= set(bootstrap["comparisons"])
    assert (output_dir / "stage4_daily_selections_B0.csv").exists()
    assert (output_dir / "stage4_daily_selections_B1.csv").exists()
    assert (output_dir / "stage4_daily_selections_B1R.csv").exists()
    assert (output_dir / "stage4_real_money_summary.csv").exists()
    assert (output_dir / "stage4_real_money_bootstrap_ci.json").exists()
    saved = json.loads((output_dir / "stage4_real_money_bootstrap_ci.json").read_text(encoding="utf-8"))
    assert saved["metric"] == "lift_pp_weighted"


def test_stage5_shrinkage_bias_check_outputs(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage5_shrinkage_bias_check as bias_check

    stage3, stage5 = _build_frames()
    db_path = tmp_path / "mitoya.db"
    stage3_csv = tmp_path / "stage3_features.csv"
    stage5_csv = tmp_path / "stage5_rank_daily.csv"
    output_dir = tmp_path / "bias_check"
    stage3.to_csv(stage3_csv, index=False, encoding="utf-8-sig")
    stage5.to_csv(stage5_csv, index=False, encoding="utf-8-sig")
    _write_db(db_path, stage3, stage5)

    outputs = bias_check.build_stage5_shrinkage_bias_check_outputs(
        hall="mitoya",
        db_path=db_path,
        stage3_csv=stage3_csv,
        stage5_csv=stage5_csv,
        output_dir=output_dir,
    )
    bias_check.save_stage5_shrinkage_bias_check_outputs(outputs, output_dir)

    machine_summary = outputs["machine_summary"]
    assert isinstance(machine_summary, pd.DataFrame)
    assert list(machine_summary.columns) == ["machine_number", "mean_G", "raw_pct_family_180d", "b_rank_180d"]
    assert (output_dir / "stage5_shrinkage_bias_check.csv").exists()
    assert np.isfinite(outputs["correlation_mean_G_b_rank_180d"])
