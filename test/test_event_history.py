import json
import sqlite3

import pandas as pd

from backtest import event_days


def _frame():
    rows = []
    for d in ["20260901", "20260910", "20260927", "20261006", "20261007"]:
        rows += [
            {
                "date": d,
                "machine_number": 1,
                "machine_name": "JUG",
                "games_normalized": 1000,
                "diff_coins_normalized": 100,
                "rb_count": 20 if d != "20260927" else 30,
                "rb_rate": 0.02 if d != "20260927" else 0.03,
                "jug_flag": 1,
                "hana_flag": 0,
                "oki_flag": 0,
                "bt_flag": 0,
            },
            {
                "date": d,
                "machine_number": 2,
                "machine_name": "AT",
                "games_normalized": 2000 if d == "20260927" else 1000,
                "diff_coins_normalized": 500 if d == "20260927" else 0,
                "rb_count": 0,
                "rb_rate": 0,
                "jug_flag": 0,
                "hana_flag": 0,
                "oki_flag": 0,
                "bt_flag": 0,
            },
        ]
    frame = pd.DataFrame(rows)
    frame["dt"] = pd.to_datetime(frame["date"])
    return frame


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def test_history_pledge_asof_and_scores(monkeypatch, tmp_path):
    monkeypatch.setattr(event_days, "load_frame", lambda hall: _frame().copy())
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_jsonl(events, [{"event_id": "target", "hall": "H", "date": "20261007", "event_name": "対象"}])
    announces = tmp_path / "announce"
    announces.mkdir()
    payloads = [
        {
            "announce_id": "target-a",
            "hall": "H",
            "target_date": "20261007",
            "source": {"account": "a", "posted_at": "2026-10-06T20:00:00+09:00"},
            "claims": [{"type": "position_rule", "field": "last_digit", "values": [7]}],
        },
        {
            "announce_id": "past-a",
            "hall": "H",
            "target_date": "20260927",
            "source": {"account": "a", "posted_at": "2026-09-26T20:00:00+09:00"},
            "claims": [
                {"type": "position_rule", "field": "last_digit", "values": [7]},
                {"type": "model_named", "machine_name": "JUG"},
                {"type": "model_named", "machine_name": "AT"},
            ],
        },
    ]
    for p in payloads:
        (announces / (p["announce_id"] + ".json")).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    links = tmp_path / "EVENT_RESULT_LINKS.jsonl"
    _write_jsonl(links, [{"hall": "H", "business_date": "20260927", "status": "linked", "report_ids": ["r1"]}])
    analysis = tmp_path / "analysis.db"
    con = sqlite3.connect(analysis)
    con.executescript("""
      create table external_result_reports(report_id text, posted_at text, tweet_url text, business_date text);
      create table external_result_machines(report_id text, machine_number integer, actual_name text, granularity text, granularity_source text, business_date text);
      create table external_result_models(report_id text, seq integer, granularity text, model_name text, n_target integer, n_total integer, number_from integer, number_to integer);
    """)
    con.execute(
        "insert into external_result_reports values (?,?,?,?)", ("r1", "2026-09-28T09:00:00+09:00", "u", "20260927")
    )
    con.execute("insert into external_result_machines values (?,?,?,?,?,?)", ("r1", 1, "JUG", "全台", "x", "20260927"))
    con.commit()
    con.close()
    obs = tmp_path / "field_obs.jsonl"
    _write_jsonl(
        obs,
        [
            {
                "hall": "H",
                "business_date": "20260927",
                "machine_number": 1,
                "text": "見た",
                "registered_at": "2026-09-28T10:00:00+09:00",
            },
            {
                "hall": "H",
                "business_date": "20260927",
                "machine_number": 2,
                "text": "後日",
                "registered_at": "2026-09-29T10:00:00+09:00",
            },
        ],
    )
    got = event_days.build_history(
        "H",
        "20261007",
        pledge_args=["末尾:7:?"],
        asof="20260928",
        event_ledger=str(events),
        series_ledger=str(tmp_path / "missing.jsonl"),
        announce_dir=str(announces),
        links_path=str(links),
        analysis_db=str(analysis),
        field_obs_path=str(obs),
    )
    assert [x["business_date"] for x in got["histories"]] == ["20260927"]
    hist = got["histories"][0]
    assert hist["result"]["reports"] == []
    assert hist["field_obs"] == []
    assert hist["machines"][0]["score"]["ratio"] == 1.5
    assert hist["machines"][1]["score"]["value"] == 666.6666666666666


