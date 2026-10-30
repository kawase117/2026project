import sqlite3

import pytest

from backtest import continuation_scan, prediction_games, scoreboard


def _con(rows, types):
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT, "
        "games_normalized REAL, diff_coins_normalized REAL, rb_count REAL)"
    )
    con.execute("CREATE TABLE machine_master (machine_name_normalized TEXT, game_type TEXT)")
    con.executemany("INSERT INTO machine_detailed_results VALUES ('20261030', ?, ?, ?, ?, 0)", rows)
    con.executemany("INSERT INTO machine_master VALUES (?, ?)", types.items())
    return con


ROWS = [
    (1, "AT1", 8000, -500),
    (2, "AT1", 4000, 200),
    (3, "AT1", 2000, -100),
    (4, "AT2", 7500, 300),
    (5, "AT2", 1000, 0),
    (11, "JUG", 6000, 800),
    (12, "JUG", 5000, -200),
    (13, "JUG", 1000, -100),
]
TYPES = {"AT1": "AT", "AT2": "AT", "JUG": "ノーマル"}


def test_units_reach_and_g_ratio_vs_same_model():
    con = _con(ROWS, TYPES)
    res = prediction_games.games_result(con, {"units": [1], "models": [], "jug_units": []}, "20261030")
    u = res["units"]
    # 台1は7,000G到達、同機種の名指し外(2,3)は0% → +100pt
    assert u["reach_edge"] == pytest.approx(100.0)
    # AT1 の中央値は4000: 台1のG比2.0、名指し外は(1.0+0.5)/2
    assert u["g_edge"] == pytest.approx(2.0 - 0.75)


def test_models_compare_against_other_models():
    con = _con(ROWS, TYPES)
    m = prediction_games.games_result(con, {"units": [], "models": ["AT2"], "jug_units": []}, "20261030")["models"]
    # AT2 の到達は 1/2、他機種の AT 台(AT1)は 1/3。ノーマル機は到達の分母に入れない
    assert m["reach_edge"] == pytest.approx(50.0 - 100 / 3)
    assert m["n_at"] == 2


def test_rb_stage_keeps_unplayed_candidates():
    con = _con(ROWS, TYPES)
    rb_auto = {"units": {"JUG": [{"machine_number": 13, "dev": 0.3}, {"machine_number": 11, "dev": 0.1}]}}
    picks = {"units": [11, 13], "models": [], "avoid_models": [], "jug_units": []}
    st = prediction_games.rb_stage_result(con, picks, "20261030", rb_auto)
    # 候補 11(6000G) は打たれ、13(1000G) は打たれていない。消さずに数える
    assert st["all"]["n_candidates"] == 2 and st["all"]["n_played"] == 1
    assert st["all"]["played_share"] == pytest.approx(50.0)
    # 同機種の候補外は 12(5000G) で 100% → −50pt
    assert st["all"]["played_edge"] == pytest.approx(-50.0)
    assert st["top5_units"] == [13, 11]


def test_jug_model_vs_same_model():
    con = _con(ROWS, TYPES)
    jm = prediction_games.jug_model_result(con, {"jug_units": [11]}, "20261030")
    assert jm["edge"] == pytest.approx(800 - (-150))


def test_mh_ratio_within_model_day():
    rows = [
        {"date": "d", "model": "A", "games": 8000, "labeled": True},
        {"date": "d", "model": "A", "games": 3000, "labeled": False},
        {"date": "d", "model": "A", "games": 2000, "labeled": True},
        # 結果の台が無い層は数えない
        {"date": "d", "model": "B", "games": 9000, "labeled": False},
        {"date": "d", "model": "B", "games": 1000, "labeled": False},
    ]
    r = continuation_scan.mh_ratio(rows, 7000)
    assert r["strata"] == 1
    assert r["ratio"] == pytest.approx((1 * 2 / 3) / (1 * 1 / 3))


def test_scoreboard_picks_up_games_series():
    preds = [
        {
            "hall": "H",
            "target_date": f"202610{d:02d}",
            "timing": "pre_open",
            "result": {
                "games": {"units": {"reach_edge": 20.0, "g_edge": 0.3}, "models": None},
                "jug_model": {"edge": -100.0},
            },
        }
        for d in range(1, 4)
    ] + [
        {
            "hall": "H",
            "target_date": "20261001",
            "timing": "pre_open",
            "source": "rb_auto",
            "result": {"rb_stage": {"all": {"played_edge": -10.0, "g_edge": 0.1}, "top5": None, "top5_rb_s1": None}},
        }
    ]
    fams = {r.family for r in scoreboard.build_prediction_rows(preds)}
    assert {"gm_reach_units", "gm_g_units", "jugm_units", "rbst_played", "rbst_g"} <= fams
