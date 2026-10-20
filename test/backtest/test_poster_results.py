# -*- coding: utf-8 -*-
"""slo_tokyo「結果速報」(発信者の設定判定)の解析と、poster_result_* への取り込みの検証。"""

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backtest"))

import result_corpus  # noqa: E402

HALL_DB = "マルハンメガシティ2000-蒲田7"

SAMPLE = """2026-10-18 マルハンメガシティ2000蒲田7 ｜結果速報

■日曜日

全体平均+310枚

ピック7.6%(54/715)

▶ ポイント
✅日曜日
※機種イチ

■ 全🌈(1機種)
・戦国乙女5 業火を穿つ宿焔の双刃

■ 5台並び(1箇所)
・ネオアイムジャグラーEX

■ 2台並び(2箇所)
・スマスロ ハナビ〜アレックス
・ファンキージャグラー2

■ その他(21台)
"""


def parse(text=SAMPLE):
    return result_corpus.parse_slo_tokyo(text)


def test_header_fields():
    header = parse()["header"]
    assert header["business_date"] == "20261018"
    assert header["hall_name_raw"] == "マルハンメガシティ2000蒲田7"
    assert header["weekday_stated"] == "日" and header["weekday_ok"] == 1  # 2026-10-18は日曜
    assert header["day_note"] == "日曜日"
    assert header["event_name"] is None  # ▶ポイントはイベント名ではない
    assert header["hall_mean_diff"] == 310
    assert (header["pick_machines"], header["total_machines"], header["pick_pct"]) == (54, 715, 7.6)


def test_event_name_comes_from_the_first_non_point_arrow_line():
    text = SAMPLE.replace("全体平均+310枚", "▶割切リサーチ\n\n全体平均+310枚")
    assert parse(text)["header"]["event_name"] == "割切リサーチ"


def test_sections_become_categorized_model_rows():
    parsed = parse()
    assert parsed["notes"] == []
    rows = parsed["models"]
    assert [(r["granularity"], r["granularity_raw"], r["model_name"]) for r in rows] == [
        ("全台", "全🌈", "戦国乙女5 業火を穿つ宿焔の双刃"),
        ("5台並び", "5台並び", "ネオアイムジャグラーEX"),
        ("2台並び", "2台並び", "スマスロ ハナビ〜アレックス"),
        ("2台並び", "2台並び", "ファンキージャグラー2"),
        ("その他", "その他", "その他"),
    ]
    assert rows[2]["model_parts"] == ["スマスロ ハナビ", "アレックス"]  # 「〜」で機種が分かれる
    assert rows[3]["model_parts"] == ["ファンキージャグラー2"]
    assert rows[4]["n_units"] == 21 and rows[4]["section_unit"] == "台"  # 機種名なしの件数だけの見出し
    assert rows[0]["section_count"] == 1 and rows[0]["section_unit"] == "機種"


def test_count_mismatch_is_reported():
    text = SAMPLE.replace("■ 2台並び(2箇所)", "■ 2台並び(3箇所)")
    assert any("件数不一致" in note for note in parse(text)["notes"])


def test_weekday_mismatch_is_reported():
    text = SAMPLE.replace("■日曜日", "■月曜日")
    parsed = parse(text)
    assert parsed["header"]["weekday_ok"] == 0
    assert any("曜日不一致" in note for note in parsed["notes"])


def test_non_result_text_is_not_parsed():
    assert parse("明日の蒲田7の予想です") is None
    assert parse("2026-13-40 蒲田7 ｜結果速報") is None  # 存在しない日付


@pytest.mark.parametrize(
    "heading, expected",
    [
        ("全", "全台"),
        ("全系", "全台"),
        ("全🌈", "全台"),
        ("単品🌈", "単品"),
        ("1/2", "1/2"),
        ("列1/2", "列1/2"),
        ("5台並び", "5台並び"),
        ("3台並び全", "3台並び"),  # 「N台並び全」は「N台並び」と同じ扱い
        ("優秀以上", "優秀以上"),
        ("特定箇所仕掛け", "特定箇所"),
        ("末尾⑤(AT機)", "末尾"),
        ("角②(ノーマル機)", "角"),
        ("列全", "列全"),
        ("パネル全", "パネル全"),
        ("取材対象", "取材対象"),
        ("その他", "その他"),
        ("見たことのない見出し", None),  # 推測で正規化しない
    ],
)
def test_granularity_normalization(heading, expected):
    assert result_corpus.poster_granularity(heading) == expected


def test_model_names_resolve_across_kana_width_and_prefixes():
    day = ["マイジャグラーV", "戦国乙女5 業火を穿つ宿焔の双刃", "アレックス ブライト", "ファンキージャグラー2"]
    resolve = result_corpus.resolve_poster_model
    assert resolve("ﾏｲｼﾞｬｸﾞﾗｰV", day) == "マイジャグラーV"  # 半角カナ
    assert resolve("L戦国乙女5", day) == "戦国乙女5 業火を穿つ宿焔の双刃"  # 先頭のL・省略
    assert resolve("LBｱﾚｯｸｽ ﾌﾞﾗｲﾄ", day) == "アレックス ブライト"  # LB・半角
    assert resolve("存在しない機種", day) is None
    assert resolve("", day) is None


