from __future__ import annotations

from pathlib import Path

import pandas as pd


def _make_source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "20260707", "machine_number": 101, "machine_name": "alpha", "diff": 100, "games": 1000},
            {"date": "20260707", "machine_number": 102, "machine_name": "beta", "diff": 50, "games": 1000},
            {"date": "20260708", "machine_number": 101, "machine_name": "alpha", "diff": 120, "games": 1000},
            {"date": "20260708", "machine_number": 102, "machine_name": "beta", "diff": 80, "games": 1000},
            {"date": "20260709", "machine_number": 101, "machine_name": "alpha", "diff": 140, "games": 1000},
            {"date": "20260709", "machine_number": 102, "machine_name": "beta", "diff": 60, "games": 1000},
        ]
    )


def _make_daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "date": "20260701",
                "date_dt": pd.Timestamp("2026-07-01"),
                "dd": 1,
                "month": 7,
                "year_month": "202607",
                "day_of_week": "Wed",
                "weekday_nth": "Wed1",
                "is_weekend": 0,
                "is_x_day": 1,
                "dd_bucket": "1-7",
                "budget_index": -5.0,
                "budget_regime": "under_budget",
            },
            {
                "hall": "蒲田7",
                "date": "20260702",
                "date_dt": pd.Timestamp("2026-07-02"),
                "dd": 2,
                "month": 7,
                "year_month": "202607",
                "day_of_week": "Thu",
                "weekday_nth": "Thu1",
                "is_weekend": 0,
                "is_x_day": 0,
                "dd_bucket": "1-7",
                "budget_index": 3.0,
                "budget_regime": "over_budget",
            },
            {
                "hall": "蒲田7",
                "date": "20260703",
                "date_dt": pd.Timestamp("2026-07-03"),
                "dd": 3,
                "month": 7,
                "year_month": "202607",
                "day_of_week": "Wed",
                "weekday_nth": "Wed1",
                "is_weekend": 0,
                "is_x_day": 0,
                "dd_bucket": "1-7",
                "budget_index": 2.0,
                "budget_regime": "over_budget",
            },
        ]
    )


def test_prepare_source_frame_derives_date_features_from_date_column() -> None:
    from eda import hall_budget_allocation_light as analysis

    frame = analysis.prepare_source_frame(_make_source_frame(), hall="蒲田7")

    assert frame.loc[0, "date_dt"] == pd.Timestamp("2026-07-07")
    assert frame.loc[0, "dd"] == 7
    assert frame.loc[0, "is_x_day"] == 1
    assert frame.loc[0, "is_weekend"] == 0
    assert frame.loc[0, "weekday_nth"] == "Tue1"


def test_classify_budget_regime_uses_cutoffs() -> None:
    from eda import hall_budget_allocation_light as analysis

    assert analysis.classify_budget_regime(-1.25) == "under_budget"
    assert analysis.classify_budget_regime(0.0) == "balanced"
    assert analysis.classify_budget_regime(1.25) == "over_budget"


def test_allocation_by_axis_share_math_is_normalized() -> None:
    from eda import hall_budget_allocation_light as analysis

    allocation = analysis.build_allocation_by_axis(_make_daily_frame(), axes=("day_of_week",))

    wed = allocation.loc[allocation["axis_level"].eq("Wed")].iloc[0]
    thu = allocation.loc[allocation["axis_level"].eq("Thu")].iloc[0]

    assert round(float(wed["budget_abs_share"]), 3) == 0.700
    assert round(float(thu["budget_abs_share"]), 3) == 0.300
    assert round(float(allocation["budget_abs_share"].sum()), 6) == 1.0


def test_offset_pair_diagnostics_finds_exact_offsets() -> None:
    from eda import hall_budget_allocation_light as analysis

    offset_pairs = analysis.build_offset_pairs(_make_daily_frame(), offsets=(1,))

    assert offset_pairs["offset_days"].tolist() == [1, 1]
    assert offset_pairs["date"].dt.strftime("%Y%m%d").tolist() == ["20260701", "20260702"]
    assert offset_pairs["other_date"].dt.strftime("%Y%m%d").tolist() == ["20260702", "20260703"]
    assert offset_pairs["delta_budget_index"].tolist() == [8.0, -1.0]


