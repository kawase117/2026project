# -*- coding: utf-8 -*-
"""学びの台帳(backtest.lessons)と、凍結前の点検(prediction_ledger.freeze_doc)・朝の示唆の検証を固定する。"""

import json
import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from backtest import lessons as L  # noqa: E402
from backtest import prediction_ledger as pl  # noqa: E402

HALL = "楽園蒲田店"
ROSTER = {"獣王": {1301, 1302}, "東京喰種": {1401, 1402, 1403, 1404, 1405, 1406, 1407, 1408}}
NEG = r"根拠にしない|続かない"


def ledger() -> list[dict]:
    xs: list[dict] = []
    L.add(xs, "前日の強さは続かない。", "prev_day", [r"前日", r"昨日"], ["2026-10-19", "2026-10-23"], "t", exempt=[NEG])
    L.add(
        xs,
        "少台数機種は根拠にならない。",
        "small_n_models",
        [r"(?<![\d,])[1-5]台(?![\d並])"],
        ["2026-10-07", "2026-10-08"],
        "t",
    )
    return xs


def test_add_requires_two_confirmations_or_stats():
    xs: list[dict] = []
    with pytest.raises(ValueError):
        L.add(xs, "1日だけの観察", "prev_day", ["前日"], ["2026-10-17"], "t")
    rec = L.add(xs, "統計あり", "prev_day", ["前日"], ["2026-10-17"], "t", stat_basis="n=40, edge −130")
    assert rec["id"] == "L001" and rec["reconfirmed"] == []
    rec = L.add(xs, "2回確認", "prev_day", ["前日"], ["2026-10-20", "2026-10-18"], "t")
    assert rec["id"] == "L002" and rec["first_seen"] == "2026-10-18" and rec["reconfirmed"] == ["2026-10-20"]


def test_reconfirm_counts_each_day_once():
    xs = ledger()
    assert L.reconfirm(xs, "L001", "2026-10-30", "doc") is True
    assert L.reconfirm(xs, "L001", "2026-10-30") is False
    assert L.reconfirm(xs, "L001", "2026-10-19") is False  # first_seen
    with pytest.raises(ValueError):
        L.reconfirm(xs, "L999", "2026-10-30")


def test_check_lines_blocks_only_lines_without_independent_basis():
    xs = ledger()
    lines = [
        (HALL, "avoid", "避ける: 獣王(前日 −2,733)。"),  # 前日だけ → 止める
        (HALL, "judge", "判断: 予告の指定機種を軸に。前日の強機種も参考。"),  # 予告がある → 通す
        (HALL, "judge", "判断: 予告なし。前日の強い東京喰種を推す。"),  # 「予告なし」は根拠でない → 止める
        (HALL, "judge", "判断: 前日の末尾は根拠にしない。開店後のRBで見る。"),  # 学びを正しく使っている
        (HALL, "avoid", "避ける: 獣王(5台、−400)。"),  # 少台数だけ → 止める
        (HALL, "judge", "判断: 4台並びを探す。"),  # 「4台並び」は台数の根拠ではない
    ]
    found = L.check_lines(lines, xs)
    assert [(f["line"], f["lessons"]) for f in found] == [
        (lines[0][2], ["L001"]),
        (lines[2][2], ["L001"]),
        (lines[4][2], ["L002"]),
    ]


def test_parse_allow_needs_reason_and_known_id():
    xs = ledger()
    assert L.parse_allow(["L001:予告で前日と同じ機種が名指し"], xs) == {"L001": "予告で前日と同じ機種が名指し"}
    with pytest.raises(ValueError):
        L.parse_allow(["L001"], xs)
    with pytest.raises(ValueError):
        L.parse_allow(["L009:x"], xs)


DOC = """# 予測

## 楽園蒲田

判断: 東京喰種(8台)を軸に、台数の多い機種から。

避ける: 獣王(前日 −2,733)。
"""


@pytest.fixture
def doc(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "roster", lambda hall, date: ("20261029", ROSTER) if hall == HALL else (None, {}))
    path = tmp_path / "2026-10-30-prediction.md"
    path.write_text(DOC, encoding="utf-8")
    return path


AT = datetime(2026, 10, 30, 9, 0, tzinfo=pl.JST)


