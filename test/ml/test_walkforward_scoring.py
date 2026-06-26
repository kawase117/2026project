from __future__ import annotations

from pathlib import Path

import pandas as pd

from ml.experiments.walkforward_scoring import config as wf_config
from ml.experiments.walkforward_scoring import compare_v7 as wf_compare
from ml.experiments.walkforward_scoring import report_generator as wf_report
from ml.experiments.walkforward_scoring import scoring_model as wf_scoring
from ml.experiments.walkforward_scoring import walk_forward_engine as wf_engine


def _make_row(
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


def test_variant_configs_include_expected_baselines() -> None:
    variants = wf_config.build_variant_configs()

    assert list(variants) == [
        "v1_baseline",
        "v2_dd_individual",
        "v3_hist_payout",
        "v4_kakuban_fix",
        "v5_optimized",
        "v6a_hit_an",
        "v6b_seg_weights",
        "v6c_short_window_30",
        "v6d_short_window_7",
        "v7_lift_weights",
        "v8_dynamic",
        "v9a_blend_07",
        "v9b_blend_05",
        "v9c_percentile",
        "v10a_dow_boost",
        "v10b_sat_adj",
        "v10c_full",
        "v10d_boost_quarter",
        "v10e_boost_half",
        "v11_seg_weights",
    ]
    assert variants["v1_baseline"].dd_mode == "bin"
    assert variants["v4_kakuban_fix"].use_new_kakuban is True
    assert variants["v5_optimized"].optimize_weights is True
    assert variants["v5_optimized"].hist_metric == "payout"
    assert variants["v6a_hit_an"].hist_metric == "hit_an"
    assert variants["v6b_seg_weights"].use_segment_weights is True
    assert variants["v6c_short_window_30"].hist_window_a == 30
    assert variants["v6d_short_window_7"].hist_window_a == 7
    assert variants["v7_lift_weights"].use_v7_weights is True
    assert variants["v8_dynamic"].use_v8_dynamic is True
    assert variants["v9a_blend_07"].use_v8_dynamic is True
    assert variants["v9a_blend_07"].blend_alpha == 0.7
    assert variants["v9b_blend_05"].blend_alpha == 0.5
    assert variants["v9c_percentile"].use_percentile_norm is True
    assert variants["v10a_dow_boost"].use_dow_kakuban_boost is True
    assert variants["v10b_sat_adj"].use_saturday_adjacent is True
    assert variants["v10c_full"].use_dow_kakuban_boost is True
    assert variants["v10c_full"].use_saturday_adjacent is True


def test_score_day_v9_blend_combines_global_and_segment_scores(monkeypatch: object) -> None:
    train = pd.DataFrame(
        [
            _make_row(
                date="2026-03-01",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=100,
            ),
        ]
    )
    actual = pd.DataFrame(
        [
            _make_row(
                date="2026-03-02",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=10,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=2002,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=20,
            ),
        ]
    )

    def _fake_build_component_columns(*args: object, **kwargs: object) -> pd.DataFrame:
        frame = actual.copy()
        frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
        frame["segment"] = ["2F_L_N", "3F_R_N"]
        frame["dd"] = [2, 2]
        frame["c1"] = [1.0, 2.0]
        frame["c2"] = [1.0, 2.0]
        frame["c3"] = [1.0, 2.0]
        frame["c4"] = [1.0, 2.0]
        frame["c5"] = [1.0, 2.0]
        frame["c6"] = [1.0, 2.0]
        frame["hist_hit_an"] = [0.0, 0.0]
        return frame

    monkeypatch.setattr(wf_scoring, "_build_component_columns", _fake_build_component_columns)
    monkeypatch.setattr(wf_scoring, "_score_from_components", lambda frame, weights, use_segment_weights=False: pd.Series([10.0, 20.0], index=frame.index))
    monkeypatch.setattr(wf_scoring, "_score_from_components_v8", lambda frame, train, test_date=None: pd.Series([100.0, 0.0], index=frame.index))

    variant = wf_config.VariantConfig(
        variant_id="v9a_blend_07",
        dd_mode="individual",
        hist_metric="hit_an",
        use_new_kakuban=True,
        use_v8_dynamic=True,
        blend_alpha=0.7,
    )
    scored = wf_scoring.score_day(train, actual, variant)

    assert list(scored["machine_number"]) == [2001, 2002]
    assert list(scored["composite"]) == [37.0, 14.0]


def test_score_day_v9_percentile_uses_segment_strength(monkeypatch: object) -> None:
    coords = wf_scoring.load_coords_bundle()
    left_machine = int(coords.loc[(coords["floor"] == "2F") & (coords["lr"] == "L"), "machine_number"].iloc[0])
    right_machine = int(coords.loc[(coords["floor"] == "3F") & (coords["lr"] == "R"), "machine_number"].iloc[0])

    train = pd.DataFrame(
        [
            _make_row(
                date="2026-03-01",
                machine_number=left_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=100,
            ),
            _make_row(
                date="2026-03-01",
                machine_number=right_machine,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
        ]
    )
    actual = pd.DataFrame(
        [
            _make_row(
                date="2026-03-02",
                machine_number=left_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=10,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=left_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=20,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=right_machine,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=30,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=right_machine,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=40,
            ),
        ]
    )

    def _fake_build_component_columns(*args: object, **kwargs: object) -> pd.DataFrame:
        frame = actual.copy()
        frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
        frame["segment"] = ["2F_L_N", "2F_L_N", "3F_R_N", "3F_R_N"]
        frame["dd"] = [2, 2, 2, 2]
        frame["c1"] = [1.0, 2.0, 1.0, 2.0]
        frame["c2"] = [1.0, 2.0, 1.0, 2.0]
        frame["c3"] = [1.0, 2.0, 1.0, 2.0]
        frame["c4"] = [1.0, 2.0, 1.0, 2.0]
        frame["c5"] = [1.0, 2.0, 1.0, 2.0]
        frame["c6"] = [1.0, 2.0, 1.0, 2.0]
        frame["hist_hit_an"] = [0.0, 0.0, 0.0, 0.0]
        return frame

    monkeypatch.setattr(wf_scoring, "_build_component_columns", _fake_build_component_columns)
    monkeypatch.setattr(wf_scoring, "_score_from_components_v8", lambda frame, train, test_date=None: pd.Series([0.2, 0.8, 0.3, 0.7], index=frame.index))

    variant = wf_config.VariantConfig(
        variant_id="v9c_percentile",
        dd_mode="individual",
        hist_metric="hit_an",
        use_new_kakuban=True,
        use_v8_dynamic=True,
        blend_alpha=0.0,
        use_percentile_norm=True,
    )
    scored = wf_scoring.score_day(train, actual, variant)

    assert list(scored["machine_number"]) == [left_machine, right_machine, left_machine, right_machine]
    assert list(scored["composite"]) == [1.0, 0.5, 0.5, 0.25]


def test_score_day_v7_includes_2f_r_n() -> None:
    coords = wf_scoring.load_coords_bundle()
    left_machine = int(coords.loc[(coords["floor"] == "2F") & (coords["lr"] == "L"), "machine_number"].iloc[0])
    right_machine = int(coords.loc[(coords["floor"] == "2F") & (coords["lr"] == "R"), "machine_number"].iloc[0])

    train = pd.DataFrame(
        [
            _make_row(
                date="2026-03-01",
                machine_number=left_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=100,
            ),
            _make_row(
                date="2026-03-01",
                machine_number=right_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=200,
            ),
        ]
    )
    actual = pd.DataFrame(
        [
            _make_row(
                date="2026-03-02",
                machine_number=left_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=right_machine,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
        ]
    )

    scored = wf_scoring.score_day(train, actual, wf_config.build_variant_configs()["v7_lift_weights"])

    assert "2F_L_N" in set(scored["segment"].unique())
    assert "2F_R_N" in set(scored["segment"].unique())


def test_score_day_uses_past_rows_only_and_prefers_stronger_history() -> None:
    train = pd.DataFrame(
        [
            _make_row(
                date="2026-03-01",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=400,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=500,
            ),
            _make_row(
                date="2026-03-01",
                machine_number=2002,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=-200,
            ),
            _make_row(
                date="2026-03-02",
                machine_number=2002,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=-100,
            ),
        ]
    )
    actual = pd.DataFrame(
        [
            _make_row(
                date="2026-03-03",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=0,
            ),
            _make_row(
                date="2026-03-03",
                machine_number=2002,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=2000,
            ),
        ]
    )

    scored = wf_scoring.score_day(train, actual, wf_config.build_variant_configs()["v4_kakuban_fix"])

    assert list(scored.sort_values("composite", ascending=False)["machine_number"]) == [2001, 2002]
    assert scored.loc[scored["machine_number"].eq(2001), "hist_diff"].iloc[0] > 0
    assert scored.loc[scored["machine_number"].eq(2002), "hist_diff"].iloc[0] < 0


def test_score_day_uses_family_thresholds_and_a_window_fallbacks() -> None:
    train_rows = [
        _make_row(
            date="2026-03-01",
            machine_number=3001,
            machine_name="マイジャグラーV",
            last_digit="1",
            games_normalized=1000,
            diff_coins_normalized=150,
        ),
        _make_row(
            date="2026-03-02",
            machine_number=3001,
            machine_name="マイジャグラーV",
            last_digit="1",
            games_normalized=1000,
            diff_coins_normalized=160,
        ),
        _make_row(
            date="2026-03-09",
            machine_number=3001,
            machine_name="マイジャグラーV",
            last_digit="1",
            games_normalized=1000,
            diff_coins_normalized=180,
        ),
        _make_row(
            date="2026-02-20",
            machine_number=3003,
            machine_name="ファンキージャグラー2",
            last_digit="3",
            games_normalized=1000,
            diff_coins_normalized=155,
        ),
        _make_row(
            date="2026-02-25",
            machine_number=3003,
            machine_name="ファンキージャグラー2",
            last_digit="3",
            games_normalized=1000,
            diff_coins_normalized=165,
        ),
        _make_row(
            date="2026-03-04",
            machine_number=3002,
            machine_name="スマスロ北斗の拳",
            last_digit="2",
            games_normalized=1000,
            diff_coins_normalized=50,
        ),
        _make_row(
            date="2026-03-05",
            machine_number=3002,
            machine_name="スマスロ北斗の拳",
            last_digit="2",
            games_normalized=1000,
            diff_coins_normalized=60,
        ),
    ]
    actual_rows = [
        _make_row(
            date="2026-03-10",
            machine_number=3001,
            machine_name="マイジャグラーV",
            last_digit="1",
            games_normalized=1000,
            diff_coins_normalized=0,
        ),
        _make_row(
            date="2026-03-10",
            machine_number=3003,
            machine_name="ファンキージャグラー2",
            last_digit="3",
            games_normalized=1000,
            diff_coins_normalized=0,
        ),
        _make_row(
            date="2026-03-10",
            machine_number=3002,
            machine_name="スマスロ北斗の拳",
            last_digit="2",
            games_normalized=1000,
            diff_coins_normalized=0,
        ),
    ]

    train = pd.DataFrame(train_rows)
    actual = pd.DataFrame(actual_rows)
    variant = wf_config.build_variant_configs()["v6c_short_window_30"]
    scored = wf_scoring.score_day(train, actual, variant)

    a_row = scored.loc[scored["machine_number"].eq(3001)].iloc[0]
    a_far_row = scored.loc[scored["machine_number"].eq(3003)].iloc[0]
    n_row = scored.loc[scored["machine_number"].eq(3002)].iloc[0]

    assert a_row["hist_hit_an"] == 100.0
    assert a_far_row["hist_hit_an"] == 100.0
    assert n_row["hist_hit_an"] == 0.0
    assert a_row["a_seg_hist_coverage"] == 100.0
    assert a_row["a_seg_fallback_count"] == 0

    short_variant = wf_config.build_variant_configs()["v6d_short_window_7"]
    short_scored = wf_scoring.score_day(train, actual, short_variant)
    short_a_row = short_scored.loc[short_scored["machine_number"].eq(3001)].iloc[0]
    short_a_far_row = short_scored.loc[short_scored["machine_number"].eq(3003)].iloc[0]

    assert short_a_row["hist_hit_an"] == 100.0
    assert short_a_far_row["hist_hit_an"] == 0.0
    assert short_a_row["a_seg_hist_coverage"] == 50.0
    assert short_a_far_row["a_seg_hist_coverage"] == 50.0
    assert short_a_row["a_seg_fallback_count"] == 1
    assert short_a_far_row["a_seg_fallback_count"] == 1


def test_summarize_metrics_includes_threshold_hits() -> None:
    rows = pd.DataFrame(
        [
            _make_row(
                date="2026-03-03",
                machine_number=2001,
                machine_name="Alpha",
                last_digit="1",
                games_normalized=1000,
                diff_coins_normalized=4000,
            ),
            _make_row(
                date="2026-03-03",
                machine_number=2002,
                machine_name="Beta",
                last_digit="2",
                games_normalized=1000,
                diff_coins_normalized=3000,
            ),
            _make_row(
                date="2026-03-03",
                machine_number=2003,
                machine_name="Gamma",
                last_digit="3",
                games_normalized=1000,
                diff_coins_normalized=-1000,
            ),
        ]
    )
    actual = rows.copy()

    metrics = wf_engine._summarize_metrics(rows, actual)

    assert metrics["hit_t2500"] == 2.0
    assert metrics["hit_t3500"] == 1.0
    assert metrics["hit_t4500"] == 0.0
    assert metrics["lift_t2500"] == 1.0
    assert metrics["lift_t3500"] == 1.0
    assert metrics["lift_t4500"] == 0.0


def test_run_backtest_writes_expected_bundle(tmp_path: Path) -> None:
    dates = pd.date_range("2026-01-01", periods=120, freq="D")
    rows: list[dict[str, object]] = []
    for dt in dates:
        date_str = dt.strftime("%Y%m%d")
        dd = dt.day
        rows.extend(
            [
                _make_row(
                    date=date_str,
                    machine_number=2001,
                    machine_name="Alpha",
                    last_digit=str(dd % 10),
                    games_normalized=1000,
                    diff_coins_normalized=100 + dd,
                ),
                _make_row(
                    date=date_str,
                    machine_number=2002,
                    machine_name="Beta",
                    last_digit=str((dd + 1) % 10),
                    games_normalized=1000,
                    diff_coins_normalized=-50 + dd,
                ),
                _make_row(
                    date=date_str,
                    machine_number=3001,
                    machine_name="Gamma",
                    last_digit=str((dd + 2) % 10),
                    games_normalized=1000,
                    diff_coins_normalized=10,
                ),
            ]
        )

    df = pd.DataFrame(rows)
    output_dir = tmp_path / "results"
    test_dates = [pd.Timestamp("2026-03-31"), pd.Timestamp("2026-04-02")]

    result = wf_engine.run_backtest(
        df,
        output_dir=output_dir,
        variants=("v1_baseline", "v4_kakuban_fix", "v5_optimized", "v6a_hit_an", "v6b_seg_weights"),
        windows=(90,),
        test_dates=test_dates,
        resume=False,
        min_actual_machines=1,
    )

    assert (output_dir / "summary.csv").exists()
    assert (output_dir / "daily_results.csv").exists()
    assert (output_dir / "component_analysis.csv").exists()
    assert (output_dir / "weight_optimization.csv").exists()
    assert (output_dir / "correlation_matrix.csv").exists()
    assert (output_dir / "segment_daily_results.csv").exists()
    assert (output_dir / "report.md").exists()

    summary = result["summary"]
    assert set(summary["variant"]) == {"v1_baseline", "v4_kakuban_fix", "v5_optimized", "v6a_hit_an", "v6b_seg_weights"}
    assert set(summary["window"]) == {90}
    assert set(summary["event_type"]) == {"all", "event", "non_event"}
    assert {"hit_t2500", "hit_t3500", "hit_t4500", "lift_t2500", "lift_t3500", "lift_t4500"}.issubset(summary.columns)
    assert {"hit_t2500", "hit_t3500", "hit_t4500", "lift_t2500", "lift_t3500", "lift_t4500"}.issubset(result["daily_results"].columns)
    assert "split_period" in result["daily_results"].columns
    assert set(result["daily_results"]["split_period"].dropna().unique()) <= {"front", "back"}

    report = wf_report.build_report(
        summary=result["summary"],
        daily_results=result["daily_results"],
        component_analysis=result["component_analysis"],
        weight_optimization=result["weight_optimization"],
        correlation_matrix=result["correlation_matrix"],
        extra_checks=result["extra_checks"],
        output_dir=output_dir,
    )
    assert "Walk-Forward Scoring Backtest" in report
    assert "v5_optimized" in report
    assert "Front/Back Split Verification" in report


def test_compare_v7_prints_conclusion(tmp_path: Path, capsys: object) -> None:
    results_dir = tmp_path / "results_v7_comparison"
    results_dir.mkdir()

    daily = pd.DataFrame(
        [
            {
                "test_date": "2026-03-01",
                "variant": "v6a_hit_an",
                "window": 90,
                "avg_diff": 100,
                "avg_diff_other": 20,
                "avg_diff_vs_other": 80,
                "win_rate": 50.0,
                "payout_rate": 102.0,
                "hit@50": 4.0,
                "lift@50": 1.00,
                "split_period": "front",
                "event_type": "event",
            },
            {
                "test_date": "2026-03-02",
                "variant": "v6a_hit_an",
                "window": 90,
                "avg_diff": 90,
                "avg_diff_other": 25,
                "avg_diff_vs_other": 65,
                "win_rate": 45.0,
                "payout_rate": 101.0,
                "hit@50": 3.0,
                "lift@50": 0.95,
                "split_period": "back",
                "event_type": "non_event",
            },
            {
                "test_date": "2026-03-01",
                "variant": "v6b_seg_weights",
                "window": 90,
                "avg_diff": 95,
                "avg_diff_other": 22,
                "avg_diff_vs_other": 73,
                "win_rate": 48.0,
                "payout_rate": 101.5,
                "hit@50": 3.5,
                "lift@50": 0.98,
                "split_period": "front",
                "event_type": "event",
            },
            {
                "test_date": "2026-03-02",
                "variant": "v6b_seg_weights",
                "window": 90,
                "avg_diff": 92,
                "avg_diff_other": 24,
                "avg_diff_vs_other": 68,
                "win_rate": 46.0,
                "payout_rate": 101.2,
                "hit@50": 3.2,
                "lift@50": 0.97,
                "split_period": "back",
                "event_type": "non_event",
            },
            {
                "test_date": "2026-03-01",
                "variant": "v7_lift_weights",
                "window": 90,
                "avg_diff": 110,
                "avg_diff_other": 18,
                "avg_diff_vs_other": 92,
                "win_rate": 55.0,
                "payout_rate": 103.0,
                "hit@50": 2.5,
                "lift@50": 1.10,
                "split_period": "front",
                "event_type": "event",
            },
            {
                "test_date": "2026-03-02",
                "variant": "v7_lift_weights",
                "window": 90,
                "avg_diff": 108,
                "avg_diff_other": 19,
                "avg_diff_vs_other": 89,
                "win_rate": 54.0,
                "payout_rate": 102.8,
                "hit@50": 2.7,
                "lift@50": 1.08,
                "split_period": "back",
                "event_type": "non_event",
            },
        ]
    )
    segment = pd.DataFrame(
        [
            {"segment": "2F_L_N", "variant": "v6a_hit_an", "avg_diff": 100},
            {"segment": "2F_L_N", "variant": "v6b_seg_weights", "avg_diff": 95},
            {"segment": "2F_L_N", "variant": "v7_lift_weights", "avg_diff": 110},
        ]
    )

    daily.to_csv(results_dir / "daily_results.csv", index=False, encoding="utf-8-sig")
    segment.to_csv(results_dir / "segment_daily_results.csv", index=False, encoding="utf-8-sig")

    assert wf_compare.main(["--results-dir", str(results_dir)]) == 0
    captured = capsys.readouterr().out
    assert "v7 vs v6a/v6b Walk-Forward Backtest 比較" in captured
    assert "推奨: v7採用" in captured