def test_kakuban_bin_groups_numbers_in_tens() -> None:
    from eda import hall_budget_allocation_light as analysis

    assert analysis._kakuban_bin_from_number(2001) == "2001-2010"
    assert analysis._kakuban_bin_from_number(2010) == "2001-2010"
    assert analysis._kakuban_bin_from_number(2011) == "2011-2020"


def test_kakuban_rank_bin_from_number_uses_local_position_thirds() -> None:
    from eda import hall_budget_allocation_light as analysis

    assert analysis._kakuban_rank_bin_from_number(2001) == "0-2"
    assert analysis._kakuban_rank_bin_from_number(2003) == "0-2"
    assert analysis._kakuban_rank_bin_from_number(2004) == "3-5"
    assert analysis._kakuban_rank_bin_from_number(2006) == "3-5"
    assert analysis._kakuban_rank_bin_from_number(2007) == "6-9"
    assert analysis._kakuban_rank_bin_from_number(2010) == "6-9"


def test_plan_source_frame_uses_rank_based_kakuban_for_exact_layout_halls() -> None:
    from eda import hall_budget_allocation_light as analysis

    raw = pd.DataFrame(
        [
            {
                "date": "20260701",
                "machine_number": 2001,
                "machine_name": "マイジャグラーV",
                "games_normalized": 1000,
                "diff_coins_normalized": 300,
            },
            {
                "date": "20260701",
                "machine_number": 2007,
                "machine_name": "アイムジャグラーEX",
                "games_normalized": 1000,
                "diff_coins_normalized": -100,
            },
        ]
    )

    frame = analysis.prepare_plan_source_frame(raw, hall="蒲田7", min_games=200)
    assert frame["kakuban_bin"].tolist() == ["0-2", "6-9"]
    # section for an exact-layout hall keeps the real contiguous-run grouping,
    # not the machine-number decade substitute.
    assert frame["section"].tolist() != ["2001-2010", "2001-2010"]


def test_run_hall_analysis_writes_expected_outputs(tmp_path: Path) -> None:
    from eda import hall_budget_allocation_light as analysis

    result = analysis.run_hall_analysis(
        "蒲田7",
        raw=_make_source_frame(),
        output_root=tmp_path,
        model_min_class_count=10,
        offsets=(1, 2),
    )

    assert result["daily"].shape[0] == 3
    assert result["model"].iloc[0]["note"].startswith("skipped")
    assert (tmp_path / "蒲田7_daily_budget_index.csv").exists()
    assert (tmp_path / "蒲田7_allocation_by_axis.csv").exists()
    assert (tmp_path / "蒲田7_offset_pairs.csv").exists()
    assert (tmp_path / "蒲田7_lightweight_model.csv").exists()
    assert (tmp_path / "蒲田7_report.md").exists()
    assert (tmp_path / "summary_report.csv").exists()


def test_compute_daily_budget_index_uses_hall_relative_zscore() -> None:
    from eda import hall_budget_allocation_light as analysis

    source = pd.DataFrame(
        [
            {
                "hall": "A",
                "date": "20260701",
                "machine_number": 1,
                "machine_name": "alpha",
                "diff": -100,
                "games": 1000,
                "plus": 0,
            },
            {
                "hall": "A",
                "date": "20260701",
                "machine_number": 2,
                "machine_name": "beta",
                "diff": -100,
                "games": 1000,
                "plus": 0,
            },
            {
                "hall": "A",
                "date": "20260702",
                "machine_number": 1,
                "machine_name": "alpha",
                "diff": 0,
                "games": 1000,
                "plus": 0,
            },
            {
                "hall": "A",
                "date": "20260702",
                "machine_number": 2,
                "machine_name": "beta",
                "diff": 0,
                "games": 1000,
                "plus": 0,
            },
            {
                "hall": "A",
                "date": "20260703",
                "machine_number": 1,
                "machine_name": "alpha",
                "diff": 100,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "A",
                "date": "20260703",
                "machine_number": 2,
                "machine_name": "beta",
                "diff": 100,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "B",
                "date": "20260701",
                "machine_number": 1,
                "machine_name": "alpha",
                "diff": 900,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "B",
                "date": "20260701",
                "machine_number": 2,
                "machine_name": "beta",
                "diff": 900,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "B",
                "date": "20260702",
                "machine_number": 1,
                "machine_name": "alpha",
                "diff": 1000,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "B",
                "date": "20260702",
                "machine_number": 2,
                "machine_name": "beta",
                "diff": 1000,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "B",
                "date": "20260703",
                "machine_number": 1,
                "machine_name": "alpha",
                "diff": 1100,
                "games": 1000,
                "plus": 1,
            },
            {
                "hall": "B",
                "date": "20260703",
                "machine_number": 2,
                "machine_name": "beta",
                "diff": 1100,
                "games": 1000,
                "plus": 1,
            },
        ]
    )

    daily = analysis.build_daily_budget_index(source)
    hall_b = daily.loc[daily["hall"].eq("B")].sort_values("date")

    assert hall_b["budget_regime"].tolist() == ["under_budget", "balanced", "over_budget"]
    assert round(float(hall_b.iloc[0]["budget_zscore"]), 3) == -1.225
    assert round(float(hall_b.iloc[1]["budget_zscore"]), 3) == 0.0
    assert round(float(hall_b.iloc[2]["budget_zscore"]), 3) == 1.225