def test_decision_lines_classifies_like_extract(doc):
    assert pl.decision_lines(DOC) == [
        (HALL, "judge", "判断: 東京喰種(8台)を軸に、台数の多い機種から。"),
        (HALL, "avoid", "避ける: 獣王(前日 −2,733)。"),
    ]


def test_freeze_doc_gate_blocks_without_writing(doc, tmp_path):
    pred = tmp_path / "pred"
    log: list[dict] = []
    with pytest.raises(pl.LessonBlocked) as e:
        pl.freeze_doc(doc, AT, "frozen_at", pred_dir=pred, lessons=ledger(), gate_log=log.extend)
    assert "L001" in str(e.value) and "獣王" in str(e.value)
    assert not pred.exists() or not list(pred.glob("*.json"))
    assert [(x["lesson"], x["action"]) for x in log] == [("L001", "blocked")]


def test_freeze_doc_dry_run_writes_and_logs_nothing(doc, tmp_path):
    pred = tmp_path / "pred"
    log: list[dict] = []
    msgs = pl.freeze_doc(doc, AT, "frozen_at", pred_dir=pred, lessons=ledger(), dry_run=True, gate_log=log.extend)
    assert any(m.startswith("止める") for m in msgs) and any("dry-run" in m for m in msgs)
    assert log == [] and not list(pred.glob("*.json"))


def test_freeze_doc_allow_keeps_reason_in_json(doc, tmp_path):
    pred = tmp_path / "pred"
    log: list[dict] = []
    pl.freeze_doc(
        doc, AT, "frozen_at", pred_dir=pred, lessons=ledger(), allow={"L001": "機械割が低い"}, gate_log=log.extend
    )
    obj = json.loads((pred / "20261030__rakuen.json").read_text(encoding="utf-8"))
    assert obj["picks"]["avoid_models"] == ["獣王"]
    assert obj["lesson_allows"][0]["reasons"] == {"L001": "機械割が低い"}
    assert obj["digest"] == pl._digest(obj)  # 許可の記録は digest を変えない(採点できる)
    assert [(x["lesson"], x["action"], x["reason"]) for x in log] == [("L001", "allowed", "機械割が低い")]


def test_freeze_doc_without_lessons_is_unchanged(doc, tmp_path):
    pred = tmp_path / "pred"
    pl.freeze_doc(doc, AT, "frozen_at", pred_dir=pred)  # backfill などは点検しない
    assert (pred / "20261030__rakuen.json").exists()


def test_stats_counts_blocked_allowed_and_reconfirmed(tmp_path):
    xs = ledger()
    L.reconfirm(xs, "L001", "2026-11-02")
    log = tmp_path / "log.jsonl"
    events = [
        {"at": "a1", "target_date": "20261101", "hall": HALL, "lesson": "L001", "action": "blocked"},
        {"at": "a1", "target_date": "20261101", "hall": HALL, "lesson": "L001", "action": "blocked"},  # 同じ実行の2行
        {"at": "a2", "target_date": "20261101", "hall": HALL, "lesson": "L001", "action": "allowed"},
        {"at": "a3", "target_date": "20261031", "hall": HALL, "lesson": "L002", "action": "blocked"},
    ]
    L.log_gate(events, log)
    nov = {s["id"]: s for s in L.stats(xs, "2026-11", log)}
    assert (nov["L001"]["blocked"], nov["L001"]["allowed"], nov["L001"]["reconfirmed"]) == (1, 1, 1)
    assert (nov["L002"]["blocked"], nov["L002"]["reconfirmed"]) == (0, 0)


def test_repo_ledger_is_valid():
    xs = L.load()
    assert len(xs) >= 6
    assert len({x["id"] for x in xs}) == len(xs)
    for x in xs:
        assert len(x["reconfirmed"]) >= 1 or x.get("stat_basis"), x["id"]
        assert set(x["applies_to"]) <= set(L.KINDS)


def test_morning_suggestion_rejects_prev_day_carryover():
    import run_morning_docs as morning

    text = """## 楽園

本文

## 今日（20261030）の予測への示唆

- 前日に強かった末尾2が今日も続くか見る。
- 予告あり(kawasakislot)。指定5機種を主に。
- 前日の強い機種は翌日続かない。開店後のG比で確認する。
"""
    errors = morning.suggestion_errors(text, ledger())
    assert len(errors) == 1 and "末尾2" in errors[0]
