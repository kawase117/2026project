# -*- coding: utf-8 -*-
"""monthly_report（層1・層2）の合成データテスト。実DB・実registryには依存しない。"""

import inspect
import json
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest import monthly_report as mr
from backtest import monthly_report_layer2 as l2

WD = "月火水木金土日"
J_SPEC = {
    "j": {
        "family_name": "J",
        "category": "ノーマル",
        "judgeable": True,
        "settings": {1: {"rb_probability": 1 / 400}, 6: {"rb_probability": 1 / 250}},
    }
}


@pytest.fixture
def tmp_path():
    """pytest.iniのrepo内basetempが権限で壊れる環境があるので、OSの一時領域を使う。"""
    with tempfile.TemporaryDirectory() as path:
        yield Path(path)


def test_wilson_boundaries():
    lo, hi = mr.wilson(0, 10)
    assert lo == 0 and hi < 0.4
    lo, hi = mr.wilson(10, 10)
    assert lo > 0.6 and hi == 1


def test_payout_pp_formula_and_zero_games_are_counted(tmp_path):
    path = tmp_path / "synthetic.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT,machine_name TEXT,machine_number INTEGER,games_normalized REAL,diff_coins_normalized REAL,bb_count REAL,rb_count REAL)"
    )
    con.executemany(
        "INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?,?)",
        [("20260901", "A", 1, 1000, 300, 1, 2), ("20260901", "A", 2, 0, 999, 0, 0)],
    )
    con.commit()
    con.close()
    out = mr.load_machine_days(path, "20260901", "20260901")
    assert len(out) == 1
    assert out.iloc[0].payout_pp == pytest.approx(10)
    assert out.attrs["excluded_zero_games"] == 1


def test_rb_posterior_is_independent_of_bb():
    spec = {
        "settings": {
            1: {"rb_probability": 0.02, "bb_probability": 0.05},
            6: {"rb_probability": 0.08, "bb_probability": 0.10},
        }
    }
    spec_no_bb = {"settings": {s: {"rb_probability": v["rb_probability"]} for s, v in spec["settings"].items()}}
    assert mr.rb_posterior(spec, 5000, rb=250) == pytest.approx(mr.rb_posterior(spec_no_bb, 5000, rb=250))


