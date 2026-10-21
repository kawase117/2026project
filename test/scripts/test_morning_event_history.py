"""朝の予測に渡すイベント系列の機械集計。"""

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scraper" / "twitter_monitor"))

import run_morning_docs as morning  # noqa: E402
from hall_aliases import plausible_halls  # noqa: E402


def _jsonl(path, rows):
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")


def _fixture(tmp_path, monkeypatch, *, today_event=True, past=True, active=True):
    hall = morning.HALLS["rakuen"][0]
    db_dir = tmp_path / "db"
    db_dir.mkdir(parents=True)
    conn = sqlite3.connect(db_dir / (hall + ".db"))
    conn.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT, "
        "games_normalized INTEGER, bb_count INTEGER, rb_count INTEGER, diff_coins_normalized INTEGER)"
    )
    rows = []

    def add(day, name, diffs, games=4000):
        rows.extend((day, number, name, games, 1, 1, diff) for number, diff in enumerate(diffs, len(rows) + 1))

    for name in ("偶数", "奇数", "1台"):
        add("20260901", name, [0])  # DB最古日に存在する機種は新台扱いしない
    add("20260910", "偶数", [100, 300], 8000)
    add("20260910", "奇数", [-100, 200, 300])
    add("20260910", "1台", [1000])
    add("20260910", "新台", [3000, 3000], 9000)
    add("20260911", "偶数", [0, 0])
    add("20260912", "偶数", [-100, 100], 8000)
    add("20260912", "1台", [-200])
    add("20260912", "新台", [4000, 4000], 9000)
    add("20260920", "当日", [9999])
    conn.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    ids = [f"{day}_{hall}_取材" for day in ("20260910", "20260912", "20260920")]
    events = [
        {"event_id": event_id, "hall": hall, "date": event_id[:8], "event_name": "取材"}
        for event_id in ids
        if today_event or event_id[:8] != "20260920"
    ]
    days_path = tmp_path / "EVENT_DAYS.jsonl"
    series_path = tmp_path / "EVENT_SERIES.jsonl"
    _jsonl(days_path, events)
    _jsonl(
        series_path,
        (
            [
                {
                    "row_id": "old",
                    "series_id": "s",
                    "axis": "name",
                    "hall": hall,
                    "label": "取材",
                    "event_ids": ids if past else ids[-1:],
                    "decision": "same",
                    "supersedes": None,
                }
            ]
            if active
            else []
        ),
    )
    monkeypatch.setattr(morning, "EVENT_DAYS_PATH", days_path)
    monkeypatch.setattr(morning, "EVENT_SERIES_PATH", series_path)
    monkeypatch.setattr(morning, "DB_DIR", db_dir)
    return ids, series_path


def test_history_summary_and_tables(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    result = morning.event_history_block("rakuen", "20260920")
    assert "過去回が少ない(2回)" in result
    assert "2026-09-10: 8台、台平均+975枚、総差枚+7800枚、台勝率87.5%" in result
    assert "2026-09-12: 5台、台平均+1560枚、総差枚+7800枚、台勝率60.0%" in result
    assert "2026-09-20" not in result
    assert "通常日(1日、系列日を除く)" in result
    assert "偶数(n>=2) 2機種日" in result
    assert "奇数(n>=2) 1機種日" in result
    assert "1台 2機種日" in result
    assert "高回転: 2台、台平均+200枚" in result  # 9,000Gの新台は除外
    assert len(result.splitlines()) <= 40


def test_history_no_series_no_past_no_today(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch, today_event=False)
    assert "本日はイベント日台帳に登録なし" in morning.event_history_block("rakuen", "20260920")
    _fixture(tmp_path / "second", monkeypatch, active=False)
    assert "同じ系列なし(前例なし)" in morning.event_history_block("rakuen", "20260920")
    _fixture(tmp_path / "third", monkeypatch, past=False)
    assert "この系列の過去回なし(初開催)" in morning.event_history_block("rakuen", "20260920")


def test_superseded_old_row_is_ignored(tmp_path, monkeypatch):
    ids, path = _fixture(tmp_path, monkeypatch)
    hall = morning.HALLS["rakuen"][0]
    _jsonl(
        path,
        [
            {
                "row_id": "old",
                "series_id": "old",
                "axis": "name",
                "hall": hall,
                "label": "旧",
                "event_ids": ids,
                "decision": "same",
                "supersedes": None,
            },
            {
                "row_id": "new",
                "series_id": "new",
                "axis": "name",
                "hall": hall,
                "label": "新",
                "event_ids": ids[-1:],
                "decision": "same",
                "supersedes": "old",
            },
            {
                "row_id": "pledge",
                "series_id": "pledge",
                "axis": "pledge",
                "hall": hall,
                "label": "公約",
                "event_ids": ids,
                "decision": "same",
                "supersedes": None,
            },
        ],
    )
    result = morning.event_history_block("rakuen", "20260920")
    assert "### 新" in result and "この系列の過去回なし(初開催)" in result
    assert "### 旧" not in result and "### 公約" not in result


def test_other_hall_aliases():
    cases = [
        ("10/20 楽園上永谷\n→スロトレ調査団 三大天", set()),
        ("10/20(火) 楽園蒲田 ハーフテン", {"楽園蒲田店"}),
        ("楽園", {"楽園蒲田店"}),
        ("楽園池袋", set()),
        ("楽園上永谷 と 楽園蒲田", {"楽園蒲田店"}),
    ]
    for text, expected in cases:
        assert plausible_halls(text, date(2026, 10, 20)) == expected


def test_announce_warning(tmp_path, monkeypatch):
    ann = tmp_path / "announce"
    ann.mkdir()
    (ann / "rakuen__20261020__other.json").write_text(
        json.dumps({"raw_text": "楽園上永谷 三大天"}, ensure_ascii=False), encoding="utf-8"
    )
    (ann / "rakuen__20261020__own.json").write_text(
        json.dumps({"raw_text": "楽園蒲田 ハーフテン"}, ensure_ascii=False), encoding="utf-8"
    )
    (ann / "rakuen__20261020__broken.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(morning, "ANNOUNCE_DIR", ann)
    monkeypatch.setattr(morning, "hall_max_dates", lambda: {morning.HALLS["rakuen"][0]: "20261019"})
    result = morning.facts_block("rakuen", "20261020", "20261019")
    lines = {
        name: next(line for line in result.splitlines() if name in line)
        for name in ("other.json", "own.json", "broken.json")
    }
    assert "※本文に別店舗名「楽園上永谷」。このホールの予告ではない可能性が高い。根拠にしない" in lines["other.json"]
    assert "※" not in lines["own.json"] and "※" not in lines["broken.json"]


def test_prediction_prompt_embeds_history_and_continues_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(morning, "facts_block", lambda *args: "事実")
    monkeypatch.setattr(morning, "announce_files", lambda *args: [])
    monkeypatch.setattr(morning, "event_history_block", lambda *args: "系列の機械集計")
    prompt = morning.prediction_prompt("rakuen", "20261020", "20261019", tmp_path / "answer", tmp_path / "out")
    assert prompt.index("## 入力") < prompt.index("系列の機械集計") < prompt.index("## 書式")
    assert "標本が少ないことは必ず書く" in prompt

    def fail(*args):
        raise RuntimeError("test")

    monkeypatch.setattr(morning, "event_history_block", fail)
    prompt = morning.prediction_prompt("rakuen", "20261020", "20261019", tmp_path / "answer", tmp_path / "out")
    assert "過去回の集計に失敗: RuntimeError" in prompt
