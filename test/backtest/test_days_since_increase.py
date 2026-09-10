# -*- coding: utf-8 -*-
"""days_since_increase が正しい機種に紐付くことを固定する。

2026-09-11 に merge_asof の索引を reindex で戻して、経過日数が無関係な機種に
付いた。楽園の増台ルールが甲鉄城のカバネリではなくスマスロ北斗の拳を選び、
凍結済み plan を1件破棄することになった。位置で貼り直すこと。
"""

import os
import sqlite3
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import run_backtest  # noqa: E402


@pytest.fixture
def analysis_db(tmp_path, monkeypatch):
    path = tmp_path / "analysis_results.db"
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE model_inventory (hall_name TEXT, date TEXT, machine_name TEXT, "
        "n_machines INTEGER, delta INTEGER, counterpart TEXT, change_kind TEXT)"
    )
    con.executemany(
        "INSERT INTO model_inventory VALUES (?,?,?,?,?,?,?)",
        [
            ("H", "20260901", "カバネリ", 26, 8, None, "increase"),
            ("H", "20260905", "ヴァルヴレイヴ", 10, 4, None, "increase"),
            ("H", "20260905", "端数", 10, 2, None, "increase"),  # delta<3 は増台と見なさない
            ("H", "20260905", "リコリス", 22, 22, None, "new"),  # 新台は別物
        ],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(run_backtest, "ANALYSIS_DB", path)
    return path


def frame(rows):
    df = pd.DataFrame(rows, columns=["date", "machine_name"])
    # 索引をわざと連番から外す。reindex で戻すと壊れることを検出するため。
    df.index = range(100, 100 + len(df))
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def test_days_are_attached_to_the_right_model(analysis_db):
    df = frame(
        [
            ("20260907", "ヴァルヴレイヴ"),
            ("20260907", "カバネリ"),
            ("20260907", "北斗"),
            ("20260907", "リコリス"),
            ("20260907", "端数"),
        ]
    )
    out = run_backtest._days_since_increase("H", df)
    got = dict(zip(df["machine_name"], out))
    assert got["カバネリ"] == 6  # 9/1 の増台
    assert got["ヴァルヴレイヴ"] == 2  # 9/5 の増台
    assert pd.isna(got["北斗"])  # 増台なし
    assert pd.isna(got["リコリス"])  # 新台は増台に数えない
    assert pd.isna(got["端数"])  # delta<3 は数えない


def test_index_is_preserved(analysis_db):
    df = frame([("20260907", "カバネリ"), ("20260903", "ヴァルヴレイヴ")])
    out = run_backtest._days_since_increase("H", df)
    assert list(out.index) == list(df.index)


def test_only_looks_backward(analysis_db):
    # 増台より前の日には値が付かない。未来の増台を先取りしてはいけない。
    df = frame([("20260831", "カバネリ")])
    assert pd.isna(run_backtest._days_since_increase("H", df).iloc[0])


def test_uses_the_most_recent_increase(analysis_db):
    df = frame([("20260910", "カバネリ")])
    assert run_backtest._days_since_increase("H", df).iloc[0] == 9


def test_other_hall_events_do_not_leak(analysis_db):
    df = frame([("20260907", "カバネリ")])
    assert pd.isna(run_backtest._days_since_increase("別ホール", df).iloc[0])


def test_missing_analysis_db_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(run_backtest, "ANALYSIS_DB", tmp_path / "nope.db")
    df = frame([("20260907", "カバネリ")])
    assert run_backtest._days_since_increase("H", df).isna().all()
