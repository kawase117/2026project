# -*- coding: utf-8 -*-
"""朝の答え合わせの機械集計と、数字の検証を固定する。

claude が書いたホール平均・総差枚が DB と食い違う出力を弾けること、
表の行や機種別の数字を誤って弾かないことを確かめる。
"""

import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import morning_facts as mf  # noqa: E402

DAY = "20261017"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "hall.db"
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE machine_detailed_results "
        "(date TEXT, machine_number INTEGER, machine_name TEXT, games_normalized INTEGER, diff_coins_normalized INTEGER)"
    )
    rows = []
    n = 0
    for name, diffs in {
        "機種A": [3000, 2500, -500, 100],  # 4台
        "機種B": [-1000, -200, 0],  # 3台
        "機種C": [5000, 4000],  # 2台（表に出さない）
    }.items():
        for d in diffs:
            n += 1
            rows.append((DAY, n, name, 4000, d))
    rows.append((DAY, 99, "差枚なし", 100, None))  # 差枚が無い行は集計に入れない
    rows.append(("20261016", 100, "機種A", 4000, 9999))  # 別の日
    con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


@pytest.fixture
def facts(db):
    return mf.day_facts(db, DAY)


def test_day_facts_hall_summary(facts):
    assert facts.n_units == 9
    assert facts.total == 12900
    assert facts.mean == pytest.approx(12900 / 9)
    assert facts.median == 100
    assert facts.win_rate == pytest.approx(5 / 9)  # 正の台: 3000, 2500, 100, 5000, 4000


def test_day_facts_models_exclude_small_and_sort(facts):
    names = [m.name for m in facts.models]
    assert names == ["機種A", "機種B"]  # 2台の機種Cは出さない。平均の降順
    a = facts.models[0]
    assert (a.n, a.n_big) == (4, 2)
    assert a.mean == pytest.approx(1275)


def test_day_facts_missing(db, tmp_path):
    assert mf.day_facts(tmp_path / "none.db", DAY) is None
    assert mf.day_facts(db, "20250101") is None


def test_render_includes_numbers_and_sections(facts, tmp_path):
    pred = tmp_path / "pred"
    ann = tmp_path / "ann"
    pred.mkdir()
    ann.mkdir()
    (pred / ("%s__k.json" % DAY)).write_text(
        json.dumps(
            {
                "picks": {"models": ["機種A"], "jug_units": [1, 2]},
                "result": {
                    "day_mean": -10,
                    "universe_size": 100,
                    "models": {"n_machines": 4, "mean_diff": 1275, "edge": 1285},
                    "jug_units": {"n_machines": 2, "mean_diff": -50, "edge": -40},
                },
            }
        ),
        encoding="utf-8",
    )
    claims = [
        {"type": "model_named_ratio", "claim": {"machine_name": "化物語", "ratio": 2}, "hit": True},
        {"type": "zentaikei_count", "claim": {"n_models": 1}, "observed_n_models": 4, "hit": False},
    ]
    (ann / ("k__%s__a.json" % DAY)).write_text(json.dumps({"result": {"claims": claims}}), encoding="utf-8")
    (ann / ("k__%s__void.json" % DAY)).write_text(json.dumps({"voided": True, "result": None}), encoding="utf-8")
    (ann / ("k__%s__b.withdrawn.json" % DAY)).write_text(json.dumps({"result": None}), encoding="utf-8")
    (ann / ("k__%s__nosc.json" % DAY)).write_text(json.dumps({"result": None}), encoding="utf-8")

    md = mf.render_facts(facts, "k", pred, ann, "k")
    assert "9台、日平均 +1433/台、中央値 +100、勝率 56%" in md
    assert "総差枚 +12,900枚" in md
    assert "| 機種A | 4 | +1275 | 2 |" in md
    assert "機種C" not in md
    assert "推した機種（機種A）: 4台、平均 +1275、edge +1285" in md
    assert "ジャグラー候補（1・2）: 2台、平均 -50、edge -40" in md
    assert "化物語 1/2 → 的中" in md
    assert "全台系 1機種以上（実測 4機種） → 外れ" in md
    assert "k__%s__nosc: 未採点" % DAY in md
    assert "void" not in md and "withdrawn" not in md


