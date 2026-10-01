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
