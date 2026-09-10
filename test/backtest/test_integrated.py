# -*- coding: utf-8 -*-
"""backtest/integrated.py の取り込みと結合の検証。"""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest import integrated  # noqa: E402


def _announce(path, **overrides):
    payload = {
        "announce_id": "rakuen__20260830__acct",
        "hall": "楽園蒲田店",
        "target_date": "20260830",
        "source": {"account": "acct", "posted_at": "2026-08-29T20:00:00+09:00", "kind": "予告"},
        "zentaikei": {"metric": "gratio_mean_diff", "threshold": 1800.0, "min_machines": 3},
        "claims": [
            {"type": "zentaikei_count", "n_models": 2, "note": "全台系2機種"},
            {"type": "model_named", "machine_name": "化物語", "note": "本命"},
        ],
        # その回限りの検討メモ。列にせず payload_json から引ける必要がある。
        "tiger_dash_history": {"note": "一過性のメモ"},
    }
    payload.update(overrides)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def test_ingest_splits_core_fields_and_keeps_the_whole_payload(tmp_path, monkeypatch):
    """安定コアだけを列にし、その回限りのキーは payload_json から引けること。"""
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    _announce(str(announce_dir / "a.json"))
    monkeypatch.setattr(integrated, "ANNOUNCE_DIR", str(announce_dir))
    analysis = str(tmp_path / "analysis.db")

    integrated.ingest_announce(analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    row = connection.execute(
        "SELECT hall_name, target_date, account, metric, threshold, min_machines FROM announce_reports"
    ).fetchone()
    assert row == ("楽園蒲田店", "20260830", "acct", "gratio_mean_diff", 1800.0, 3)

    payload = json.loads(connection.execute("SELECT payload_json FROM announce_reports").fetchone()[0])
    assert payload["tiger_dash_history"]["note"] == "一過性のメモ"

    claims = connection.execute(
        "SELECT claim_type, machine_name, n_models FROM announce_claims ORDER BY seq"
    ).fetchall()
    assert claims == [("zentaikei_count", None, 2), ("model_named", "化物語", None)]


def test_withdrawn_and_invalidated_files_are_not_ingested(tmp_path, monkeypatch):
    """取り下げた予告を採点対象に戻さない。ファイル名で判別している。"""
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    _announce(str(announce_dir / "keep.json"))
    _announce(str(announce_dir / "drop.withdrawn.json"), announce_id="withdrawn__1")
    _announce(str(announce_dir / "old.invalidated.json"), announce_id="invalidated__1")
    monkeypatch.setattr(integrated, "ANNOUNCE_DIR", str(announce_dir))
    analysis = str(tmp_path / "analysis.db")

    integrated.ingest_announce(analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    ids = [row[0] for row in connection.execute("SELECT announce_id FROM announce_reports")]
    assert ids == ["rakuen__20260830__acct"]


def test_ingest_is_idempotent_and_claims_do_not_accumulate(tmp_path, monkeypatch):
    """同じファイルを二度取り込んでも claim が増えないこと。"""
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    _announce(str(announce_dir / "a.json"))
    monkeypatch.setattr(integrated, "ANNOUNCE_DIR", str(announce_dir))
    analysis = str(tmp_path / "analysis.db")

    integrated.ingest_announce(analysis_db=analysis)
    integrated.ingest_announce(analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    assert connection.execute("SELECT COUNT(*) FROM announce_reports").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM announce_claims").fetchone()[0] == 2


def test_a_report_without_hall_or_date_is_skipped(tmp_path, monkeypatch):
    """結合キーが無いものは取り込まない。黙って NULL キーの行を作らせない。"""
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    _announce(str(announce_dir / "broken.json"), hall=None)
    monkeypatch.setattr(integrated, "ANNOUNCE_DIR", str(announce_dir))
    analysis = str(tmp_path / "analysis.db")

    integrated.ingest_announce(analysis_db=analysis)

    connection = sqlite3.connect(analysis)
    assert connection.execute("SELECT COUNT(*) FROM announce_reports").fetchone()[0] == 0


def test_retroactive_lane_never_leaks_into_the_prereg_columns(tmp_path, monkeypatch):
    """遡及の名指しが `announced_model` に混ざらないこと。

    混ざると、結果を知ってから読んだ予告が的中率の分子分母に入る。
    分離はこのシステムの前提なので、壊れたら必ず落ちるようにしておく。
    """
    analysis = str(tmp_path / "analysis.db")
    connection = sqlite3.connect(analysis)
    connection.executescript(integrated.SCHEMA)
    connection.execute(
        "INSERT INTO announce_reports (announce_id, hall_name, target_date, account, "
        " posted_at, kind, file_path, payload_json, ingested_at, retroactive) "
        "VALUES ('retro__1', '楽園蒲田店', '20260820', 'acct', NULL, '予告(遡及)', "
        "        '(tweet 1)', '{}', 'now', 1)"
    )
    connection.execute(
        "INSERT INTO announce_claims (announce_id, seq, claim_type, machine_name) "
        "VALUES ('retro__1', 0, 'model_named_mechanical', '化物語')"
    )
    connection.commit()
    connection.close()

    import pandas as pd

    frame = pd.DataFrame(
        {
            "date": ["20260820", "20260820"],
            "machine_number": [1000, 1001],
            "machine_name": ["化物語", "北斗の拳"],
            "diff_coins_normalized": [100, -100],
            "games_normalized": [5000, 5000],
        }
    )
    monkeypatch.setattr(integrated, "load_frame_for_test", None, raising=False)
    monkeypatch.setattr("backtest.run_backtest.load_frame", lambda hall: frame.copy())

    out = integrated.machine_frame("楽園蒲田店", analysis_db=analysis)
    assert list(out["announced_model"]) == [0, 0], "遡及が事前登録の列に漏れている"
    assert list(out["announced_model_retro"]) == [1, 0]
    assert out["announce_id"].isna().all(), "遡及に announce_id が付いている"
