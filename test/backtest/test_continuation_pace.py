import json
import sqlite3
from datetime import datetime

import pytest

from backtest import continuation_pace as cp
from backtest import scoreboard
from scraper.realtime.schema import JST


def _db(path, rows):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT, "
        "games_normalized REAL, diff_coins_normalized REAL)"
    )
    con.execute("CREATE TABLE IF NOT EXISTS machine_master (machine_name_normalized TEXT, game_type TEXT)")
    con.execute("DELETE FROM machine_master")
    con.executemany("INSERT INTO machine_master VALUES (?, ?)", [("AT1", "AT"), ("NEW", "AT"), ("JUG", "ノーマル")])
    con.executemany("INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


# 前日(10/29)の配置。NEW は10/29に初出なので新台。
HISTORY = [
    ("20261001", 1, "AT1", 3000, 0),
    ("20261029", 1, "AT1", 3000, 0),
    ("20261029", 2, "AT1", 3000, 0),
    ("20261029", 3, "AT1", 3000, 0),
    ("20261029", 4, "NEW", 3000, 0),
    ("20261029", 5, "JUG", 3000, 0),
]
CLOSE = [
    ("20261030", 1, "AT1", 8200, -300),
    ("20261030", 2, "AT1", 4000, 500),
    ("20261030", 3, "AT1", 7100, 100),
    ("20261030", 4, "NEW", 9000, 0),
    ("20261030", 5, "JUG", 8000, 0),
]


def _snapshot(directory, when, rows):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"楽園蒲田店_quick_{when.strftime('%Y%m%d_%H%M%S')}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for unit, model, games, diff in rows:
            row = {
                "hall": "楽園蒲田店",
                "observed_at": when.isoformat(),
                "source_updated_at": None,
                "unit": unit,
                "model": model,
                "model_raw": model,
                "games": games,
                "bb": 1,
                "rb": 1,
                "diff": diff,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    _db(db_dir / "楽園蒲田店.db", HISTORY)
    monkeypatch.setattr(cp, "busy_dates", lambda hall: set())
    monkeypatch.setattr(cp, "load_labels", lambda hall: {"20261030": {1}})
    return tmp_path, db_dir


def test_pace_line_and_exclusions(env):
    tmp, db_dir = env
    t = datetime(2026, 10, 30, 13, 15, tzinfo=JST)  # 経過3.25時間 → ペース線 2,000G
    # 台2のスナップショットの機種名は略称でも、前日の配置(AT1)で判定する。台5のジャグラー・台4の新台は外す
    rows = [
        (1, "AT1", 2100, None),
        (2, "略称", 1500, None),
        (3, "AT1", 0, None),
        (4, "NEW", 2500, None),
        (5, "JUG", 2500, None),
    ]
    _snapshot(tmp / "snap", t, rows)
    written = cp.freeze_due(now=t, snapshot_dir=tmp / "snap", frozen_dir=tmp / "frozen", db_dir=db_dir)
    assert [p.name for p in written] == ["20261030__rakuen__13.json"]
    frozen = json.loads(written[0].read_text(encoding="utf-8"))
    assert frozen["pace_line_games"] == 2000
    assert [(u["unit"], u["pace"]) for u in frozen["units"]] == [(1, True), (2, False)]
    # 当たりのある0Gは回転数の欠損
    assert frozen["skipped"] == {"新台": 1, "AT機以外": 1, "回転数なし": 1}
    # 同じ窓では二度と書かない(上書きしない)
    assert cp.freeze_due(now=t, snapshot_dir=tmp / "snap", frozen_dir=tmp / "frozen", db_dir=db_dir) == []


def test_no_freeze_after_window_closes(env):
    tmp, db_dir = env
    _snapshot(tmp / "snap", datetime(2026, 10, 30, 13, 15, tzinfo=JST), [(1, "AT1", 2100, None)])
    late = datetime(2026, 10, 30, 15, 30, tzinfo=JST)
    assert cp.freeze_due(now=late, snapshot_dir=tmp / "snap", frozen_dir=tmp / "frozen", db_dir=db_dir) == []


def test_score_against_same_model(env):
    tmp, db_dir = env
    t = datetime(2026, 10, 30, 13, 15, tzinfo=JST)
    _snapshot(tmp / "snap", t, [(1, "AT1", 2100, -1000), (2, "AT1", 1500, 0), (3, "AT1", 1200, 0)])
    cp.freeze_due(now=t, snapshot_dir=tmp / "snap", frozen_dir=tmp / "frozen", db_dir=db_dir)
    _db(db_dir / "楽園蒲田店.db", CLOSE)
    [path] = cp.score_due(frozen_dir=tmp / "frozen", db_dir=db_dir)
    res = json.loads(path.read_text(encoding="utf-8"))["result"]
    # 台1(ペース)は到達、ペース外の台2・3は 1/2 → 到達率の差 +50pt
    assert res["reach_edge"] == pytest.approx(50.0)
    # 閉店時7,000G到達は台1・3。台1だけがペース台 → 拾えた割合 50%
    assert res["recall"] == pytest.approx(50.0)
    # 結果ツイートは台1だけ → 100 − 0
    assert res["result_edge"] == pytest.approx(100.0)
    assert res["diff_edge"] == pytest.approx(-300 - 300)
    # 収集時点 −1000 → 閉店時 −300 なので、座ってからは +700
    assert res["rest_diff_mean"] == pytest.approx(700.0)
    # 採点済みは書き換えない
    assert cp.score_due(frozen_dir=tmp / "frozen", db_dir=db_dir) == []

    rows = scoreboard.build_pace_rows(cp.load_scored(tmp / "frozen"))
    assert {(r.family, r.label) for r in rows} == {
        ("cp_reach", "13時"),
        ("cp_result", "13時"),
        ("cp_diff", "13時"),
        ("cp_rest", "13時"),
    }


def test_result_ignored_when_no_at_unit_listed():
    units = [
        {"unit": 1, "model": "AT1", "games": 2100, "pace": True, "diff_at_obs": None},
        {"unit": 2, "model": "AT1", "games": 100, "pace": False, "diff_at_obs": None},
    ]
    close = {1: {"model": "AT1", "games": 8000, "diff": 0}, 2: {"model": "AT1", "games": 500, "diff": 0}}
    res = cp.score({"reach": 7000, "units": units}, close, labels={999})
    assert res["result_edge"] is None and res["pace_result_rate"] is None


def test_split_label_for_kamata7():
    f = {"hall": "マルハンメガシティ2000-蒲田7", "checkpoint_hour": 15, "busy": True}
    assert cp.series_label(f) == "15時・土日イベント"
    assert cp.series_label({**f, "hall": "楽園蒲田店"}) == "15時"


def test_snapshot_with_other_day_data_is_ignored(env):
    """収集に失敗して前の日の台表のまま書かれたスナップショットは、その日の凍結に使わない。"""
    tmp, db_dir = env
    _snapshot(tmp / "snap", datetime(2026, 10, 27, 14, 27, tzinfo=JST), [(1, "AT1", 5000, None)])
    stale = next((tmp / "snap").glob("*.jsonl"))
    stale.rename(stale.with_name("楽園蒲田店_quick_20261030_015148.jsonl"))
    assert cp.load_snapshots("20261030", tmp / "snap") == {}
