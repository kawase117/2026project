"""マスター未登録の新機種が旧スペックに部分一致で紐づくとき、警告が出る(2026-10-25)。"""

import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from database import sync_new_machine_master as sync

URL = "https://1geki.jp/slot/new_a/"
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


def _setup(tmp_path: Path, machine_name: str):
    header, _ = sync.research.read_csv()
    master = tmp_path / "machine_master.csv"
    with master.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerow(header)
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    with closing(sqlite3.connect(db_dir / "テスト店.db")) as conn:
        conn.execute("CREATE TABLE machine_detailed_results (machine_name TEXT, date TEXT)")
        conn.execute("CREATE TABLE machine_master (machine_name_normalized TEXT PRIMARY KEY, spec_category TEXT)")
        conn.execute("INSERT INTO machine_detailed_results VALUES (?, '20261006')", (machine_name,))
        conn.execute("INSERT INTO machine_master VALUES (?, NULL)", (machine_name,))
        conn.commit()
    return dict(master_csv=master, db_dir=db_dir, review_path=tmp_path / "review.json", halls=["テスト店"])


def test_unregistered_name_matching_old_spec_is_warned_and_status_is_unchanged(tmp_path):
    kwargs = _setup(tmp_path, "アイムジャグラーEX アニバーサリー")
    result = sync.run(apply=True, fetch_search=lambda _: "", fetch_page=lambda _: "", **kwargs)
    warnings = result["partial_match_warnings"]
    assert len(warnings) == 1
    assert warnings[0]["machine_name"] == "アイムジャグラーEX アニバーサリー"
    assert warnings[0]["matched_family"]
    assert warnings[0]["first_seen"] == "20261006"
    assert [outcome["status"] for outcome in result["outcomes"]] == ["needs_review"]
    saved = json.loads(kwargs["review_path"].read_text(encoding="utf-8"))
    assert saved["partial_match_warnings"] == warnings


def test_name_without_partial_match_has_no_warning(tmp_path):
    kwargs = _setup(tmp_path, "新台A")
    result = sync.run(
        apply=False,
        fetch_search=lambda _: f'<a href="{URL}">新台A</a>',
        fetch_page=lambda _: PAGE,
        **kwargs,
    )
    assert result["partial_match_warnings"] == []
    assert result["outcomes"][0]["status"] == "ready"
