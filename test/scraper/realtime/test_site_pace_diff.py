"""楽園のクイック収集で、示唆続行台のペース台だけグラフから差枚を取る(2026-10 振り返り 作業6の続き)。"""

import json
import sqlite3
from datetime import datetime

import pytest

from backtest import continuation_pace as cp
from scraper.realtime import run
from scraper.realtime.adapters import site777
from scraper.realtime.quick_filter import site_model_allowlist
from scraper.realtime.schema import JST
from scraper.realtime.store import write_snapshot
from scraper.site777.site777_prepare_graph_targets import build_config

HALL = "楽園蒲田店"
STARTED = "2026-10-30T06:00:00.000Z"


def _quick_data(path, games_by_unit, started=STARTED):
    rows = [["台番", "累計ゲーム", "BB回数", "RB回数", "ART回数"]]
    rows += [[str(u), str(g), "1", "1", "3"] for u, g in games_by_unit.items()]
    path.write_text(
        json.dumps(
            {
                "complete": True,
                "startedAt": started,
                "models": {
                    "900": {
                        "mdc": "900",
                        "name": "AT1",
                        "jackpot": {"updateTime": "2026/10/30 15:00", "pages": [{"rows": rows}]},
                    }
                },
            }
        ),
        encoding="utf-8-sig",
    )


def _metrics(path, machines, source=STARTED):
    path.write_text(json.dumps({"sourceSnapshotId": source, "machines": machines}), encoding="utf-8-sig")


def _db(path, rows):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT, "
        "games_normalized REAL, diff_coins_normalized REAL)"
    )
    con.execute("CREATE TABLE machine_master (machine_name_normalized TEXT, game_type TEXT)")
    con.executemany("INSERT INTO machine_master VALUES (?, ?)", [("AT1", "AT")])
    con.executemany("INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?)", rows)
    con.commit()
    con.close()


@pytest.fixture(autouse=True)
def _names(monkeypatch):
    monkeypatch.setattr(site777, "model_name", lambda raw: raw)


def test_allowlist_extra_models(tmp_path):
    path = tmp_path / "full.json"
    path.write_text(json.dumps({"models": {"1": {"name": "判別可"}, "2": {"name": "AT機"}, "3": {"name": "他"}}}))
    resolve = {"判別可": "正式A", "AT機": "正式AT", "他": "正式他"}.get
    audit = {(HALL, "正式A"): "A"}
    assert site_model_allowlist(path, HALL, audit, {}, resolve) == ["判別可"]
    assert site_model_allowlist(path, HALL, audit, {}, resolve, {"正式AT"}) == ["AT機", "判別可"]


def test_prepare_targets_only_given_keys():
    source = {
        "complete": True,
        "startedAt": STARTED,
        "models": {
            "900": {
                "mdc": "900",
                "jackpot": {"pages": [{"rows": [["台番", "累計"], ["1", "500"], ["2", "3000"], ["3", "4000"]]}]},
            }
        },
    }
    config = build_config(
        source, 0, allow_incomplete=True, keys={"900:1", "900:3"}, image_prefix="site777_graphs_quick"
    )
    assert [t["key"] for t in config["targets"]] == ["900:1", "900:3"]
    assert config["imageDirectory"].startswith("site777_graphs_quick/")
    # keys を渡さなければ従来どおり min_games だけで選ぶ
    assert [t["key"] for t in build_config(source, 2000, allow_incomplete=True)["targets"]] == ["900:2", "900:3"]


