"""設定ラベル台帳の CLI と追記ルールを小さな DB で検証する。"""

import json
import sqlite3

import pytest

from backtest import setting_labels as labels


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    ledger = tmp_path / "registry" / "SETTING_LABELS.jsonl"
    db = db_dir / "ヒロキ東口店.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, "
            "machine_name TEXT, games_normalized INTEGER, diff_coins_normalized INTEGER, "
            "rb_count INTEGER, bb_count INTEGER)"
        )
        con.execute(
            "INSERT INTO machine_detailed_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("20261005", 2385, "テスト機種", 3000, -500, 10, 15),
        )
    monkeypatch.setattr(labels, "DB_DIR", db_dir)
    monkeypatch.setattr(labels, "LEDGER", ledger)
    return ledger


def add_args(*extra):
    return [
        "add",
        "--hall",
        "ヒロキ東口",
        "--date",
        "20261006",
        "--machine-number",
        "2385",
        "--setting",
        "低設定",
        "--evidence",
        "self_play",
        "--played",
        *extra,
    ]


def test_dry_run_warns_and_does_not_create_ledger(workspace, capsys):
    assert labels.main(add_args("--dry-run")) == 0
    output = capsys.readouterr().out
    assert "警告:" in output
    assert "machine_name=null" in output
    row = json.loads(output.splitlines()[-1])
    assert row["label_id"] == "20261006_ヒロキ東口店_2385"
    assert row["machine_name"] is None
    assert (row["setting_low"], row["setting_high"]) == (1, 2)
    assert row["setting_text"] == "低設定"
    assert row["played"] is True
    assert not workspace.exists()


def test_append_list_show_and_validate(workspace, capsys):
    assert labels.main(add_args()) == 0
    first = json.loads(workspace.read_text(encoding="utf-8"))
    assert first["supersedes"] is None
    assert first["source"] == "user"
    assert labels.main(["validate"]) == 0
    assert capsys.readouterr().out.endswith("OK\n")
    assert labels.main(["list", "--hall", "ヒロキ東口", "--since", "20261006"]) == 0
    assert "20261006_ヒロキ東口店_2385" in capsys.readouterr().out
    assert labels.main(["show", first["label_id"]]) == 0
    assert "実績未収録" in capsys.readouterr().out


def test_same_day_result_and_correction_are_append_only(workspace, capsys):
    args = [
        "add",
        "--hall",
        "ヒロキ東口",
        "--date",
        "20261005",
        "--machine-number",
        "2385",
        "--setting",
        "4-6",
        "--evidence",
        "hint",
    ]
    assert labels.main(args) == 0
    label_id = "20261005_ヒロキ東口店_2385"
    first_text = workspace.read_text(encoding="utf-8")
    assert json.loads(first_text)["machine_name"] == "テスト機種"
    assert labels.main(args) == 1
    assert workspace.read_text(encoding="utf-8") == first_text
    assert labels.main(args + ["--supersedes", label_id]) == 0
    rows = [json.loads(line) for line in workspace.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["label_id"] == rows[1]["label_id"]
    assert rows[1]["supersedes"] == label_id
    capsys.readouterr()
    assert labels.main(["list"]) == 0
    assert capsys.readouterr().out.count(label_id) == 1
    assert labels.main(["list", "--all"]) == 0
    output = capsys.readouterr().out
    assert output.count(label_id) == 2
    assert "訂正済み" in output
    assert labels.main(["show", label_id]) == 0
    output = capsys.readouterr().out
    assert "games_normalized: 3000" in output
    assert "diff_coins_normalized: -500" in output
    assert "rb_count: 10" in output
    assert "bb_count: 15" in output
    assert labels.main(["validate"]) == 0


@pytest.mark.parametrize("setting", ["0", "7", "6-4", "1～3", "推定5", "4-7"])
def test_invalid_setting_rejected_without_creating_file(workspace, setting):
    args = add_args()
    args[args.index("低設定")] = setting
    assert labels.main(args) == 1
    assert not workspace.exists()


def test_unknown_machine_and_missing_supersedes_rejected(workspace):
    args = add_args()
    args[args.index("2385")] = "9999"
    assert labels.main(args) == 1
    assert labels.main(add_args("--supersedes", "missing")) == 1
    assert not workspace.exists()


def test_empty_list_and_invalid_ledger(workspace, capsys):
    assert labels.main(["list"]) == 0
    assert capsys.readouterr().out == "0件\n"
    workspace.parent.mkdir()
    workspace.write_text('{"bad":1}\n', encoding="utf-8")
    assert labels.main(["validate"]) == 1
    assert "schema 不一致" in capsys.readouterr().out


def test_setting_terms_and_exact():
    assert labels.parse_setting("4") == (4, 4, "4")
    assert labels.parse_setting("4-6") == (4, 6, "4-6")
    assert labels.parse_setting("高設定") == (5, 6, "高設定")
    assert labels.parse_setting("中間") == (3, 4, "中間")
