"""台の補助を候補機種に限らず全機種の機種内上位20%に広げる(2026-10-25)。"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from backtest import prediction_ledger as ledger, prediction_rb as rb, rb_candidates as cand


def _db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
        "games_normalized REAL, rb_count REAL, diff_coins_normalized REAL)"
    )
    return con


def _seed(con, end="20261024", families=5):
    """各機種の0番目の台だけ、毎日RBが2回多い(機種内で突出した台)。機種の強さは family の番号で変わる。"""
    last = datetime.strptime(end, "%Y%m%d")
    for age in range(169, -1, -1):
        date = (last - timedelta(days=age)).strftime("%Y%m%d")
        for family in range(families):
            for unit in range(5):
                con.execute(
                    "INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?)",
                    (date, family * 100 + unit, f"F{family}", 4000, 8 + 2 * family + (unit == 0) * 2, 100),
                )
    con.commit()


@pytest.fixture
def specs(monkeypatch):
    monkeypatch.setattr(rb, "rb_family", lambda name: (name, 0.002, 0.006) if name.startswith("F") else None)
    if hasattr(rb.family_offsets, "cache_clear"):
        rb.family_offsets.cache_clear()
    yield
    if hasattr(rb.family_offsets, "cache_clear"):
        rb.family_offsets.cache_clear()


def test_rank_units_picks_standout_unit_in_every_family(tmp_path, specs):
    with _db(tmp_path / "a.db") as con:
        _seed(con)
        result = cand.rank_units(con, "20261025", "20261024", [f"F{i}" for i in range(5)])
    assert set(result) == {f"F{i}" for i in range(5)}
    for family, picks in result.items():
        assert [p["machine_number"] for p in picks] == [int(family[1:]) * 100]
        assert picks[0]["dev"] > 0


def test_generate_freezes_units_of_non_candidate_families(tmp_path, specs, monkeypatch):
    hall = "みとや大森町店"
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    with _db(db_dir / f"{hall}.db") as con:
        _seed(con)
    offsets = {f"F{i}": 0.25 for i in range(5)}
    monkeypatch.setattr(cand, "RB_HALLS", (hall,))
    monkeypatch.setattr(rb, "family_offsets", lambda *_: offsets)
    original_freeze = ledger.freeze_rb_auto
    monkeypatch.setattr(
        cand.prediction_ledger,
        "freeze_rb_auto",
        lambda h, d, p, e, t: original_freeze(h, d, p, e, t, tmp_path / "pred"),
    )
    rows = cand.generate("20261025", db_dir, tmp_path / "out")
    assert [r["family_name"] for r in rows[0]["candidates"]] == ["F4"]
    saved = json.loads(next((tmp_path / "pred").glob("*rbauto.json")).read_text(encoding="utf-8"))
    # 候補機種(F4)だけでなく、その他の機種の台も凍結される
    assert saved["picks"]["units"] == [0, 100, 200, 300, 400]


def _row(units):
    return {
        "hall": "みとや大森町店",
        "status": "ok",
        "reason": None,
        "data_asof": "20261024",
        "lag_days": 0,
        "candidates": [{"family_name": "F4", "units": 5, "adj90": 0.1, "z90": 0.5, "z7": 0.6}],
        "avoid": [],
        "units": units,
        "day_flag": None,
    }


def _pick(number, dev):
    return {"machine_number": number, "n_days": 90, "s1": 1.2, "dev": dev}


def test_render_splits_candidate_and_other_units():
    text = cand.render_section([_row({"F4": [_pick(400, 0.1)], "F0": [_pick(0, 0.3)], "F1": [_pick(100, 0.2)]})])
    assert "台の補助(候補機種):\n- F4: 400" in text
    other = text.split("台の補助(その他の機種", 1)[1]
    # 偏差の大きい順に並び、候補機種の台は含まれない
    assert other.index("- F0: 0(+0.30)") < other.index("- F1: 100(+0.20)")
    assert "F4" not in other


def test_render_caps_other_units(monkeypatch):
    monkeypatch.setattr(cand, "OTHER_UNIT_LIMIT", 2)
    text = cand.render_section([_row({"F0": [_pick(1, 0.1), _pick(2, 0.4), _pick(3, 0.3)]})])
    other = text.split("台の補助(その他の機種", 1)[1]
    assert "- F0: 2(+0.40)・3(+0.30)" in other and "1(" not in other
