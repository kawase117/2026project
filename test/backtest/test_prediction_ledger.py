# -*- coding: utf-8 -*-
"""予測文書の台帳(backtest.prediction_ledger)の抽出・凍結・採点を固定する。"""

import json
import os
import sqlite3
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import prediction_ledger as pl  # noqa: E402

HALL = "楽園蒲田店"
ROSTER = {
    "甲鉄城のカバネリ 海門(うなと)決戦": {1001, 1002},
    "からくりサーカス": {1101},
    "からくりサーカス2": {1102, 1103},
    "うみねこのなく頃に2": {1201},
    "獣王": {1301},
    "ネオアイムジャグラーEX": {1401, 1402, 1403},
}

DOC = """# 予測

## 楽園蒲田(木曜)

- 避ける機種: 獣王(−1,815)。
- 1102は前日+3,000だが根拠にしない。

判断: 狙い台を絞る根拠はなく、分散先はカバネリ海門・からくり2。ジャグラーは下表(ネオアイムEXの1401)。

## ジャグラー候補

| ホール | 履歴の翌日平均 | 上位の候補 |
|---|---|---|
| 楽園蒲田店 | 0.094 | 1401・1402(ネオアイムEX)。1402は3,755GでRB 14と良好 |
"""


@pytest.fixture
def roster(monkeypatch):
    monkeypatch.setattr(pl, "roster", lambda hall, date: ("20261014", ROSTER) if hall == HALL else (None, {}))


def test_extract_judgement_avoid_and_jug_table(roster):
    [s] = pl.extract(DOC, "20261015")
    p = s["picks"]
    # 助詞の後ろの機種名を拾い、「からくり2」を初代に当てない
    assert p["models"] == ["甲鉄城のカバネリ 海門(うなと)決戦", "からくりサーカス2"]
    # 「根拠はなく」の「なく」を『うみねこのなく頃に2』に当てない
    assert "うみねこのなく頃に2" not in p["models"]
    assert p["avoid_models"] == ["獣王"]
    # 表の G 数(3,755G)を台番号と取り違えない。判断行が表を指すだけの台は jug 側で1回だけ数える
    assert p["jug_units"] == [1401, 1402]
    assert p["units"] == []


def test_timing():
    t = "20261015"
    assert pl.timing_of(datetime(2026, 10, 15, 9, 59, tzinfo=pl.JST), t) == "pre_open"
    assert pl.timing_of(datetime(2026, 10, 15, 23, 0, tzinfo=pl.JST), t) == "same_day"
    assert pl.timing_of(datetime(2026, 10, 16, 0, 1, tzinfo=pl.JST), t) == "after"


def test_freeze_does_not_overwrite_and_score_detects_tamper(roster, tmp_path):
    [s] = pl.extract(DOC, "20261015")
    when = datetime(2026, 10, 15, 9, 0, tzinfo=pl.JST)
    path = pl.freeze(s, when, "frozen_at", "doc.md", tmp_path)
    assert path is not None
    assert pl.freeze(s, when, "frozen_at", "doc.md", tmp_path) is None  # 2回目は書かない
    assert len((tmp_path / pl.LEDGER_NAME).read_text(encoding="utf-8").splitlines()) == 1

    obj = json.loads(path.read_text(encoding="utf-8"))
    assert obj["timing"] == "pre_open"
    obj["picks"]["models"].append("獣王")
    with pytest.raises(ValueError, match="digest"):
        pl.score(obj)


def test_score_edges_against_day_mean(roster, tmp_path, monkeypatch):
    db = tmp_path / f"{HALL}.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE machine_detailed_results "
        "(date TEXT, machine_number INT, machine_name TEXT, diff_coins_normalized REAL)"
    )
    rows = [(n, name) for name, nums in ROSTER.items() for n in sorted(nums)]
    diffs = {1001: 1000, 1002: 600, 1102: 200, 1103: 0, 1301: -900, 1401: 300, 1402: -100}
    con.executemany(
        "INSERT INTO machine_detailed_results VALUES ('20261015', ?, ?, ?)",
        [(n, name, diffs.get(n, 0)) for n, name in rows],
    )
    con.commit()
    con.close()
    monkeypatch.setattr(pl, "DB_DIR", tmp_path)

    [s] = pl.extract(DOC, "20261015")
    path = pl.freeze(s, datetime(2026, 10, 15, 9, 0, tzinfo=pl.JST), "frozen_at", "doc.md", tmp_path / "pred")
    obj = pl.score(json.loads(path.read_text(encoding="utf-8")))
    r = obj["result"]
    day_mean = sum(diffs.get(n, 0) for n, _ in rows) / len(rows)
    assert r["day_mean"] == round(day_mean, 1)
    # 機種は台合計/台数(機種平均の単純平均ではない): (1000+600+200+0)/4
    assert r["models"]["edge"] == round(450 - day_mean, 1)
    assert r["avoid_models"]["edge"] == round(day_mean - (-900), 1)
    assert r["jug_units"]["edge"] == round(100 - day_mean, 1)
    with pytest.raises(ValueError, match="採点済み"):
        pl.score(obj)
