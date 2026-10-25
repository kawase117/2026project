# -*- coding: utf-8 -*-
"""朝の答え合わせに差し込む「発信者(slo_tokyo)の設定判定と実績」の節を固定する。"""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

import morning_facts as mf  # noqa: E402
from backtest import result_corpus  # noqa: E402

HALL = "テスト店"
DAY = "20261018"


@pytest.fixture
def hall_db(tmp_path):
    path = tmp_path / (HALL + ".db")
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE machine_detailed_results "
        "(date TEXT, machine_number INTEGER, machine_name TEXT, games_normalized INTEGER, diff_coins_normalized INTEGER)"
    )
    rows, n = [], 0
    for name, diffs in {
        "マイジャグラーV": [3000, 2500, -500, 1000],  # 全系(4台): 平均+1500、勝率75%、+2000以上2台
        "戦国乙女5 業火を穿つ宿焔の双刃": [-2000, -1000],  # 全系・1台目が大きくマイナス
        "ノーマル機": [0, -100, 100, -200],
    }.items():
        for d in diffs:
            n += 1
            rows.append((DAY, n, name, 4000, d))
    con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


def make_analysis(tmp_path, parse_ok=1, notes=None):
    path = tmp_path / "analysis.db"
    con = sqlite3.connect(str(path))
    con.executescript(result_corpus.POSTER_SCHEMA)
    con.execute(
        "INSERT INTO poster_result_reports (report_id, source, hall_name, business_date, event_name, hall_mean_diff, "
        "pick_machines, total_machines, pick_pct, is_tracked_hall, text_complete, parse_ok, parse_notes, raw_text, "
        "ingested_at) VALUES ('r1','slo_tokyo',?,?,?,?,?,?,?,1,1,?,?,'x','now')",
        (
            HALL,
            DAY,
            "割切リサーチ",
            400,
            6,
            10,
            60.0,
            parse_ok,
            json.dumps(notes, ensure_ascii=False) if notes else None,
        ),
    )
    models = [
        ("全台", "全🌈", 2, "機種", "ﾏｲｼﾞｬｸﾞﾗｰV", ["ﾏｲｼﾞｬｸﾞﾗｰV"], None),
        ("全台", "全🌈", 2, "機種", "L戦国乙女5", ["L戦国乙女5"], None),
        ("優秀以上", "優秀以上", 1, "箇所", "L存在しない機種", ["L存在しない機種"], None),
        ("2台並び", "2台並び", 1, "箇所", "マイジャグラーV〜ノーマル機", ["マイジャグラーV", "ノーマル機"], None),
        ("その他", "その他", 3, "台", "その他", [], 3),
    ]
    for seq, (gran, raw, count, unit, name, parts, n_units) in enumerate(models):
        con.execute(
            "INSERT INTO poster_result_models VALUES ('r1',?,?,?,?,?,?,?,?)",
            (seq, gran, raw, count, unit, name, json.dumps(parts, ensure_ascii=False) if parts else None, n_units),
        )
    con.commit()
    con.close()
    return path


def test_no_report_or_no_db_gives_nothing(tmp_path, hall_db):
    missing = tmp_path / "none.db"
    assert mf.poster_lines(missing, hall_db, HALL, DAY) == []
    analysis = make_analysis(tmp_path)
    assert mf.poster_lines(analysis, hall_db, HALL, "20261017") == []  # その日の速報なし
    assert mf.poster_lines(analysis, hall_db, "別の店", DAY) == []
    assert mf.poster_lines(analysis, tmp_path / "nothing.db", HALL, DAY) == []  # 実績DBなし


def test_section_reports_poster_claims_against_the_actual_day(tmp_path, hall_db):
    text = "\n".join(mf.poster_lines(make_analysis(tmp_path), hall_db, HALL, DAY))
    assert "ホール公表ではない" in text
    # 日平均はDBの値: (3000+2500-500+1000-2000-1000+0-100+100-200)/10 = +280
    assert "発信者の全体平均 +400(DBは +280)" in text
    assert "ピック 6/10台(60.0%)=設定4以上と判定した台" in text and "▶割切リサーチ" in text
    # 発信者の機種名(半角カナ・先頭のL)がDBの機種名に引き当たり、実績が出る
    assert "| 全台 | ﾏｲｼﾞｬｸﾞﾗｰV | マイジャグラーV | 4 | +1500 | 2 | 75% |" in text
    assert "| 全台 | L戦国乙女5 | 戦国乙女5 業火を穿つ宿焔の双刃 | 2 | -1500 | 0 | 0% |" in text
    assert "| 優秀以上 | L存在しない機種 | (DBに見つからない) | - | - | - | - |" in text
    # 全系の機種の全台: 6台、平均 (3000+2500-500+1000-2000-1000)/6 = +500、勝率 3/6 = 50%
    assert "全系の機種の全台: 6台、平均 +500、勝率 50%(ホール平均 +280)" in text
    # 並びとその他は、機種ごとの実績ではなく件数と原文だけ
    assert "- 2台並び(1件): マイジャグラーV〜ノーマル機" in text
    assert "- その他(1件): 3台" in text


def test_failed_check_is_flagged_in_the_section(tmp_path, hall_db):
    analysis = make_analysis(tmp_path, parse_ok=0, notes=["件数不一致: 全系 見出し2 箇条書き1"])
    text = "\n".join(mf.poster_lines(analysis, hall_db, HALL, DAY))
    assert "検算が通っていない" in text and "件数不一致" in text


def test_render_facts_appends_the_block_only_when_given(tmp_path, hall_db):
    facts = mf.day_facts(hall_db, DAY)
    empty = tmp_path / "empty"
    empty.mkdir()
    base = mf.render_facts(facts, "x", empty, empty, "x")
    assert "発信者(slo_tokyo)" not in base  # 既存の呼び出しは出力が変わらない
    block = mf.poster_lines(make_analysis(tmp_path), hall_db, HALL, DAY)
    with_block = mf.render_facts(facts, "x", empty, empty, "x", block)
    assert with_block.startswith(base) and "発信者(slo_tokyo)の設定判定と実績" in with_block
