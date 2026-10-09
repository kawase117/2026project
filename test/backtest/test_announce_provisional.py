"""仮登録・事後登録・修正(amend)の台帳まわりのテスト(合成データのみ)。"""

import json

import pandas as pd
import pytest

from backtest import announce


def _payload(**over):
    obj = {
        "announce_id": "h__20261008__acct",
        "hall": "ホールX",
        "target_date": "20261008",
        "source": {"account": "acct", "url": "u", "posted_at": "2026-10-07T22:00:00+09:00", "kind": "予告"},
        "raw_text": "本文",
        "zentaikei": {"metric": "gratio_mean_diff", "threshold": 1800.0, "min_machines": 3},
        "claims": [{"type": "model_named", "machine_name": "機種A"}],
        "result": None,
        "announce_digest": None,
    }
    obj.update(over)
    return obj


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(announce, "ANNOUNCE_DIR", tmp_path)
    monkeypatch.setattr(announce, "LEDGER", tmp_path / "LEDGER.jsonl")
    return tmp_path


def _frame(db_max):
    return pd.DataFrame({"date": [db_max]})


def _lines(ledger_dir):
    return [json.loads(x) for x in (ledger_dir / "LEDGER.jsonl").read_text(encoding="utf-8").splitlines()]


def test_empty_claims_only_allowed_when_provisional():
    with pytest.raises(ValueError):
        announce.validate(_payload(claims=[]))
    announce.validate(_payload(claims=[], provisional=True))


def test_posted_after_midnight_before_open_is_accepted_but_flagged(ledger, monkeypatch):
    monkeypatch.setattr(announce, "load_frame", lambda hall: _frame("20261007"))
    obj = _payload(source={"account": "acct", "url": "u", "posted_at": "2026-10-08T00:26:00+09:00", "kind": "予告"})
    announce.register_object(ledger / "a.json", obj)
    assert _lines(ledger)[0]["posted_after_midnight"] is True


def test_posted_after_open_is_rejected():
    obj = _payload(source={"account": "acct", "url": "u", "posted_at": "2026-10-08T10:00:00+09:00", "kind": "予告"})
    with pytest.raises(ValueError):
        announce.validate(obj)


def test_register_rejects_after_db_max_unless_post_hoc(ledger, monkeypatch):
    monkeypatch.setattr(announce, "load_frame", lambda hall: _frame("20261008"))
    with pytest.raises(SystemExit):
        announce.register_object(ledger / "a.json", _payload())
    announce.register_object(ledger / "a.json", _payload(), post_hoc=True)
    rec = _lines(ledger)[0]
    assert rec["late_registration"] is True and rec["post_hoc"] is True


def test_amend_appends_ledger_line_and_keeps_digest_valid(ledger, monkeypatch):
    monkeypatch.setattr(announce, "load_frame", lambda hall: _frame("20261007"))
    path = ledger / "a.json"
    obj = announce.register_object(path, _payload(claims=[], provisional=True))
    obj["claims"] = [{"type": "model_named", "machine_name": "機種B"}]
    announce.amend_object(path, obj, reason="機種名を補完")
    lines = _lines(ledger)
    assert [x.get("kind") for x in lines] == [None, "amendment"]
    assert lines[0]["claims_detail"] == []
    assert lines[1]["claims_detail"][0]["machine_name"] == "機種B"
    announce._verify_ledger(json.loads(path.read_text(encoding="utf-8")))


def test_voided_announce_is_not_scored(ledger, monkeypatch):
    monkeypatch.setattr(announce, "load_frame", lambda hall: _frame("20261007"))
    path = ledger / "a.json"
    obj = announce.register_object(path, _payload())
    obj = announce.amend_object(path, obj, reason="結果発表であって予告ではない", void=True)
    assert _lines(ledger)[-1]["voided"] is True
    with pytest.raises(ValueError):
        announce.score(obj)
