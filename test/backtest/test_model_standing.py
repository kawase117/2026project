# -*- coding: utf-8 -*-
"""機種の立ち位置表の集計と表示名を固定する。

この表の用途は「同じ機種でも店によって扱いが逆になる」を見ることなので、
ホール名が潰れて区別できなくなると表そのものが意味を失う。
"""

import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import model_standing  # noqa: E402


def build_hall(path, rows):
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, "
        "machine_name TEXT, games_normalized INTEGER, diff_coins_normalized INTEGER, "
        "bb_count INTEGER, rb_count INTEGER)"
    )
    con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


@pytest.fixture
def hall(tmp_path, monkeypatch):
    rows = []
    for day in range(1, 21):
        date = "202609%02d" % day
        for i in range(3):
            rows.append((date, 100 + i, "厚い", 4000, 600, 10, 5))
            rows.append((date, 200 + i, "薄い", 4000, -600, 10, 5))
            rows.append(
                (date, 300 + i, "少台数", 4000, 5000, 10, 5) if i == 0 else (date, 300 + i, "ふつう", 4000, 0, 10, 5)
            )
    build_hall(tmp_path / "テスト店.db", rows)
    monkeypatch.setattr(model_standing, "DB_DIR", str(tmp_path))
    return "テスト店"


def test_short_name_keeps_the_distinguishing_tail():
    # 蒲田1 と 蒲田7 は先頭14文字が同じ。頭を残すと区別できなくなる。
    assert model_standing.short("マルハンメガシティ2000-蒲田1") == "蒲田1"
    assert model_standing.short("マルハンメガシティ2000-蒲田7") == "蒲田7"
    assert model_standing.short("マルハンメガシティ2000-蒲田1") != model_standing.short("マルハンメガシティ2000-蒲田7")


def test_short_name_drops_the_trailing_store_suffix():
    assert model_standing.short("楽園蒲田店") == "楽園蒲田"
    assert model_standing.short("ARROW池上店") == "ARROW池上"


def test_edge_is_relative_to_the_same_day_pool(hall):
    s = model_standing.standing(hall, window=60)
    # 同日プール平均は (600 - 600 + 5000/3 + 0*2/3)/3 ではなく全行の平均。
    # 厚い(+600) が薄い(-600) より上であることだけを固定する。
    assert s.loc["厚い", "edge"] > 0 > s.loc["薄い", "edge"]
    assert s.loc["厚い", "pct"] > s.loc["薄い", "pct"]


def test_models_with_too_few_machines_are_dropped(hall):
    # 少台数は1台しかない。機種平均がその台の個性と区別できないので載せない。
    s = model_standing.standing(hall, window=60)
    assert "少台数" not in s.index
    assert "厚い" in s.index


def test_window_limits_the_period(hall):
    # 窓を 1 日にすると、必要な台日数(30)に届かず何も残らない。
    assert model_standing.standing(hall, window=1) is None


def test_hall_names_skips_files_without_the_results_table(tmp_path, monkeypatch):
    build_hall(tmp_path / "本物店.db", [("20260901", 1, "A", 4000, 0, 1, 1)])
    con = sqlite3.connect(str(tmp_path / "集計用.db"))
    con.execute("CREATE TABLE something_else (x INTEGER)")
    con.commit()
    con.close()
    (tmp_path / "メモ.txt").write_text("db ではない", encoding="utf-8")
    monkeypatch.setattr(model_standing, "DB_DIR", str(tmp_path))
    assert model_standing.hall_names() == ["本物店"]


def test_analysis_results_is_never_treated_as_a_hall(tmp_path, monkeypatch):
    # 集計DBにも同名テーブルが出来うるので、名前でも弾いておく。
    build_hall(tmp_path / "analysis_results.db", [("20260901", 1, "A", 4000, 0, 1, 1)])
    monkeypatch.setattr(model_standing, "DB_DIR", str(tmp_path))
    assert model_standing.hall_names() == []
