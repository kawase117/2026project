# -*- coding: utf-8 -*-
"""backtest/result_corpus.py のパースと取り込みの検証。"""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backtest"))

import result_corpus  # noqa: E402


POSTED = "2026-08-21T00:52:34+09:00"

SAME_LINE = """8月20日(木)
楽園松戸店

四星　ブラックホール
34/311台(10.9%)
対象台平均+2944枚
店舗総差枚+50760枚

【全台】
バイオRE3　3/3　平均+3639枚

【1/2】
SAO2　10台中5台
"""

SPLIT_LINE = """8月20日(木)
楽園松戸店

【全台】
バイオRE3
3/3　平均+3639枚
"""

WITH_NUMBERS = """7月20日(月)
楽園蒲田店

【3台並び】
L戦国乙女5 (2220-2222)
平均+7547枚
"""


def test_header_fields_are_extracted():
    header, _ = result_corpus.parse_report(SAME_LINE, POSTED)
    assert header["business_date"] == "20260820"
    assert header["hall_name"] == "楽園松戸店"
    assert header["event_name"] == "四星　ブラックホール"
    assert header["target_machines"] == 34
    assert header["total_machines"] == 311
    assert header["target_pct"] == pytest.approx(10.9)
    assert header["target_mean_diff"] == 2944
    assert header["hall_total_diff"] == 50760


def test_weekday_is_verified_against_the_derived_date():
    """本文の曜日と導出日付が一致するかを検算する。書式変更を黙って飲まないため。"""
    header, _ = result_corpus.parse_report(SAME_LINE, POSTED)
    assert header["weekday_stated"] == "木"
    assert header["weekday_ok"] == 1

    wrong = SAME_LINE.replace("8月20日(木)", "8月20日(金)")
    header, _ = result_corpus.parse_report(wrong, POSTED)
    assert header["weekday_ok"] == 0


def test_year_comes_from_the_post_and_rolls_back_across_new_year():
    """本文は年を書かない。1月の投稿が12月を指していれば前年とする。"""
    header, _ = result_corpus.parse_report("12月31日(水)\nどこかホール\n", "2027-01-02T03:00:00+09:00")
    assert header["business_date"] == "20261231"


def test_model_rows_parse_in_both_layouts():
    """機種名と数値が同じ行の書式と、別行に分かれる書式の両方を取る。"""
    _, same = result_corpus.parse_report(SAME_LINE, POSTED)
    _, split = result_corpus.parse_report(SPLIT_LINE, POSTED)

    zentai_same = [row for row in same if row["granularity"] == "全台"]
    assert zentai_same == [
        {"granularity": "全台", "model_name": "バイオRE3", "mean_diff": 3639, "n_target": 3, "n_total": 3}
    ]
    assert [row for row in split if row["granularity"] == "全台"] == zentai_same


def test_nibuichi_row_keeps_counts_without_a_mean():
    _, rows = result_corpus.parse_report(SAME_LINE, POSTED)
    nibuichi = [row for row in rows if row["granularity"] == "1/2"]
    assert nibuichi[0]["model_name"] == "SAO2"
    # 「10台中5台」= 設置10台のうち該当5台。台数の多いほうが n_total。
    assert (nibuichi[0]["n_target"], nibuichi[0]["n_total"]) == (5, 10)
    assert "mean_diff" not in nibuichi[0]


def test_machine_number_range_carries_over_from_the_name_line():
    """台番号は機種名の行、平均差枚は次の行に来る。範囲を落とさないこと。"""
    _, rows = result_corpus.parse_report(WITH_NUMBERS, POSTED)
    assert len(rows) == 1
    assert rows[0]["model_name"] == "L戦国乙女5"
    assert (rows[0]["number_from"], rows[0]["number_to"]) == (2220, 2222)
    assert rows[0]["mean_diff"] == 7547


def test_zero_width_characters_do_not_leak_into_model_names():
    text = WITH_NUMBERS.replace("L戦国乙女5", "​L戦国乙女5")
    _, rows = result_corpus.parse_report(text, POSTED)
    assert rows[0]["model_name"] == "L戦国乙女5"


