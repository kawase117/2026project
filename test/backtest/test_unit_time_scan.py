import datetime as dt

import numpy as np
import pandas as pd

import backtest.unit_time_scan as us


def _days(n=84, start=dt.date(2026, 1, 1)):
    return [(start + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _frame(days, boost_days=(), seed=0):
    """機種A(RB側)と機種B(機械割側)。boost_daysの日だけ、Aの当りを2倍にする。"""
    rng = np.random.default_rng(seed)
    rows = []
    for d in days:
        for num in range(3):
            g = 3000.0
            e = 10.0
            hit = rng.poisson(e * (2.0 if d in boost_days else 1.0))
            rows.append(
                dict(ds=d, machine_name="A", section="s1", seg="RB", hit=hit, E=e, diff=0.0, Ediff=np.nan, G=g, Gx=g)
            )
            diff = float(rng.normal(0, 300))
            rows.append(
                dict(
                    ds=d,
                    machine_name="B",
                    section="s2",
                    seg="OTHER",
                    hit=np.nan,
                    E=np.nan,
                    diff=diff,
                    Ediff=0.0,
                    G=g,
                    Gx=g,
                )
            )
    return pd.DataFrame(rows)


def test_bh_is_monotone_and_bounded():
    q = us._bh(pd.Series([0.001, 0.02, 0.5, 0.04]))
    assert q.between(0, 1).all()
    assert q.iloc[0] <= q.iloc[3] <= q.iloc[2]


def test_perm_index_stays_inside_strata():
    strata = np.array(["a", "a", "a", "b", "b", "b"])
    out = us.perm_index(strata, 50, np.random.default_rng(1))
    assert set(out[:, :3].ravel()) <= {0, 1, 2}
    assert set(out[:, 3:].ravel()) <= {3, 4, 5}


def test_strata_weekday_axis_uses_month():
    days = ["20260101", "20260102", "20260201"]
    assert list(us.strata_of("曜日", days)) == ["202601", "202601", "202602"]


def test_scan_detects_planted_effect_and_not_null():
    days = _days()
    mondays = {d for d in days if dt.datetime.strptime(d, "%Y%m%d").weekday() == 0}
    df = _frame(days, boost_days=mondays)
    ax = us.time_labels(days, pd.Series(1.0, index=days), set())
    F, C = us.scan_units(df, "machine_name", ax, days, B=400, min_unit_days=30)
    hit = C[(C.axis == "曜日") & (C.level == "月曜") & (C.outcome == "RB当り") & (C.unit == "A")]
    assert len(hit) == 1 and hit.p.iloc[0] < 0.01 and hit.obs.iloc[0] > 0.5
    null = C[(C.axis == "曜日") & (C.level == "火曜") & (C.outcome == "RB当り") & (C.unit == "A")]
    assert abs(null.obs.iloc[0]) < 0.3


def test_outcome_is_limited_to_its_own_segment():
    days = _days(56)
    df = _frame(days)
    ax = us.time_labels(days, pd.Series(1.0, index=days), set())
    F, C = us.scan_units(df, "machine_name", ax, days, B=100, min_unit_days=30)
    assert C[(C.unit == "B") & (C.outcome == "RB当り")].empty
    assert C[(C.unit == "A") & (C.outcome == "機械割")].empty


def test_machine_type_groups():
    assert us.machine_type("マイジャグラーV", "ノーマル") == "ジャグラー"
    assert us.machine_type("新ハナビ", "A+AT") == "ハナハナ・ハナビ"
    assert us.machine_type("北斗の拳", "AT") == "AT・ART"
