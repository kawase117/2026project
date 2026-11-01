"""backtest/persistent_units.py のテスト。合成データ（実データなし）。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from backtest import persistent_units as pu

START = datetime(2026, 1, 1)
DAYS = 230  # 最古の週（t-182日）の28日窓が稼働20日以上になる長さ


def _frame(strong_unit: int = 1, changing_unit: int | None = None) -> pd.DataFrame:
    rows = []
    for i in range(DAYS):
        day = START + timedelta(days=i)
        for n in range(1, 13):
            diff = 1500 if n == strong_unit else -60 + (n % 3) * 20
            nm = "M"
            if changing_unit == n and i >= DAYS - 10:
                nm = "OTHER"
            rows.append((day, n, nm, 3000, diff))
    return pd.DataFrame(rows, columns=["date", "n", "nm", "g", "df"])


def test_flagged_units_picks_only_strong_unit():
    d = _frame()
    t = d["date"].max() + timedelta(days=1)
    f = pu.flagged_units(d, t)
    assert list(f["n"]) == [1]
    assert f["s"].iloc[0] >= pu.FLAG_THRESHOLD


def test_flagged_units_excludes_unit_whose_machine_changed_in_window():
    d = _frame(strong_unit=1, changing_unit=1)
    t = d["date"].max() + timedelta(days=1)
    assert pu.flagged_units(d, t).empty


def test_persistent_units_counts_flag_weeks():
    d = _frame()
    t = d["date"].max() + timedelta(days=1)
    u = pu.persistent_units(d, t)
    assert list(u["n"]) == [1]
    assert u["flag_weeks"].iloc[0] == pu.LOOKBACK_WEEKS + 1


def test_weekly_freezes_and_refuses_overwrite(tmp_path, monkeypatch):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    conn = sqlite3.connect(db_dir / "テスト店.db")
    conn.execute(
        "create table machine_detailed_results (date text, machine_number integer, machine_name text, "
        "games_normalized integer, diff_coins_normalized integer)"
    )
    d = _frame()
    conn.executemany(
        "insert into machine_detailed_results values (?,?,?,?,?)",
        [(r.date.strftime("%Y%m%d"), r.n, r.nm, r.g, r.df) for r in d.itertuples()],
    )
    conn.commit()
    conn.close()

    out = tmp_path / "out"
    monkeypatch.setattr(pu, "OUT_DIR", out)
    monkeypatch.setattr(pu, "LIST_DIR", out / "lists")
    monkeypatch.setattr(pu, "SCORES_PATH", out / "SCORES.jsonl")
    monkeypatch.setattr(pu, "REPORT_PATH", out / "REPORT.md")
    monkeypatch.setattr(pu, "hall_db_paths", lambda: sorted(db_dir.glob("*.db")))

    assert pu.weekly() == 0
    frozen = list((out / "lists").glob("*.json"))
    assert len(frozen) == 1
    payload = json.loads(frozen[0].read_text(encoding="utf-8"))
    assert [u["n"] for u in payload["halls"]["テスト店"]["units"]] == [1]
    assert pu.weekly() == 1  # 凍結済みは上書きしない
    assert pu.score() == 0  # 翌週のデータが無いので採点しない
    assert not (out / "SCORES.jsonl").exists()
