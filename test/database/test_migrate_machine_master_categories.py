"""未照合の行に残った古い分類列をNULLに戻す(2026-10-25)。"""

import sqlite3
from contextlib import closing

import pytest

from backtest.bonus_specs import normalize
from database import migrate_machine_master_categories as mig

HALL = "テスト店"
MATCHED = "アイムジャグラー"
STALE = "もっと！謎の機種"
CLEAN = "別の機種"

SPECS = {
    normalize(MATCHED): {
        "family_name": MATCHED,
        "category": "ノーマル",
        "game_type": "ノーマル",
        "judgeable": True,
        "settings": {},
        "source": "テスト",
    }
}


def _make_db(tmp_path, with_new_columns=True):
    extra = (
        ", game_type TEXT, spec_category TEXT, bonus_judgeable INTEGER, spec_source TEXT" if with_new_columns else ""
    )
    with closing(sqlite3.connect(tmp_path / f"{HALL}.db")) as con:
        con.execute(
            "CREATE TABLE machine_master (machine_name_normalized TEXT PRIMARY KEY, jug_flag INTEGER, bt_flag INTEGER%s)"
            % extra
        )
        if with_new_columns:
            con.execute("INSERT INTO machine_master VALUES (?, 1, 0, 'AT', 'AT', 0, '古い')", (MATCHED,))
            con.execute("INSERT INTO machine_master VALUES (?, 0, 1, 'ノーマル', 'BT', 1, '一撃 古い値')", (STALE,))
            con.execute("INSERT INTO machine_master VALUES (?, 0, 0, NULL, NULL, NULL, NULL)", (CLEAN,))
        else:
            for name in (MATCHED, STALE, CLEAN):
                con.execute("INSERT INTO machine_master VALUES (?, 0, 1)", (name,))
        con.commit()


def _rows(tmp_path):
    with closing(sqlite3.connect(tmp_path / f"{HALL}.db")) as con:
        return {row[0]: row[1:] for row in con.execute("SELECT * FROM machine_master")}


@pytest.fixture(autouse=True)
def _db_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(mig, "DB_DIR", str(tmp_path))


def test_dry_run_lists_stale_rows_and_writes_nothing(tmp_path, capsys):
    _make_db(tmp_path)
    before = _rows(tmp_path)
    assert mig.migrate(HALL, SPECS, apply_changes=False) == (1, 2)
    assert _rows(tmp_path) == before
    out = capsys.readouterr().out
    assert "分類列をNULLに戻す(対象)" in out
    assert STALE in out
    assert out.count("分類列をNULLに戻す(対象)") == 1


def test_apply_clears_only_stale_unmatched_rows(tmp_path, capsys):
    _make_db(tmp_path)
    before = _rows(tmp_path)
    assert mig.migrate(HALL, SPECS, apply_changes=True) == (1, 2)
    rows = _rows(tmp_path)
    assert rows[STALE] == (0, 1, None, None, None, None)
    assert rows[STALE][:2] == before[STALE][:2]
    assert rows[CLEAN] == before[CLEAN]
    assert rows[MATCHED] == (1, 0, "ノーマル", "ノーマル", 1, "テスト")
    assert "分類列をNULLに戻した" in capsys.readouterr().out


def test_apply_is_idempotent(tmp_path, capsys):
    _make_db(tmp_path)
    mig.migrate(HALL, SPECS, apply_changes=True)
    first = _rows(tmp_path)
    capsys.readouterr()
    mig.migrate(HALL, SPECS, apply_changes=True)
    assert _rows(tmp_path) == first
    assert "NULLに戻" not in capsys.readouterr().out


def test_db_without_new_columns_has_no_stale_rows(tmp_path, capsys):
    _make_db(tmp_path, with_new_columns=False)
    assert mig.migrate(HALL, SPECS, apply_changes=False) == (1, 2)
    assert "NULLに戻" not in capsys.readouterr().out
    assert mig.migrate(HALL, SPECS, apply_changes=True) == (1, 2)
    rows = _rows(tmp_path)
    assert rows[MATCHED][-4:] == ("ノーマル", "ノーマル", 1, "テスト")
    assert rows[STALE][-4:] == (None, None, None, None)
