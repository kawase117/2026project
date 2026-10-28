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


# ---- 打ち消しの文・動詞の「避ける」を推す/避けるとして拾わない(2026-10-29 の自動下書きで起きた誤り)

ROSTERS_1029 = {
    "金時蒲田東口店": {
        "マイジャグラーⅥ": {601, 603, 606},
        "ジャグラーガールズSS": {642},
        "ミスタージャグラー": {700},
    },
    "金時京急蒲田店": {"ミリオンゴッド‐神々の軌跡‐": {101, 102}, "真打吉宗": {201}, "獣王": {301}},
    "ARROW池上店": {
        "革命機ヴァルヴレイヴ2": {11, 12},
        "東京喰種": {21},
        "ソードアート・オンラインII": {31},
        "獣王": {41},
    },
}

DOC_1029 = """# 予測

## 金時東口

判断: 機種を絞る根拠がない。ジャグラー候補(マイⅥ 606・601・603、ガールズ 642、ミスター 700)を開店後のRBで確認する。稼働が少なく判断は弱い。

## 金時京急

判断: 機種を絞る根拠がなく、開店後の末尾別RB初期値とホール全体の稼働で確認する。直近の高設定候補（ミリオンゴッド・真打吉宗）は、前日の実績だけでは翌日の固定を見込まない。

避ける: 獣王（直近−630/台）。

## ARROW

前日（10/27）の実績で強かった機種は3種（ヴァルヴレイヴ2 +1,570、東京喰種 +1,564、SAO +1,077）だが、単日実績だけでは翌日への外挿は避けるべき。継続性の確認が必要。

### 判断

前日の上位（ヴァルヴレイヴ2・東京喰種）は単日実績だけでは翌日への外挿は避けるべき。
判断: 根拠の薄さから、特定の機種・台を推奨できない。

**避ける:** 獣王。

## ジャグラー候補

| ホール | 履歴の翌日平均 | 上位の候補 |
|---|---|---|
| 金時蒲田東口店 | 0.038 | 606・601・603(マイⅥ)、642(ガールズ)、700(ミスター) |
"""


@pytest.fixture
def rosters_1029(monkeypatch):
    monkeypatch.setattr(
        pl, "roster", lambda hall, date: ("20261028", ROSTERS_1029[hall]) if hall in ROSTERS_1029 else (None, {})
    )


def _by_hall(specs):
    return {s["hall"]: s for s in specs}


def test_jug_table_reference_is_not_a_model_pick(rosters_1029):
    s = _by_hall(pl.extract(DOC_1029, "20261029"))["金時蒲田東口店"]
    assert s["picks"]["models"] == []
    assert s["picks"]["jug_units"] == [606, 601, 603, 642, 700]
    assert s["picks"]["units"] == []
    # 推さなかった機種は消さずに skipped に残す(凍結時に表示して確認できるように)
    assert {m for sk in s["skipped"] for m in sk["models"]} >= {"ジャグラーガールズSS", "ミスタージャグラー"}


def test_negated_judgement_sentence_is_not_a_pick(rosters_1029):
    s = _by_hall(pl.extract(DOC_1029, "20261029"))["金時京急蒲田店"]
    assert s["picks"]["models"] == []
    assert s["picks"]["avoid_models"] == ["獣王"]
    assert s["skipped"][0]["models"] == ["ミリオンゴッド‐神々の軌跡‐", "真打吉宗"]


def test_avoid_requires_line_head_label(rosters_1029):
    s = _by_hall(pl.extract(DOC_1029, "20261029"))["ARROW池上店"]
    # 動詞の「避けるべき」は避ける行ではない。判断の節にあっても推さない
    assert s["picks"]["avoid_models"] == ["獣王"]
    assert s["picks"]["models"] == []


@pytest.mark.parametrize(
    "line, expected",
    [
        ("避ける: 獣王", True),
        ("避ける：獣王", True),
        ("**避ける:** 獣王", True),
        ("- 避ける機種: 獣王", True),
        ("| 獣王 | 561〜564(4台) | **避ける。** 差枚が悪い |", True),
        ("単日実績だけでは翌日への外挿は避けるべき。", False),
        ("- **語呂の数字**: 獣王は6台で30日平均 −1,153、避ける。", False),
        ("| ヤバチバ | 4 | 23%、-458 | 13% | 超え率の割に平均が負。避ける側 |", False),
    ],
)
def test_is_avoid_line(line, expected):
    assert pl.is_avoid_line(line) is expected


def test_push_parts_keeps_positive_tail_after_negated_clause():
    # 「絞る根拠はなく、分散先は…」は文末が肯定なので推す。下表を指す節は台番号だけ
    parts, skip = pl.push_parts("判断: カバネリ海門を軸に、化物語、ジャグラーは下表の台から探す。")
    assert skip == []
    assert [take for _, take in parts] == [True, True, False]
    parts, skip = pl.push_parts(
        "判断: 機種を絞る根拠がない。カバネリ海門決戦は日の効果は無いが常に強いので並べて見る。"
    )
    assert len(skip) == 1 and [take for _, take in parts] == [True]