def _frame(days=12, at=False, machines=3, start=date(2026, 8, 20), games=2000, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(days):
        ds = (start + timedelta(days=i)).strftime("%Y%m%d")
        for n in range(machines):
            rows.append(
                {
                    "date": ds,
                    "machine_name": "AT" if at else "J",
                    "machine_number": n + 1,
                    "games_normalized": games,
                    "diff_coins_normalized": float(rng.normal(0, 600)),
                    "bb_count": 2 if at else 5,
                    "rb_count": int(rng.integers(3, 9)),
                }
            )
    return pd.DataFrame(rows)


def test_period_window_and_baseline_do_not_overlap():
    window, baseline = mr.period_dates("20260831", window_days=7, baseline_days=10, regime_start="20260101")
    assert set(window).isdisjoint(baseline)
    assert max(baseline) < min(window)


def test_baseline_is_clipped_at_regime_start():
    _, baseline = mr.period_dates("20260930", window_days=28, baseline_days=90, regime_start="20260706")
    assert min(baseline) == "20260706"


def test_at_has_gate_but_no_setting_posterior():
    specs = {"at": {"family_name": "AT", "category": "AT", "judgeable": False, "settings": {}}}
    out = mr.build_layer1(
        _frame(at=True), "20260831", window_days=7, baseline_days=5, regime_start="20260801", specs=specs
    )
    assert not out.empty
    assert not any("事後" in str(c) for c in out.columns)
    assert "gate_pass" in out.columns and bool(out.iloc[0].gate_pass) is False


def _gate_rows(corr, n=400, seed=1):
    rng = np.random.default_rng(seed)
    rate = rng.uniform(1 / 300, 1 / 100, n)
    noise = rng.normal(0, 1, n)
    payout = (3000 * rate + noise) if corr else noise
    g = np.full(n, 3000.0)
    return pd.DataFrame({"games_normalized": g, "bonus_total": rate * g, "payout_pp": payout})


def test_at_gate_passes_when_correlated_and_fails_when_independent():
    assert mr.at_effectiveness_gate(_gate_rows(True))["gate_pass"] is True
    independent = mr.at_effectiveness_gate(_gate_rows(False))
    assert independent["gate_pass"] is False and independent["n_gate"] == 400


def test_at_gate_needs_enough_machine_days():
    assert mr.at_effectiveness_gate(_gate_rows(True, n=100))["gate_pass"] is False


def test_at_gate_negative_r_is_not_used():
    rows = _gate_rows(True)
    rows["payout_pp"] = -rows["payout_pp"]
    gate = mr.at_effectiveness_gate(rows)
    assert gate["r"] < 0 and gate["gate_pass"] is False


def test_pooled_payout_point_estimate_is_inside_its_ci():
    out = mr.build_layer1(
        _frame(days=40, machines=4, seed=3),
        "20260928",
        window_days=28,
        baseline_days=10,
        regime_start="20260801",
        specs=J_SPEC,
        first_seen={"J": "20260801"},
        db_min_date="20250101",
    )
    row = out.iloc[0]
    assert row["機械割pp_ci_lo"] <= row["機械割pp"] <= row["機械割pp_ci_hi"]
    assert row["差枚_ci_lo"] <= row["差枚平均/台日"] <= row["差枚_ci_hi"]


def test_intro_days_come_from_full_history_not_the_window():
    kwargs = dict(window_days=7, baseline_days=5, regime_start="20260801", specs=J_SPEC)
    new = mr.build_layer1(_frame(), "20260831", first_seen={"J": "20260828"}, db_min_date="20250101", **kwargs).iloc[0]
    assert new["導入日数"] == 3 and "新台" in new["判定保留理由"]
    old = mr.build_layer1(_frame(), "20260831", first_seen={"J": "20250301"}, db_min_date="20250101", **kwargs).iloc[0]
    assert old["導入日数"] > 100 and "新台" not in old["判定保留理由"]
    unknown = mr.build_layer1(
        _frame(), "20260831", first_seen={"J": "20250101"}, db_min_date="20250101", **kwargs
    ).iloc[0]
    assert pd.isna(unknown["導入日数"]) and "新台" not in unknown["判定保留理由"]


def test_low_activity_hold_uses_installed_machine_count():
    out = mr.build_layer1(
        _frame(machines=2),
        "20260831",
        window_days=7,
        baseline_days=5,
        regime_start="20260801",
        specs=J_SPEC,
        first_seen={"J": "20250301"},
        db_min_date="20250101",
    )
    assert "設置2台" in out.iloc[0]["判定保留理由"]
    ok = mr.build_layer1(
        _frame(machines=4),
        "20260831",
        window_days=7,
        baseline_days=5,
        regime_start="20260801",
        specs=J_SPEC,
        first_seen={"J": "20250301"},
        db_min_date="20250101",
    )
    assert ok.iloc[0]["判定保留理由"] == ""


def test_rb_column_empty_machine_gets_no_setting_posterior():
    frame = _frame().assign(rb_count=0, bb_count=5)
    row = mr.build_layer1(
        frame,
        "20260831",
        window_days=7,
        baseline_days=5,
        regime_start="20260801",
        specs=J_SPEC,
        first_seen={"J": "20250301"},
        db_min_date="20250101",
    ).iloc[0]
    assert "RB列が空" in row["設定判定"]
    assert pd.isna(row["P(設定4以上)"]) and pd.isna(row["設定1_事後確率"]) and "RB_z" not in row.index


def test_normal_days_exact_dates_only():
    summary = pd.DataFrame({"date": ["20260901", "20260902", "20260903"]})
    assert mr.normal_days(
        summary, [{"hall": "別ホール", "date": "20260901"}, {"hall": "楽園蒲田店", "date": "20260902"}]
    ) == ["20260901", "20260903"]


def test_layer1_never_touches_result_announcements():
    source = inspect.getsource(mr)
    assert "external_result" not in source and "RESULT_DB" not in source and "RESULT_LINKS" not in source
    assert not any("result" in p.lower() for p in inspect.signature(mr.build_layer1).parameters)


def test_layer3_and_report_are_registered():
    parser = mr._parser()
    assert parser.parse_args(["layer3", "--asof", "20260930", "--target-month", "202610"]).command == "layer3"
    assert (
        parser.parse_args(["report", "--asof", "20260930", "--target-month", "202610", "--out", "x.md"]).command
        == "report"
    )
    from backtest import monthly_report_layer3 as l3

    source = inspect.getsource(l3)
    # docstringの言及は許す。結果コーパスへ接続するコード（sqlite3のimport・RESULT_DB・外部結果テーブル）が無いことを見る
    assert "import sqlite3" not in source and "RESULT_DB" not in source and "external_result" not in source


# ---- 層3 ----
from backtest import monthly_report_layer3 as l3  # noqa: E402

AT_SPEC = {"at": {"family_name": "AT", "category": "AT", "judgeable": False, "settings": {}}}


def _labels(rows):
    return pd.DataFrame(rows, columns=["date", "category", "weekday", "dd", "y"]).assign(machine_name="J")


def test_l3_labels_are_continuous_and_missing_when_pool_games_are_low():
    frame = pd.DataFrame(
        {
            "ds": ["20260901"] * 2 + ["20260902"] * 2,
            "machine_name": ["J"] * 4,
            "machine_number": [1, 2, 1, 2],
            "games_normalized": [500, 500, 2000, 2200],
            "rb_count": [1, 1, 8, 9],
            "bb_count": 5,
            "diff_coins_normalized": 0.0,
        }
    )
    labels = l3.make_labels(frame, {**J_SPEC, **AT_SPEC}, {"20260901": "火", "20260902": "水"})
    assert list(labels.date) == ["20260902"] and labels.attrs["excluded"]["low_pool_games"] == 1
    assert 0.0 < labels.iloc[0].y < 1.0
    empty_rb = frame.assign(rb_count=0)
    assert l3.make_labels(empty_rb, {**J_SPEC, **AT_SPEC}, {}).empty
    assert l3.make_labels(empty_rb, {**J_SPEC, **AT_SPEC}, {}).attrs["excluded"]["rb_column_empty"] == 2
    at = frame.assign(machine_name="AT")
    assert l3.make_labels(at, {**J_SPEC, **AT_SPEC}, {}).empty


def test_l3_shrinkage_goes_to_the_parent_cell():
    rows = (
        [("20260706", "C", "月", 6, 0.9)] * 2
        + [("20260713", "C", "月", 13, 0.1)] * 20
        + [("20260707", "C", "火", 7, 0.3)] * 20
    )
    labels = _labels(rows)
    tight, loose = l3.fit_prior(labels, k=1000), l3.fit_prior(labels, k=0.01)
    weekday_cell = tight["weekday"][("C", "月")]
    assert abs(l3.predict_cell(tight, "C", "月", 6) - weekday_cell) < 0.01
    assert l3.predict_cell(loose, "C", "月", 6) > 0.85
    assert l3.predict_cell(tight, "C", "月", 20) == pytest.approx(weekday_cell)
    assert l3.predict_cell(tight, "C", "水", 20) == pytest.approx(tight["type"]["C"])
    assert np.isnan(l3.predict_cell(tight, "X", "月", 1))


def test_l3_machine_names_are_not_a_feature():
    rng = np.random.default_rng(0)
    labels = _labels([(f"2026071{i % 7}", "C", WD[i % 7], 10 + i % 7, float(rng.uniform())) for i in range(60)])
    shuffled = labels.assign(machine_name=rng.permutation(["a", "b", "c", "d"] * 15))
    assert l3.fit_prior(labels) == l3.fit_prior(shuffled)


def _month_labels():
    rows = []
    for ds in _days("20260801", 61):
        rows.append((ds, "C", WD[_to_date(ds).weekday()], int(ds[6:]), 0.2 if ds < "20260901" else 0.8))
    return _labels(rows)


def test_l3_walk_forward_never_trains_on_the_evaluated_month():
    labels = _month_labels()
    out = l3.walk_forward(labels, {}, "202608", "202609", regime_start="20260801", k=5)
    assert [f["fold"] for f in out["folds"]] == ["202609"]
    fold = out["folds"][0]
    assert fold["train_n"] == int((labels.date < "20260901").sum()) and fold["constant"] == pytest.approx(0.2)
    assert out["observations"].pred.max() < 0.3
    assert out["bins"].n.sum() == fold["test_n"] == len(out["observations"])


def test_l3_walk_forward_all_history_ignores_the_regime_boundary():
    labels = _month_labels()
    out = l3.walk_forward(labels, {}, "202608", "202609", regime_start="20260901", k=5, all_history=True)
    assert [f["fold"] for f in out["folds"]] == ["202609"] and out["folds"][0]["train_n"] == int(
        (labels.date < "20260901").sum()
    )


def test_l3_mse_ratio():
    actual = np.array([0.1, 0.5, 0.9])
    assert l3._mse_ratio(actual, actual, 0.5) == 0.0
    assert l3._mse_ratio(np.full(3, 0.5), actual, 0.5) == pytest.approx(1.0)


def test_l3_bootstrap_ci_depends_on_the_cell():
    rng = np.random.default_rng(1)
    labels = _labels(
        [
            (ds, "C", WD[_to_date(ds).weekday()], int(ds[6:]), float(rng.uniform(0, 1)))
            for ds in _days("20260706", 87)
            for _ in range(5)
        ]
    )
    pred = l3.predict_month(labels, _weekdays(_days("20261001", 31)), "202610", k=5, seed=3)
    width = pred.ci_hi - pred.ci_lo
    assert (pred.ci_lo <= pred.ci_hi).all() and width.nunique() > 3
    assert pred.n_dd.min() < pred.n_type.min()
    again = l3.predict_month(labels, _weekdays(_days("20261001", 31)), "202610", k=5, seed=3)
    pd.testing.assert_frame_equal(pred, again)


def test_l3_report_wiring_keeps_results_out_of_layers_1_and_3():
    source = inspect.getsource(l3)
    assert "external_result" not in source and "monthly_report_layer2" not in source


# ---- 層2 ----
def _to_date(ds):
    return date(int(ds[:4]), int(ds[4:6]), int(ds[6:]))


def _days(start="20260706", n=84):
    first = _to_date(start)
    return [(first + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _metrics(days, seed=0, boost=None):
    rng = np.random.default_rng(seed)
    m = pd.DataFrame(
        {
            "win_rate": rng.normal(0.38, 0.02, len(days)),
            "payout_pp": rng.normal(0.5, 1.0, len(days)),
            "rb_per_1000g": rng.normal(2.4, 0.1, len(days)),
            "avg_games": rng.normal(3200, 100, len(days)),
            "n_md": 300,
        },
        index=days,
    )
    for d, delta in (boost or {}).items():
        m.loc[d, "payout_pp"] += delta
    return m


def _records(dates, kind, hall="楽園蒲田店"):
    return [
        {"event_id": f"{d}_{kind}_{hall}", "hall": hall, "date": d, "kind": kind, "event_name": kind} for d in dates
    ]


def _weekdays(days):
    return {d: WD[_to_date(d).weekday()] for d in days}


def test_perm_test_reproducible_with_fixed_seed():
    strata = [(np.array([1.0, 2.0, 3.0]), np.array([0.0, 0.5, 1.0, 1.5]))]
    assert l2.stratified_perm_test(strata, 2000, 7) == l2.stratified_perm_test(strata, 2000, 7)


def test_perm_test_detects_a_real_shift_and_not_a_null():
    rng = np.random.default_rng(0)
    shifted = [(rng.normal(3, 1, 8), rng.normal(0, 1, 20))]
    null = [(rng.normal(0, 1, 8), rng.normal(0, 1, 20))]
    assert l2.stratified_perm_test(shifted, 4000, 1)[1] < 0.01
    assert l2.stratified_perm_test(null, 4000, 1)[1] > 0.05


def test_kinds_below_five_days_get_no_effect_or_p():
    days = _days()
    recs = _records(days[:3], "small") + _records(days[10:20:2], "big")
    out = l2.analyse_events(_metrics(days), _weekdays(days), recs, "20260706", days[-1], perm=500)
    tests = out["tests"]
    small = tests[tests.kind == "small"]
    assert small["効果量"].isna().all() and small["p(並べ替え)"].isna().all()
    assert small["備考"].fillna("").str.contains("n<5").sum() == 3
    big = tests[(tests.kind == "big") & (tests["指標"] != "平均G/台日")]
    assert big["p(並べ替え)"].notna().all()
    assert out["m_tests"] == 3 and len(out["daily"]) == 3 + 5


def test_bonferroni_scales_p_by_the_number_of_tests():
    days = _days()
    recs = _records(days[10:30:2], "k")
    out = l2.analyse_events(_metrics(days), _weekdays(days), recs, "20260706", days[-1], perm=500)
    t = out["tests"].dropna(subset=["p(並べ替え)"])
    assert len(t) == 3
    assert np.allclose(t["補正p(Bonferroni)"], np.minimum(1.0, t["p(並べ替え)"] * out["m_tests"]))


def test_event_days_never_leak_into_the_normal_pool():
    days = _days()
    recs = _records(days[10:20:2], "a") + _records(days[11:21:2], "b")
    out = l2.analyse_events(_metrics(days), _weekdays(days), recs, "20260706", days[-1], perm=200)
    assert out["n_normal"] == len(days) - len({r["date"] for r in recs})


def test_a_boosted_event_kind_is_found():
    days = _days()
    event_days = days[7:70:7]
    out = l2.analyse_events(
        _metrics(days, boost={d: 5.0 for d in event_days}),
        _weekdays(days),
        _records(event_days, "boost"),
        "20260706",
        days[-1],
        perm=3000,
    )
    row = out["tests"].query("kind == 'boost' and 指標 == '機械割pp'").iloc[0]
    assert row["効果量"] > 3 and row["p(並べ替え)"] < 0.01


def test_pre_regime_events_are_listed_but_not_tested():
    days = _days()
    recs = _records(["20260610", "20260611"], "old") + _records(days[10:20:2], "new")
    out = l2.analyse_events(_metrics(days), _weekdays(days), recs, "20260706", days[-1], perm=200)
    assert out["pre_regime"]["old"] == ["20260610", "20260611"]
    assert out["tests"].query("kind == 'old'")["イベント日数(層化後)"].eq(0).all()


def test_hall_event_records_use_the_exact_hall_only(tmp_path):
    path = tmp_path / "events.jsonl"
    rows = (
        _records(["20260901"], "a")
        + _records(["20260902"], "a", hall="別ホール")
        + _records(["20260903"], "a", hall="楽園蒲田店別館")
    )
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    assert [r["date"] for r in mr.hall_event_records(path)] == ["20260901"]


def test_layer2_metrics_exclude_low_game_machine_days():
    frame = pd.DataFrame(
        {
            "ds": ["20260901"] * 3,
            "machine_name": ["J"] * 3,
            "machine_number": [1, 2, 3],
            "games_normalized": [100, 1000, 3000],
            "diff_coins_normalized": [-300.0, 100.0, 300.0],
            "bb_count": 0,
            "rb_count": [1, 2, 8],
        }
    )
    m = l2.hall_day_metrics(frame, J_SPEC, min_games=500)
    assert m.attrs["excluded_below_min_games"] == 1 and m.loc["20260901", "n_md"] == 2
    assert m.loc["20260901", "payout_pp"] == pytest.approx(100 * 400 / (3 * 4000))
    assert m.loc["20260901", "rb_per_1000g"] == pytest.approx(1000 * 10 / 4000)


def _ref_frame():
    low = pd.DataFrame({"games_normalized": 1500.0, "diff_coins_normalized": np.linspace(-3000, 3000, 20)})
    high = pd.DataFrame({"games_normalized": 5000.0, "diff_coins_normalized": np.linspace(0, 10000, 20)})
    return pd.concat([low, high], ignore_index=True)


def test_g_stratified_rank_compares_within_the_same_g_band():
    ref = _ref_frame()
    high_rep = pd.DataFrame({"games_normalized": [5000.0], "diff_coins_normalized": [3000.0]})
    raw = float((ref.diff_coins_normalized <= 3000).mean())
    banded = l2.g_stratified_ranks(high_rep, ref)[0]
    assert banded < raw and banded == pytest.approx(0.35, abs=0.06)
    low_rep = pd.DataFrame({"games_normalized": [1500.0], "diff_coins_normalized": [3000.0]})
    assert l2.g_stratified_ranks(low_rep, ref)[0] == pytest.approx(1.0)


def test_g_stratified_rank_is_nan_when_the_band_has_too_few_reference_days():
    ref = _ref_frame()
    mid = pd.DataFrame({"games_normalized": [3000.0], "diff_coins_normalized": [100.0]})
    assert np.isnan(l2.g_stratified_ranks(mid, ref)[0])


def test_mde_grows_with_noise_and_with_the_number_of_tests_and_shrinks_with_n():
    base = l2._mde(1.0, 10, 30, 1)
    assert l2._mde(2.0, 10, 30, 1) == pytest.approx(2 * base)
    assert l2._mde(1.0, 10, 30, 6) > base
    assert l2._mde(1.0, 40, 30, 1) < base
    assert np.isnan(l2._mde(float("nan"), 10, 30, 1)) and np.isnan(l2._pooled_sd([np.array([1.0])]))


def _announce_frame(days=6):
    rows = []
    for i in range(days):
        ds = f"2026091{i}"
        for machine, rb, bb in (("J", 14, 0), ("K", 6, 0), ("E", 0, 9)):
            for number in (1, 2, 3):
                rows.append(
                    {
                        "ds": ds,
                        "machine_name": machine,
                        "machine_number": number,
                        "games_normalized": 3000.0,
                        "rb_count": rb,
                        "bb_count": bb,
                        "diff_coins_normalized": 0.0,
                    }
                )
    return pd.DataFrame(rows)


def test_announced_rb_comparison_is_per_day_and_skips_rb_empty_machines():
    spec = lambda name, hi: {
        "family_name": name,
        "category": "ノーマル",
        "judgeable": True,  # noqa: E731
        "settings": {1: {"rb_probability": 1 / 400}, 6: {"rb_probability": 1 / 220}},
    }
    specs = {"j": spec("J", 1), "k": spec("K", 1), "e": spec("E", 1)}
    announced = {(f"2026091{i}", "J"): {1, 2} for i in range(6)}
    out = l2.announced_rb_comparison(_announce_frame(), announced, specs, perm=500, seed=1)
    assert out["n_announced"] == 6 and out["n_unannounced"] == 6 and out["n_dates"] == 6
    assert out["effect"] > 0 and out["mean_announced"] > out["mean_unannounced"]
    few = l2.announced_rb_comparison(
        _announce_frame(3), {k: v for k, v in announced.items() if k[0] < "20260913"}, specs, perm=100, seed=1
    )
    assert "effect" not in few


def test_g_band_summary_reports_each_band_with_counts():
    md = pd.DataFrame(
        {
            "G": [1000.0, 1500.0, 3000.0, 5000.0],
            "G帯": [0, 0, 1, 2],
            "差枚": [500.0, -100.0, 200.0, 2000.0],
            "q_素": [0.9, 0.4, 0.6, 0.95],
            "q_G帯": [0.8, np.nan, 0.5, 0.7],
        }
    )
    out = l2.g_band_summary(md)
    assert list(out["回転数帯"]) == ["G<2000", "2000<=G<4000", "G>=4000"] and list(out["台日数"]) == [2, 1, 1]
    assert out.iloc[0]["G帯分位が計算できた台日"] == 1


def test_holm_adjust_matches_the_textbook_example_and_keeps_order():
    adjusted = mr.holm_adjust([0.01, 0.04, 0.03, 0.005])
    assert adjusted == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert mr.holm_adjust([]).size == 0
    assert mr.holm_adjust([0.4])[0] == pytest.approx(0.4)
    assert (mr.holm_adjust([0.5, 0.9]) <= 1.0).all()


def _segment_frame(days, machines=("J",), rb=2, bb=1, diff=300.0, games=1000.0):
    rows = []
    for ds in days:
        for name in machines:
            rows.append(
                {
                    "ds": ds,
                    "machine_name": name,
                    "machine_number": 1,
                    "games_normalized": games,
                    "diff_coins_normalized": diff,
                    "bb_count": bb,
                    "rb_count": rb,
                }
            )
    return pd.DataFrame(rows)


def test_segments_partition_the_window_without_overlap():
    window = [(date(2026, 9, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(14)]
    out = mr.build_segment_table(_segment_frame(window), window, ["20260907", "20260910"], J_SPEC)
    assert list(out["区間"]) == ["9/1〜9/6", "9/7〜9/9", "9/10〜9/14"]
    assert list(out["区間日数"]) == [6, 3, 5]
    assert sum(out["区間日数"]) == len(window)


def test_segment_boundary_date_belongs_to_the_new_segment():
    window = [f"2026090{i}" for i in range(1, 9)]
    out = mr.build_segment_table(_segment_frame(window), window, ["20260907"], J_SPEC)
    assert list(out["区間日数"]) == [6, 2]


def test_machine_absent_in_a_segment_gets_an_explicit_row():
    window = [f"2026090{i}" for i in range(1, 9)]
    frame = pd.concat([_segment_frame(window[:6], ("J",)), _segment_frame(window[6:], ("K",))], ignore_index=True)
    out = mr.build_segment_table(frame, window, ["20260907"], J_SPEC)
    absent = out[(out.machine_name == "K") & (out["区間"] == "9/1〜9/6")].iloc[0]
    assert absent.n_machine_days == 0 and "この区間に出現なし" in absent["備考"]


def test_segment_pooled_payout_matches_the_formula():
    window = [f"2026090{i}" for i in range(1, 9)]
    row = mr.build_segment_table(_segment_frame(window, diff=300.0, games=1000.0), window, [], J_SPEC).iloc[0]
    assert row["機械割pp"] == pytest.approx(10.0)


def test_segment_ci_is_omitted_when_fewer_than_seven_days():
    window = [f"2026090{i}" for i in range(1, 7)]
    row = mr.build_segment_table(_segment_frame(window), window, [], J_SPEC).iloc[0]
    assert np.isnan(row["機械割pp_ci_lo"]) and np.isnan(row["機械割pp_ci_hi"])


def test_segment_rb_column_empty_machine_has_no_rb_rate():
    window = [f"2026090{i}" for i in range(1, 8)]
    row = mr.build_segment_table(_segment_frame(window, rb=0, bb=5), window, [], J_SPEC).iloc[0]
    assert np.isnan(row["RB確率 1/x"]) and np.isnan(row["RB回数"]) and "RB列が空" in row["備考"]


def test_layer1_output_unchanged_without_split_dates():
    out = mr.build_layer1(
        _frame(days=12), "20260831", window_days=7, baseline_days=5, regime_start="20260801", specs=J_SPEC
    )
    assert "## 窓の分割（配置替え・機種入替の前後）" not in mr.render_layer1_markdown(out)


def test_layer1_holm_column_only_covers_machines_without_a_hold_reason():
    frames = []
    for name, rb in (("J", 3), ("K", 30)):
        f = _frame(days=40, machines=4, seed=5).assign(machine_name=name, rb_count=rb)
        frames.append(f)
    specs = {n: {**J_SPEC["j"], "family_name": n} for n in ("j", "k")}
    out = mr.build_layer1(
        pd.concat(frames, ignore_index=True),
        "20260928",
        window_days=28,
        baseline_days=10,
        regime_start="20260801",
        specs=specs,
        first_seen={"J": "20250301", "K": "20250301"},
        db_min_date="20250101",
    )
    assert "RB_p(Holm補正)" in out.columns
    ok = out[out["判定保留理由"] == ""]
    assert ok["RB_p(Holm補正)"].notna().all() and (ok["RB_p(Holm補正)"] >= ok["RB_p"]).all()


def test_main_forces_utf8_stdout_so_cp932_consoles_do_not_crash(monkeypatch, capsys):
    import io

    class Cp932Stdout(io.TextIOWrapper):
        pass

    raw = io.BytesIO()
    fake = Cp932Stdout(raw, encoding="cp932")
    monkeypatch.setattr("sys.stdout", fake)
    monkeypatch.setattr(mr, "run_layer1", lambda args: pd.DataFrame())
    monkeypatch.setattr(mr, "render_layer1_markdown", lambda df: "出率≈100%〜")
    assert mr.main(["layer1", "--asof", "20260930"]) == 0
    fake.flush()
    assert "出率≈100%〜".encode("utf-8") in raw.getvalue()


def test_l3_default_k_is_30_and_wired_to_the_cli():
    assert l3.DEFAULT_K == 30
    parser = mr._parser()
    assert parser.parse_args(["layer3", "--asof", "20260930", "--target-month", "202610"]).k == 30
    assert parser.parse_args(["report", "--asof", "20260930", "--target-month", "202610", "--out", "x.md"]).k == 30


def test_l3_walk_forward_drop_removes_dd_and_weekday_terms():
    rng = np.random.default_rng(2)
    rows = []
    for ds in _days("20260801", 61):
        dd = int(ds[6:])
        rows.append((ds, "C", WD[_to_date(ds).weekday()], dd, 0.7 if dd % 10 == 3 else 0.3))  # DDだけに信号がある
    labels = _labels(rows)
    full = l3.walk_forward(labels, {}, "202609", "202609", regime_start="20260801", k=3)
    no_dd = l3.walk_forward(labels, {}, "202609", "202609", regime_start="20260801", k=3, drop=("dd",))
    assert full["folds"][0]["mse_ratio"] < no_dd["folds"][0]["mse_ratio"]
    only_type = l3.walk_forward(labels, {}, "202609", "202609", regime_start="20260801", k=3, drop=("dd", "weekday"))
    assert only_type["folds"][0]["mse_ratio"] == pytest.approx(1.0, abs=0.05)


def test_l3_ablation_lists_every_variant_with_a_fold_column():
    labels = _month_labels()
    out = l3.ablation(labels, {}, "202608", "202609", regime_start="20260801", k=5)
    assert list(out["モデル"]) == ["タイプ平均のみ", "曜日のみ", "DDのみ", "曜日+DD（本体）"]
    assert any(c.startswith("MSE比") for c in out.columns)


def test_l3_segment_levels_split_at_the_boundaries_without_overlap_and_skip_ci_for_short_runs():
    rows = []
    rng = np.random.default_rng(4)
    for ds in _days("20260901", 30):
        rows.append(
            (
                ds,
                "C",
                WD[_to_date(ds).weekday()],
                int(ds[6:]),
                float(np.clip(rng.normal(0.2 if ds < "20260907" else 0.8, 0.05), 0, 1)),
            )
        )
    out = l3.segment_levels(_labels(rows), boundaries=("20260907", "20260921"))
    assert list(out["日数"]) == [6, 14, 10] and out["機種日数"].sum() == 30
    assert list(out["区間"])[1].startswith("20260907") and list(out["区間"])[2].startswith("20260921")
    # CIは14日以上の区間だけ。7日ちょうどの区間で幅ゼロのCIを出さない（ブロック長と同じ日数では回転にしかならない）
    assert out.iloc[0]["備考"] != "" and np.isnan(out.iloc[0]["ci_lo"]) and out.iloc[2]["備考"] != ""
    assert out.iloc[1]["備考"] == "" and out.iloc[1]["ci_hi"] > out.iloc[1]["ci_lo"]
    assert out.iloc[0]["y平均"] == pytest.approx(0.2, abs=0.05) and out.iloc[2]["y平均"] == pytest.approx(0.8, abs=0.05)


def test_exactly_one_block_of_days_never_yields_a_zero_width_ci():
    by_date = {f"202609{d:02d}": (float(d), 100.0) for d in range(1, 8)}
    lo, hi = mr.block_bootstrap_ratio_ci(by_date, block=7, B=200, seed=1)
    assert lo == hi  # 7日=1ブロックでは幅ゼロ。だから MIN_CI_DAYS 未満ではCIを出さない
    assert mr.MIN_CI_DAYS == 14 and mr.MIN_CI_DAYS >= 2 * 7


# ---- 層2b（予告の名指し）----
from backtest import monthly_report_announce as an  # noqa: E402


def _bundle(status="active", hall="楽園蒲田店", date="20260910", claims=None):
    return {"status": status, "payload": {"hall": hall, "target_date": date, "claims": claims or []}}


def test_named_loader_uses_only_active_same_hall_in_range_named_claims():
    named_claims = [
        {"type": "model_named", "machine_name": "J"},
        {"type": "model_named_ratio", "machine_name": "K"},
        {"type": "zentaikei_count", "n_models": 2},
        {"type": "position_rule"},
    ]
    bundles = [
        _bundle(claims=named_claims),
        _bundle(status="withdrawn", claims=[{"type": "model_named", "machine_name": "W"}]),
        _bundle(status="retroactive", claims=[{"type": "model_named", "machine_name": "R"}]),
        _bundle(hall="別ホール", claims=[{"type": "model_named", "machine_name": "X"}]),
        _bundle(date="20260601", claims=[{"type": "model_named", "machine_name": "OLD"}]),
        _bundle(date="20261005", claims=[{"type": "model_named", "machine_name": "FUTURE"}]),
    ]
    got = an.load_named("楽園蒲田店", "20260706", "20260930", bundles)
    assert set(got) == {("20260910", "J"), ("20260910", "K")}
    assert got[("20260910", "J")] == {"model_named"}


def _an_frame(days=8):
    rows = []
    for i in range(days):
        ds = f"2026092{i}"
        for machine, diff in (("J", 3000.0), ("K", -500.0), ("L", -200.0)):
            for number in (1, 2):
                rows.append(
                    {
                        "ds": ds,
                        "machine_name": machine,
                        "machine_number": number,
                        "games_normalized": 4500.0,
                        "diff_coins_normalized": diff,
                        "rb_count": 10,
                        "bb_count": 0,
                    }
                )
    return pd.DataFrame(rows)


def test_machine_day_table_labels_named_machines_and_compares_within_each_day():
    frame = _an_frame()
    named = {(f"2026092{i}", "J"): {"model_named"} for i in range(8)}
    normal = frame.assign(diff_coins_normalized=0.0)  # 通常日の差枚はすべて0 → 名指しJの分位は1.0
    table = an.machine_day_table(frame, named, {}, normal)
    assert table["named"].sum() == 8 and set(table[table.named].machine) == {"J"} and len(table) == 24
    assert (table[table.named].q_g == 1.0).all() and (table[~table.named].q_g < 1.0).all()
    out = an.compare(table, perm=500, seed=1)
    row = out[out["指標"] == "機械割pp(G>=2000)"].iloc[0]
    assert row["差(名指し−未名指し)"] > 0 and row["比較できた日数"] == 8 and row["名指し機種×日"] == 8


def test_announce_compare_gives_no_effect_or_p_below_five_named_machine_days():
    frame = _an_frame(4)
    named = {(f"2026092{i}", "J"): {"model_named"} for i in range(4)}
    table = an.machine_day_table(frame, named, {}, frame.assign(diff_coins_normalized=0.0))
    out = an.compare(table, perm=100, seed=1)
    # 5件未満なら効果量・pの列自体を作らない（出さない）
    assert "差(名指し−未名指し)" not in out.columns and "p(並べ替え)" not in out.columns
    assert out["備考"].str.contains("未満").all()


def test_announce_layer_never_reads_result_announcements():
    source = inspect.getsource(an)
    assert (
        "external_result" not in source
        and "RESULT_DB" not in source
        and "analysis_results" not in source.replace("analysis_results.db", "")
    )
