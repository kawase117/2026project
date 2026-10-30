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


def _add_report(analysis, report_id, ds, posted):
    con = sqlite3.connect(analysis)
    con.execute(
        "insert into external_result_reports values (?,?,?,?,?)",
        (report_id, f"https://x.test/status/{report_id}", posted, "楽園蒲田店", ds),
    )
    con.execute("insert into external_result_machines values (?,?,?)", (report_id, "x", 1))
    con.commit()
    con.close()


def test_link_changes_are_reported_only_when_status_changes(tmp_path, capsys):
    """遅れて出た結果発表で waiting→linked に変わった過去回を、変化があるときだけ書き出す。"""
    analysis, state = _dbs(tmp_path)
    business = date.today() - timedelta(days=20)
    ds = business.strftime("%Y%m%d")
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(events, [{"event_id": "e", "hall": "楽園", "date": ds}])
    out = tmp_path / "out" / "link_changes.md"
    args = _args(tmp_path, events, analysis, state)
    args.changes_out = str(out)

    # 初回の waiting は変化として扱わない（ファイルも作らない）。
    event_days.cmd_link(args)
    assert not out.exists()
    assert "結果発表の紐付けが変わった過去回" not in capsys.readouterr().out

    # 変化なしの再実行でも、ファイルは作らない。
    event_days.cmd_link(args)
    assert not out.exists()

    # 結果発表が遅れて出ると waiting → linked として記録される。
    _add_report(analysis, "r1", ds, (business + timedelta(days=20)).isoformat() + "T10:00:00+09:00")
    event_days.cmd_link(args)
    text = out.read_text(encoding="utf-8")
    assert "楽園蒲田店" in text or "楽園" in text
    assert "waiting → linked" in text
    assert "営業日の 20 日後" in text
    assert "結果発表の紐付けが変わった過去回: 1 件" in capsys.readouterr().out

    # 同じ日に再度走って変化が無ければ、追記もしない。
    before = out.read_text(encoding="utf-8")
    event_days.cmd_link(args)
    assert out.read_text(encoding="utf-8") == before

    # 報告が増えたとき（linked のまま）は追記される。前の回の記録は消えない。
    _add_report(analysis, "r2", ds, (business + timedelta(days=21)).isoformat() + "T10:00:00+09:00")
    event_days.cmd_link(args)
    after = out.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert len(after) > len(before)
    assert after.count("linked → linked") == 1


def test_first_time_linked_is_reported_and_multiple_candidates_ask_for_human(tmp_path):
    analysis, state = _dbs(tmp_path)
    business = date.today() - timedelta(days=15)
    ds = business.strftime("%Y%m%d")
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(events, [{"event_id": "e", "hall": "楽園", "date": ds}])
    _add_report(analysis, "r1", ds, (business + timedelta(days=1)).isoformat() + "T10:00:00+09:00")
    out = tmp_path / "link_changes.md"
    args = _args(tmp_path, events, analysis, state)
    args.changes_out = str(out)
    event_days.cmd_link(args)
    assert "（新規） → linked" in out.read_text(encoding="utf-8")

    # 候補が複数のときは自動で選ばず、人が確認するよう書く。
    pending = [
        {
            "hall": "楽園蒲田店",
            "business_date": ds,
            "status": "multiple_candidates",
            "report_ids": [],
            "candidate_tweets": [{"tweet_id": "a"}, {"tweet_id": "b"}],
            "delay_days": None,
        }
    ]
    previous = {("楽園蒲田店", ds): {"status": "waiting", "report_ids": []}}
    lines = event_days._render_link_changes(event_days._link_changes(pending, previous))
    assert any("waiting → multiple_candidates" in line for line in lines)
    assert any("人が確認" in line for line in lines)


def _linked_row(ds, report_ids, hall="楽園蒲田店", delay=3):
    return {
        "row_id": "erl-test-1",
        "hall": hall,
        "business_date": ds,
        "status": "linked",
        "report_ids": report_ids,
        "candidate_tweets": [],
        "delay_days": delay,
    }


