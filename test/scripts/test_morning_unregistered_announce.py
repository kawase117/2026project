"""朝の予測: 未登録の予告を判断に使わせない。登録済みの予告に無い台番号は不合格にする。"""

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_morning_docs as morning  # noqa: E402

TODAY = "20261101"


def write_announce(directory, key, handle, raw_text, claims=None, void=False):
    obj = {"raw_text": raw_text, "claims": claims or [], "amendments": [{"void": True}] if void else []}
    (directory / f"{key}__{TODAY}__{handle}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def errors_for(line):
    return morning.validate_prediction("## 蒲田7\n" + line + "\n", "kamata7", TODAY, True)


def test_number_in_announce_text_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    write_announce(tmp_path, "kamata7", "acct", "狙い目は2046番と２０４７番")
    assert errors_for("判断: 機種Aの2046番を推す。") == []
    assert errors_for("判断: 機種Aの2047番を推す。") == []


def test_number_in_claims_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    write_announce(tmp_path, "kamata7", "acct", "本文", claims=[{"machine_number": 2046}])
    assert errors_for("判断: 2046番を推す。") == []


def test_number_missing_from_announce_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    write_announce(tmp_path, "kamata7", "acct", "狙い目は2046番")
    errors = errors_for("判断: 機種Aの2046番と2050番を推す。")
    assert len(errors) == 1 and "(2050)" in errors[0]


def test_number_without_any_announce_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    assert any("2046" in e for e in errors_for("判断: 機種Aの2046番を推す。"))


def test_voided_announce_does_not_justify_number(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    write_announce(tmp_path, "kamata7", "acct", "狙い目は2046番", void=True)
    assert errors_for("判断: 2046番を推す。")


def test_non_machine_numbers_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    assert errors_for("判断: 機種A(平均差枚+1,800、約300枚、2026年、1000回転、6.123)を推す。") == []
    assert errors_for("判断: 基準の3機種に絞る。") == []


def test_numbers_outside_judgement_line_are_not_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", tmp_path)
    assert errors_for("判断: 基準どおり。\n- 補足: 2046番は強かった。") == []


def make_state_db(path, rows):
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE seen_tweets (tweet_id TEXT, handle TEXT, tweet_url TEXT, tweet_text TEXT, "
        "posted_at_jst TEXT, scraped_at_jst TEXT, has_image INTEGER, full_text TEXT)"
    )
    con.executemany("INSERT INTO seen_tweets (tweet_id, handle, tweet_text, posted_at_jst) VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()


def test_unregistered_post_is_reported_only_when_no_json(tmp_path, monkeypatch):
    from backtest import announce_autodraft as ad

    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    posted = datetime.now().astimezone().replace(hour=1, minute=0)
    today = posted.strftime("%Y%m%d")
    db = tmp_path / "state.db"
    make_state_db(db, [("111", "acct_new", "%d/%d 楽園蒲田店 予告" % (posted.month, posted.day), posted.isoformat())])
    monkeypatch.setattr(ad, "STATE_DB", db)
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", announce_dir)

    assert morning.unregistered_announce_posts("rakuen", today) == [("acct_new", "https://x.com/acct_new/status/111")]
    assert "acct_new" in morning.unregistered_announce_block("rakuen", today)
    assert morning.unregistered_announce_posts("kamata7", today) == []

    (announce_dir / f"rakuen__{today}__acct_new.json").write_text("{}", encoding="utf-8")
    assert morning.unregistered_announce_posts("rakuen", today) == []
    assert morning.unregistered_announce_block("rakuen", today) == ""


def test_prompt_no_longer_tells_llm_to_read_collected_tweets():
    prompt = morning.prediction_prompt("kamata7", TODAY, "20261031", Path("a.md"), Path("b.md"))
    assert "未登録の予告があれば読む" not in prompt
    assert "予告として使ってよいのは登録済みのファイルだけ" in prompt
