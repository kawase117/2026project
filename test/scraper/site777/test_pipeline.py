from __future__ import annotations

from copy import deepcopy

from scraper.site777.site777_prepare_graph_targets import build_config
from scraper.site777.site777_rate_limiter import SharedRateLimiter
from scraper.site777.site777_analyze import snapshot_time_status


def _partial_source(*, complete: bool) -> dict:
    return {
        "complete": complete,
        "startedAt": "2026-08-15T01:00:00Z",
        "updatedAt": "2026-08-15T01:05:00Z",
        "completedAt": "2026-08-15T01:20:00Z" if complete else None,
        "expectedMachineCount": 2,
        "models": {
            "120001": {
                "complete": True,
                "mdc": "120001",
                "name": "テスト機種",
                "jackpot": {
                    "updateTime": "2026/08/15 10:55",
                    "pages": [
                        {
                            "rows": [
                                ["1001", "2500", "10", "8", "--"],
                                ["1002", "1500", "4", "3", "--"],
                            ]
                        }
                    ],
                },
            }
        },
    }


def test_partial_and_final_configs_keep_pipeline_snapshot_identity() -> None:
    partial = build_config(
        _partial_source(complete=False),
        min_games=2000,
        allow_incomplete=True,
    )
    final_source = deepcopy(_partial_source(complete=True))
    final = build_config(
        final_source,
        min_games=2000,
        allow_incomplete=True,
    )

    assert partial["sourceComplete"] is False
    assert final["sourceComplete"] is True
    assert partial["sourceSnapshotId"] == final["sourceSnapshotId"]
    assert partial["sourceSnapshotId"] == "2026-08-15T01:00:00Z"
    assert partial["collectTargetCount"] == 1
    assert partial["completedMachineCount"] == 2


def test_shared_rate_limiter_applies_interval_and_pause() -> None:
    limiter = SharedRateLimiter(interval_ms=20)

    first = limiter.acquire("normal")
    second = limiter.acquire("graph")
    limiter.pause(20)
    after_pause = limiter.acquire("normal")

    assert first["waitMs"] < 10
    assert second["waitMs"] >= 10
    assert after_pause["waitMs"] >= 10


def test_pipeline_started_at_is_recognized_as_same_run() -> None:
    source = _partial_source(complete=True)
    status = snapshot_time_status(source, {"sourceSnapshotId": source["startedAt"]})

    assert status["same_run"] is True
    assert "同じ収集ラン" in status["note"]


def test_different_snapshot_is_labeled_without_rejecting_rankings() -> None:
    status = snapshot_time_status(
        _partial_source(complete=True),
        {"sourceSnapshotId": "2026-08-14T01:00:00Z"},
    )

    assert status["same_run"] is False
    assert "別時刻" in status["note"]
