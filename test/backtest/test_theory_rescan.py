"""backtest/theory_rescan.py のテスト。合成データのみ(DBは使わない)。"""

import json

import numpy as np
import pandas as pd

from backtest import theory_rescan as tr


def _ledger(tmp_path):
    return tr.Ledger("テスト", "20261104", root=tmp_path)


def _record(ledger, axis_id, planned, cells, excluded=()):
    return ledger.record(
        axis_id, planned=planned, cells=list(cells), excluded=list(excluded), unit="u", metrics="差枚", window="3m",
        scope="s", basis="ex_post", runner="r",
    )  # fmt: skip


CELL = dict(unit="a", level="", metric="差枚", p=0.01, q=0.1, effect=1.0)


def test_record_is_complete_only_when_counts_match(tmp_path):
    ledger = _ledger(tmp_path)
    assert (
        _record(ledger, "L1", 2, [CELL], [tr._ex("L1", "機種", "b", "", "差枚", "vs_hall", "3m", "FEW")])["status"]
        == "完了"
    )
    assert _record(ledger, "L2", 5, [CELL])["status"] == "失敗"
    assert "一部のみ" in ledger.rows["L2"]["reason"]


def test_reconcile_finds_tampered_counts(tmp_path):
    ledger = _ledger(tmp_path)
    for axis_id in tr.CATALOG:
        ledger.not_run(axis_id, "未実施", "テスト")
    _record(ledger, "L1", 1, [CELL])
    assert tr.reconcile(ledger)["ok"]
    path = ledger.results / "L1.json"
    summary = json.loads(path.read_text("utf-8"))
    summary["p05"] = 9
    path.write_text(json.dumps(summary, ensure_ascii=False), "utf-8")
    assert not tr.reconcile(ledger)["ok"]


