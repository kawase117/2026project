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


def _est_row(model, games, bb, rb, source="dmm", hall="ヒロキ東口店"):
    return SnapshotRow(
        hall=hall,
        observed_at="2026-10-07T15:00:00+09:00",
        source_updated_at=None,
        unit=1,
        model=model,
        model_raw=model,
        games=games,
        bb=bb,
        rb=rb,
        diff=None,
        source=source,
    )


def test_bb_is_used_together_with_rb_for_machines_with_both_specs():
    from scraper.realtime.estimate import estimate

    low_bb = estimate(_est_row("アレックス ブライト", 3000, 6, 8))
    high_bb = estimate(_est_row("アレックス ブライト", 3000, 14, 8))
    assert "BBとRBを別々" in " ".join(low_bb["notes"])
    assert high_bb["p_high"] > low_bb["p_high"]  # BBが多いほど高設定寄り(RBは同じ)


def test_fujiko_bt_bb_column_is_total_only_for_site777():
    from scraper.realtime.estimate import estimate

    site = estimate(_est_row("不二子BT", 3000, 20, 8, source="site777", hall="楽園蒲田店"))
    assert "BB−RB" in " ".join(site["notes"])
    dmm = estimate(_est_row("不二子BT", 3000, 20, 8, source="dmm"))
    assert "RBのみ" in " ".join(dmm["notes"])


def test_combined_only_bt_machine_is_estimated_but_a_plus_at_is_not():
    from scraper.realtime.estimate import estimate

    isekai = estimate(_est_row("A‐SLOT+ 異世界かるてっと", 3000, 20, 10))
    assert isekai["p_high"] is not None and "合算" in " ".join(isekai["notes"])
    assert estimate(_est_row("ツインエンジェルPARTY", 3000, 20, 10))["p_high"] is None


def test_top_up_keeps_first_pass_details_and_retries_failed_unit_once(tmp_path, monkeypatch):
    path = tmp_path / "latest_quick.json"
    first = {
        "observed_at": "2026-10-07T15:00:00+09:00",
        "complete": True,
        "machines": [
            _machine(1, "マイジャグラーV", 3, 2),
            _machine(2, "マイジャグラーV", 4, 4),
            _machine(3, "マイジャグラーV", 5, 5),
        ],
        "details": {"3": {"games": 3000, "bb_count": 5, "rb_count": 5}},
        "failures": [],
    }
    path.write_text(json.dumps(first), encoding="utf-8")
    old = path.stat().st_mtime_ns
    os.utime(path, ns=(old, old - 10_000_000_000))
    calls = []

    def fake_run(command):
        units = command[command.index("--units") + 1 :]
        calls.append(units)
        if len(calls) == 1:  # 追加取得: 2は45秒タイムアウトで失敗(非ゼロ終了)、1は成功
            doc = dict(
                first,
                details={"1": {"games": 1500}},
                failures=[{"machine_number": "2", "error": "Timeout"}],
                complete=False,
            )
            code = 1
        else:  # 再試行: 2が成功
            doc = dict(first, details={"2": {"games": 2000}}, failures=[])
            code = 0
        path.write_text(json.dumps(doc), encoding="utf-8")
        st = path.stat().st_mtime_ns
        os.utime(path, ns=(st, st + len(calls) * 1_000_000_000))
        return subprocess.CompletedProcess(command, code)

    monkeypatch.setattr(run, "_run_command", fake_run)
    base = ["py", "collector.py", "--rb-quick-min-games", "1000", "--snapshot-hall", HALL]
    run._top_up(path, HALL, base, {}, {"マイジャグラーV": True}, subprocess.CompletedProcess(base, 0))
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert calls == [["1", "2"], ["2"]]  # 失敗した台だけを1回再試行
    assert set(merged["details"]) == {"1", "2", "3"}  # 失敗があっても1回目の詳細(3)は消えない
    assert merged["failures"] == [] and merged["complete"] is True
