import json
import sqlite3
from datetime import date, timedelta
from types import SimpleNamespace

from backtest import event_days


def _dbs(tmp_path):
    analysis = tmp_path / "analysis.db"
    state = tmp_path / "state.db"
    con = sqlite3.connect(analysis)
    con.executescript(
        """
        create table external_result_reports (
          report_id text primary key, tweet_url text, posted_at text,
          hall_name text, business_date text
        );
        create table external_result_machines (report_id text, image_path text,
          machine_number integer);
        """
    )
    con.commit()
    con.close()
    con = sqlite3.connect(state)
    con.executescript(
        """
        create table accounts (handle text primary key, hall text, role text);
        create table seen_tweets (tweet_id text primary key, handle text,
          tweet_url text, posted_at_jst text, tweet_text text, full_text text);
        """
    )
    con.commit()
    con.close()
    return analysis, state


def _args(tmp_path, event_ledger, analysis, state, dry=False):
    return SimpleNamespace(
        event_ledger=str(event_ledger),
        analysis_db=str(analysis),
        state_db=str(state),
        links_ledger=str(tmp_path / "EVENT_RESULT_LINKS.jsonl"),
        dry_run=dry,
    )


def _write_events(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_link_report_delay_and_same_day_events(tmp_path):
    analysis, state = _dbs(tmp_path)
    business = date.today() - timedelta(days=30)
    ds = business.strftime("%Y%m%d")
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(
        events,
        [
            {"event_id": "e1", "hall": "楽園", "date": ds, "event_name": "A"},
            {"event_id": "e2", "hall": "楽園", "date": ds, "event_name": "B"},
        ],
    )
    con = sqlite3.connect(analysis)
    posted = (business + timedelta(days=30)).isoformat() + "T10:00:00+09:00"
    con.execute(
        "insert into external_result_reports values (?,?,?,?,?)",
        ("r1", "https://x.test/status/r1", posted, "楽園蒲田店", ds),
    )
    con.execute("insert into external_result_machines values (?,?,?)", ("r1", "x", 1))
    con.commit()
    con.close()
    assert event_days.cmd_link(_args(tmp_path, events, analysis, state)) == 0
    row = _rows(tmp_path / "EVENT_RESULT_LINKS.jsonl")[0]
    assert row["status"] == "linked"
    assert row["delay_days"] == 30
    assert row["event_ids"] == ["e1", "e2"]


def test_candidates_not_found_and_before_business_date_are_handled(tmp_path):
    analysis, state = _dbs(tmp_path)
    waiting = date.today() - timedelta(days=10)
    old = date.today() - timedelta(days=46)
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(
        events,
        [
            {"event_id": "w", "hall": "楽園", "date": waiting.strftime("%Y%m%d")},
            {"event_id": "o", "hall": "楽園", "date": old.strftime("%Y%m%d")},
        ],
    )
    con = sqlite3.connect(state)
    con.execute("insert into accounts values (?,?,?)", ("answer", "rakuen_kamata", "答え合わせ"))
    # 2 candidates for the waiting event; the earlier post must be ignored.
    for tid, posted, text in [
        (
            "before",
            (waiting - timedelta(days=1)).isoformat() + "T09:00:00+09:00",
            f"{waiting.month}/{waiting.day} 楽園蒲田 結果",
        ),
        (
            "c1",
            (waiting + timedelta(days=1)).isoformat() + "T09:00:00+09:00",
            f"{waiting.month}/{waiting.day} 楽園蒲田 結果1",
        ),
        (
            "c2",
            (waiting + timedelta(days=2)).isoformat() + "T09:00:00+09:00",
            f"{waiting.month}/{waiting.day} 楽園蒲田 結果2",
        ),
        # 他ホール（同チェーンの楽園柏店）と、後日の予告が過去回に触れるだけの投稿は候補にしない
        (
            "other",
            (waiting + timedelta(days=1)).isoformat() + "T09:00:00+09:00",
            f"{waiting.month}月{waiting.day}日 楽園柏店 結果",
        ),
        (
            "preview",
            (waiting + timedelta(days=3)).isoformat() + "T09:00:00+09:00",
            f"{(waiting + timedelta(days=4)).month}/{(waiting + timedelta(days=4)).day} 楽園蒲田 過去回（{waiting.month}/{waiting.day}）",
        ),
    ]:
        con.execute(
            "insert into seen_tweets values (?,?,?,?,?,?)", (tid, "answer", f"https://x.test/{tid}", posted, text, None)
        )
    con.commit()
    con.close()
    event_days.cmd_link(_args(tmp_path, events, analysis, state))
    rows = {r["business_date"]: r for r in _rows(tmp_path / "EVENT_RESULT_LINKS.jsonl")}
    assert rows[waiting.strftime("%Y%m%d")]["status"] == "multiple_candidates"
    assert {c["tweet_id"] for c in rows[waiting.strftime("%Y%m%d")]["candidate_tweets"]} == {"c1", "c2"}
    assert rows[old.strftime("%Y%m%d")]["status"] == "not_found"


def test_old_event_with_candidate_is_not_marked_not_found(tmp_path):
    """45日を過ぎても候補ツイートがある回は not_found にせず、遡及探索で拾えるよう残す。"""
    analysis, state = _dbs(tmp_path)
    old = date.today() - timedelta(days=60)
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(events, [{"event_id": "o", "hall": "楽園", "date": old.strftime("%Y%m%d")}])
    con = sqlite3.connect(state)
    con.execute("insert into accounts values (?,?,?)", ("answer", "rakuen_kamata", "答え合わせ"))
    con.execute(
        "insert into seen_tweets values (?,?,?,?,?,?)",
        (
            "late",
            "answer",
            "https://x.test/late",
            (old + timedelta(days=3)).isoformat() + "T09:00:00+09:00",
            f"{old.month}/{old.day} 楽園蒲田 結果",
            None,
        ),
    )
    con.commit()
    con.close()
    event_days.cmd_link(_args(tmp_path, events, analysis, state))
    row = _rows(tmp_path / "EVENT_RESULT_LINKS.jsonl")[0]
    assert row["status"] == "waiting"
    assert [c["tweet_id"] for c in row["candidate_tweets"]] == ["late"]


def test_link_is_idempotent_and_supersedes_when_candidate_changes(tmp_path):
    analysis, state = _dbs(tmp_path)
    business = date.today() - timedelta(days=5)
    ds = business.strftime("%Y%m%d")
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(events, [{"event_id": "e", "hall": "楽園", "date": ds}])
    con = sqlite3.connect(state)
    con.execute("insert into accounts values (?,?,?)", ("answer", "rakuen_kamata", "結果報告"))
    con.commit()
    con.close()
    args = _args(tmp_path, events, analysis, state)
    event_days.cmd_link(args)
    event_days.cmd_link(args)
    assert len(_rows(tmp_path / "EVENT_RESULT_LINKS.jsonl")) == 1
    con = sqlite3.connect(state)
    con.execute(
        "insert into seen_tweets values (?,?,?,?,?,?)",
        (
            "new",
            "answer",
            "https://x.test/new",
            (business + timedelta(days=1)).isoformat(),
            f"{business.month}/{business.day} 楽園蒲田 結果",
            None,
        ),
    )
    con.commit()
    con.close()
    event_days.cmd_link(args)
    rows = _rows(tmp_path / "EVENT_RESULT_LINKS.jsonl")
    assert len(rows) == 2
    assert rows[1]["supersedes"] == rows[0]["row_id"]
    assert rows[1]["candidate_tweets"][0]["tweet_id"] == "new"
