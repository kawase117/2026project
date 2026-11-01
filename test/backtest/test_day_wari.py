"""日の軸を割・phで測る backtest.day_wari の計算部分。"""

import numpy as np
import pandas as pd

from backtest.day_wari import DAY_HYPOTHESES, bootstrap_diff, score_day_hypothesis, wari_by_day


def test_wari_is_one_plus_total_diff_over_three_times_total_games():
    df = pd.DataFrame(
        {
            "date": ["20261101"] * 3 + ["20261102"],
            "g": [3000, 6000, 0, 3000],
            "diff": [900, -900, 5000, 0],  # 回っていない台(g=0)は数えない
            "grp": ["AT", "JUG", "JUG", "AT"],
        }
    )
    day = wari_by_day(df)
    assert day.loc["20261101", "w_all"] == 1.0
    assert day.loc["20261101", "w_at"] == 1.1
    assert np.isclose(day.loc["20261101", "w_jug"], 1 - 900 / 18000)
    assert day.loc["20261101", "hm"] == 0
    assert day.loc["20261102", "G"] == 3000


def test_bootstrap_interval_needs_three_days_each_side():
    assert np.isnan(bootstrap_diff([1, 2], [0, 0, 0])["lo"])
    r = bootstrap_diff([5, 6, 7, 6], [0, 1, 0, 1, 0])
    assert r["diff"] == 6 - 0.4 and r["lo"] > 0 and (r["n_in"], r["n_out"]) == (4, 5)


def test_score_compares_target_days_with_the_rest():
    day = pd.DataFrame({"hm": [100.0, 0, 0, 100, 0, 0], "dd": [8, 1, 2, 8, 3, 4], "weekday": [0] * 6})
    out = score_day_hypothesis(day, {"dd": 8})
    assert out.loc["hm", "diff"] == 100 and out.loc["hm", "n_in"] == 2


def test_day_hypotheses_cover_the_day_level_ids_of_the_prereg():
    import json
    from pathlib import Path

    reg = json.loads(
        (
            Path(__file__).resolve().parents[2] / "backtest/hypothesis_prereg/pattern_scan_trials_20261031.json"
        ).read_text(encoding="utf-8")
    )
    ids = {h["id"] for h in reg["hypotheses"]}
    assert set(DAY_HYPOTHESES) <= ids
