import csv
import sqlite3
from pathlib import Path

import pytest

from database import sync_new_machine_master as sync


PAGE = """<html><head><title>新台A（スマスロ）解析攻略</title></head><body>
<h1>新台A</h1>
<p class="h1_mini">スマスロ 新台A</p>
<table>
<tr><th>メーカー</th><td>テストメーカー</td></tr>
<tr><th>導入開始日</th><td>2026年10月5日</td></tr>
<tr><th>タイプ</th><td>ATタイプ、スマスロ</td></tr>
</table>
<table><thead><tr><th>設定</th><th>AT初当り確率</th><th>出玉率</th></tr></thead><tbody>
<tr><td>1</td><td>1/350.0</td><td>97.5%</td></tr>
<tr><td>2</td><td>1/330.0</td><td>98.8%</td></tr>
<tr><td>4</td><td>1/280.0</td><td>105.2%</td></tr>
<tr><td>5</td><td>1/260.0</td><td>108.4%</td></tr>
<tr><td>6</td><td>1/240.0</td><td>112.4%</td></tr>
</tbody></table></body></html>"""


def test_assess_page_rejects_old_or_different_machine():
    url = "https://1geki.jp/slot/new_a/"
    assert sync.assess_page("新台A", "20261006", url, PAGE)[1] == "verified"
    assert sync.assess_page("新台A2", "20261006", url, PAGE)[1] == "official_name_mismatch"
    assert sync.assess_page("新台A", "20260701", url, PAGE)[1] == "release_outside_new_machine_window"
    assert sync.assess_page("新台A", "20261006", "https://example.com/slot/new_a/", PAGE)[1] == "invalid_source_url"


def test_known_rows_keeps_old_and_smart_slot_editions_separate():
    header = ["machine_name", "canonical_machine_name"]
    rows = [["炎炎ノ消防隊", "炎炎ノ消防隊"], ["スマスロ炎炎ノ消防隊", "スマスロ炎炎ノ消防隊"]]
    known = sync.known_rows(header, rows)
    assert known[sync.match_key("炎炎ノ消防隊")]["machine_name"] == "炎炎ノ消防隊"
    assert known[sync.match_key("スマスロ炎炎ノ消防隊")]["machine_name"] == "スマスロ炎炎ノ消防隊"


@pytest.mark.parametrize("with_columns", [True, False])
def test_run_adds_once_and_syncs_category(tmp_path: Path, with_columns: bool):
    header, _ = sync.research.read_csv()
    master = tmp_path / "machine_master.csv"
    with master.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerow(header)
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db = db_dir / "テスト店.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE machine_detailed_results (machine_name TEXT, date TEXT)")
        if with_columns:
            conn.execute(
                "CREATE TABLE machine_master (machine_name_normalized TEXT PRIMARY KEY, game_type TEXT, spec_category TEXT, bonus_judgeable INTEGER, spec_source TEXT)"
            )
        else:
            conn.execute("CREATE TABLE machine_master (machine_name_normalized TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO machine_detailed_results VALUES ('新台A', '20261006')")
        conn.execute("INSERT INTO machine_master (machine_name_normalized) VALUES ('新台A')")

    url = "https://1geki.jp/slot/new_a/"
    search = lambda _: f'<a href="{url}">新台A</a>'
    page = lambda _: PAGE
    kwargs = dict(
        halls=["テスト店"],
        master_csv=master,
        db_dir=db_dir,
        review_path=tmp_path / "review.json",
        fetch_search=search,
        fetch_page=page,
    )
    dry = sync.run(apply=False, **kwargs)
    assert dry["outcomes"][0]["status"] == "ready"
    assert not (tmp_path / "review.json").exists()
    with master.open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
    first = sync.run(apply=True, **kwargs)
    assert first["added"] == ["新台A"]
    assert first["category_rows_synced"] == 1
    with master.open(encoding="utf-8-sig", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["rtp_setting3"] == ""
    assert row["rtp_setting4"] == "105.2"
    assert row["at_initial_setting4"] == "1/280.0"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT game_type,spec_category,bonus_judgeable,spec_source FROM machine_master"
        ).fetchone() == ("AT", "AT", 0, "1geki")
    second = sync.run(apply=True, **kwargs)
    assert second["new_names"] == 0
    assert second["added"] == []


def test_run_preserves_external_csv_change(tmp_path: Path):
    header, _ = sync.research.read_csv()
    master = tmp_path / "machine_master.csv"
    with master.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerow(header)
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    with sqlite3.connect(db_dir / "テスト店.db") as conn:
        conn.execute("CREATE TABLE machine_detailed_results (machine_name TEXT, date TEXT)")
        conn.execute("CREATE TABLE machine_master (machine_name_normalized TEXT PRIMARY KEY, spec_category TEXT)")
        conn.execute("INSERT INTO machine_detailed_results VALUES ('新台A', '20261006')")
        conn.execute("INSERT INTO machine_master VALUES ('新台A', NULL)")

    url = "https://1geki.jp/slot/new_a/"

    def search(_):
        with master.open("a", encoding="utf-8") as handle:
            handle.write("external edit\n")
        return f'<a href="{url}">新台A</a>'

    with pytest.raises(RuntimeError, match="処理中に変更"):
        sync.run(
            halls=["テスト店"],
            apply=True,
            master_csv=master,
            db_dir=db_dir,
            review_path=tmp_path / "review.json",
            fetch_search=search,
            fetch_page=lambda _: PAGE,
        )
    assert master.read_text(encoding="utf-8-sig").endswith("external edit\n")