def make_state(path, tweets):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE seen_tweets (tweet_id TEXT, handle TEXT, tweet_url TEXT, posted_at_jst TEXT, "
        "tweet_text TEXT, full_text TEXT)"
    )
    con.executemany("INSERT INTO seen_tweets VALUES (?,?,?,?,?,?)", tweets)
    con.commit()
    con.close()


def make_hall_db(root):
    os.makedirs(os.path.join(root, "db"), exist_ok=True)
    con = sqlite3.connect(os.path.join(root, "db", HALL_DB + ".db"))
    con.execute("CREATE TABLE machine_detailed_results (date TEXT, machine_name TEXT, machine_number INTEGER)")
    rows = []
    number = 1
    for name, count in (
        ("戦国乙女5 業火を穿つ宿焔の双刃", 24),
        ("ネオアイムジャグラーEX", 5),
        ("スマスロ ハナビ", 1),
        ("アレックス ブライト", 1),
        ("ファンキージャグラー2", 2),
    ):
        for _ in range(count):
            rows.append(("20261018", name, number))
            number += 1
    con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?)", rows)
    con.commit()
    con.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(result_corpus, "ROOT", str(tmp_path))
    make_hall_db(str(tmp_path))
    return tmp_path


def test_build_poster_stores_reports_models_and_checks(env):
    state, analysis = str(env / "state.db"), str(env / "analysis.db")
    make_state(
        state, [("t1", "slo_tokyo", "https://x.com/slo_tokyo/status/t1", "2026-10-19T08:00:00+09:00", None, SAMPLE)]
    )
    assert result_corpus.build_poster(state, analysis) == 1
    con = sqlite3.connect(analysis)
    row = con.execute(
        "SELECT hall_name, business_date, is_tracked_hall, text_complete, parse_ok, parse_notes, hall_mean_diff, "
        "pick_machines, pick_units_sum, models_resolved, models_total FROM poster_result_reports"
    ).fetchone()
    # 24(全の機種の全台)+5(5台並び)+2×2(2台並び×2箇所)+21(その他)=54=ピック
    assert row == (HALL_DB, "20261018", 1, 1, 1, None, 310, 54, 54.0, 4, 4)
    assert con.execute("SELECT COUNT(*) FROM poster_result_models").fetchone()[0] == 5
    parts = con.execute("SELECT model_parts FROM poster_result_models WHERE model_name LIKE '%〜%'").fetchone()[0]
    assert json.loads(parts) == ["スマスロ ハナビ", "アレックス"]
    # 既存のホール公表の表は作らない・触らない(読み手に混ざらない)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"external_result_reports", "external_result_models", "external_result_machines"} & tables


def test_truncated_text_is_stored_but_not_parsed_into_models(env):
    state, analysis = str(env / "state.db"), str(env / "analysis.db")
    short = (
        "2026-10-18 マルハンメガシティ2000蒲田7 ｜結果速報\n\n■ 全🌈(2機種)\n・" + "あ" * 100
    )  # full_text なし・120字以上
    make_state(state, [("t1", "slo_tokyo", "u", "2026-10-19T08:00:00+09:00", short, None)])
    result_corpus.build_poster(state, analysis)
    con = sqlite3.connect(analysis)
    complete, ok, notes = con.execute(
        "SELECT text_complete, parse_ok, parse_notes FROM poster_result_reports"
    ).fetchone()
    assert (complete, ok) == (0, 0) and "途中で切れている" in notes
    assert con.execute("SELECT COUNT(*) FROM poster_result_models").fetchone()[0] == 0  # 切れた本文から機種行を作らない


def test_rebuild_is_idempotent_and_latest_post_wins(env):
    state, analysis = str(env / "state.db"), str(env / "analysis.db")
    older = SAMPLE.replace("全体平均+310枚", "全体平均+300枚")
    make_state(
        state,
        [
            ("t1", "slo_tokyo", "u1", "2026-10-19T08:00:00+09:00", None, older),
            ("t2", "slo_tokyo", "u2", "2026-10-19T09:00:00+09:00", None, SAMPLE),  # 同じ(ホール, 営業日)の訂正投稿
        ],
    )
    result_corpus.build_poster(state, analysis)
    result_corpus.build_poster(state, analysis)
    con = sqlite3.connect(analysis)
    assert con.execute("SELECT report_id, hall_mean_diff FROM poster_result_reports").fetchall() == [("t2", 310)]
    assert con.execute("SELECT COUNT(*) FROM poster_result_models").fetchone()[0] == 5


def test_unmapped_hall_is_kept_as_untracked(env):
    state, analysis = str(env / "state.db"), str(env / "analysis.db")
    text = SAMPLE.replace("マルハンメガシティ2000蒲田7", "マルハン亀有")
    make_state(state, [("t1", "slo_tokyo", "u", "2026-10-19T08:00:00+09:00", None, text)])
    result_corpus.build_poster(state, analysis)
    row = (
        sqlite3.connect(analysis)
        .execute("SELECT hall_name, hall_name_raw, is_tracked_hall, pick_units_sum FROM poster_result_reports")
        .fetchone()
    )
    assert row == ("マルハン亀有", "マルハン亀有", 0, None)  # 実績DBが無いので検算はしない
