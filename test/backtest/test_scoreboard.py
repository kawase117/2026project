# -*- coding: utf-8 -*-
"""総合採点表(backtest.scoreboard)の集計単位・除外・判定を固定する。"""

import json
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


def by_family(rows, family):
    return {r.key: r for r in rows if r.family == family}


def test_unit_is_rule_day_and_exclusions(tmp_path):
    for d in dates(12):
        write_plan(tmp_path, "good", d, 300.0 + (int(d[-2:]) % 3) * 10)
    write_plan(tmp_path, "good", "20260913", 99999.0, dry=True)  # dry run は数えない
    write_plan(tmp_path, "good", "20260914", None, scored=False)  # 未採点は数えない
    (tmp_path / "invalidated").mkdir()
    write_plan(tmp_path / "invalidated", "good", "20260915", -99999.0)  # 無効化済みは数えない

    r = by_family(scoreboard.build(tmp_path), "forward_edge")["good"]
    assert r.stat.n_days == 12
    assert 300 <= r.stat.mean <= 320
    assert r.verdict == "有効"
    assert r.extra["criterion_edge"] == 150


def test_harmful_and_insufficient(tmp_path):
    for d in dates(12):
        write_plan(tmp_path, "bad", d, -200.0 - (int(d[-2:]) % 4) * 10)
    for d in dates(4):
        write_plan(tmp_path, "few", d, 500.0)
    rows = by_family(scoreboard.build(tmp_path), "forward_edge")
    assert rows["bad"].verdict == "有害"
    assert rows["few"].verdict == "標本不足"


def test_noise_is_not_called_effective(tmp_path):
    vals = [800, -900, 700, -600, 500, -800, 900, -700, 600, -500, 400, -300]
    for d, v in zip(dates(12), vals, strict=True):
        write_plan(tmp_path, "noisy", d, float(v))
    r = by_family(scoreboard.build(tmp_path), "forward_edge")["noisy"]
    assert r.verdict == "差を検出できず"
    assert r.days_needed and r.days_needed > 0


def test_rb_ratio_family_centered_at_zero(tmp_path):
    for d in dates(10):
        write_plan(tmp_path, "rb", d, 0.0, ratios=[1.2, 1.4])
    r = by_family(scoreboard.build(tmp_path), "forward_rb")["rb"]
    assert abs(r.stat.mean - 0.3) < 1e-9


def test_juggler_ledger_one_value_per_day(tmp_path):
    lines = [
        {"hall": "店", "date": "20261001", "model": "マイ", "top_ph": 0.3, "rest_ph": 0.1},
        {"hall": "店", "date": "20261002", "model": "マイ", "top_ph": 0.2, "rest_ph": 0.2},
    ]
    (tmp_path / scoreboard.JUGGLER_LEDGER_NAME).write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8"
    )
    r = by_family(scoreboard.build(tmp_path), "juggler_ph")["店/マイ"]
    assert r.stat.n_days == 2
    assert abs(r.stat.mean - 0.1) < 1e-9


def test_bootstrap_ci_not_degenerate_for_short_series():
    lo, hi = scoreboard.block_bootstrap_ci([100.0, -50.0, 300.0])
    assert lo < hi


def test_bh_monotone_and_skips_none():
    q = scoreboard.benjamini_hochberg([0.01, 0.04, None, 0.03])
    assert q[2] is None
    assert q[0] <= q[3] <= q[1]
