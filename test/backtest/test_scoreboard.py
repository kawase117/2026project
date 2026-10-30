# -*- coding: utf-8 -*-
"""総合採点表(backtest.scoreboard)の集計単位・除外・判定を固定する。"""

import json

import pytest
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import scoreboard  # noqa: E402


def write_plan(directory, rule, date, edge, *, dry=False, scored=True, ratios=None):
    result = None
    if scored:
        result = {"mean_edge_per_pick": edge, "picks_realized": [{"diff": edge}]}
        if ratios is not None:
            result["rb_perspective"] = {"picks_rb": [{"baseline_ratio": r} for r in ratios]}
    obj = {
        "rule_id": rule,
        "hall": "テスト店",
        "target_date": date,
        "is_dry_run": dry,
        "success_criterion": "edge 平均が +150枚/台 以上",
        "result": result,
    }
    (directory / f"{rule}__{date}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def dates(n):
    return [f"202609{d:02d}" for d in range(1, n + 1)]


def build(tmp_path):
    """本番の予測台帳・予告ディレクトリを読まないよう、空のディレクトリを渡す。"""
    return scoreboard.build(tmp_path, None, tmp_path / "no_pred", tmp_path / "no_announce")


def by_family(rows, family):
    return {r.key: r for r in rows if r.family == family}


def test_unit_is_rule_day_and_exclusions(tmp_path):
    for d in dates(12):
        write_plan(tmp_path, "good", d, 300.0 + (int(d[-2:]) % 3) * 10)
    write_plan(tmp_path, "good", "20260913", 99999.0, dry=True)  # dry run は数えない
    write_plan(tmp_path, "good", "20260914", None, scored=False)  # 未採点は数えない
    (tmp_path / "invalidated").mkdir()
    write_plan(tmp_path / "invalidated", "good", "20260915", -99999.0)  # 無効化済みは数えない

    r = by_family(build(tmp_path), "forward_edge")["good"]
    assert r.stat.n_days == 12
    assert 300 <= r.stat.mean <= 320
    assert r.verdict == "有効"
    assert r.extra["criterion_edge"] == 150


def test_harmful_and_insufficient(tmp_path):
    for d in dates(12):
        write_plan(tmp_path, "bad", d, -200.0 - (int(d[-2:]) % 4) * 10)
    for d in dates(4):
        write_plan(tmp_path, "few", d, 500.0)
    rows = by_family(build(tmp_path), "forward_edge")
    assert rows["bad"].verdict == "有害"
    assert rows["few"].verdict == "標本不足"


def test_noise_is_not_called_effective(tmp_path):
    vals = [800, -900, 700, -600, 500, -800, 900, -700, 600, -500, 400, -300]
    for d, v in zip(dates(12), vals, strict=True):
        write_plan(tmp_path, "noisy", d, float(v))
    r = by_family(build(tmp_path), "forward_edge")["noisy"]
    assert r.verdict == "差を検出できず"
    assert r.days_needed and r.days_needed > 0


def test_rb_ratio_family_centered_at_zero(tmp_path):
    for d in dates(10):
        write_plan(tmp_path, "rb", d, 0.0, ratios=[1.2, 1.4])
    r = by_family(build(tmp_path), "forward_rb")["rb"]
    assert abs(r.stat.mean - 0.3) < 1e-9


def test_juggler_ledger_one_value_per_day(tmp_path):
    lines = [
        {"hall": "店", "date": "20261001", "model": "マイ", "top_ph": 0.3, "rest_ph": 0.1},
        {"hall": "店", "date": "20261002", "model": "マイ", "top_ph": 0.2, "rest_ph": 0.2},
    ]
    (tmp_path / scoreboard.JUGGLER_LEDGER_NAME).write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8"
    )
    r = by_family(build(tmp_path), "juggler_ph")["店/マイ"]
    assert r.stat.n_days == 2
    assert abs(r.stat.mean - 0.1) < 1e-9


