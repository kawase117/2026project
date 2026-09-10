# -*- coding: utf-8 -*-
"""朝のチートシートの窓の切り方を固定する。

効果が7日で消えることが実測なので、8日目の増台を拾ってしまうと紙の主張が
根拠を失う。境界は境界としてテストする。
"""

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import morning  # noqa: E402


@pytest.fixture
def analysis(tmp_path):
    path = tmp_path / "analysis.db"
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE model_inventory (hall_name TEXT, date TEXT, machine_name TEXT, "
        "n_machines INTEGER, delta INTEGER, counterpart TEXT, change_kind TEXT)"
    )
    rows = [
        ("H", "20260910", "当日増台", 10, 4, None, "increase"),
        ("H", "20260904", "7日目増台", 10, 4, None, "increase"),  # 経過6日 = 窓の最終日
        ("H", "20260903", "8日目増台", 10, 4, None, "increase"),  # 窓の外
        ("H", "20260910", "端数増台", 10, 2, None, "increase"),  # delta < 3
        ("H", "20260910", "新台", 8, 8, None, "new"),
        ("H", "20260910", "減台", 4, -5, None, "decrease"),
        ("別ホール", "20260910", "他店増台", 10, 4, None, "increase"),
    ]
    con.executemany("INSERT INTO model_inventory VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def test_shift_crosses_month_boundary():
    assert morning._shift("20260901", -6) == "20260826"
    assert morning._shift("20260301", -1) == "20260228"


def test_recent_increases_window_is_seven_days_inclusive(analysis):
    names = [row[1] for row in morning.recent_increases(analysis, "H", "20260910")]
    assert names == ["当日増台", "7日目増台"]


def test_recent_increases_excludes_new_and_decrease_and_small_delta(analysis):
    names = [row[1] for row in morning.recent_increases(analysis, "H", "20260910")]
    assert "新台" not in names
    assert "減台" not in names
    assert "端数増台" not in names


def test_recent_increases_does_not_leak_other_halls(analysis):
    names = [row[1] for row in morning.recent_increases(analysis, "H", "20260910")]
    assert "他店増台" not in names


def test_fading_increases_starts_where_the_window_ends(analysis):
    names = [row[1] for row in morning.fading_increases(analysis, "H", "20260910")]
    assert names == ["8日目増台"]


def test_new_models_are_reported_separately(analysis):
    names = [row[1] for row in morning.new_models(analysis, "H", "20260910")]
    assert names == ["新台"]


def test_every_measured_hall_has_a_frozen_edge():
    # 紙にホール別の実測を載せる以上、符号と件数が揃っていること
    for hall, (edge, win_rate, n) in morning.HALL_INCREASE_EDGE.items():
        assert isinstance(hall, str) and hall
        assert -10 < edge < 10
        assert 0 <= win_rate <= 100
        assert n > 0
