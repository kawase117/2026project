# -*- coding: utf-8 -*-
"""日付条件の判定と、ボーナス確率による測り方を固定する。

条件の定義がずれると、朝の紙が「今日は強ゾロ目です」と間違ったことを言う。
また z と lift は別物で、z は回転数が多いほど大きく出る。混同しないよう
両方を返すことをテストで明示しておく。
"""

import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import date_conditions as dc  # noqa: E402


def test_strong_zorome_is_month_equals_day():
    assert "強ゾロ目" in dc.today_conditions("20260909")
    assert "強ゾロ目" in dc.today_conditions("20261212")
    assert "強ゾロ目" not in dc.today_conditions("20260910")


def test_zorome_day_is_eleven_or_twentytwo():
    assert "ゾロ目日" in dc.today_conditions("20260911")
    assert "ゾロ目日" in dc.today_conditions("20260922")
    assert "ゾロ目日" not in dc.today_conditions("20260912")


def test_seven_and_one_use_the_last_digit_not_the_leading_one():
    # 17日・27日も「7のつく日」。1のつく日も同様に 11/21/31 を含む。
    assert "7のつく日" in dc.today_conditions("20260917")
    assert "7のつく日" in dc.today_conditions("20260927")
    assert "1のつく日" in dc.today_conditions("20260921")
    assert "7のつく日" in dc.today_conditions("20260907")  # 7日自身も該当
    assert "7のつく日" not in dc.today_conditions("20260916")


def test_month_end_covers_short_months():
    # その月の実際の日数から取る。29日以上のハードコードは2月末を取りこぼす。
    assert "月末" in dc.today_conditions("20260930")  # 30日の月
    assert "月末" in dc.today_conditions("20261031")  # 31日の月
    assert "月末" in dc.today_conditions("20260228")  # 28日の月
    assert "月末" in dc.today_conditions("20240229")  # うるう年
    assert "月末" not in dc.today_conditions("20260927")
    assert "月末" not in dc.today_conditions("20260226")


def test_weekend_flag():
    assert "土日" in dc.today_conditions("20260912")  # 土
    assert "土日" in dc.today_conditions("20260913")  # 日
    assert "土日" not in dc.today_conditions("20260911")  # 金


def test_zscore_grows_with_games_but_lift_does_not():
    # 同じ「1割増し」でも、回転数が10倍なら z は約√10倍になる。
    small = dc._zscore(110, 1000, 1000, 10000)
    large = dc._zscore(1100, 10000, 10000, 100000)
    assert large > small
    assert large == pytest.approx(small * np.sqrt(10), rel=0.05)


def test_zscore_is_zero_when_the_rate_matches():
    assert dc._zscore(100, 1000, 1000, 10000) == pytest.approx(0.0)


def test_zscore_handles_empty_windows():
    assert np.isnan(dc._zscore(0, 0, 100, 1000))
    assert np.isnan(dc._zscore(10, 100, 0, 0))


@pytest.fixture
def hall(tmp_path, monkeypatch):
    """強ゾロ目だけボーナスが2割増しになる店を作る。"""
    con = sqlite3.connect(str(tmp_path / "テスト店.db"))
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_name TEXT, "
        "games_normalized INTEGER, bb_count INTEGER, rb_count INTEGER)"
    )
    con.execute("CREATE TABLE machine_master (machine_name_normalized TEXT, bonus_judgeable INTEGER)")
    con.execute("INSERT INTO machine_master VALUES ('ジャグ', 1)")
    con.execute("INSERT INTO machine_master VALUES ('AT機', 0)")
    rows = []
    for month in range(1, 13):
        for day in range(1, 29):
            date = "2026%02d%02d" % (month, day)
            bonus = 36 if month == day else 30
            rows.append((date, "ジャグ", 4000, bonus // 2, bonus - bonus // 2))
            rows.append((date, "AT機", 4000, 100, 100))
    con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()
    monkeypatch.setattr(dc, "DB_DIR", str(tmp_path))
    return "テスト店"


def test_measure_finds_the_planted_lift(hall):
    m = dc.measure(hall)
    row = m[m.condition == "強ゾロ目"].iloc[0]
    assert row.lift == pytest.approx(20.0, abs=1.0)
    assert row.z > 2
    assert row.days == 12


def test_measure_ignores_non_judgeable_models(hall):
    # AT機はボーナス確率で設定を割れないので混ぜない。混ざると仕込んだ2割増しが薄まる。
    m = dc.measure(hall)
    assert m[m.condition == "強ゾロ目"].iloc[0].lift > 15


def test_day_verdict_only_returns_matching_conditions(hall):
    names = [v[0] for v in dc.day_verdict(hall, "20260909")]
    assert "強ゾロ目" in names
    assert "月末" not in names
