import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scraper.realtime.adapters import daidata, dmm, site777
from scraper.realtime.quick_filter import rb_eligible, select_units
from scraper.realtime.run import Result, first_line, format_table, main
from scraper.realtime.schema import SnapshotRow
from scraper.realtime.store import write_snapshot

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=JST)


def row(unit=1, **kwargs):
    return SnapshotRow(
        hall="ヒロキ東口店",
        observed_at=NOW.isoformat(),
        source_updated_at=None,
        unit=unit,
        model="新ハナビ",
        model_raw="新ハナビ",
        **kwargs,
    )


def test_schema_null_and_diff_kind():
    actual = row().to_dict()
    assert actual["games"] is None and actual["diff_kind"] is None
    assert actual["is_new_machine"] is None and isinstance(actual["unit"], int)
    assert actual["observed_at"].endswith("+09:00")
    with pytest.raises(ValueError):
        row(diff=100)


def test_dmm_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.realtime.adapters.dmm.model_name", lambda _: None)
    path = tmp_path / "latest_full.json"
    path.write_text(
        json.dumps(
            {
                "observed_at": NOW.isoformat(),
                "complete": True,
                "machines": [
                    {"machine_number": "123", "machine_name": "raw", "bb_count": 0, "machine_name_normalized": "正式"}
                ],
                "details": {
                    "123": {"games": 1000, "source_updated_at": "2026.10.07 11:50", "latest_diff_estimated": -40}
                },
            }
        ),
        encoding="utf-8",
    )
    actual = dmm.adapt(path, "ヒロキ西口店")
    assert (actual[0].unit, actual[0].model, actual[0].model_raw) == (123, "正式", "raw")
    assert actual[0].bb == 0 and actual[0].rb is None
    assert actual[0].diff == -40 and actual[0].diff_kind == "estimated"


def test_site777_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.realtime.adapters.site777.model_name", lambda _: "新ハナビ")
    full = {
        "complete": True,
        "completedAt": "2026-10-07T03:00:00Z",
        "models": {
            "abc": {
                "name": "raw",
                "jackpot": {
                    "updateTime": "2026/10/07 11:50",
                    "pages": [
                        {
                            "rows": [
                                ["台番", "累計ゲーム", "BB回数", "RB回数", "ART回数"],
                                ["1", "1999", "2", "1", "--"],
                                ["2", "2000", "3", "2", "4"],
                            ]
                        }
                    ],
                },
            }
        },
    }
    (tmp_path / "site777_full_data.json").write_text(json.dumps(full), encoding="utf-8-sig")
    (tmp_path / "site777_graph_summary_filtered.json").write_text(
        json.dumps({"ok": True, "complete": False, "failures": 1}), encoding="utf-8-sig"
    )
    (tmp_path / "site777_graph_metrics_filtered.json").write_text(
        json.dumps({"machines": [{"key": "abc:2", "status": "ok", "estimatedLatestDiff": 45}]}), encoding="utf-8-sig"
    )
    actual = site777.adapt(tmp_path)
    assert len(actual) == 2 and actual[0].diff is None
    assert "diff_unreadable" in actual[0].quality_flags
    assert "incomplete" in actual[1].quality_flags
    assert actual[1].diff == 45 and actual[1].diff_kind == "estimated"
    assert actual[1].at_first_hits == 4


def test_daidata_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.realtime.adapters.daidata.model_name", lambda _: "新ハナビ")
    path = tmp_path / "rows.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["Price", "Unit", "Machine", "ObservedAt", "CumulativeStart", "BBCount", "RBCount", "MaxPayout"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Price": "21.3",
                "Unit": "100",
                "Machine": "raw",
                "ObservedAt": NOW.isoformat(),
                "CumulativeStart": "1234",
                "BBCount": "0",
                "RBCount": "--",
                "MaxPayout": "500",
            }
        )
        writer.writerow({"Price": "5", "Unit": "101", "ObservedAt": NOW.isoformat()})
    actual = daidata.adapt(path)
    assert len(actual) == 1 and actual[0].games == 1234
    assert actual[0].bb == 0 and actual[0].rb is None and actual[0].diff is None


def test_store_sequence(tmp_path):
    first = write_snapshot([row()], tmp_path, "ヒロキ東口店", "full", NOW)
    second = write_snapshot([row()], tmp_path, "ヒロキ東口店", "full", NOW)
    assert first != second and second.stem.endswith("_1")
    assert json.loads(first.read_text(encoding="utf-8").strip())["unit"] == 1


def test_quick_filter_x_and_changes():
    audit = {("ヒロキ東口店", "新ハナビ"): "A", ("ヒロキ東口店", "モンキーターンV"): "X"}
    assert rb_eligible("ヒロキ東口店", "新ハナビ", audit, {})
    assert not rb_eligible("ヒロキ東口店", "モンキーターンV", audit, {"モンキーターンV": True})
    current = [row(1, games=999, bb=2), row(2, games=1000), row(3, games=500)]
    previous = [row(1, games=999, bb=1), row(3, games=500)]
    assert select_units(current, previous, audit, {}, 1000) == [1, 2]


def test_dry_run_and_table(capsys):
    assert main(["--halls", "hiroki_west,rakuen", "--mode", "quick", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "nishiguchi" in out and "RB eligible" in out and "site777" in out
    table = format_table([Result("h", "dmm", 2, 1, 1.2, "now", "INCOMPLETE")])
    assert "h | dmm | 2 | 1 | 1.2 | now | INCOMPLETE" in table


def test_exception_first_line():
    assert first_line(RuntimeError("first\nsecret header")) == "first"