def test_retro_addendum_goes_to_human_doc_or_sidecar_and_is_idempotent(tmp_path):
    analysis, _state = _dbs(tmp_path)
    ds = "20260920"
    _add_report(analysis, "r1", ds, "2026-09-23T10:00:00+09:00")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    changes = [({"status": "waiting", "report_ids": []}, _linked_row(ds, ["r1"]))]

    # 答え合わせ文書が無い日は、別ファイルを作る。
    got = event_days._append_retro_addenda(changes, str(reviews), str(analysis), "2026-10-25T08:00:00+09:00")
    side = reviews / "2026-09-20-answercheck-addendum.md"
    assert got == [str(side)]
    text = side.read_text(encoding="utf-8")
    assert "追記（遡及）" in text and "https://x.test/status/r1" in text and "3 日後" in text

    # 同じ報告は二重に足さない。
    assert event_days._append_retro_addenda(changes, str(reviews), str(analysis), "x") == []
    assert side.read_text(encoding="utf-8").count("追記（遡及）") == 1

    # 人手の文書がある日は、その文書の末尾へ足し、本文は変えない。
    ds2 = "20260921"
    _add_report(analysis, "r2", ds2, "2026-09-22T10:00:00+09:00")
    human = reviews / "2026-09-21-answercheck.md"
    human.write_text("# 人手の答え合わせ\n\n本文。\n", encoding="utf-8")
    event_days._append_retro_addenda([(None, _linked_row(ds2, ["r2"], delay=1))], str(reviews), str(analysis), "x")
    body = human.read_text(encoding="utf-8")
    assert body.startswith("# 人手の答え合わせ\n\n本文。\n")
    assert "追記（遡及）" in body
    assert not (reviews / "2026-09-21-answercheck-addendum.md").exists()

    # 自動下書き（朝の処理に作り直される文書）には書かず、別ファイルへ。
    ds3 = "20260922"
    _add_report(analysis, "r3", ds3, "2026-09-23T10:00:00+09:00")
    auto = reviews / "2026-09-22-answercheck.md"
    auto.write_text("# 自動\n\n<!-- auto-morning-docs --> 07:42 作成。\n", encoding="utf-8")
    event_days._append_retro_addenda([(None, _linked_row(ds3, ["r3"], delay=1))], str(reviews), str(analysis), "x")
    assert "追記（遡及）" not in auto.read_text(encoding="utf-8")
    assert (reviews / "2026-09-22-answercheck-addendum.md").exists()


def test_cmd_link_writes_addenda_only_for_newly_linked(tmp_path):
    analysis, state = _dbs(tmp_path)
    business = date.today() - timedelta(days=12)
    ds = business.strftime("%Y%m%d")
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_events(events, [{"event_id": "e", "hall": "楽園", "date": ds}])
    reviews = tmp_path / "reviews"
    args = _args(tmp_path, events, analysis, state)
    args.addenda_dir = str(reviews)
    event_days.cmd_link(args)  # 初回 waiting: 追記なし
    assert not reviews.exists()
    _add_report(analysis, "r1", ds, (business + timedelta(days=2)).isoformat() + "T10:00:00+09:00")
    event_days.cmd_link(args)
    files = list(reviews.glob("*-answercheck-addendum.md"))
    assert len(files) == 1 and "追記（遡及）" in files[0].read_text(encoding="utf-8")
    event_days.cmd_link(args)  # 変化なし: 重複しない
    assert files[0].read_text(encoding="utf-8").count("追記（遡及）") == 1


def test_multi_hall_account_key_and_result_hours(tmp_path):
    """結果の役割のアカウントは、担当キー(ここでは hiroki)を問わず本文のホール名で候補になる。
    営業日22時前の投稿は予告・途中経過として外す。"""
    analysis, state = _dbs(tmp_path)
    con = sqlite3.connect(state)
    con.execute("insert into accounts values (?,?,?)", ("hunter", "hiroki", "結果報告"))
    for tid, posted in [("early", "2026-10-20T21:00:00+09:00"), ("late", "2026-10-20T23:30:00+09:00")]:
        con.execute(
            "insert into seen_tweets values (?,?,?,?,?,?)",
            (tid, "hunter", f"https://x.test/{tid}", posted, "10/20 ヒロキ西口 結果", None),
        )
    con.commit()
    con.close()
    reports, candidates = event_days._result_data(str(analysis), str(state), "ヒロキ蒲田西口店", "20261020")
    assert reports == []
    assert [c["tweet_id"] for c in candidates] == ["late"]


def test_poster_result_reports_count_as_reports(tmp_path):
    analysis, state = _dbs(tmp_path)
    con = sqlite3.connect(analysis)
    con.execute(
        "create table poster_result_reports (report_id text, tweet_url text, posted_at text,"
        " hall_name text, business_date text)"
    )
    con.execute(
        "insert into poster_result_reports values (?,?,?,?,?)",
        ("p1", "https://x.test/status/p1", "2026-10-21T09:00:00+09:00", "ヒロキMAX蒲田店", "20261020"),
    )
    con.commit()
    con.close()
    reports, _ = event_days._result_data(str(analysis), str(state), "ヒロキMAX蒲田店", "20261020")
    assert [r["report_id"] for r in reports] == ["p1"]


def test_other_store_of_same_chain_is_not_a_candidate(tmp_path):
    """「みとや」は同系列の他店舗(水道橋・浅草など)にも当たるので、その店名を除いて判定する。"""
    analysis, state = _dbs(tmp_path)
    con = sqlite3.connect(state)
    con.execute("insert into accounts values (?,?,?)", ("kotae", "rakuen_kamata", "答え合わせ"))
    for tid, text in [("other", "10月14日(水) みとや浅草千束 周年日"), ("own", "10月14日(水) みとや大森町 結果")]:
        con.execute(
            "insert into seen_tweets values (?,?,?,?,?,?)",
            (tid, "kotae", f"https://x.test/{tid}", "2026-10-15T11:00:00+09:00", text, None),
        )
    con.commit()
    con.close()
    _, candidates = event_days._result_data(str(analysis), str(state), "みとや大森町店", "20261014")
    assert [c["tweet_id"] for c in candidates] == ["own"]