def _frame_labels():
    """喰種3台（10-12）とJUG1台。12番は 20261001 に別機種へ入替。"""
    rows = []
    for d in ["20260910", "20260920", "20261001"]:
        rows.append(
            {
                "date": d,
                "machine_number": 1,
                "machine_name": "JUG",
                "games_normalized": 5000,
                "diff_coins_normalized": -300,
                "rb_count": 20,
                "rb_rate": 0.004,
                "jug_flag": 1,
                "hana_flag": 0,
                "oki_flag": 0,
                "bt_flag": 0,
            }
        )
        for n, diff in ((10, 800), (11, -500), (12, 1200)):
            name = "NEW" if (n == 12 and d == "20261001") else "喰種"
            rows.append(
                {
                    "date": d,
                    "machine_number": n,
                    "machine_name": name,
                    "games_normalized": 4000,
                    "diff_coins_normalized": diff,
                    "rb_count": 0,
                    "rb_rate": 0,
                    "jug_flag": 0,
                    "hana_flag": 0,
                    "oki_flag": 0,
                    "bt_flag": 0,
                }
            )
    frame = pd.DataFrame(rows)
    frame["dt"] = pd.to_datetime(frame["date"])
    return frame


def test_history_label_granularity_repeats_and_name_series(monkeypatch, tmp_path):
    monkeypatch.setattr(event_days, "load_frame", lambda hall: _frame_labels().copy())
    events = tmp_path / "EVENT_DAYS.jsonl"
    _write_jsonl(
        events,
        [
            {"event_id": "e0910", "hall": "H", "date": "20260910", "event_name": "取材A"},
            {"event_id": "e0920", "hall": "H", "date": "20260920", "event_name": "取材A"},
            {"event_id": "e1010", "hall": "H", "date": "20261010", "event_name": "取材A"},
        ],
    )
    series = tmp_path / "EVENT_SERIES.jsonl"
    _write_jsonl(
        series,
        [
            {
                "series_id": "H__name__A",
                "axis": "name",
                "hall": "H",
                "decision": "same",
                "event_ids": ["e0910", "e0920", "e1010"],
            }
        ],
    )
    links = tmp_path / "EVENT_RESULT_LINKS.jsonl"
    _write_jsonl(
        links,
        [
            {"hall": "H", "business_date": d, "status": "linked", "report_ids": ["r" + d]}
            for d in ("20260910", "20260920")
        ],
    )
    analysis = tmp_path / "analysis.db"
    con = sqlite3.connect(analysis)
    con.executescript("""
      create table external_result_reports(report_id text, posted_at text, tweet_url text, business_date text);
      create table external_result_machines(report_id text, machine_number integer, actual_name text, granularity text, granularity_source text, business_date text);
      create table external_result_models(report_id text, seq integer, granularity text, model_name text, n_target integer, n_total integer, number_from integer, number_to integer);
    """)
    for d in ("20260910", "20260920"):
        con.execute(
            "insert into external_result_reports values (?,?,?,?)",
            ("r" + d, d[:4] + "-" + d[4:6] + "-" + d[6:] + "T23:00:00+09:00", "u", d),
        )
        # 機種単位: JUG は全台（台が特定できる）、喰種は3台並び（どの台か分からない）
        con.execute(
            "insert into external_result_models values (?,?,?,?,?,?,?,?)",
            ("r" + d, 0, "全台", "JUG", None, None, None, None),
        )
        con.execute(
            "insert into external_result_models values (?,?,?,?,?,?,?,?)",
            ("r" + d, 1, "3台並び", "喰種", None, None, None, None),
        )
        # 台単位: 喰種の11番だけ画像で特定されている
        con.execute(
            "insert into external_result_machines values (?,?,?,?,?,?)", ("r" + d, 11, "喰種", "3台並び", "x", d)
        )
    con.commit()
    con.close()

    got = event_days.build_history(
        "H",
        "20261010",
        asof="20261010",
        event_ledger=str(events),
        series_ledger=str(series),
        announce_dir=str(tmp_path / "no_announce"),
        links_path=str(links),
        analysis_db=str(analysis),
        field_obs_path=str(tmp_path / "none.jsonl"),
    )
    assert [h["business_date"] for h in got["histories"]] == ["20260920", "20260910"]
    rows = {m["machine_number"]: m for m in got["histories"][0]["machines"]}
    assert rows[1]["classification"] == "ラベルあり・差枚マイナス（不発台）"  # 全台ラベル × 差枚マイナス
    assert rows[10]["classification"] == "粒度不一致"  # 機種単位の並びだけ
    assert rows[12]["classification"] == "粒度不一致"
    assert rows[11]["classification"] == "ラベルあり・差枚マイナス（不発台）"  # 台単位で特定済み
    assert rows[12]["machine_change"] is True and rows[12]["current_machine_name"] == "NEW"
    assert got["histories"][0]["summary"]["labeled_count"] == 2
    # 繰り返しは「何回の開催で出たか」。2回中2回を超えない。粒度不一致の台は数えない。
    numbers = {x["value"]: x for x in got["repeated"]["machine_number"]}
    assert numbers["11"]["count"] == 2 and numbers["11"]["of"] == 2
    assert "10" not in numbers
    names = {x["value"]: x["count"] for x in got["repeated"]["machine_name"]}
    assert names == {"JUG": 2, "喰種": 2}