def test_prediction_rows_one_value_per_hall_day(tmp_path):
    pred = tmp_path / "pred"
    pred.mkdir()
    for i, d in enumerate(dates(3)):
        obj = {
            "hall": "店",
            "target_date": d,
            "timing": "pre_open" if i == 0 else "after",
            "result": {"models": {"edge": 100.0 * (i + 1)}, "avoid_models": None, "units": None, "jug_units": None},
        }
        (pred / f"{d}__x.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    (pred / "20260930__x.json").write_text(json.dumps({"hall": "店", "target_date": "20260930", "result": None}))
    rows = scoreboard.build(tmp_path, None, pred, tmp_path / "no_announce")
    r = by_family(rows, "pred_models")["pred_models/店"]
    assert r.stat.n_days == 3
    assert abs(r.stat.mean - 200.0) < 1e-9
    assert r.extra["timing"] == {"pre_open": 1, "same_day": 0, "after": 2}
    assert "pred_avoid/店" not in by_family(rows, "pred_avoid")


def write_pred(pred, name, hall, date, *, models=None, avoid=None, timing="pre_open", **kw):
    obj = {
        "hall": hall,
        "target_date": date,
        "timing": timing,
        "result": {
            "models": None if models is None else {"edge": models},
            "avoid_models": None if avoid is None else {"edge": avoid},
            "units": None,
            "jug_units": None,
        },
        **kw,
    }
    (pred / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_avoid_split_by_timing(tmp_path):
    pred = tmp_path / "pred"
    pred.mkdir()
    write_pred(pred, "20261001__a.json", "店", "20261001", avoid=100.0, timing="pre_open")
    write_pred(pred, "20261002__a.json", "店", "20261002", avoid=-300.0, timing="same_day")
    write_pred(pred, "20261003__a.json", "店", "20261003", avoid=-500.0, timing="after")
    rows = scoreboard.build(tmp_path, None, pred, tmp_path / "no_announce")
    pre = by_family(rows, "pred_avoid")["pred_avoid/店"]
    late = by_family(rows, "pred_avoid_late")["pred_avoid_late/店"]
    assert pre.stat.n_days == 1 and pre.stat.mean == 100.0
    assert late.stat.n_days == 2 and late.stat.mean == -400.0


def test_vs_base_same_hall_same_day(tmp_path):
    hall_a, hall_b = scoreboard.CORE_HALLS[0], scoreboard.CORE_HALLS[1]
    for hall, rule in ((hall_a, "rakuen"), (hall_b, "mitoya")):
        for d, edge in (("20261001", 50.0), ("20261002", 80.0)):
            obj = {
                "rule_id": f"{rule}{scoreboard.BASE_RULE_SUFFIX}",
                "hall": hall,
                "target_date": d,
                "result": {"mean_edge_per_pick": edge, "picks_realized": []},
            }
            (tmp_path / f"{rule}{scoreboard.BASE_RULE_SUFFIX}__{d}.json").write_text(
                json.dumps(obj, ensure_ascii=False), encoding="utf-8"
            )
    pred = tmp_path / "pred"
    pred.mkdir()
    write_pred(pred, "20261001__r.json", hall_a, "20261001", models=250.0)
    write_pred(pred, "20261002__r.json", hall_a, "20261002", models=0.0, timing="after")
    write_pred(pred, "20261001__m.json", hall_b, "20261001", models=150.0)
    write_pred(pred, "20261003__r.json", hall_a, "20261003", models=999.0)  # 基準の無い日は比べない
    write_pred(pred, "20261001__r__v2.json", hall_a, "20261001", models=999.0, revision_of="x", revision=2)
    write_pred(pred, "20261001__r__rbauto.json", hall_a, "20261001", models=999.0, source="rb_auto")
    rows = by_family(scoreboard.build(tmp_path, None, pred, tmp_path / "no_announce"), "pred_vs_base")
    a = rows[f"pred_vs_base/{hall_a}"]
    assert a.stat.n_days == 2
    assert abs(a.stat.mean - (200.0 - 80.0) / 2) < 1e-9  # (250−50) と (0−80)
    assert a.extra["own_mean"] == 125.0 and a.extra["base_mean"] == 65.0
    core = rows[f"pred_vs_base/{scoreboard.CORE_LABEL}"]
    # 10/01 は2ホールの日平均 (200 + 100)/2、10/02 は1ホール −80
    assert core.stat.n_days == 2
    assert abs(core.stat.mean - (150.0 - 80.0) / 2) < 1e-9
    assert core.extra["timing"] == {"pre_open": 1, "same_day": 0, "after": 1}


def test_markdown_has_plan_map_and_rb_note(tmp_path):
    md = scoreboard.render_markdown(build(tmp_path), "2026-10-30T00:00:00+09:00", None)
    assert "11月の検証計画と判定に使う表" in md
    assert "月次はRB比の表で判定し、差枚の表は3か月単位" in md


def test_announce_rows_weight_by_machines_and_skip_withdrawn(tmp_path):
    ann = tmp_path / "ann"
    ann.mkdir()

    def write(name, date, claims, **kw):
        obj = {
            "hall": "店",
            "target_date": date,
            "source": {"account": "acc"},
            "result": {"hall_baseline_mean_diff": 100.0, "claims": claims},
            **kw,
        }
        (ann / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    claims = [
        {"type": "model_named", "mean_diff": 400.0, "n_machines": 3, "hit": True, "base_rate": 0.1},
        {"type": "model_named", "mean_diff": 0.0, "n_machines": 1, "hit": False, "base_rate": 0.1},
        {"type": "zentaikei_count", "hit": True},
    ]
    write("h__20261001__acc.json", "20261001", claims)
    write("h__20261002__acc.json", "20261002", claims)
    (ann / "h__20261002__acc.withdrawn.json").write_text("{}")  # 撤回された版は数えない
    write("h__20261003__acc.json", "20261003", claims, retroactive=True)  # 遡及登録も数えない
    rows = scoreboard.build(tmp_path, None, tmp_path / "no_pred", ann)
    r = by_family(rows, "announce_named")["acc/店"]
    assert r.stat.n_days == 1
    assert abs(r.stat.mean - 200.0) < 1e-9  # (400*3 + 0*1)/4 − 100
    assert r.extra["hits"] == 1 and r.extra["expected_hits"] == 0.2


def test_bootstrap_ci_not_degenerate_for_short_series():
    lo, hi = scoreboard.block_bootstrap_ci([100.0, -50.0, 300.0])
    assert lo < hi


def test_bh_monotone_and_skips_none():
    q = scoreboard.benjamini_hochberg([0.01, 0.04, None, 0.03])
    assert q[2] is None
    assert q[0] <= q[3] <= q[1]


def test_result_check_rows_use_base_rate_and_latest_record(tmp_path):
    path = tmp_path / "RESULT_CHECKS.jsonl"
    recs = [
        # 同じホール・日の古い記録(結果が増える前)は使わない
        {
            "hall": "H",
            "business_date": "20261027",
            "status": "linked",
            "scores": {"人の予測": {"models": {"named": 2, "hit": [], "base": 0.5}}},
        },
        {
            "hall": "H",
            "business_date": "20261027",
            "status": "linked",
            "scores": {
                "人の予測": {
                    "models": {"named": 2, "hit": ["A"], "base": 0.25},
                    "avoid_models": {"named": 1, "hit": [], "base": 0.25},
                },
                "rev1": {"models": {"named": 1, "hit": ["A"], "base": 0.25}},
                "RB自動候補": {"jug_units": {"named": 4, "hit": [1], "base": None}},
            },
        },
        {"hall": "H", "business_date": "20261028", "status": "waiting", "scores": {}},
    ]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    rows = {r.key: r for r in scoreboard.build_result_check_rows(scoreboard.load_result_checks(path))}
    assert set(rows) == {"rc_models/人/H", "rc_avoid_models/人/H"}  # 改訂版と基準の無い記録は数えない
    assert rows["rc_models/人/H"].stat.mean == pytest.approx(25.0)  # 1/2 − 0.25
    assert rows["rc_avoid_models/人/H"].stat.mean == pytest.approx(25.0)  # 0.25 − 0/1
