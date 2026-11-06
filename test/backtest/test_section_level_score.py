# -*- coding: utf-8 -*-
"""島の直近水準スコアが、対象日より前のデータだけで上位25%の島を選ぶことを固定する。"""

import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest.prereg import ALLOWED_SCORES  # noqa: E402
from backtest.run_backtest import score_history  # noqa: E402

RESID = "hist_section_resid30_top25pct"
LEVEL = "hist_section_recent30_top25pct"
D0 = pd.Timestamp("2026-11-01")


def rows(section, number, start_back, end_back, diff, games=3000):
    """対象日の start_back 日前から end_back 日前まで、毎日1行。"""
    return [
        {
            "dt": D0 - pd.Timedelta(days=back),
            "section": section,
            "machine_number": number,
            "machine_name": f"機種{number}",
            "games_normalized": games,
            "diff_coins_normalized": diff,
        }
        for back in range(start_back, end_back - 1, -1)
    ]


def frame(*parts):
    return pd.DataFrame([r for part in parts for r in part])


def four_sections():
    """古い期間は全島0。直近30日だけ A>B>C>D。"""
    parts = []
    for i, (name, recent) in enumerate({"A": 900, "B": 450, "C": 90, "D": -450}.items()):
        parts += [rows(name, i + 1, 180, 31, 0), rows(name, i + 1, 30, 1, recent)]
    return frame(*parts)


@pytest.mark.parametrize("score", [RESID, LEVEL])
def test_scores_are_registered(score):
    assert score in ALLOWED_SCORES


@pytest.mark.parametrize("score", [RESID, LEVEL])
def test_selects_only_the_top_quarter_of_sections(score):
    s = score_history(four_sections(), score, d0=D0).dropna()
    assert set(s.index) == {1}
    assert s[1] > 0


def test_resid_removes_the_sections_own_long_run_level():
    # X はいつも強いが直近に変化なし。Y はいつも弱いが直近で上がった。
    df = frame(
        rows("X", 1, 180, 1, 900),
        rows("Y", 2, 180, 31, -900),
        rows("Y", 2, 30, 1, 0),
        rows("Z", 3, 180, 1, 0),
        rows("W", 4, 180, 1, 0),
    )
    assert set(score_history(df, RESID, d0=D0).dropna().index) == {2}
    assert set(score_history(df, LEVEL, d0=D0).dropna().index) == {1}


@pytest.mark.parametrize("score", [RESID, LEVEL])
def test_data_on_or_after_the_target_day_is_ignored(score):
    base = four_sections()
    leak = frame(rows("D", 4, 0, 0, 90000), rows("D", 4, -5, -5, 90000))
    both = pd.concat([base, leak], ignore_index=True)
    pd.testing.assert_series_equal(
        score_history(base, score, d0=D0).dropna(), score_history(both, score, d0=D0).dropna()
    )


@pytest.mark.parametrize("score", [RESID, LEVEL])
def test_section_with_too_few_recent_days_is_not_scored(score):
    df = pd.concat([four_sections(), frame(rows("新", 9, 180, 31, 0), rows("新", 9, 5, 1, 9000))], ignore_index=True)
    assert 9 not in score_history(df, score, d0=D0).dropna().index


def test_resid_requires_a_long_run_history():
    # 導入40日。直近30日は足りるが長期が足りないので、差を取らない。
    df = pd.concat([four_sections(), frame(rows("短", 9, 40, 1, 9000))], ignore_index=True)
    assert 9 not in score_history(df, RESID, d0=D0).dropna().index


@pytest.mark.parametrize("score", [RESID, LEVEL])
def test_machines_without_a_section_are_never_picked(score):
    df = pd.concat([four_sections(), frame(rows(None, 9, 180, 1, 9000))], ignore_index=True)
    assert 9 not in score_history(df, score, d0=D0).dropna().index


def test_first_week_of_a_machine_introduced_in_the_window_is_dropped():
    # 島 N の台9は窓の途中で導入され、最初の7日だけ大きく勝った。除けば N は最下位。
    df = pd.concat(
        [
            four_sections(),
            frame(rows("N", 8, 180, 1, -900), rows("N", 9, 30, 24, 90000), rows("N", 9, 23, 1, -900)),
        ],
        ignore_index=True,
    )
    assert 9 not in score_history(df, LEVEL, d0=D0).dropna().index


def test_zero_game_rows_do_not_count_as_observed_days():
    df = pd.concat(
        [four_sections(), frame(rows("空", 9, 180, 26, 0), rows("空", 9, 25, 1, 0, games=0))], ignore_index=True
    )
    assert 9 not in score_history(df, RESID, d0=D0).dropna().index


def test_requires_target_day():
    with pytest.raises(ValueError):
        score_history(four_sections(), RESID)
