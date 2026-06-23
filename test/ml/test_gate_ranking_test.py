from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.experiments.gate_ranking_test.run_gate_ranking_test import (
    HAS_CATBOOST,
    _build_v6b_rule_features,
    build_relative_targets,
    run_gate_ranking_test,
)
from ml.experiments.walkforward_scoring.scoring_model import ScoreContext


def _coord_row(
    *,
    machine_number: int,
    floor: str,
    section: str,
    section_min: int,
    section_max: int,
    rank_from_min: int,
    rank_from_max: int,
    section_size: int,
    section_size_group: str,
    lr: str,
    kakuban_old: int,
    kakuban_new: int,
) -> dict[str, object]:
    return {
        "machine_number": machine_number,
        "floor": floor,
        "section": section,
        "section_min": section_min,
        "section_max": section_max,
        "rank_from_min": rank_from_min,
        "rank_from_max": rank_from_max,
        "section_size": section_size,
        "section_size_group": section_size_group,
        "lr": lr,
        "kakuban_old": kakuban_old,
        "kakuban_new": kakuban_new,
    }


def _machine_row(
    *,
    date: str,
    machine_number: int,
    machine_name: str,
    last_digit: str,
    games_normalized: int,
    diff_coins_normalized: int,
) -> dict[str, object]:
    return {
        "date": date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "last_digit": last_digit,
        "is_zorome": int(last_digit in {"0", "5", "6", "9"}),
        "games_normalized": games_normalized,
        "diff_coins_normalized": diff_coins_normalized,
    }


def _build_context() -> ScoreContext:
    coords = pd.DataFrame(
        [
            _coord_row(
                machine_number=1001 + idx,
                floor="3F",
                section="3017-3030",
                section_min=3017,
                section_max=3030,
                rank_from_min=idx + 1,
                rank_from_max=5 - idx,
                section_size=5,
                section_size_group="small",
                lr="L",
                kakuban_old=idx + 1,
                kakuban_new=idx + 1,
            )
            for idx in range(5)
        ]
        + [
            _coord_row(
                machine_number=2001 + idx,
                floor="3F",
                section="3043-3057",
                section_min=3043,
                section_max=3057,
                rank_from_min=idx + 1,
                rank_from_max=15 - idx,
                section_size=15,
                section_size_group="large",
                lr="R",
                kakuban_old=idx + 1,
                kakuban_new=idx + 1,
            )
            for idx in range(15)
        ]
    )
    return ScoreContext(coords=coords)


def _build_frame() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", "2026-04-03", freq="D")
    rows: list[dict[str, object]] = []
    for dt in dates:
        date_str = dt.strftime("%Y%m%d")
        day_bias = int(dt.day)
        for idx in range(5):
            machine_number = 1001 + idx
            diff = 220 - idx * 40 + day_bias
            if dt >= pd.Timestamp("2026-04-01"):
                diff = 500 - idx * 120
            rows.append(
                _machine_row(
                    date=date_str,
                    machine_number=machine_number,
                    machine_name="ジャグラーV",
                    last_digit=str((idx + day_bias) % 10),
                    games_normalized=1000,
                    diff_coins_normalized=diff,
                )
            )
        for idx in range(15):
            machine_number = 2001 + idx
            diff = -180 + idx * 8 + day_bias
            if dt >= pd.Timestamp("2026-04-01"):
                diff = -50 + idx * 2
            rows.append(
                _machine_row(
                    date=date_str,
                    machine_number=machine_number,
                    machine_name=f"Beta-{idx + 1}",
                    last_digit=str((idx + 3 + day_bias) % 10),
                    games_normalized=1000,
                    diff_coins_normalized=diff,
                )
            )
    return pd.DataFrame(rows)


def _build_segment_daily_counts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for test_date in ["20260401", "20260402", "20260403"]:
        is_active_day = test_date != "20260403"
        rows.extend(
            [
                {
                    "date": test_date,
                    "segment": "3F_L_A",
                    "n_machines": 5,
                    "segment_avg_payout": 106.0 if is_active_day else 90.0,
                    "history_days": 90,
                    "eligible_for_gate": is_active_day,
                    "rolling_q60": 105.0,
                    "gate_positive_q60": is_active_day,
                    "rolling_q70": 105.0,
                    "gate_positive_q70": is_active_day,
                    "rolling_q80": 105.0,
                    "gate_positive_q80": is_active_day,
                    "gate_positive": is_active_day,
                    "primary_gate_quantile": 0.7,
                    "is_event": test_date.endswith("01"),
                    "dow": "Thu" if test_date.endswith("01") else "Fri",
                    "dd": int(test_date[-2:]),
                },
                {
                    "date": test_date,
                    "segment": "3F_R_N",
                    "n_machines": 15,
                    "segment_avg_payout": 97.0,
                    "history_days": 90,
                    "eligible_for_gate": True,
                    "rolling_q60": 96.0,
                    "gate_positive_q60": False,
                    "rolling_q70": 96.0,
                    "gate_positive_q70": False,
                    "rolling_q80": 96.0,
                    "gate_positive_q80": False,
                    "gate_positive": False,
                    "primary_gate_quantile": 0.7,
                    "is_event": test_date.endswith("01"),
                    "dow": "Thu" if test_date.endswith("01") else "Fri",
                    "dd": int(test_date[-2:]),
                },
            ]
        )
    return pd.DataFrame(rows)


