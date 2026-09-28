"""hist_tail_rb_due3: 直近で RB が出ていない末尾の台だけを選ぶ。"""

import pandas as pd

from backtest.run_backtest import score_history


def _frame(rb_by_tail_recent):
    rows = []
    for day in range(1, 11):
        for tail in range(10):
            for block in (0, 1):
                number = 1000 + block * 10 + tail
                # 前半5日はどの末尾も期待どおり、後半5日は末尾ごとに RB の出方を変える
                rb = 20 if day <= 5 else rb_by_tail_recent[tail]
                rows.append(
                    {
                        "date": "202609%02d" % day,
                        "machine_number": number,
                        "machine_name": "機種A" if block == 0 else "機種B",
                        "games_normalized": 5000,
                        "rb_count": rb,
                    }
                )
    return pd.DataFrame(rows)


def test_picks_only_machines_of_the_three_least_used_tails():
    recent = {t: 20 for t in range(10)}
    recent.update({3: 10, 6: 12, 8: 14, 1: 40})  # 末尾3・6・8 は直近で RB が少ない、1 は多い
    scores = score_history(_frame(recent), "hist_tail_rb_due3")
    assert sorted({n % 10 for n in scores.index}) == [3, 6, 8]
    # いちばん出ていない末尾3が最上位
    assert scores.idxmax() % 10 == 3
    # 同じ末尾の台は機種が違っても同じスコア（末尾単位の判断）
    assert scores[1003] == scores[1013]


def test_empty_history_returns_empty():
    empty = pd.DataFrame(columns=["date", "machine_number", "machine_name", "games_normalized", "rb_count"])
    assert score_history(empty, "hist_tail_rb_due3").empty