def test_text_without_a_date_line_is_rejected():
    assert result_corpus.parse_report("全台系あります！", POSTED) is None


def test_reported_values_convert_to_the_local_scale():
    """報告値は当方の diff_coins_normalized より約3%低い（楽園55件の回帰）。"""
    assert result_corpus.to_local_scale(7547) == pytest.approx(7778, abs=30)
    assert result_corpus.to_local_scale(-680) == pytest.approx(-682, abs=30)


def _state_db(path):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE seen_tweets (tweet_id TEXT PRIMARY KEY, handle TEXT, "
        "tweet_url TEXT, tweet_text TEXT, posted_at_jst TEXT, "
        "scraped_at_jst TEXT, has_image INTEGER, full_text TEXT)"
    )
    connection.execute(
        "INSERT INTO seen_tweets (tweet_id, handle, tweet_url, posted_at_jst, full_text) "
        "VALUES ('1', 'slokotae7', 'https://x.com/slokotae7/status/1', ?, ?)",
        (POSTED, SAME_LINE),
    )
    connection.commit()
    connection.close()


def test_build_is_idempotent(tmp_path):
    """同じ投稿を二度取り込んでも行が増えないこと。"""
    state = str(tmp_path / "state.db")
    analysis = str(tmp_path / "analysis.db")
    _state_db(state)

    result_corpus.build(state_db=state, analysis_db=analysis)
    result_corpus.build(state_db=state, analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    assert connection.execute("SELECT COUNT(*) FROM external_result_reports").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM external_result_models").fetchone()[0] == 2


def _hall_db(path, date, numbers_and_names):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT)")
    connection.executemany(
        "INSERT INTO machine_detailed_results VALUES (?,?,?)",
        [(date, number, name) for number, name in numbers_and_names],
    )
    connection.commit()
    connection.close()


def test_link_machines_drops_images_from_another_hall(tmp_path, monkeypatch):
    """scrape_tweets が別ツイートの画像を紐付けることがある。

    画像単位で存在率を見て、本文のホールに無い番号ばかりの画像は丸ごと捨てること。
    """
    state = str(tmp_path / "state.db")
    analysis = str(tmp_path / "analysis.db")

    text = "8月20日(木)\n楽園蒲田店\n\n【全台】\nバイオRE3\n3/3　平均+3639枚\n"
    connection = sqlite3.connect(state)
    connection.execute(
        "CREATE TABLE seen_tweets (tweet_id TEXT PRIMARY KEY, handle TEXT, "
        "tweet_url TEXT, tweet_text TEXT, posted_at_jst TEXT, "
        "scraped_at_jst TEXT, has_image INTEGER, full_text TEXT)"
    )
    connection.execute(
        "INSERT INTO seen_tweets (tweet_id, handle, posted_at_jst, full_text) VALUES ('1', 'slokotae7', ?, ?)",
        (POSTED, text),
    )
    connection.execute(
        "CREATE TABLE extraction_entries (tweet_id TEXT, image_path TEXT, machine_number TEXT, machine_name TEXT)"
    )
    connection.executemany(
        "INSERT INTO extraction_entries VALUES (?,?,?,?)",
        [
            ("1", "own.png", "1000", "バイオRE3"),
            ("1", "own.png", "1001", "バイオRE3"),
            ("1", "own.png", "1002", "バイオRE3"),
            # 別ホールの画像。楽園のレンジ外の番号ばかりで、当日データに存在しない。
            ("1", "other.png", "249", "からくり2"),
            ("1", "other.png", "274", "北斗転生"),
            ("1", "other.png", "288", "化物語"),
        ],
    )
    connection.commit()
    connection.close()

    hall_dir = tmp_path / "db"
    hall_dir.mkdir()
    _hall_db(
        str(hall_dir / "楽園蒲田店.db"), "20260820", [(1000, "バイオRE:3"), (1001, "バイオRE:3"), (1002, "バイオRE:3")]
    )

    monkeypatch.setattr(result_corpus, "ROOT", str(tmp_path))
    result_corpus.build(state_db=state, analysis_db=analysis)
    result_corpus.link_machines(state_db=state, analysis_db=analysis)

    con = sqlite3.connect(analysis)
    rows = con.execute(
        "SELECT machine_number, image_path, name_agrees FROM external_result_machines ORDER BY machine_number"
    ).fetchall()
    assert [r[0] for r in rows] == [1000, 1001, 1002]
    assert {r[1] for r in rows} == {"own.png"}
    assert all(r[2] == 1 for r in rows)


