import json
import os
import subprocess

from scraper.realtime import run
from scraper.realtime.rank import build_ranking, format_final, format_hall_report
from scraper.realtime.schema import SnapshotRow

HALL = "ヒロキ西口店"


def _machine(unit, name, bb, rb):
    return {
        "machine_number": str(unit),
        "machine_name": name,
        "machine_name_normalized": name,
        "bb_count": bb,
        "rb_count": rb,
    }


def test_without_removes_flag_and_value_pairs():
    command = ["py", "c.py", "--rb-quick-min-games", "1000", "--snapshot-hall", "ホール", "--mode", "quick"]
    assert run._without(command, "--rb-quick-min-games", "--snapshot-hall") == ["py", "c.py", "--mode", "quick"]


def test_top_up_fetches_hit_units_without_detail_and_keeps_first_pass_details(tmp_path, monkeypatch):
    path = tmp_path / "latest_quick.json"
    first = {
        "observed_at": "2026-10-07T15:00:00+09:00",
        "complete": True,
        "machines": [
            _machine(1, "マイジャグラーV", 3, 2),  # 当たりあり・詳細なし -> 追加取得
            _machine(2, "マイジャグラーV", 0, 0),  # 当たりなし -> 取らない
            _machine(3, "マイジャグラーV", 5, 5),  # 1回目で取得済み -> 保持
        ],
        "details": {"3": {"games": 3000, "bb_count": 5, "rb_count": 5}},
    }
    path.write_text(json.dumps(first), encoding="utf-8")
    old = path.stat().st_mtime_ns
    os.utime(path, ns=(old, old - 5_000_000_000))
    seen = {}

    def fake_run(command):
        seen["command"] = command
        second = dict(first, details={"1": {"games": 1500, "bb_count": 3, "rb_count": 2}})
        path.write_text(json.dumps(second), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(run, "_run_command", fake_run)
    base = ["py", "collector.py", "--rb-quick-min-games", "1000", "--snapshot-hall", HALL]
    process = run._top_up(path, HALL, base, {}, {"マイジャグラーV": True}, subprocess.CompletedProcess(base, 0))
    assert process.returncode == 0
    assert seen["command"][-2:] == ["--units", "1"]  # 当たりのある未取得台だけ
    assert "--rb-quick-min-games" not in seen["command"]  # 二重取得を避ける
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert set(merged["details"]) == {"1", "3"}  # 1回目の詳細(3)が消えない
    assert merged["detail_count"] == 2


def _row(unit, games, rb):
    return SnapshotRow(
        hall=HALL,
        observed_at="2026-10-07T15:00:00+09:00",
        source_updated_at=None,
        unit=unit,
        model="マイジャグラーV",
        model_raw="x",
        games=games,
        bb=10,
        rb=rb,
        diff=None,
        source="dmm",
    )


def test_hall_report_and_final_ranking_are_ordered_by_probability():
    rows = [_row(1, 3000, 8), _row(2, 3000, 20), _row(3, 3000, 14)]
    lines = [line for line in format_hall_report(HALL, rows, top=2).splitlines() if line.startswith("  ")]
    assert len(lines) == 2 and lines[0].strip().startswith("2 ")  # RBが多い台が先頭
    final = format_final(build_ranking(rows, top=3))
    assert final.index("| 2 |") < final.index("| 3 |") < final.index("| 1 |")


def test_csv_only_machines_count_as_rb_judgeable_in_quick_selection():
    from scraper.realtime.quick_filter import ROOT, load_master_flags_any

    flags = load_master_flags_any(ROOT / "db")
    assert flags.get("CCエンジェル") and flags.get("ガルフィー")  # ホールDBに無いがCSVに登録済み
    assert not flags.get("ミルキィホームズR 大収穫祭")  # AT機は判別可能に含めない
