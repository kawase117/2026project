"""結果ツイートとの照合(二段階の答え合わせ、2026-10-30 作業4)。"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import result_check as rc  # noqa: E402

HALL = "楽園蒲田店"
DAY = "20261027"


@pytest.fixture
def env(tmp_path):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    con = sqlite3.connect(db_dir / ("%s.db" % HALL))
    con.execute("create table machine_detailed_results (date text, machine_number integer, machine_name text)")
    units = {n: "ネオアイムジャグラーEX" for n in range(1101, 1111)}
    units.update({n: "東京リベンジャーズ" for n in range(1201, 1205)})
    units.update({n: "マイジャグラーV" for n in range(1301, 1306)})
    con.executemany("insert into machine_detailed_results values (?,?,?)", [(DAY, n, m) for n, m in units.items()])
    con.commit()
    con.close()

    analysis = tmp_path / "analysis.db"
    con = sqlite3.connect(analysis)
    con.executescript(
        """
        create table external_result_reports (report_id text primary key, tweet_url text, posted_at text,
          hall_name text, business_date text, source text);
        create table external_result_machines (report_id text, image_path text, machine_number integer);
        create table external_result_models (report_id text, granularity text, model_name text,
          number_from integer, number_to integer);
        """
    )
    con.execute(
        "insert into external_result_reports values (?,?,?,?,?,?)",
        ("900", "https://x.test/status/900", "2026-10-28T10:00:00+09:00", HALL, DAY, "slokotae7"),
    )
    con.execute("insert into external_result_models values ('900','全台系','L東京リベンジャーズ',null,null)")
    con.execute("insert into external_result_models values ('900','並び','アイムジャグラーEX',1101,1103)")
    con.commit()
    con.close()

    state = tmp_path / "state.db"
    con = sqlite3.connect(state)
    con.executescript(
        """
        create table accounts (handle text primary key, hall text, role text);
        create table seen_tweets (tweet_id text primary key, handle text, tweet_url text, posted_at_jst text,
          tweet_text text, full_text text);
        create table extraction_entries (tweet_id text, handle text, image_path text, machine_number text);
        """
    )
    # 報告ツイートの画像: 1枚は当日の台、1枚は別ホールの台番号(当日このホールに無い)
    rows = [("900", "slokotae7", "900_1.jpg", str(n)) for n in (1104, 1105, 1106)]
    rows += [("900", "slokotae7", "900_2.jpg", str(n)) for n in (3001, 3002, 3003, 1301)]
    con.executemany("insert into extraction_entries values (?,?,?,?)", rows)
    con.commit()
    con.close()
    return {"db_dir": db_dir, "analysis": analysis, "state": state, "tmp": tmp_path}


def _collect(env):
    return rc.collect(HALL, DAY, analysis_db=env["analysis"], state_db=env["state"], db_dir=env["db_dir"])


def test_accept_image_needs_three_numbers_and_80_percent_existing():
    units = {n: "A" for n in range(1, 11)}
    assert rc.accept_image({1, 2, 3}, units)
    assert not rc.accept_image({1, 2}, units)  # 2台では画像の誤紐付けを見分けられない
    assert not rc.accept_image({1, 2, 3, 98, 99}, units)  # 実在 60%
    assert rc.accept_image({1, 2, 3, 4, 99}, units)  # 実在 80%
    assert not rc.accept_image({1, 2, 3}, {})


def test_collect_uses_number_ranges_models_and_report_images(env):
    found = _collect(env)
    assert found["status"] == "linked"
    # 並びの範囲 1101-1103 と、報告の画像 900_1 の 1104-1106
    assert set(found["units"]) == {1101, 1102, 1103, 1104, 1105, 1106}
    # 「L東京リベンジャーズ」を当日の機種名に当てる
    assert found["models"] == {"東京リベンジャーズ": ["全台系"]}
    assert [r["image"] for r in found["rejected_images"]] == ["900_2.jpg"]


def test_score_picks_counts_units_models_and_avoid(env):
    found = _collect(env)
    picks = {
        "jug_units": [1101, 1107],
        "models": ["東京リベンジャーズ", "マイジャグラーV"],
        "avoid_models": ["マイジャグラーV"],
    }
    s = rc.score_picks(found, picks)
    # 台の基準は同じ機種(ネオアイム 10台中 6台が結果)、機種の基準は当日の3機種中2機種
    assert s["jug_units"] == {"named": 2, "hit": [1101], "base": 0.6}
    assert s["models"] == {"named": 2, "hit": ["東京リベンジャーズ"], "base": 2 / 3}
    assert s["avoid_models"] == {"named": 1, "hit": [], "base": 2 / 3}
    assert rc.model_base_rate(found) == (3, 2)


def _waiting(hall=HALL):
    return {
        "hall": hall,
        "day": DAY,
        "status": "waiting",
        "sources": [],
        "units": {},
        "models": {},
        "rejected_images": [],
        "day_units": {},
    }


def test_render_waiting_and_append_is_idempotent(env):
    found = _waiting()
    lines = rc.render(found, [], "2026-10-28T07:00")
    assert any("結果ツイート未着(waiting)" in line for line in lines)

    reviews = env["tmp"] / "reviews"
    reviews.mkdir()
    main = reviews / "2026-10-27-answercheck.md"
    main.write_text("# 人の答え合わせ\n", encoding="utf-8")
    assert rc.append(found, lines, reviews) == main
    assert rc.append(found, lines, reviews) is None  # 同じ状態は二度書かない
    linked = dict(found, status="linked", units={1101: ["slokotae7"]})
    assert rc.append(linked, rc.render(linked, [], "t"), reviews) == main  # 状態が変われば追記する
    assert main.read_text(encoding="utf-8").count("## 結果ツイートとの照合") == 2


def test_append_goes_to_addendum_when_answercheck_is_auto_draft(env):
    reviews = env["tmp"] / "reviews"
    reviews.mkdir()
    (reviews / "2026-10-27-answercheck.md").write_text(rc.AUTO_DOC_MARK + "\n下書き\n", encoding="utf-8")
    found = _waiting()
    path = rc.append(found, rc.render(found, [], "t"), reviews)
    assert path.name == "2026-10-27-answercheck-addendum.md"


def test_run_writes_log_and_skips_non_event_waiting(env):
    reviews = env["tmp"] / "reviews"
    log = env["tmp"] / "RESULT_CHECKS.jsonl"
    msgs = rc.run(
        [DAY],
        reviews_dir=reviews,
        log_path=log,
        collect_fn=lambda h, d: _collect(env) if h == HALL else _waiting(h),
        halls_fn=lambda d: {HALL: False, "X": False},
        picks_fn=lambda d, k: [("人の予測", {"models": ["東京リベンジャーズ"]})],
    )
    assert len(msgs) == 1  # イベントの無い日の未着(X)は書かない
    rec = json.loads(log.read_text(encoding="utf-8"))
    assert rec["hall"] == HALL and rec["status"] == "linked"
    assert rec["scores"]["人の予測"]["models"]["hit"] == ["東京リベンジャーズ"]


def test_default_days_are_two_and_one_days_before():
    assert rc.default_days("20261030") == ["20261028", "20261029"]