def test_quick_adapter_reads_pace_diff_and_ignores_stale(tmp_path):
    _quick_data(tmp_path / "site777_quick_data.json", {1: 3000, 2: 3100, 3: 3200, 4: 500})
    _metrics(
        tmp_path / "site777_quick_graph_metrics.json",
        [
            {"key": "900:1", "status": "ok", "estimatedLatestDiff": -800},
            {"key": "900:2", "status": "ok", "estimatedLatestDiff": 900, "diffUnreliable": True},
            {"key": "900:3", "status": "ok", "estimatedLatestDiff": 5000, "diffCensoredHigh": True},
        ],
    )
    rows = {r.unit: r for r in site777.adapt(tmp_path, HALL, quick=True)}
    assert (rows[1].diff, rows[1].diff_kind) == (-800, "estimated")
    assert rows[2].diff is None and "diff_unreadable" in rows[2].quality_flags
    assert rows[3].diff is None and "diff_censored" in rows[3].quality_flags
    assert rows[4].diff is None and "diff_not_collected" in rows[4].quality_flags
    assert site777.unit_keys(tmp_path) == {1: "900:1", 2: "900:2", 3: "900:3", 4: "900:4"}

    # 別の回の台表から作ったグラフは使わない
    _metrics(
        tmp_path / "site777_quick_graph_metrics.json",
        [{"key": "900:1", "status": "ok", "estimatedLatestDiff": -800}],
        source="2026-10-30T04:00:00.000Z",
    )
    assert all(r.diff is None for r in site777.adapt(tmp_path, HALL, quick=True))


def test_pace_keys_and_retro_rest_diff(tmp_path, monkeypatch):
    """ペース台の選定 → 差枚つきのスナップショット → retro で楽園の残りの差枚が出るまで。"""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    history = [("20261001", u, "AT1", 3000, 0) for u in (1, 2, 3)]
    history += [("20261029", u, "AT1", 3000, 0) for u in (1, 2, 3)]
    _db(db_dir / f"{HALL}.db", history)
    out = tmp_path / "site"
    out.mkdir()
    # 15:00 は経過5時間 → ペース線 8,000×5/13 ≒ 3,077G。台1・2がペース台
    _quick_data(out / "site777_quick_data.json", {1: 3500, 2: 3100, 3: 1500})
    rows = site777.adapt(out, HALL, quick=True)
    assert run.site_pace_keys(rows, HALL, site777.unit_keys(out), db_dir=db_dir) == ["900:1", "900:2"]

    _metrics(
        out / "site777_quick_graph_metrics.json",
        [
            {"key": "900:1", "status": "ok", "estimatedLatestDiff": -500},
            {"key": "900:2", "status": "ok", "estimatedLatestDiff": 200},
        ],
    )
    rows = site777.adapt(out, HALL, quick=True)
    write_snapshot(rows, tmp_path, HALL, "quick", datetime(2026, 10, 30, 15, 5, tzinfo=JST))

    # 閉店時: 台1 +1,000(座ってから +1,500)、台2 −100(−300)
    close = [("20261030", 1, "AT1", 8200, 1000), ("20261030", 2, "AT1", 7500, -100), ("20261030", 3, "AT1", 4000, 0)]
    con = sqlite3.connect(db_dir / f"{HALL}.db")
    con.executemany("INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?)", close)
    con.commit()
    con.close()
    monkeypatch.setattr(cp, "busy_dates", lambda hall: set())
    monkeypatch.setattr(cp, "load_labels", lambda hall: {})
    [frozen] = cp.retro("20261030", "20261030", snapshot_dir=tmp_path / "snapshots", db_dir=db_dir)
    assert frozen["checkpoint_hour"] == 15
    assert frozen["result"]["rest_n"] == 2
    assert frozen["result"]["rest_diff_mean"] == pytest.approx((1500 - 300) / 2)


def test_pace_due_only_first_run_of_each_window(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "FROZEN_DIR", tmp_path)
    monkeypatch.setattr(cp, "frozen_path", lambda h, d, hour, frozen_dir=tmp_path: tmp_path / f"{d}__{hour:02d}.json")
    assert not run.pace_due(HALL, datetime(2026, 10, 30, 12, 50, tzinfo=JST))
    assert run.pace_due(HALL, datetime(2026, 10, 30, 13, 10, tzinfo=JST))
    (tmp_path / "20261030__13.json").write_text("{}")
    assert not run.pace_due(HALL, datetime(2026, 10, 30, 14, 10, tzinfo=JST))
    assert run.pace_due(HALL, datetime(2026, 10, 30, 15, 10, tzinfo=JST))
    assert not run.pace_due(HALL, datetime(2026, 10, 30, 19, 10, tzinfo=JST))
