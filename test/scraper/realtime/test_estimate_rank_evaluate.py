"""ネットワークを使わない推定・順位・評価テスト。"""

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backtest.bonus_specs import load_specs, normalize
from scraper.realtime.estimate import at_scores, estimate, mark_new_machines
from scraper.realtime.evaluate import evaluate_rows, main as evaluate_main
from scraper.realtime.rank import build_ranking, read_snapshots, write_ranking
from scraper.realtime.schema import SnapshotRow

NOW = datetime(2026, 10, 7, 12, tzinfo=ZoneInfo("Asia/Tokyo"))


def row(model="新ハナビ", unit=1, hall="ヒロキ東口店", **kwargs):
    return SnapshotRow(
        hall=hall,
        observed_at=NOW.isoformat(),
        source_updated_at=None,
        unit=unit,
        model=model,
        model_raw=model,
        games=3000,
        rb=10,
        **kwargs,
    )


def test_rb_monotone_and_setting_sets():
    specs = load_specs()
    for name, expected in [
        (name, {1, 2, 5, 6})
        for name in (
            "新ハナビ",
            "バーサスリヴァイズ",
            "スマスロ ハナビ",
            "サンダーV",
            "アレックス ブライト",
            "SHAKE",
            "クランキー",
        )
    ] + [("不二子BT", {1, 2, 4, 5, 6})]:
        actual = estimate(row(name), specs=specs, audit={})
        assert set(actual["setting_probabilities"]) == expected
    low = estimate(row("新ハナビ", unit=1), specs=specs, audit={})
    high_row = row("新ハナビ", unit=2)
    high_row.rb = 20
    high = estimate(high_row, specs=specs, audit={})
    assert high["p_high"] > low["p_high"]
    small = row("新ハナビ", unit=3)
    small.games, small.rb = 300, 1
    small_result = estimate(small, specs=specs, audit={})
    assert abs(small_result["p_high"] - 0.5) < abs(low["p_high"] - 0.5)
    assert "1000G未満" in " ".join(small_result["notes"])
    site = row("新ハナビ")
    site.source = "site777"
    assert estimate(site, specs=specs, audit={})["p_high"] == pytest.approx(low["p_high"])


def test_verdict_x_at_and_missing():
    specs = load_specs()
    monkey = row("モンキーターンV")
    assert estimate(monkey, specs=specs, audit={(monkey.hall, monkey.model): "X"})["kind"] == "none"
    at = row("スマスロ北斗の拳", diff=500, diff_kind="measured")
    result = estimate(at, specs=specs, audit={}, at_context=at_scores([at]))
    assert result["kind"] == "at_gratio_diff" and result["p_high"] is None
    missing = row()
    missing.rb = None
    assert estimate(missing, specs=specs, audit={})["kind"] == "none"


def test_ranking_separate_and_prior(tmp_path):
    specs = load_specs()
    a = row(unit=1)
    b = row(unit=2, hall="ヒロキ西口店")
    b.rb = 18
    c = row("スマスロ北斗の拳", unit=3, diff=200, diff_kind="measured")
    d = row(unit=4)
    d.is_new_machine = True
    result = build_ranking([a, b, c, d], db_dir=tmp_path, specs_by_hall={a.hall: specs, b.hall: specs}, audit={})
    assert result["ranked"][0]["unit"] == 2
    assert len(result["at_scores"]) == 1
    assert len(result["new_machines"]) == 1
    priors = {a.hall: {1: 10, 2: 10, 5: 1, 6: 1}, b.hall: {1: 1, 2: 1, 5: 10, 6: 10}}
    changed = build_ranking(
        [a, b], db_dir=tmp_path, specs_by_hall={a.hall: specs, b.hall: specs}, audit={}, hall_prior=priors
    )
    assert changed["ranked"][0]["p_high"] > result["ranked"][0]["p_high"]
    first = write_ranking(result, tmp_path, NOW)
    second = write_ranking(result, tmp_path, NOW)
    assert first != second and json.loads(first.read_text(encoding="utf-8")) == result


def test_new_machine_first_seen_boundary(tmp_path):
    hall = "ヒロキ東口店"
    with sqlite3.connect(tmp_path / f"{hall}.db") as con:
        con.execute("CREATE TABLE machine_detailed_results (date TEXT, machine_name TEXT)")
        con.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?)", [("20261001", "新ハナビ"), ("20260930", "SHAKE")]
        )
    new, old, unknown = row(), row("SHAKE", 2), row("不明機", 3)
    mark_new_machines([new, old, unknown], tmp_path)
    assert new.is_new_machine is True
    assert old.is_new_machine is False
    assert unknown.is_new_machine is None


def test_evaluation_synthetic_and_missing_db(tmp_path, capsys, monkeypatch):
    specs = load_specs()
    rows = []
    final = []
    for i in range(20):
        item = row(unit=i + 1)
        item.rb = i + 1
        rows.append(item)
        final.append({"unit": i + 1, "model": "新ハナビ", "games": 6000, "rb": (i + 1) * 2})
    result = evaluate_rows(rows, final, hall="ヒロキ東口店", db_dir=tmp_path, specs=specs, audit={})
    cell = result["12:00"]
    assert cell["n"] == 20 and cell["spearman"] > 0.99
    assert cell["top_mean"] > cell["all_mean"]
    assert len(cell["calibration"]) == 10
    assert sum(q["n"] for q in cell["calibration"]) == 20
    small = evaluate_rows(rows[:2], final, hall="ヒロキ東口店", db_dir=tmp_path, specs=specs, audit={})
    assert small["12:00"]["status"] == "判定不能"
    monkeypatch.setattr("scraper.realtime.evaluate.ROOT", tmp_path)
    assert evaluate_main(["--date", "20261007", "--hall", "ヒロキ西口店"]) == 0
    assert "結果DBなし" in capsys.readouterr().out
