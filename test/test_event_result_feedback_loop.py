import json

import pandas as pd
import pytest

from backtest.announce import (
    _judge_narabi,
    announce_digest,
    extract_narabi_mentions,
    validate,
)
from backtest.event_days import cmd_series_accuracy, pledge_keys
from backtest.event_days import _name_similarity, _series_candidates, cmd_series_decide


def _payload(claims):
    return {
        "announce_id": "synthetic",
        "hall": "H",
        "target_date": "20260928",
        "source": {"account": "a", "url": "u", "posted_at": "20260927T12:00:00+09:00", "kind": "予告"},
        "zentaikei": {"metric": "gratio_mean_diff", "threshold": 1, "min_machines": 1},
        "claims": claims,
        "raw_text": "3台並び",
        "result": None,
    }


def test_extract_narabi_mentions_all_forms():
    text = "3台並び 3台並び⑤⑥×2か所 3台並びが20箇所以上 5台並び⑤⑥複数 4台並び×15か所 各フロアに3台並びが4箇所以上"
    got = extract_narabi_mentions(text)
    assert [(x["n_adjacent"], x["count"]) for x in got] == [(3, None), (3, 2), (3, 20), (5, None), (4, 15), (3, 4)]


def test_narabi_validation_rejects_short_block():
    with pytest.raises(ValueError, match="2 以上"):
        validate(_payload([{"type": "narabi", "n_adjacent": 1, "scope": "hall"}]))


def test_narabi_score_has_percentile_and_no_hit():
    rows = []
    for d, games, diffs in [
        ("20260927", 1000, [100, 100, 100, 100, 100, 100, 100]),
        ("20260928", 15000, [2000, 2100, 2200, -100, -100, -100, -100]),
    ]:
        for number, diff in enumerate(diffs, 1):
            row_games = games if d == "20260927" or number <= 3 else 1000
            rows.append(
                {
                    "date": d,
                    "machine_number": number,
                    "machine_name": "A",
                    "section": "S",
                    "games_normalized": row_games,
                    "diff_coins_normalized": diff,
                }
            )
    for row in rows:
        if row["date"] == "20260928" and row["machine_number"] <= 3:
            row["games_normalized"] = 30000
    frame = pd.DataFrame(rows)
    result = _judge_narabi({"n_adjacent": 3, "scope": "hall"}, frame[frame.date == "20260928"], frame, "20260928")
    assert result["hit"] is None
    assert result["detected_count"] == 1
    assert result["baseline_percentile"] == 100.0
    assert result["blocks"][0]["machines"] == [1, 2, 3]
    assert result["games_blocks"]


def test_existing_digest_ignores_result_only():
    payload = _payload([{"type": "narabi", "n_adjacent": 3, "count": None, "scope": "hall"}])
    digest = announce_digest(payload)
    payload["result"] = {"claims": []}
    assert announce_digest(payload) == digest


def test_pledge_keys():
    payload = {
        "claims": [
            {"type": "position_rule", "field": "last_digit", "values": [7], "ratio": 2},
            {"type": "model_named_ratio", "ratio": 3},
            {"type": "model_named", "machine_name": "A"},
            {"type": "zentaikei_count", "n_models": 2},
            {"type": "narabi", "n_adjacent": 3},
        ],
        "raw_text": "5台並び",
    }
    assert pledge_keys(payload) == {"末尾:7:1/2", "機種指名:1/3", "機種指名:全", "全台系:2機種", "並び:3台", "並び:5台"}


def test_series_accuracy(tmp_path, capsys):
    path = tmp_path / "EVENT_SERIES.jsonl"
    rows = [{"decision": "same", "auto_decision": "same", "decided_by": "user"} for _ in range(19)]
    rows.append({"decision": "different", "auto_decision": "same", "decided_by": "user"})
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    args = type("Args", (), {"series_ledger": str(path)})()
    assert cmd_series_accuracy(args) == 0
    assert "19件一致" in capsys.readouterr().out


def test_name_axis_and_series_decide_are_append_only(tmp_path):
    assert _name_similarity("スロトレ調査団三大天", "スロトレ調査団 三大天 2日目") >= 0.5
    assert _name_similarity("スロトレ調査団", "別イベント") < 0.5
    event_ledger = tmp_path / "EVENT_DAYS.jsonl"
    announce_dir = tmp_path / "announce"
    announce_dir.mkdir()
    events = [
        {"event_id": "e1", "hall": "H", "date": "20260901", "event_name": "スロトレ調査団三大天", "source_tweets": []},
        {
            "event_id": "e2",
            "hall": "H",
            "date": "20260902",
            "event_name": "スロトレ調査団 三大天 2日目",
            "source_tweets": [],
        },
    ]
    event_ledger.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in events) + "\n", encoding="utf-8")
    for event in events:
        payload = _payload([])
        payload.update(
            {
                "announce_id": event["event_id"],
                "hall": "H",
                "target_date": event["date"],
                "claims": [{"type": "narabi", "n_adjacent": 3, "scope": "hall"}],
            }
        )
        (announce_dir / f"{event['event_id']}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    ledger = tmp_path / "EVENT_SERIES.jsonl"
    candidates = _series_candidates(str(event_ledger), str(announce_dir), str(ledger), str(tmp_path / "missing.db"))
    name = next(row for row in candidates if row["axis"] == "name")
    args = type(
        "Args",
        (),
        {
            "series_ledger": str(ledger),
            "series_id": name["series_id"],
            "axis": "name",
            "hall": "H",
            "label": name["label"],
            "pledge_key": None,
            "event_ids": ",".join(name["event_ids"]),
            "decision": "same",
            "auto_score": name["auto_score"],
        },
    )()
    cmd_series_decide(args)
    args.decision = "different"
    cmd_series_decide(args)
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert rows[1]["supersedes"] == rows[0]["row_id"]
    assert not any(
        row["axis"] == "name" and set(row["event_ids"]) == set(name["event_ids"])
        for row in _series_candidates(str(event_ledger), str(announce_dir), str(ledger), str(tmp_path / "missing.db"))
    )