def test_summarize_offset_pairs_uses_chance_rate() -> None:
    from eda import hall_budget_allocation_light as analysis

    daily = pd.DataFrame(
        {
            "budget_regime": ["under_budget", "under_budget", "balanced", "over_budget"],
        }
    )
    offset_pairs = pd.DataFrame(
        {
            "hall": ["H", "H", "H", "H"],
            "offset_days": [7, 7, 7, 7],
            "date": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"]),
            "other_date": pd.to_datetime(["2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11"]),
            "budget_index": [1.0, 2.0, 3.0, 4.0],
            "other_budget_index": [1.5, 2.5, 3.5, 4.5],
            "delta_budget_index": [0.5, 0.5, 0.5, 0.5],
            "same_regime": [True, True, False, False],
        }
    )

    summary = analysis._summarize_offset_pairs(offset_pairs, daily)
    row = summary.iloc[0]

    assert round(float(row["expected_same_regime_rate"]), 3) == 0.375
    assert round(float(row["same_regime_rate"]), 3) == 0.500
    assert round(float(row["same_regime_uplift"]), 3) == 0.125


def test_summarize_hall_exposes_model_baseline_gap() -> None:
    from eda import hall_budget_allocation_light as analysis

    source = _make_source_frame()
    daily = _make_daily_frame()
    allocation = analysis.build_allocation_by_axis(daily, axes=("day_of_week",))
    offset_pairs = pd.DataFrame(
        columns=[
            "hall",
            "offset_days",
            "date",
            "other_date",
            "budget_index",
            "other_budget_index",
            "delta_budget_index",
            "same_regime",
        ]
    )
    model_eval = pd.DataFrame(
        [
            {
                "hall": "蒲田7",
                "model_name": "logistic_regression",
                "n_rows": 3,
                "train_rows": 2,
                "test_rows": 1,
                "positive_rows": 2,
                "negative_rows": 1,
                "positive_rate": 0.667,
                "baseline_accuracy": 0.65,
                "accuracy": 0.55,
                "accuracy_delta": -0.10,
                "balanced_accuracy": 0.50,
                "roc_auc": 0.851,
                "top_feature_1": "is_x_day:3.1600",
                "top_feature_2": "",
                "top_feature_3": "",
                "note": "trained",
            }
        ]
    )

    summary = analysis._summarize_hall("蒲田7", source, daily, allocation, offset_pairs, model_eval)
    row = summary.iloc[0]

    assert round(float(row["model_baseline_accuracy"]), 2) == 0.65
    assert round(float(row["model_accuracy"]), 2) == 0.55
    assert round(float(row["model_accuracy_delta"]), 2) == -0.10
    assert round(float(row["model_roc_auc"]), 2) == 0.85
    assert row["model_status"] == "trained_above_baseline"


