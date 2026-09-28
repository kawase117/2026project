"""position_rule の採点に、ノーマル機の RB（同じ日・同じ機種の台との比較）を併記する。"""

import pandas as pd

from backtest.announce import _position_rb_normal


def _day():
    rows = []
    for number in range(1000, 1020):
        rows.append(
            {
                "machine_number": number,
                "machine_name": "ジャグA",
                "last_digit": str(number % 10),
                "bonus_judgeable": 1,
                "games_normalized": 6000,
                # 末尾7だけ RB が多い
                "rb_count": 30 if number % 10 == 7 else 20,
            }
        )
    # AT 機は判定に入れない（RB が極端でも無視される）
    rows.append(
        {
            "machine_number": 2007,
            "machine_name": "AT機",
            "last_digit": "7",
            "bonus_judgeable": 0,
            "games_normalized": 6000,
            "rb_count": 0,
        }
    )
    return pd.DataFrame(rows)


def test_target_tail_with_more_rb_than_same_model_is_a_hit():
    r = _position_rb_normal(_day(), "last_digit", ["7"])
    assert r["n_target"] == 2
    assert r["rb_z"] > 0 and r["hit_rb"] is True


def test_target_tail_with_fewer_rb_is_not_a_hit():
    r = _position_rb_normal(_day(), "last_digit", ["3"])
    assert r["hit_rb"] is False


def test_model_only_on_target_tail_has_nothing_to_compare():
    day = _day()
    day = day[day["machine_name"] == "AT機"].assign(bonus_judgeable=1)
    assert _position_rb_normal(day, "last_digit", ["7"]) is None