def _prose_state(path, text, entries, tweet_id="9001"):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE seen_tweets (tweet_id TEXT PRIMARY KEY, handle TEXT, "
        "tweet_url TEXT, tweet_text TEXT, posted_at_jst TEXT, "
        "scraped_at_jst TEXT, has_image INTEGER, full_text TEXT)"
    )
    connection.execute(
        "INSERT INTO seen_tweets (tweet_id, handle, posted_at_jst, full_text) VALUES (?, '999999Q9Q', ?, ?)",
        (tweet_id, POSTED, text),
    )
    connection.execute(
        "CREATE TABLE extraction_entries (tweet_id TEXT, image_path TEXT, "
        "machine_number TEXT, machine_name TEXT, business_date TEXT)"
    )
    connection.executemany(
        "INSERT INTO extraction_entries VALUES (?,?,?,?,?)", [(tweet_id, "a.png", n, m, d) for n, m, d in entries]
    )
    connection.commit()
    connection.close()


def _tracked(tmp_path):
    hall_dir = tmp_path / "db"
    hall_dir.mkdir(exist_ok=True)
    for name in ("マルハンメガシティ2000-蒲田7", "マルハンメガシティ2000-蒲田1"):
        sqlite3.connect(str(hall_dir / (name + ".db"))).close()
    return hall_dir


def test_prose_nickname_resolves_the_hall(tmp_path, monkeypatch):
    """本文の愛称でホールを決める。infer_hall の画像照合には頼らない。"""
    state = str(tmp_path / "state.db")
    analysis = str(tmp_path / "analysis.db")
    _tracked(tmp_path)
    _prose_state(state, "GALAXYウスイのメガなな速報\n\n月曜のカマタは全仕掛け。", [("2301", "化物語", "2026-08-20")])
    monkeypatch.setattr(result_corpus, "ROOT", str(tmp_path))

    result_corpus.ingest_prose_reports(state_db=state, analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    row = connection.execute("SELECT hall_name, business_date, source FROM external_result_reports").fetchone()
    assert row == ("マルハンメガシティ2000-蒲田7", "20260820", "999999Q9Q")


def test_prediction_posts_are_not_ingested_as_results(tmp_path, monkeypatch):
    """予想を正解ラベルにしない。外れた予測が『ホールが公表した該当台』になる。"""
    state = str(tmp_path / "state.db")
    analysis = str(tmp_path / "analysis.db")
    _tracked(tmp_path)
    _prose_state(state, "GALAXYウスイのメガなな予想\n\n明日は1の付く日。", [("2301", "化物語", "2026-08-20")])
    monkeypatch.setattr(result_corpus, "ROOT", str(tmp_path))

    result_corpus.ingest_prose_reports(state_db=state, analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    assert connection.execute("SELECT COUNT(*) FROM external_result_reports").fetchone()[0] == 0


def test_a_tweet_whose_entries_disagree_on_the_date_is_skipped(tmp_path, monkeypatch):
    """同一投稿で営業日が割れていたら取り込まない。どちらが正しいか判断材料が無い。"""
    state = str(tmp_path / "state.db")
    analysis = str(tmp_path / "analysis.db")
    _tracked(tmp_path)
    _prose_state(
        state,
        "ファンキーサトウのメガいち速報\n\n火曜のカマタは角◯仕掛け。",
        [("2001", "化物語", "2026-08-20"), ("2002", "化物語", "2026-08-19")],
    )
    monkeypatch.setattr(result_corpus, "ROOT", str(tmp_path))

    result_corpus.ingest_prose_reports(state_db=state, analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    assert connection.execute("SELECT COUNT(*) FROM external_result_reports").fetchone()[0] == 0
