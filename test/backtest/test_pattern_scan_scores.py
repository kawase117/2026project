"""2026-11-01 追加の score: all_eligible・prev_day_ph・lag7/lag8_model_top1。"""

import pandas as pd
import pytest

from backtest.prereg import ALLOWED_SCORES
from backtest.run_backtest import score_history

D0 = pd.Timestamp("2026-09-15")


def _rows(day, name, diffs, start=100):
    return [
        {
            "date": day,
            "machine_number": start + i,
            "machine_name": name,
            "games_normalized": 5000,
            "diff_coins_normalized": d,
        }
        for i, d in enumerate(diffs)
    ]


def test_new_scores_are_allowed():
    assert {"all_eligible", "prev_day_ph", "lag7_model_top1", "lag8_model_top1"} <= ALLOWED_SCORES


def test_all_eligible_scores_every_machine_equally():
    hist = pd.DataFrame(_rows("20260914", "機種A", [10, -20, 30]) + _rows("20260913", "機種A", [0, 0, 0]))
    s = score_history(hist, "all_eligible")
    assert sorted(s.index) == [100, 101, 102]
    assert (s == 1.0).all()


def test_lag7_picks_the_top_machine_of_each_model_on_that_day_only():
    hist = pd.DataFrame(
        _rows("20260908", "機種A", [100, 900, -50])  # 7日前: 機種Aの1位は101
        + _rows("20260908", "機種B", [300, 200], start=200)  # 機種Bの1位は200
        + _rows("20260908", "機種C", [5000], start=300)  # 1台しかない機種は対象外
        + _rows("20260909", "機種A", [9999, 0, 0])  # 6日前の値は使わない
    )
    s = score_history(hist, "lag7_model_top1", d0=D0)
    assert sorted(s.index) == [101, 200]


def test_lag8_uses_eight_days_before():
    hist = pd.DataFrame(_rows("20260907", "機種A", [0, 0, 700]) + _rows("20260908", "機種A", [800, 0, 0]))
    assert list(score_history(hist, "lag8_model_top1", d0=D0).index) == [102]


def test_lag_is_empty_when_the_day_is_missing():
    hist = pd.DataFrame(_rows("20260909", "機種A", [1, 2, 3]))
    assert score_history(hist, "lag7_model_top1", d0=D0).empty


def test_lag_requires_d0():
    hist = pd.DataFrame(_rows("20260908", "機種A", [1, 2]))
    with pytest.raises(ValueError):
        score_history(hist, "lag7_model_top1")


def _juggler(day, rb_by_unit, games=6000, bb=24):
    return [
        {
            "date": day,
            "machine_number": u,
            "machine_name": "マイジャグラーV",
            "games_normalized": games,
            "diff_coins_normalized": 0,
            "bb_count": bb,
            "rb_count": rb,
        }
        for u, rb in rb_by_unit.items()
    ]


def test_prev_day_ph_ranks_the_unit_with_most_rb_on_the_previous_day_first():
    rows = []
    for d in range(1, 14):
        rows += _juggler("202609%02d" % d, {641: 20, 642: 20, 643: 20, 644: 20})
    rows += _juggler("20260914", {641: 15, 642: 35, 643: 18, 644: 20})  # 前日: 642 のRBが突出
    s = score_history(pd.DataFrame(rows), "prev_day_ph", d0=D0, hall="みとや大森町店")
    assert s.idxmax() == 642
    assert s.between(0, 1).all()


def test_prev_day_ph_is_empty_when_the_previous_day_is_missing():
    rows = []
    for d in range(1, 13):  # 20260914 が無い
        rows += _juggler("202609%02d" % d, {641: 20, 642: 20, 643: 20})
    assert score_history(pd.DataFrame(rows), "prev_day_ph", d0=D0, hall="みとや大森町店").empty
