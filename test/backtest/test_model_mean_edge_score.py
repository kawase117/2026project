# -*- coding: utf-8 -*-
"""hist_model_mean_edge が「同日ホール平均との差」を機種単位で返すことを固定する。

gratio 版と混同されやすい。あちらは回転数の高い機種を持ち上げる指標で、
こちらは回転数と無関係に「この店で恒常的に厚い機種」を選ぶためのもの。
実測では選ばれる機種の回転数はホール平均の 0.8 倍前後で、向きが逆になる。
"""

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest.prereg import ALLOWED_SCORES  # noqa: E402
from backtest.run_backtest import score_history  # noqa: E402

SCORE = "hist_model_mean_edge"


def frame(rows):
    df = pd.DataFrame(rows, columns=["date", "machine_name", "games_normalized", "diff_coins_normalized"])
    # score_history は入口で machine_number を groupby するので列が要る。
    # このスコア自体は台番号を使わないが、値がぶつからないよう連番を振る。
    df["machine_number"] = range(1, len(df) + 1)
    return df


def test_score_is_registered():
    assert SCORE in ALLOWED_SCORES


def test_edge_is_measured_against_the_same_day_pool():
    # 1日目はホール平均 +100、2日目は -100。強はどちらの日も平均+200。
    df = frame(
        [
            ("20260901", "強", 4000, 300),
            ("20260901", "他A", 4000, 0),
            ("20260901", "他B", 4000, 0),
            ("20260902", "強", 4000, 100),
            ("20260902", "他A", 4000, -200),
            ("20260902", "他B", 4000, -200),
        ]
    )
    s = score_history(df, SCORE)
    assert s["強"] == pytest.approx(200.0)
    assert s["他A"] == pytest.approx(-100.0)


def test_hall_wide_good_and_bad_days_cancel_out():
    # ホール全体が出た日も絞った日も、機種の相対位置が同じなら同じスコアになる。
    calm = frame([("20260901", "A", 4000, 100), ("20260901", "B", 4000, -100)])
    wild = frame([("20260901", "A", 4000, 5100), ("20260901", "B", 4000, 4900)])
    assert score_history(calm, SCORE)["A"] == pytest.approx(score_history(wild, SCORE)["A"])


def test_games_do_not_change_the_score():
    # gratio 版との違い。回転数で持ち上げない。
    low = frame([("20260901", "A", 600, 200), ("20260901", "B", 600, -200)])
    high = frame([("20260901", "A", 6000, 200), ("20260901", "B", 6000, -200)])
    assert score_history(low, SCORE)["A"] == pytest.approx(score_history(high, SCORE)["A"])


def test_gratio_version_does_weight_by_games():
    # 対照。同じデータで gratio 版は回転数の差を拾う（混同防止のため明示しておく）。
    df = frame(
        [
            ("20260901", "よく回る", 6000, 200),
            ("20260901", "回らない", 600, 200),
            ("20260901", "他", 3000, -400),
        ]
    )
    g = score_history(df, "hist_model_gratio_mean_diff")
    assert g["よく回る"] > g["回らない"]
    e = score_history(df, SCORE)
    assert e["よく回る"] == pytest.approx(e["回らない"])


def test_rows_are_equally_weighted_not_double_averaged():
    # 台×日の行を等重みで平均する。台ごとの平均を平均する二重平均にしない。
    df = frame(
        [
            ("20260901", "A", 4000, 300),
            ("20260902", "A", 4000, 300),
            ("20260902", "A", 4000, -300),
            ("20260901", "他", 4000, 0),
            ("20260902", "他", 4000, 0),
        ]
    )
    s = score_history(df, SCORE)
    # 1日目: pool平均150 → A=+150。2日目: pool平均0 → A=+300, A=-300。
    assert s["A"] == pytest.approx((150 + 300 - 300) / 3)
