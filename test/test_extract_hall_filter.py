"""画像抽出は本文に追跡対象ホールの手がかりがある投稿だけに絞る。上限到達で止める（2026-10-12）。"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper" / "twitter_monitor"))

import extract_answers  # noqa: E402
from hall_aliases import mentions_target_hall  # noqa: E402


@pytest.mark.parametrize(
    "text, on_date, expected",
    [
        ("9/7 楽園蒲田", date(2026, 10, 1), True),
        ("楽蒲の結果", date(2026, 10, 1), True),
        ("メガ1とメガ7", date(2026, 10, 1), True),
        ("GALAXYウスイの速報", date(2026, 10, 1), True),  # 店長名で示唆
        ("よこやん店長の初日", date(2026, 10, 1), True),
        ("よこやん", date(2026, 8, 30), False),  # 就任(9/1)前
        ("サトウ", date(2026, 10, 1), False),  # 退任済み
        ("マルハン川口店の結果", date(2026, 10, 1), False),
        ("楽園池袋の結果", date(2026, 10, 1), False),
        ("", date(2026, 10, 1), False),
        (None, None, False),
    ],
)
def test_mentions_target_hall(text, on_date, expected):
    assert mentions_target_hall(text, on_date) is expected


def _db():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE seen_tweets (tweet_id TEXT, handle TEXT, posted_at_jst TEXT, tweet_text TEXT, has_image INTEGER);
        CREATE TABLE tweet_images (id INTEGER PRIMARY KEY, tweet_id TEXT, image_path TEXT);
        CREATE TABLE image_features (image_path TEXT, is_candidate INTEGER);
        CREATE TABLE extractions (tweet_id TEXT, image_path TEXT, status TEXT);
        """
    )
    tweets = [
        ("1", "kawasakislot", "2026-10-10T20:00:00+09:00", "10/11 楽園蒲田"),
        ("2", "sloneko222", "2026-10-10T21:00:00+09:00", "10/10 マルハン川口店"),
        ("3", "999999Q9Q", "2026-10-10T22:00:00+09:00", "ウスイの予想"),
        ("4", "slokotae7", "2026-10-09T22:00:00+09:00", "メガ7の結果"),
    ]
    for tweet_id, handle, posted, text in tweets:
        connection.execute("INSERT INTO seen_tweets VALUES (?, ?, ?, ?, 1)", (tweet_id, handle, posted, text))
        connection.execute(
            "INSERT INTO tweet_images (tweet_id, image_path) VALUES (?, ?)", (tweet_id, f"{tweet_id}.jpg")
        )
        connection.execute("INSERT INTO image_features VALUES (?, 1)", (f"{tweet_id}.jpg",))
    return connection


def _select(connection, **kwargs):
    defaults = dict(handles=[], halls=[], priority_halls=[], limit=None, newest_first=True, redo_failed=False)
    return extract_answers.select_pending_images(connection, **{**defaults, **kwargs})


def test_select_drops_posts_without_target_hall():
    rows = _select(_db())
    assert [row[0] for row in rows] == ["3", "1", "4"]  # 新しい順。sloneko222の他店舗(2)は除外
    assert all(len(row) == 4 for row in rows)


def test_limit_applies_after_filter():
    rows = _select(_db(), limit=2)
    assert [row[0] for row in rows] == ["3", "1"]


def test_no_hall_filter_and_tweet_ids_bypass():
    assert len(_select(_db(), hall_filter=False)) == 4
    assert [row[0] for row in _select(_db(), tweet_ids=["2"])] == ["2"]


def test_usage_limit_is_raised_and_not_retried(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "ERROR: You've hit your usage limit."})()

    monkeypatch.setattr(extract_answers.subprocess, "run", fake_run)
    monkeypatch.setattr(extract_answers, "codex_command", lambda image_path, output_path: ["codex"])
    with pytest.raises(extract_answers.UsageLimitReached):
        extract_answers.extract_image(str(Path(__file__)))
    assert len(calls) == 1