def test_run_plan_output_writes_plan_style_files(tmp_path: Path) -> None:
    from eda import hall_budget_allocation_light as analysis

    raw = pd.DataFrame(
        [
            {
                "date": "20260701",
                "machine_number": 2001,
                "machine_name": "マイジャグラーV",
                "games_normalized": 1000,
                "diff_coins_normalized": 300,
            },
            {
                "date": "20260701",
                "machine_number": 3001,
                "machine_name": "スマスロ北斗の拳",
                "games_normalized": 1000,
                "diff_coins_normalized": -100,
            },
            {
                "date": "20260702",
                "machine_number": 2001,
                "machine_name": "マイジャグラーV",
                "games_normalized": 1000,
                "diff_coins_normalized": -200,
            },
            {
                "date": "20260702",
                "machine_number": 3001,
                "machine_name": "スマスロ北斗の拳",
                "games_normalized": 1000,
                "diff_coins_normalized": 200,
            },
        ]
    )

    result = analysis.run_plan_output("蒲田7", raw=raw, output_root=tmp_path, min_games=200)

    allocation = pd.read_csv(result["paths"]["allocation"])
    offset_pairs = pd.read_csv(result["paths"]["offset_pairs"])
    report_text = result["paths"]["report"].read_text(encoding="utf-8")
    kakuban_rows = allocation.loc[allocation["axis"].eq("kakuban_bin"), "axis_value"].tolist()

    assert {
        "hall",
        "date",
        "axis",
        "axis_value",
        "share_of_total_diff",
        "excess_vs_hall_day",
        "hit104_lift",
        "games_share",
    }.issubset(allocation.columns)
    assert {
        "hall",
        "axis",
        "focus_value",
        "offset_value",
        "n_days",
        "focus_mean_excess",
        "offset_mean_excess",
        "offset_gap",
        "corr_excess",
        "verdict",
    }.issubset(offset_pairs.columns)
    # 蒲田7 is an exact-layout hall: kakuban_bin uses rank_from_min thirds, not
    # the machine-number decade substitute. Both 2001 and 3001 sit at local
    # rank 0 within their row, so both fall in the "0-2" bin.
    assert kakuban_rows == ["0-2", "0-2"]
    assert "all_high" in report_text
    assert "focused_machine" in report_text
    assert "focused_category" in report_text
    assert "balanced" in report_text
    assert "recovery" in report_text
    assert "decoy_heavy" in report_text
    assert result["paths"]["summary"].exists()


def test_plan_source_frame_excludes_kamata7_anniversary() -> None:
    from eda import hall_budget_allocation_light as analysis

    raw = pd.DataFrame(
        [
            {
                "date": "20250707",
                "machine_number": 2001,
                "machine_name": "マイジャグラーV",
                "games_normalized": 1000,
                "diff_coins_normalized": 300,
            },
            {
                "date": "20250708",
                "machine_number": 2001,
                "machine_name": "マイジャグラーV",
                "games_normalized": 1000,
                "diff_coins_normalized": -200,
            },
        ]
    )

    frame = analysis.prepare_plan_source_frame(raw, hall="蒲田7", min_games=200)
    assert "20250707" not in frame["date"].astype(str).tolist()
    assert frame["date"].astype(str).tolist() == ["20250708"]


def test_plan_source_frame_uses_kakuban_bins_without_layout_csv() -> None:
    from eda import hall_budget_allocation_light as analysis

    raw = pd.DataFrame(
        [
            {
                "date": "20260701",
                "machine_number": 2001,
                "machine_name": "???????V",
                "games_normalized": 1000,
                "diff_coins_normalized": 300,
            },
            {
                "date": "20260701",
                "machine_number": 2009,
                "machine_name": "????????",
                "games_normalized": 1000,
                "diff_coins_normalized": -100,
            },
        ]
    )

    frame = analysis.prepare_plan_source_frame(raw, hall="ARROW", min_games=200)
    assert frame["section"].tolist() == ["2001-2010", "2001-2010"]
    assert frame["kakuban_bin"].tolist() == ["2001-2010", "2001-2010"]


def test_plan_report_uses_cumulative_share_label(tmp_path: Path) -> None:
    from eda import hall_budget_allocation_light as analysis

    raw = pd.DataFrame(
        [
            {
                "date": "20260701",
                "machine_number": 2001,
                "machine_name": "マイジャグラーV",
                "games_normalized": 1000,
                "diff_coins_normalized": 300,
            },
            {
                "date": "20260701",
                "machine_number": 3001,
                "machine_name": "スマスロ北斗の拳",
                "games_normalized": 1000,
                "diff_coins_normalized": -100,
            },
        ]
    )

    result = analysis.run_plan_output("蒲田7", raw=raw, output_root=tmp_path, min_games=200)
    report_text = result["paths"]["report"].read_text(encoding="utf-8")
    assert "cumulative_share_of_total_diff=" in report_text
