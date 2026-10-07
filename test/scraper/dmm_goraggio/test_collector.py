import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from scraper.dmm_goraggio.collector import (
    CollectionError,
    check_hall_name,
    load_db_names,
    load_prior,
    normalize_machine_name,
    parse_args,
    save_snapshot,
)


def test_full_cache_is_preferred_even_when_quick_is_newer() -> None:
    with tempfile.TemporaryDirectory() as directory:
        temp_path = Path(directory)
        full = temp_path / "latest_full.json"
        quick = temp_path / "latest_quick.json"
        full.write_text(json.dumps({"mode": "full", "details": {"1001": {}}}), encoding="utf-8")
        quick.write_text(json.dumps({"mode": "quick", "details": {}}), encoding="utf-8")
        assert load_prior(temp_path, "full")["mode"] == "full"


def test_hall_settings_and_overrides(tmp_path: Path) -> None:
    default = parse_args([])
    assert default.hall == "max"
    assert default.dmm_url.endswith("/265/jackpot")
    assert default.output_dir.name == "output"

    east = parse_args(["--hall", "higashiguchi"])
    assert east.dmm_url.endswith("/255/jackpot")
    assert east.output_dir.name == "output_higashiguchi"

    from scraper.dmm_goraggio.collector import HALLS

    assert HALLS["higashiguchi"]["db_hall"] == "ヒロキ東口店"
    override = parse_args(
        ["--hall", "higashiguchi", "--dmm-url", "https://example.test", "--output-dir", str(tmp_path)]
    )
    assert override.dmm_url == "https://example.test"
    assert override.output_dir == tmp_path


def test_hall_name_guard_rejects_other_hall() -> None:
    max_html = "<title>ヒロキMAX蒲田店 - 台データオンライン</title>"
    east_html = "<title>ヒロキ東口店 - 台データオンライン</title>"
    check_hall_name(max_html, "ヒロキMAX蒲田店")
    check_hall_name(east_html, "ヒロキ東口店")
    with pytest.raises(CollectionError, match="取得先ホール名が一致しません"):
        check_hall_name(max_html, "ヒロキ東口店")
    with pytest.raises(CollectionError, match="取得先ホール名が一致しません"):
        check_hall_name(east_html, "ヒロキMAX蒲田店")


def test_machine_name_from_latest_db_date_then_alias(tmp_path: Path) -> None:
    db_path = tmp_path / "hall.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT)"
        )
        connection.executemany(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?)",
            [
                ("20261001", 1001, "旧機種"),
                ("20261006", 1001, "マイジャグラーV"),
                ("20261005", 1002, "スマスロ北斗の拳"),
            ],
        )
    by_number, names = load_db_names(db_path)
    assert (
        normalize_machine_name({"machine_number": "1001", "machine_name": "別表記"}, by_number, names)
        == "マイジャグラーV"
    )
    assert (
        normalize_machine_name({"machine_number": "9999", "machine_name": "ﾏｲｼﾞｬｸﾞﾗｰV"}, by_number, names)
        == "マイジャグラーV"
    )
    assert normalize_machine_name({"machine_number": "bad", "machine_name": "不明機種"}, by_number, names) is None


def test_missing_db_continues_with_null(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    by_number, names = load_db_names(tmp_path / "missing.db")
    assert "警告" in capsys.readouterr().err
    assert normalize_machine_name({"machine_number": "1001", "machine_name": "ﾏｲｼﾞｬｸﾞﾗｰV"}, by_number, names) is None


def test_snapshot_path_and_no_overwrite(tmp_path: Path) -> None:
    result = {"mode": "quick", "observed_at": "2026-10-07T12:34:56+09:00"}
    payload = json.dumps(result)
    path = save_snapshot(result, tmp_path, "higashiguchi", payload)
    assert path == tmp_path / "snapshots" / "higashiguchi_quick_20261007_123456.json"
    assert path.read_text(encoding="utf-8") == payload
    with pytest.raises(FileExistsError):
        save_snapshot(result, tmp_path, "higashiguchi", "changed")
    assert path.read_text(encoding="utf-8") == payload
