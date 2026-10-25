"""予測台帳の改訂は元版を保持し、採点と表示で別系列になる。"""

import json
import sqlite3
from datetime import datetime

import pytest

from backtest import prediction_ledger as pl
from backtest import scoreboard
from scripts import morning_facts

DAY = "20261025"
HALL = "楽園蒲田店"
OTHER = "みとや大森町店"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    doc = tmp_path / "2026-10-25-prediction.md"
    doc.write_text("予測", encoding="utf-8")
    specs = [
        {
            "hall": hall,
            "target_date": DAY,
            "data_asof": "20261024",
            "picks": {"models": ["A"], "avoid_models": ["B"], "units": [101], "jug_units": [102]},
            "unresolved": [],
        }
        for hall in (HALL, OTHER)
    ]
    monkeypatch.setattr(pl, "extract", lambda md, target: specs)
    return doc, tmp_path / "pred"


def at(day=25, hour=9):
    return datetime(2026, 10, day, hour, tzinfo=pl.JST)


def freeze_originals(doc, pred):
    pl.freeze_doc(doc, at(), "frozen_at", pred)


def test_revision_freeze_keeps_original_and_selects_hall(setup):
    doc, pred = setup
    freeze_originals(doc, pred)
    original = pred / f"{DAY}__rakuen.json"
    before = original.read_bytes()
    msgs = pl.freeze_doc(doc, at(25, 11), "frozen_at", pred, "rev1", [HALL], "記載訂正")
    revised = pred / f"{DAY}__rakuen__rev1.json"
    obj = json.loads(revised.read_text(encoding="utf-8"))
    assert len(msgs) == 1 and "凍結" in msgs[0]
    assert obj["prediction_id"] == f"{DAY}__rakuen__rev1"
    assert (obj["revision_of"], obj["revision"], obj["revision_reason"]) == (f"{DAY}__rakuen", "rev1", "記載訂正")
    assert obj["timing"] == "same_day"
    assert original.read_bytes() == before
    assert not (pred / f"{DAY}__mitoya__rev1.json").exists()
    ledger = [json.loads(line) for line in (pred / pl.LEDGER_NAME).read_text(encoding="utf-8").splitlines()]
    assert ledger[-1]["prediction_id"] == obj["prediction_id"]
    assert ledger[-1]["digest"] == obj["digest"]


def test_revision_resolves_short_hall_name(setup):
    doc, pred = setup
    freeze_originals(doc, pred)
    pl.freeze_doc(doc, at(), "frozen_at", pred, "rev1", ["楽園"])
    assert (pred / f"{DAY}__rakuen__rev1.json").exists()
    assert not (pred / f"{DAY}__mitoya__rev1.json").exists()


@pytest.mark.parametrize("case", ["missing", "scored", "duplicate", "late"])
def test_revision_refusal_does_not_write(setup, case):
    doc, pred = setup
    if case != "missing":
        freeze_originals(doc, pred)
    original = pred / f"{DAY}__rakuen.json"
    if case == "scored":
        obj = json.loads(original.read_text(encoding="utf-8"))
        obj["result"] = {"models": None}
        original.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    if case == "duplicate":
        pl.freeze_doc(doc, at(), "frozen_at", pred, "rev1", [HALL])
    before = {p.name: p.read_bytes() for p in pred.iterdir()} if pred.exists() else {}
    msgs = pl.freeze_doc(doc, at(26) if case == "late" else at(), "frozen_at", pred, "rev1", [HALL])
    assert len(msgs) == 1 and "改訂拒否" in msgs[0]
    assert ({p.name: p.read_bytes() for p in pred.iterdir()} if pred.exists() else {}) == before


@pytest.mark.parametrize(
    "args",
    [
        ["--revision", "v2", "--hall", HALL],
        ["--revision", "rev", "--hall", HALL],
        ["--revision", "rev1"],
        ["--revision", "rev1", "--hall", "未知のホール"],
    ],
)
def test_cli_invalid_revision_options_write_nothing(setup, monkeypatch, args):
    doc, pred = setup
    monkeypatch.setattr(pl, "PRED_DIR", pred)
    with pytest.raises(SystemExit) as exc:
        pl.main(["freeze-doc", str(doc), *args])
    assert exc.value.code == 2
    assert not pred.exists()


def test_score_due_scores_revision_and_rejects_tamper(setup, tmp_path, monkeypatch):
    doc, pred = setup
    freeze_originals(doc, pred)
    pl.freeze_doc(doc, at(), "frozen_at", pred, "rev1", [HALL])
    db = tmp_path / "score.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, diff_coins_normalized REAL)"
        )
        con.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?)",
            [
                (DAY, 101, "A", 1000),
                (DAY, 102, "B", -500),
            ],
        )
    monkeypatch.setattr(pl, "_ro", lambda hall: sqlite3.connect(db))
    revised = pred / f"{DAY}__rakuen__rev1.json"
    valid_revision = revised.read_bytes()
    obj = json.loads(revised.read_text(encoding="utf-8"))
    assert pl.score(obj)["result"]["models"]["edge"] == 750
    obj = json.loads(revised.read_text(encoding="utf-8"))
    obj["picks"]["models"] = ["B"]
    revised.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    msgs = pl.score_due(pred)
    assert any("未採点" in m and "digest" in m for m in msgs)
    assert json.loads(revised.read_text(encoding="utf-8"))["result"] is None
    # 元版の採点後も、未採点の正しい改訂は glob 対象として採点される。
    revised.write_bytes(valid_revision)
    msgs = pl.score_due(pred)
    assert any("採点" in m and revised.name in m for m in msgs)
    assert json.loads(revised.read_text(encoding="utf-8"))["result"] is not None


def test_scoreboard_revision_is_separate_series():
    base = {
        "hall": HALL,
        "target_date": DAY,
        "timing": "pre_open",
        "result": {"models": {"edge": 100}, "avoid_models": None, "units": None, "jug_units": None},
    }
    original = scoreboard.build_prediction_rows([base])
    assert [r.key for r in original] == [f"pred_models/{HALL}"]
    revised = {
        **base,
        "revision_of": f"{DAY}__rakuen",
        "revision": "rev1",
        "result": {**base["result"], "models": {"edge": 200}},
    }
    rows = scoreboard.build_prediction_rows([base, revised])
    assert {r.key for r in rows} == {f"pred_models/{HALL}", f"pred_models[rev1]/{HALL}"}
    assert next(r for r in rows if r.key == f"pred_models/{HALL}").stat.n_days == 1
    scoreboard.finalize(rows)


def test_morning_lines_include_revision_after_original(tmp_path):
    pred = tmp_path / "pred"
    pred.mkdir()
    base = {
        "picks": {"models": ["A"]},
        "result": {"day_mean": 0, "universe_size": 2, "models": {"n_machines": 1, "mean_diff": 100, "edge": 100}},
    }
    (pred / f"{DAY}__rakuen.json").write_text(json.dumps(base), encoding="utf-8")
    original_lines = morning_facts.ledger_lines(pred, "rakuen", DAY)
    assert not any("改訂" in line for line in original_lines)
    (pred / f"{DAY}__rakuen__rev1.json").write_text(json.dumps({**base, "revision": "rev1"}), encoding="utf-8")
    lines = morning_facts.ledger_lines(pred, "rakuen", DAY)
    assert lines[: len(original_lines)] == original_lines
    assert any(line.startswith("改訂rev1: ") for line in lines)
    (pred / f"{DAY}__rakuen.json").unlink()
    assert any(line.startswith("改訂rev1: ") for line in morning_facts.ledger_lines(pred, "rakuen", DAY))