def test_not_run_requires_reason_in_reconcile(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.rows["T12"]["reason"] = ""
    assert any("T12" in p for p in tr.reconcile(ledger)["problems"])


def test_metric_arrays_keep_zero_games_for_games_but_not_rates():
    df = pd.DataFrame(
        dict(G=[0.0, 100.0], diff=[0.0, 30.0], hit=[0, 1], hit_kind=["RB", "RB"], r1=[0.001, 0.001], r6=[0.002, 0.002])
    )
    assert tr.metric_arrays(df, "回転数")[2].tolist() == [True, True]
    for metric in ("機械割差", "RB位置"):
        assert tr.metric_arrays(df, metric)[2].tolist() == [False, True]
    num, den, _ = tr.metric_arrays(df, "機械割差")
    assert num[1] / den[1] == 10.0


def test_rb_position_scale():
    df = pd.DataFrame(dict(G=[1000.0], diff=[0.0], hit=[2], hit_kind=["RB"], r1=[0.001], r6=[0.003]))
    num, den, _ = tr.metric_arrays(df, "RB位置")
    assert abs(num[0] / den[0] - 0.5) < 1e-9


def test_history_feature_uses_calendar_days_and_excludes_target():
    N = np.arange(30, dtype=float).reshape(10, 3)
    D, O = np.ones((10, 3)), np.ones((10, 3))
    M = np.zeros((10, 3), int)
    assert tr.history_feature(N, D, O, M, 5, 1, 1, per_unit_min=1).tolist() == N[4].tolist()
    window = tr.history_feature(N, D, O, M, 5, 1, 3, per_unit_min=1)
    assert window.tolist() == N[2:5].mean(0).tolist()
    N2 = N.copy()
    N2[5] = 1e9  # 対象日の値を壊しても、特徴量は変わらない
    assert tr.history_feature(N2, D, O, M, 5, 1, 3, per_unit_min=1).tolist() == window.tolist()


def test_history_feature_missing_day_is_nan_not_shifted():
    N, D, O = np.ones((10, 2)), np.ones((10, 2)), np.ones((10, 2))
    N[4], D[4], O[4] = 0, 0, 0  # d=4 が欠測(休業)
    assert np.isnan(tr.history_feature(N, D, O, np.zeros((10, 2), int), 5, 1, 1, per_unit_min=1)).all()


def test_history_feature_same_machine_ignores_other_machine_history():
    N = np.ones((20, 1))
    N[:5] = 100.0  # 入替前の機種の値
    M = np.ones((20, 1), int)
    M[:5] = 0
    out = tr.history_feature(N, np.ones((20, 1)), np.ones((20, 1)), M, 19, 1, 18, per_unit_min=1, same_machine=True)
    assert out[0] == 1.0


def _panel(carry, days=120, units=40, seed=3):
    rng = np.random.default_rng(seed)
    V = np.zeros((days, units))
    V[0] = rng.normal(size=units)
    for d in range(1, days):
        V[d] = carry * V[d - 1] + rng.normal(size=units)
    return (None, V, np.ones_like(V), np.ones_like(V), np.zeros_like(V, dtype=int))


def test_history_cell_detects_carryover_and_null_is_quiet():
    rng = np.random.default_rng(1)
    days = list(range(30, 110))
    weekday = [d % 7 for d in days]
    carry = tr.history_cell(_panel(0.7), days, weekday, (1, 1), "ld", False, 300, rng)
    assert carry["rho"] > 0.3 and carry["p"] < 0.05
    assert abs(tr.history_cell(_panel(0.0), days, weekday, (1, 1), "ld", False, 300, rng)["rho"]) < 0.1


def test_residual_rows_leave_one_out_and_drop_singletons():
    df = pd.DataFrame(
        dict(ds=["a", "a", "b"], machine_name=["m", "m", "n"], G=[100.0, 100.0, 100.0], diff=[30.0, 0.0, 9.0])
    )
    out = tr.residual_rows(df, "差枚", ["ds", "machine_name"])
    assert out._r.tolist() == [30.0, -30.0]


def test_block_weights_sum_to_days():
    w = tr.block_weights(20, 50, np.random.default_rng(0))
    assert w.shape == (50, 20) and (w.sum(1) == 20).all()


def test_boot_table_detects_planted_unit():
    rng = np.random.default_rng(0)
    days = [f"d{i:03d}" for i in range(60)]
    rows = [dict(ds=d, u="good", _r=rng.normal(5, 1), _d=1.0) for d in days] + [
        dict(ds=d, u="flat", _r=rng.normal(0, 1), _d=1.0) for d in days
    ]
    table = tr.boot_table(pd.DataFrame(rows), "u", days, 300, rng).set_index("unit")
    assert table.loc["good", "p"] < 0.01 and table.loc["good", "ci_lo"] > 0
    assert table.loc["flat", "ci_lo"] < 0 < table.loc["flat", "ci_hi"]


def test_time_stats_in_minus_out():
    lab = np.array([True, False, False, True])
    assert tr.time_stats(lab[None], np.array([[2.0], [1.0], [1.0], [2.0]]), np.ones((4, 1)))[0, 0] == 1.0


def test_holiday_runs_finds_three_day_weekend():
    days = [f"202609{d:02d}" for d in range(17, 26)]  # 2026-09-19(土)〜23(水・祝)は連休
    out = dict(zip(days, tr.holiday_runs(days)))
    assert out["20260919"] and out["20260923"] and not out["20260918"]


def test_s1_classify_labels():
    wide = pd.DataFrame(dict(machine_name=list("abcd"), active=5, good=[3, 3, 3, 0], expected=1.0))
    assert tr.s1_classify(wide)["label"] == "全体型"
    conc = pd.DataFrame(dict(machine_name=list("abcdef"), active=5, good=[5, 0, 0, 0, 0, 0], expected=1.0))
    assert tr.s1_classify(conc)["label"] == "集中型"


def test_verdict_never_calls_underpowered_dead():
    assert tr.verdict_from("UNDERPOWERED", (-1.0, 1.0), 0.1, 2.0) == "判別不能"
    assert tr.verdict_from("ALIVE", (0.5, 1.0), 0.7, 0.8) == "残っている"
    assert tr.verdict_from("DEAD", (-0.5, 0.5), 0.0, 2.0) == "消えた"
    assert tr.verdict_from("REVERSED", (-2.0, -1.0), -1.5, 2.0) == "消えた"
    assert tr.verdict_from("NO_BASELINE", (0.5, 1.0), 0.7, 0.1) == "直近のみ検出(正)"
    assert tr.verdict_from("NO_BASELINE", (-0.5, 1.0), 0.1, 0.1).startswith("判別不能")


def test_neighbors_are_circular():
    assert tr.neighbors_for("L5", "0") == ["9", "1"]
    assert tr.neighbors_for("T2", "9のつく日") == ["8のつく日", "0のつく日"]
    assert tr.neighbors_for("T1", "月曜") == ["日曜", "火曜"]
    assert tr.neighbors_for("L3", "端1") == ["端2"]


def _claim_df(days=200, seed=2, drop_after=None):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("20260101", periods=days).strftime("%Y%m%d")
    rows = []
    for i, d in enumerate(dates):
        edge = 3.0 if drop_after is None or i < drop_after else 0.0
        for n in range(6):
            rows.append(
                dict(
                    date=d, machine_name="J", machine_number=100 + n, jug_flag=1, rank_from_aisle=1 if n == 0 else 5,
                    payout=(edge if n == 0 else 0.0) / 100 + rng.normal(0, 0.005), dd=int(d[6:8]),
                )
            )  # fmt: skip
    return pd.DataFrame(rows)


CLAIM = dict(
    claim_id="c",
    text="角1",
    contrast="same_day",
    universe={"jug_flag": 1},
    target={"rank_from_aisle": 1},
    metrics=["payout"],
)


def test_evaluate_claim_detects_death_and_survival():
    assert tr.evaluate_claim(_claim_df(drop_after=110), CLAIM, 90, 500)[0]["verdict"] == "消えた"
    alive = tr.evaluate_claim(_claim_df(), CLAIM, 90, 500)[0]
    assert alive["verdict"] == "残っている" and alive["n_recent"] == 90


def test_update_doc_keeps_old_body_and_is_idempotent():
    old = "# 題\n\n> **2026-11-06 棚卸し**: 古い注記\n> - `x`: DEAD\n\n> **目的**: 本文の注記\n\n## 古い節\n本文\n"
    section = f"{tr.DOC_START}\n## 新\n{tr.DOC_END}\n"
    once = tr.update_doc(old, section, "> 新しい注記")
    assert "古い注記" not in once and "本文の注記" in once and "## 古い節" in once and tr.OLD_BODY_HEADING in once
    assert once.index("## 新") < once.index(tr.OLD_BODY_HEADING)
    twice = tr.update_doc(once, f"{tr.DOC_START}\n## 新2\n{tr.DOC_END}\n", "> 新しい注記")
    assert (
        "## 新2" in twice and "## 新\n" not in twice and twice.count(tr.OLD_BODY_HEADING) == 1 and "## 古い節" in twice
    )


def test_evaluate_claim_reports_short_window_as_undetermined():
    assert tr.evaluate_claim(_claim_df(days=60), CLAIM, 90, 200)[0]["verdict"].startswith("判別不能")
