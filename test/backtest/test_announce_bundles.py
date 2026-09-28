import json
import sqlite3
from pathlib import Path

from backtest import announce, integrated


def write_json(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def base(announce_id: str, hall: str = "テスト店") -> dict:
    return {
        "announce_id": announce_id,
        "hall": hall,
        "target_date": "20260930",
        "raw_text": "予告",
        "source": {"account": "tester"},
        "zentaikei": {"min_machines": 1, "threshold": 1},
        "claims": [{"type": "model_named", "machine_name": "A"}],
    }


def test_load_announce_bundles_handles_all_file_kinds(tmp_path: Path):
    write_json(tmp_path, "active__20260930__tester.json", base("active__20260930__tester"))
    write_json(tmp_path, "withdrawn__20260930__tester.json", base("withdrawn__20260930__tester"))
    write_json(
        tmp_path,
        "withdrawn__20260930__tester.withdrawn.json",
        {"kind": "withdrawal", "announce_id": "withdrawn__20260930__tester"},
    )
    write_json(
        tmp_path,
        "retro__20260929__tester.retro.json",
        {"hall": "テスト店", "target_date": "20260929", "raw_text": "後追い"},
    )
    write_json(
        tmp_path,
        "active__20260930__tester.correction.json",
        {"kind": "correction", "announce_id": "active__20260930__tester", "text": "訂正"},
    )
    write_json(
        tmp_path,
        "active__20260930__tester.addendum.json",
        {"kind": "addendum", "addendum_to": "active__20260930__tester", "text": "追記"},
    )
    write_json(
        tmp_path,
        "active__20260930__tester.scoring.json",
        {"kind": "scoring", "announce_id": "active__20260930__tester", "score": 1},
    )
    write_json(tmp_path, "active__20260930__tester__v2.json", base("active__20260930__tester__v2"))
    write_json(tmp_path, "missing.correction.json", {"kind": "correction", "announce_id": "missing"})

    result = announce.load_announce_bundles(tmp_path)
    bundles = {item["announce_id"]: item for item in result["bundles"]}

    assert bundles["withdrawn__20260930__tester"]["status"] == "withdrawn"
    assert bundles["retro__20260929__tester"]["status"] == "retroactive"
    active = bundles["active__20260930__tester"]
    assert active["status"] == "active"
    assert active["payload"]["claims"][0]["machine_name"] == "A"
    assert len(active["corrections"]) == 1
    assert len(active["addenda"]) == 1
    assert len(active["scoring"]) == 1
    assert bundles["active__20260930__tester__v2"]["status"] == "active"
    assert all(item["announce_id"] != "missing" for item in result["bundles"])
    assert len(result["orphans"]) == 1


def test_ingest_is_idempotent_and_excludes_withdrawn(tmp_path: Path, monkeypatch):
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    write_json(announce_dir, "kept__20260930__tester.json", base("kept__20260930__tester"))
    write_json(announce_dir, "gone__20260930__tester.json", base("gone__20260930__tester"))
    write_json(
        announce_dir,
        "gone__20260930__tester.withdrawn.json",
        {"kind": "withdrawal", "announce_id": "gone__20260930__tester"},
    )
    write_json(
        announce_dir,
        "retro__20260929__tester.retro.json",
        {"hall": "テスト店", "target_date": "20260929", "raw_text": "後追い"},
    )
    write_json(
        announce_dir,
        "kept__20260930__tester.correction.json",
        {"kind": "correction", "announce_id": "kept__20260930__tester", "text": "訂正"},
    )
    monkeypatch.setattr(integrated, "ANNOUNCE_DIR", str(announce_dir))
    db_path = tmp_path / "analysis.db"

    integrated.ingest_announce(str(db_path))
    with sqlite3.connect(db_path) as connection:
        first = connection.execute(
            "SELECT announce_id, retroactive, payload_json FROM announce_reports ORDER BY announce_id"
        ).fetchall()
        first_claims = connection.execute("SELECT COUNT(*) FROM announce_claims").fetchone()[0]
    integrated.ingest_announce(str(db_path))
    with sqlite3.connect(db_path) as connection:
        second = connection.execute(
            "SELECT announce_id, retroactive, payload_json FROM announce_reports ORDER BY announce_id"
        ).fetchall()
        second_claims = connection.execute("SELECT COUNT(*) FROM announce_claims").fetchone()[0]

    assert [row[0] for row in first] == ["kept__20260930__tester", "retro__20260929__tester"]
    assert dict((row[0], row[1]) for row in first) == {
        "kept__20260930__tester": 0,
        "retro__20260929__tester": 1,
    }
    assert "_corrections" in json.loads(first[0][2])
    assert second == first
    assert second_claims == first_claims == 1


def test_ingest_announce_keeps_tweet_retro_lane(tmp_path: Path, monkeypatch):
    """ファイル由来の再取り込みが、state.db 由来の遡及レーンを消さない（2026-09-28 に286件消えた）。"""
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    write_json(announce_dir, "kept__20260930__tester.json", base("kept__20260930__tester"))
    monkeypatch.setattr(integrated, "ANNOUNCE_DIR", str(announce_dir))
    db_path = tmp_path / "analysis.db"
    integrated.ingest_announce(str(db_path))
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO announce_reports (announce_id, hall_name, target_date, file_path, payload_json,"
            " ingested_at, retroactive) VALUES ('retro__123__テスト店', 'テスト店', '20260901',"
            " '(tweet 123)', '{}', 'x', 1)"
        )
        connection.execute(
            "INSERT INTO announce_claims (announce_id, seq, claim_type, machine_name)"
            " VALUES ('retro__123__テスト店', 0, 'model_named', 'B')"
        )

    integrated.ingest_announce(str(db_path))
    with sqlite3.connect(db_path) as connection:
        ids = [r[0] for r in connection.execute("SELECT announce_id FROM announce_reports ORDER BY 1")]
        lane_claims = connection.execute(
            "SELECT COUNT(*) FROM announce_claims WHERE announce_id = 'retro__123__テスト店'"
        ).fetchone()[0]
    assert ids == ["kept__20260930__tester", "retro__123__テスト店"]
    assert lane_claims == 1