def test_render_without_ledger_and_announce(facts, tmp_path):
    md = mf.render_facts(facts, "k", tmp_path, tmp_path, "k")
    assert "凍結した予測の採点" not in md
    assert "予告の機械採点" not in md


# ---------------------------------------------------------------- 数字の検証


def test_check_numbers_accepts_correct_and_rounded(facts):
    text = "## H\n\n- 日平均+1433/台（総差枚+12,900）\n### ホール全体\n平均差枚 +1,433.3/台、合計 +12,900枚。\n"
    assert mf.check_numbers(text, facts) == []


def test_check_numbers_rejects_wrong_mean_and_total(facts):
    errors = mf.check_numbers("- 日平均+999/台（総差枚+30,000）", facts)
    assert any("平均差枚" in e and "+1433" in e for e in errors)
    assert any("総差枚" in e and "+12,900" in e for e in errors)
    # 見出しがホール全体なら、行頭の「平均差枚」も照合する
    assert mf.check_numbers("### ホール全体\n平均差枚 +999/台", facts) != []


def test_check_numbers_handles_unicode_minus_and_bold():
    f = mf.DayFacts(day=DAY, n_units=10, mean=-90.0, median=-100.0, win_rate=0.3, avg_games=2500, total=-900)
    assert mf.check_numbers("**ホール平均** −90/台、総差枚 −900", f) == []
    assert mf.check_numbers("### ホール全体\n平均差枚 −90/台", f) == []
    assert mf.check_numbers("### ホール全体\n平均差枚 －190/台", f) != []  # 全角マイナスも読む


def test_check_numbers_does_not_confuse_juggler_section_with_hall(facts):
    # 実例（雑色 2026-10-17）: ジャグラー全体の「平均差枚」とホール全体の値を並べた正しい記述
    f = mf.DayFacts(day=DAY, n_units=128, mean=105.9, median=-100.0, win_rate=0.4, avg_games=2000, total=13551)
    text = (
        "### ジャグラー全体\n\n平均差枚 −187.6/台。**ホール全体+105.9に対して、ジャグラー全体が−187.6と大きく乖離。**\n"
    )
    assert mf.check_numbers(text, f) == []
    wrong = "### ジャグラー全体\n**ホール全体+205.9に対して、ジャグラー全体が−187.6**\n"
    assert mf.check_numbers(wrong, f) != []  # 行の途中の「ホール全体＋数字」は照合する


def test_check_numbers_ignores_unsigned_numbers_in_prose(facts):
    # 実例（雑色 2026-10-17）: 「ホール全体平均の2倍以上」の2は平均ではない
    assert mf.check_numbers("回転数でホール全体平均の2倍以上なら設定示唆。", facts) == []


def test_check_numbers_ignores_table_rows_baselines_and_other_days(facts):
    text = (
        "| 指標 | 予測根拠 | 実測 |\n"
        "| ホール平均 | 7の付く日+203(他日+82) | +99 |\n"
        "- カバネリ(42台)の平均+340\n"
        "- 前回の日平均は別の日の話です\n"
        "- 日平均は予測根拠の7の付く日+203に対して+99\n"
        "- 10/12の日平均+300\n"
    )
    assert mf.check_numbers(text, facts) == []
    assert mf.check_numbers("- 10/17の日平均+999", facts) != []  # 当日の日付なら見る


def test_check_numbers_without_facts_skips():
    assert mf.check_numbers("日平均+99999/台", None) == []


def test_inject_facts_after_heading(tmp_path):
    path = tmp_path / "x.md"
    path.write_text("## 蒲田7\n\n本文1\n本文2\n", encoding="utf-8")
    mf.inject_facts(path, "### 機械集計\n- 表")
    assert path.read_text(encoding="utf-8").splitlines() == [
        "## 蒲田7",
        "",
        "### 機械集計",
        "- 表",
        "",
        "",
        "本文1",
        "本文2",
    ]