def test_build_relative_targets_marks_segment_top20_with_boundary_inclusion() -> None:
    frame = pd.DataFrame(
        [
            {"date": "20260401", "segment": "3F_L_A", "machine_number": 1, "payout_rate": 80.0},
            {"date": "20260401", "segment": "3F_L_A", "machine_number": 2, "payout_rate": 85.0},
            {"date": "20260401", "segment": "3F_L_A", "machine_number": 3, "payout_rate": 90.0},
            {"date": "20260401", "segment": "3F_L_A", "machine_number": 4, "payout_rate": 95.0},
            {"date": "20260401", "segment": "3F_L_A", "machine_number": 5, "payout_rate": 100.0},
            {"date": "20260401", "segment": "3F_R_N", "machine_number": 6, "payout_rate": 10.0},
            {"date": "20260401", "segment": "3F_R_N", "machine_number": 7, "payout_rate": 20.0},
            {"date": "20260401", "segment": "3F_R_N", "machine_number": 8, "payout_rate": 30.0},
            {"date": "20260401", "segment": "3F_R_N", "machine_number": 9, "payout_rate": 40.0},
            {"date": "20260401", "segment": "3F_R_N", "machine_number": 10, "payout_rate": 50.0},
        ]
    )

    labeled = build_relative_targets(frame)

    a_labels = labeled[labeled["segment"].eq("3F_L_A")].sort_values("payout_rate")
    assert list(a_labels["is_top20"]) == [False, False, False, False, True]
    assert a_labels["top20_threshold"].iloc[0] == 96.0


def test_run_gate_ranking_test_writes_expected_files_and_is_deterministic(tmp_path: Path) -> None:
    frame = _build_frame()
    segment_daily_counts = _build_segment_daily_counts()
    context = _build_context()
    output_dir = tmp_path / "results"

    result = run_gate_ranking_test(
        df=frame,
        segment_daily_counts=segment_daily_counts,
        context=context,
        output_dir=output_dir,
        test_dates=[pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-02"), pd.Timestamp("2026-04-03")],
        window_days=90,
        seed=7,
    )

    assert (output_dir / "summary.csv").exists()
    assert (output_dir / "daily_results.csv").exists()
    assert (output_dir / "front_back_split.csv").exists()
    assert (output_dir / "report.md").exists()

    summary = result["summary"]
    expected_series = {"nogate_v6a", "gate_v6a", "gate_random", "gate_v6b_rule"}
    if HAS_CATBOOST:
        expected_series.add("gate_ml_shadow")
    assert set(summary["series_id"]) == expected_series
    assert set(summary["event_type"]) == {"all", "event", "non_event"}
    assert {"precision_at_10", "precision_at_15", "lift_at_10", "avg_payout_at_10", "n_days_active_lt_10"} <= set(summary.columns)
    assert summary[summary["event_type"].eq("all")]["n_test_days"].eq(2).all()
    assert summary[summary["event_type"].eq("event")]["n_test_days"].eq(1).all()
    assert summary[summary["event_type"].eq("non_event")]["n_test_days"].eq(1).all()

    daily_results = result["daily_results"]
    assert set(daily_results["series_id"]) == expected_series
    assert {"n_total_machines", "n_active_machines", "n_active_segments", "active_segments", "split_period"} <= set(daily_results.columns)
    assert set(daily_results["split_period"]) == {"front", "back"}

    front_back = result["front_back_split"]
    assert set(front_back["series_id"]) == expected_series
    assert set(front_back["split_period"]) == {"front", "back"}
    assert front_back["n_test_days"].eq(1).all()

    report_text = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "PASS / FAIL / PARTIAL" in report_text
    assert "Series Comparison (Active Days Only)" in report_text
    assert "gate_v6b_rule precision@10 > gate_v6a precision@10 (all)" in report_text
    if HAS_CATBOOST:
        assert "ML Shadow vs Rule-Based" in report_text
    assert "to_markdown()" not in report_text

    rerun = run_gate_ranking_test(
        df=frame,
        segment_daily_counts=segment_daily_counts,
        context=context,
        output_dir=tmp_path / "results_2",
        test_dates=[pd.Timestamp("2026-04-01"), pd.Timestamp("2026-04-02"), pd.Timestamp("2026-04-03")],
        window_days=90,
        seed=7,
    )
    rerun_random = rerun["daily_results"][rerun["daily_results"]["series_id"].eq("gate_random")]["precision_at_10"].tolist()
    baseline_random = daily_results[daily_results["series_id"].eq("gate_random")]["precision_at_10"].tolist()
    assert rerun_random == baseline_random


def test_build_v6b_rule_features_uses_segment_history_and_fallbacks() -> None:
    train = pd.DataFrame(
        [
            {"date": "20260101", "machine_number": 1001, "machine_name": "ジャグラーV", "games_normalized": 500, "diff_coins_normalized": 100},
            {"date": "20260101", "machine_number": 1002, "machine_name": "ジャグラーV", "games_normalized": 500, "diff_coins_normalized": -100},
            {"date": "20260102", "machine_number": 1001, "machine_name": "ジャグラーV", "games_normalized": 500, "diff_coins_normalized": 120},
            {"date": "20260102", "machine_number": 1002, "machine_name": "ジャグラーV", "games_normalized": 500, "diff_coins_normalized": -80},
            {"date": "20260103", "machine_number": 1001, "machine_name": "ジャグラーV", "games_normalized": 350, "diff_coins_normalized": 999},
        ]
    )
    actual = pd.DataFrame(
        [
            {"machine_number": 1001},
            {"machine_number": 1002},
            {"machine_number": 1003},
        ]
    )

    features = _build_v6b_rule_features(train, actual, _build_context()).set_index("machine_number")

    assert features.loc[1001, "seg_relative_hist_top20"] == 1.0
    assert features.loc[1002, "seg_relative_hist_top20"] == 0.0
    assert features.loc[1001, "seg_relative_rank_payout"] > features.loc[1002, "seg_relative_rank_payout"]
    assert features.loc[1003, "seg_relative_hist_top20"] == 0.0
    assert features.loc[1003, "seg_relative_rank_payout"] == 0.5
