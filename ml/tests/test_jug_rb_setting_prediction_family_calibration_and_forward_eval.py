from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest


def _write_db(path: Path, rows: list[dict[str, object]]) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE machine_detailed_results (
                date TEXT,
                machine_number INTEGER,
                machine_name TEXT,
                games_normalized INTEGER,
                diff_coins_normalized INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?)",
            [
                (
                    row["date"],
                    row["machine_number"],
                    row["machine_name"],
                    row["games_normalized"],
                    row["diff_coins_normalized"],
                )
                for row in rows
            ],
        )
        conn.commit()


def _stage2_frame() -> pd.DataFrame:
    rows = []
    for date, payout_base in [("20260701", 101.0), ("20260702", 102.0)]:
        rows.extend(
            [
                {
                    "date": date,
                    "machine_number": 641,
                    "machine_name": "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ",
                    "G": 1000,
                    "rb": 4,
                    "bb": 2,
                    "p_set1": 0.1,
                    "p_set2": 0.1,
                    "p_set3": 0.1,
                    "p_set4": 0.2,
                    "p_set5": 0.2,
                    "p_set6": 0.3,
                    "p_high": 0.7,
                    "e_setting": 5.4,
                    "e_payout": payout_base,
                },
                {
                    "date": date,
                    "machine_number": 642,
                    "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
                    "G": 1000,
                    "rb": 3,
                    "bb": 2,
                    "p_set1": 0.2,
                    "p_set2": 0.2,
                    "p_set3": 0.2,
                    "p_set4": 0.1,
                    "p_set5": 0.1,
                    "p_set6": 0.2,
                    "p_high": 0.4,
                    "e_setting": 3.2,
                    "e_payout": payout_base - 2.0,
                },
            ]
        )
    return pd.DataFrame(rows)


def _stage5_frame() -> pd.DataFrame:
    rows = []
    candidate_specs = [
        (641, "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ", 0.70),
        (642, "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV", 0.60),
        (674, "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ", 0.55),
        (675, "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV", 0.50),
        (733, "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ", 0.45),
    ]
    for date_idx, date in enumerate(["20260701", "20260702", "20260703"]):
        for machine_number, machine_name, base in candidate_specs:
            rows.append(
                {
                    "date": date,
                    "machine_number": machine_number,
                    "machine_name": machine_name,
                    "pct_family": min(base + 0.02 * date_idx, 0.99),
                }
            )
    return pd.DataFrame(rows)


def test_family_calibration_builds_expected_rows(tmp_path: Path, monkeypatch) -> None:
    from ml.experiments.jug_rb_setting_prediction import family_calibration_check as fam

    stage2 = _stage2_frame()
    db_rows = [
        {
            "date": row["date"],
            "machine_number": row["machine_number"],
            "machine_name": row["machine_name"],
            "games_normalized": 1000,
            "diff_coins_normalized": 30 if row["machine_number"] == 641 else 0,
        }
        for row in stage2.to_dict(orient="records")
    ]
    stage2_csv = tmp_path / "stage2_daily_posterior.csv"
    db_path = tmp_path / "hall.db"
    stage2.to_csv(stage2_csv, index=False, encoding="utf-8-sig")
    _write_db(db_path, db_rows)

    spec = fam.HallSpec("testhall", db_path, stage2_csv)
    monkeypatch.setattr(fam, "HALL_SPECS", (spec,))

    frame = fam.build_family_calibration_check()
    assert list(frame.columns) == ["hall_slug", "family_key", "n_rows", "mean_e_payout", "realized_weighted", "gap_pp"]
    assert frame.iloc[0]["hall_slug"] == "testhall"
    output_path = tmp_path / "family_calibration_check.csv"
    fam.save_family_calibration_check(frame, output_path)
    saved = pd.read_csv(output_path, encoding="utf-8-sig")
    assert len(saved) == len(frame)


def test_forward_eval_leak_guard_rejects_pre_freeze_rows() -> None:
    from ml.experiments.jug_rb_setting_prediction import stage6_forward_eval as forward_eval

    eval_frame = pd.DataFrame({"date_dt": pd.to_datetime(["2026-07-06", "2026-07-07"])})
    with pytest.raises(AssertionError):
        forward_eval._validate_eval_frame(eval_frame, freeze_date="20260706")


def test_forward_eval_reports_insufficient_data(tmp_path: Path) -> None:
    from ml.experiments.jug_rb_setting_prediction import stage6_forward_eval as forward_eval

    freeze_json = tmp_path / "freeze.json"
    stage5_csv = tmp_path / "stage5_rank_daily.csv"
    db_path = tmp_path / "mitoya.db"
    result_path = tmp_path / "stage6_forward_eval_result.json"

    freeze_json.write_text(
        json.dumps(
            {
                "freeze_date": "20260706",
                "hall": "mitoya",
                "db_path": "db/みとや大森町店.db",
                "frozen_candidates": [641, 642, 674, 675, 733],
                "selection_rule": "B1R: b_rank_180d (shrunk rolling pct_family) top-3 daily",
                "hypothesis": "みとやには少数の持続的優遇台（座席）が存在し、実差枚で+1pp級のエッジを持つ",
                "eval_protocol": {
                    "eval_start": "20260707",
                    "min_eval_days": 60,
                    "primary_metric": "selected realized weighted payout lift vs hall juggler average",
                    "secondary_metric": "lift vs deterministic-seed B0 random top-3",
                    "ci_method": "moving block bootstrap, block=7, n=2000",
                    "success_criterion": "primary metric 95%CI lower bound > 0",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _stage5_frame().to_csv(stage5_csv, index=False, encoding="utf-8-sig")
    _write_db(
        db_path,
        [
            {
                "date": "20260701",
                "machine_number": 641,
                "machine_name": "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ",
                "games_normalized": 1000,
                "diff_coins_normalized": 30,
            },
            {
                "date": "20260701",
                "machine_number": 642,
                "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
                "games_normalized": 1000,
                "diff_coins_normalized": 0,
            },
            {
                "date": "20260701",
                "machine_number": 674,
                "machine_name": "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ",
                "games_normalized": 1000,
                "diff_coins_normalized": 15,
            },
            {
                "date": "20260701",
                "machine_number": 675,
                "machine_name": "繝槭う繧ｸ繝｣繧ｰ繝ｩ繝ｼV",
                "games_normalized": 1000,
                "diff_coins_normalized": -5,
            },
            {
                "date": "20260701",
                "machine_number": 733,
                "machine_name": "繧ｦ繝ｫ繝医Λ繝溘Λ繧ｯ繝ｫ繧ｸ繝｣繧ｰ繝ｩ繝ｼ",
                "games_normalized": 1000,
                "diff_coins_normalized": -10,
            },
        ],
    )

    result = forward_eval.build_forward_eval_result(freeze_json=freeze_json, db_path=db_path, stage5_csv=stage5_csv)
    forward_eval.save_forward_eval_result(result, result_path)

    assert result["status"] == "insufficient_data"
    assert result["message"] == "データ不足（現在0日）"
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["status"] == "insufficient_data"
