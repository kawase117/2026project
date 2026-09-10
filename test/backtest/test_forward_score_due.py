# -*- coding: utf-8 -*-
"""score-due が「採点し忘れ」を作らないことを固定する。

2026-08-13〜09-10 の29日間、採点も凍結も走らず13件が未採点で残った。
一括採点はその再発防止のために足したので、対象日の境界と、
採点済みを二度触らないことをテストする。
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backtest import forward  # noqa: E402


@pytest.fixture
def forward_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(forward, "FORWARD_DIR", tmp_path)
    return tmp_path


def write_plan(directory, name, target_date, result=None):
    path = directory / name
    path.write_text(
        json.dumps({"target_date": target_date, "result": result}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_future_target_is_not_due(forward_dir, monkeypatch):
    write_plan(forward_dir, "r__20260920.json", "20260920")
    monkeypatch.setattr(forward, "score", lambda obj: pytest.fail("未来日を採点してはいけない"))
    report = forward.score_due(now=forward.datetime(2026, 9, 11, 8, 0, tzinfo=forward.JST))
    assert report["counts"] == {"not_due": 1}


def test_today_is_not_due_yet(forward_dir, monkeypatch):
    # 当日はまだ営業中なので採点しない。翌朝に拾う。
    write_plan(forward_dir, "r__20260911.json", "20260911")
    monkeypatch.setattr(forward, "score", lambda obj: pytest.fail("当日を採点してはいけない"))
    report = forward.score_due(now=forward.datetime(2026, 9, 11, 8, 0, tzinfo=forward.JST))
    assert report["counts"] == {"not_due": 1}


def test_past_target_gets_scored_and_written_back(forward_dir, monkeypatch):
    path = write_plan(forward_dir, "r__20260910.json", "20260910")

    def fake_score(obj):
        obj["result"] = {"mean_diff_per_pick": 123.0, "mean_edge_per_pick": 45.0}
        return obj

    monkeypatch.setattr(forward, "score", fake_score)
    report = forward.score_due(now=forward.datetime(2026, 9, 11, 8, 0, tzinfo=forward.JST))
    assert report["counts"] == {"scored": 1}
    assert json.loads(path.read_text(encoding="utf-8"))["result"]["mean_diff_per_pick"] == 123.0


def test_already_scored_is_left_alone(forward_dir, monkeypatch):
    write_plan(forward_dir, "r__20260910.json", "20260910", result={"mean_diff_per_pick": 1.0})
    monkeypatch.setattr(forward, "score", lambda obj: pytest.fail("採点済みをやり直してはいけない"))
    report = forward.score_due(now=forward.datetime(2026, 9, 11, 8, 0, tzinfo=forward.JST))
    assert report["counts"] == {}


def test_missing_data_is_skipped_not_fatal(forward_dir, monkeypatch):
    # 実績が未取込なだけなら翌日に解消しうる。落とさず残す。
    write_plan(forward_dir, "r__20260910.json", "20260910")

    def raise_missing(obj):
        raise ValueError("20260910 のデータが DB にまだ無い。")

    monkeypatch.setattr(forward, "score", raise_missing)
    report = forward.score_due(now=forward.datetime(2026, 9, 11, 8, 0, tzinfo=forward.JST))
    assert report["counts"] == {"skipped": 1}


def test_corrupt_plan_is_reported(forward_dir):
    (forward_dir / "r__20260910.json").write_text("{ではないJSON", encoding="utf-8")
    report = forward.score_due(now=forward.datetime(2026, 9, 11, 8, 0, tzinfo=forward.JST))
    assert report["counts"] == {"corrupt": 1}
