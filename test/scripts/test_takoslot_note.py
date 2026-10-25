"""日付の末尾が7〜9の日だけ、タコスロの機械集計を答え合わせ・予測に添える(2026-10-26)。"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_morning_docs  # noqa: E402
import takoslot_note as tn  # noqa: E402


@pytest.fixture
def hall_db(tmp_path):
    path = tmp_path / "hall.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
            "games_normalized REAL, bb_count INT, rb_count INT, diff_coins_normalized REAL)"
        )
        rows = [
            # 末尾8の日: 台1はRBが多い、台2はBB0回(3000G以上)、台3は2000G未満
            ("20261018", 1, "タコスロ", 5000, 15, 25, 1500),
            ("20261018", 2, "タコスロ", 4000, 0, 11, 300),
            ("20261018", 3, "タコスロ", 1500, 5, 4, -200),
            # 末尾4の日: 設定1並み
            ("20261014", 1, "タコスロ", 3523, 11, 10, 0),
            # 別機種は拾わない
            ("20261018", 9, "ジャグラー", 5000, 10, 10, 0),
        ]
        con.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?,?)", rows)
    return path


def test_target_days_are_last_digit_7_to_9():
    days = (6, 7, 8, 9, 10, 17, 18, 19, 20, 27, 28, 29, 30)
    got = [tn.is_target_day(f"202610{d:02d}") for d in days]
    assert got == [d % 10 in (7, 8, 9) for d in days]


def test_answer_section_has_unit_table_and_bb0_mark(hall_db):
    text = tn.takoslot_section(hall_db, "20261018", "楽園", "answer")
    assert "### 楽園 タコスロ（20261018分、末尾8の日）" in text
    assert "| 1 | 5000 | 15 | 25 | 1/200 | 1.76 |" in text
    assert "BB0回(要確認)" in text  # 台2: 4000GでBB0回
    assert "2,000G未満" in text  # 台3
    assert "ジャグラー" not in text
    assert "- 末尾7〜9の日: 該当なし" in text  # 対象日自身は履歴に含めない
    assert "- それ以外の日: 1日・1台日、RB設定1比 1.00" in text


def test_prediction_section_uses_previous_day_and_history(hall_db):
    text = tn.takoslot_section(hall_db, "20261019", "楽園", "prediction")
    assert "### 楽園 タコスロ（20261019は末尾9の日）" in text
    assert "前日（20261018）の台別:" in text
    assert "- 末尾7〜9の日: 1日・2台日" in text  # 10/18 の台1・台2(台3は2,000G未満で除く)


def test_other_days_and_hall_without_takoslot_give_empty_text(hall_db, tmp_path):
    assert tn.takoslot_section(hall_db, "20261020", "楽園", "answer") == ""  # 末尾0
    empty = tmp_path / "empty.db"
    with sqlite3.connect(empty) as con:
        con.execute(
            "CREATE TABLE machine_detailed_results (date TEXT, machine_number INT, machine_name TEXT, "
            "games_normalized REAL, bb_count INT, rb_count INT, diff_coins_normalized REAL)"
        )
    assert tn.takoslot_section(empty, "20261018", "楽園", "answer") == ""
    assert tn.takoslot_section(tmp_path / "missing.db", "20261018", "楽園", "prediction") == ""


def test_section_never_uses_words_the_ledger_extracts(hall_db):
    # prediction_ledger は「判断:」で始まる行と「避ける/避け」を含む行を機械的に拾う
    text = tn.takoslot_section(hall_db, "20261019", "楽園", "prediction")
    assert "避け" not in text
    assert not any(line.lstrip(" -*").startswith("判断") for line in text.splitlines())


def test_append_takoslot_adds_only_on_target_days(hall_db, tmp_path):
    part = tmp_path / "x.prediction.md"
    part.write_text("## 楽園\n本文\n", encoding="utf-8")
    run_morning_docs.append_takoslot(part, hall_db, "20261020", "楽園", "prediction")
    assert part.read_text(encoding="utf-8") == "## 楽園\n本文\n"
    run_morning_docs.append_takoslot(part, hall_db, "20261019", "楽園", "prediction")
    out = part.read_text(encoding="utf-8")
    assert out.startswith("## 楽園\n本文\n") and "タコスロ（20261019は末尾9の日）" in out
