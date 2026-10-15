"""database.data_audit の各検査が小さな一時DBで発火することを確かめる。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from database import data_audit as da
from database.date_info_calculator import DateInfoCalculator

HALL = "テストホール"
OTHER = "別ホール"
START = datetime(2026, 9, 1)
N_DAYS = 20


def _days(n: int = N_DAYS) -> list[str]:
    return [(START + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _machines(base: int, n: int, seed: int) -> list[tuple]:
    return [
        (base + i, "マイジャグラーV", 3000 + (i * 37 + seed) % 2000, (i * 53 + seed) % 1500 - 700, 10, 10)
        for i in range(n)
    ]


def _write_hall(db_dir: Path, data_dir: Path, config: Path, hall: str, by_day: dict, json_days=None) -> None:
    db = sqlite3.connect(db_dir / ("%s.db" % hall))
    db.execute(
        "CREATE TABLE machine_detailed_results (date TEXT, machine_number INTEGER, machine_name TEXT, "
        "games_normalized INTEGER, diff_coins_normalized INTEGER, bb_count INTEGER, rb_count INTEGER)"
    )
    cols = ", ".join("%s TEXT" % c for c in da.DATE_FLAG_COLUMNS)
    db.execute("CREATE TABLE daily_hall_summary (date TEXT, total_machines INTEGER, %s)" % cols)
    calc = DateInfoCalculator(hall, db_path="unused", config_path=str(config))
    for day, rows in by_day.items():
        db.executemany("INSERT INTO machine_detailed_results VALUES (?,?,?,?,?,?,?)", [(day, *r) for r in rows])
        info = calc.calculate_date_info(day)
        db.execute(
            "INSERT INTO daily_hall_summary VALUES (?,?,%s)" % ",".join("?" * len(da.DATE_FLAG_COLUMNS)),
            (day, len(rows), *[info[c] for c in da.DATE_FLAG_COLUMNS]),
        )
    db.commit()
    db.close()
    folder = data_dir / hall
    folder.mkdir(parents=True, exist_ok=True)
    for day in json_days if json_days is not None else by_day:
        records = [{"機種名": r[1], "台番号": str(r[0])} for r in by_day.get(day, [])]
        (folder / ("%s_%s_data.json" % (day, hall))).write_text(
            json.dumps({"date": day, "hall_name": hall, "all_data": records}, ensure_ascii=False), encoding="utf-8"
        )


@pytest.fixture
def env(tmp_path):
    db_dir, data_dir = tmp_path / "db", tmp_path / "data"
    db_dir.mkdir()
    data_dir.mkdir()
    config = tmp_path / "hall_config.json"
    config.write_text(
        json.dumps(
            {"halls": [{"hall_name": HALL, "active": True}, {"hall_name": OTHER, "active": True}]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    da._json_index.clear()
    da._date_calc_cache.clear()
    return db_dir, data_dir, config


def _clean() -> dict[str, list[tuple]]:
    return {d: _machines(1000, 100, i) for i, d in enumerate(_days())}


def _setup(env, mutate=None, json_days=None, other=None) -> dict:
    db_dir, data_dir, config = env
    by_day = _clean()
    if mutate:
        mutate(by_day)
    _write_hall(db_dir, data_dir, config, HALL, by_day, json_days)
    other_days = other if other is not None else {d: _machines(5000, 80, i) for i, d in enumerate(_days())}
    _write_hall(db_dir, data_dir, config, OTHER, other_days)
    return by_day


def _audit(env, day: str) -> dict:
    db_dir, data_dir, config = env
    da._json_index.clear()
    [rec] = da.run_audit([day], [HALL], db_dir, data_dir, config)
    return rec


def _checks(rec: dict, severity: str) -> set[str]:
    return {i["check"] for i in rec["issues"] if i["severity"] == severity}


def _messages(rec: dict, check: str, severity: str) -> list[str]:
    return [i["message"] for i in rec["issues"] if i["check"] == check and i["severity"] == severity]


def test_clean_day_is_ok(env):
    _setup(env)
    rec = _audit(env, _days()[-1])
    assert rec["status"] == "OK", rec
    assert rec["machines"] == 100


def test_gap_with_json_is_ingest_failure(env):
    days = _days()

    def drop(by_day):
        del by_day[days[15]]

    _setup(env, mutate=drop, json_days=list(_clean()))  # JSON は欠けた日にもある
    rec = _audit(env, days[16])
    assert "continuity" in _checks(rec, "ERROR")


def test_gap_without_json_is_warn(env):
    days = _days()

    def drop(by_day):
        del by_day[days[15]]

    _setup(env, mutate=drop)
    rec = _audit(env, days[16])
    assert "continuity" in _checks(rec, "WARN")
    assert rec["status"] == "WARN"


def test_machine_count_shift_warns_once(env):
    days = _days()

    def shrink(by_day):
        for d in days[-2:]:
            by_day[d] = by_day[d][:85]  # -15% が2日続く

    _setup(env, mutate=shrink, json_days=[])
    assert "machine_count" in _checks(_audit(env, days[-2]), "WARN")
    assert "machine_count" in _checks(_audit(env, days[-1]), "INFO")


def test_machine_count_half_is_error_and_partial_insert(env):
    days = _days()

    def shrink(by_day):
        by_day[days[-1]] = by_day[days[-1]][:40]

    db_dir, data_dir, config = env
    _setup(env, mutate=shrink)
    full = [{"機種名": r[1], "台番号": str(r[0])} for r in _clean()[days[-1]]]
    (data_dir / HALL / ("%s_%s_data.json" % (days[-1], HALL))).write_text(
        json.dumps({"date": days[-1], "hall_name": HALL, "all_data": full}, ensure_ascii=False), encoding="utf-8"
    )
    rec = _audit(env, days[-1])
    assert "machine_count" in _checks(rec, "ERROR")
    assert any("部分投入" in m for m in _messages(rec, "json", "ERROR"))  # JSON 100件 vs DB 40行


def test_hall_identity_numbers_do_not_overlap(env):
    days = _days()

    def swap(by_day):
        by_day[days[-1]] = _machines(7000, 100, 3)

    _setup(env, mutate=swap)
    assert "hall_identity" in _checks(_audit(env, days[-1]), "ERROR")


def test_hall_identity_same_as_other_hall(env):
    days = _days()
    other = {d: _machines(5000, 80, i) for i, d in enumerate(days)}
    other[days[-1]] = list(_clean()[days[-1]])  # 別ホールに同じ中身が入った
    _setup(env, other=other)
    rec = _audit(env, days[-1])
    assert any("他ホール" in m for m in _messages(rec, "hall_identity", "ERROR")), rec


def test_json_hall_name_mismatch(env):
    db_dir, data_dir, config = env
    days = _days()
    _setup(env)
    path = data_dir / HALL / ("%s_%s_data.json" % (days[-1], HALL))
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["hall_name"] = "金時京急蒲田店"
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    assert any("hall_name" in m for m in _messages(_audit(env, days[-1]), "json", "ERROR"))


def test_success_but_zero_rows(env):
    db_dir, data_dir, config = env
    _setup(env)
    target = (START + timedelta(days=N_DAYS)).strftime("%Y%m%d")
    # 成功と表示されたが all_data が空のJSON（DBにも入っていない日）
    (data_dir / HALL / ("%s_%s_data.json" % (target, HALL))).write_text(
        json.dumps({"date": target, "hall_name": HALL, "all_data": []}), encoding="utf-8"
    )
    rec = _audit(env, target)
    assert rec["status"] == "ERROR"
    assert "json" in _checks(rec, "ERROR")


def test_empty_json_but_db_ok_is_warn(env):
    db_dir, data_dir, config = env
    days = _days()
    _setup(env)
    (data_dir / HALL / ("%s_%s_data.json" % (days[-1], HALL))).write_text(
        json.dumps({"date": days[-1], "hall_name": HALL, "all_data": []}), encoding="utf-8"
    )
    rec = _audit(env, days[-1])
    assert rec["status"] == "WARN"
    assert "json" in _checks(rec, "WARN")


def test_missing_day_without_json_is_not_error(env):
    _setup(env)
    target = (START + timedelta(days=N_DAYS)).strftime("%Y%m%d")
    rec = _audit(env, target)
    assert rec["status"] == "OK"
    assert "presence" in _checks(rec, "INFO")


def test_missing_db_is_error(env):
    db_dir, data_dir, config = env
    _setup(env)
    (db_dir / ("%s.db" % HALL)).unlink()
    rec = _audit(env, _days()[-1])
    assert "presence" in _checks(rec, "ERROR")


def test_date_flag_mismatch(env):
    db_dir, data_dir, config = env
    days = _days()
    _setup(env)
    db = sqlite3.connect(db_dir / ("%s.db" % HALL))
    db.execute("UPDATE daily_hall_summary SET is_zorome='1', day_of_week='月' WHERE date=?", (days[-1],))
    db.commit()
    db.close()
    rec = _audit(env, days[-1])
    wrong = [i for i in rec["issues"] if i["check"] == "date_flags" and i["severity"] == "ERROR"]
    assert wrong and {"is_zorome", "day_of_week"} <= set(wrong[0]["detail"])


def test_summary_row_missing(env):
    db_dir, data_dir, config = env
    days = _days()
    _setup(env)
    db = sqlite3.connect(db_dir / ("%s.db" % HALL))
    db.execute("DELETE FROM daily_hall_summary WHERE date=?", (days[-1],))
    db.commit()
    db.close()
    assert "date_flags" in _checks(_audit(env, days[-1]), "ERROR")


def test_values_null_negative_duplicate(env):
    days = _days()

    def corrupt(by_day):
        rows = by_day[days[-1]]
        rows[0] = (rows[0][0], rows[0][1], None, 10, 1, 1)
        rows[1] = (rows[1][0], rows[1][1], -5, 10, 1, 1)
        rows.append(rows[2])

    _setup(env, mutate=corrupt, json_days=[])
    messages = _messages(_audit(env, days[-1]), "values", "ERROR")
    assert any("NULL" in m for m in messages)
    assert any("負値" in m for m in messages)
    assert any("重複" in m for m in messages)


def test_constant_diff_closed_day_page(env):
    days = _days()

    def closed(by_day):
        by_day[days[-1]] = [(no, name, 0, -6142, 0, 0) for no, name, *_ in by_day[days[-1]]]

    _setup(env, mutate=closed)
    messages = _messages(_audit(env, days[-1]), "values", "ERROR")
    assert any("G数が0" in m for m in messages)
    assert any("差枚が同じ値" in m for m in messages)


def test_avg_games_spike_and_extreme(env):
    days = _days()

    def tripled(by_day):
        by_day[days[-1]] = [(no, name, g * 3, d, bb, rb) for no, name, g, d, bb, rb in by_day[days[-1]]]

    _setup(env, mutate=tripled)
    rec = _audit(env, days[-1])
    assert "avg_games" in _checks(rec, "WARN")
    assert "values" in _checks(rec, "WARN")  # 3倍で >12000G の台が出る


def test_cli_writes_jsonl_and_exit_code(env, tmp_path):
    db_dir, data_dir, config = env
    days = _days()

    def shrink(by_day):
        by_day[days[-1]] = by_day[days[-1]][:40]

    _setup(env, mutate=shrink)
    out = tmp_path / "audit.jsonl"
    base = ["--db-dir", str(db_dir), "--data-dir", str(data_dir), "--config", str(config), "--out", str(out)]
    assert da.main(["--date", days[-2], "--hall", HALL, *base]) == 0
    iso = "%s-%s-%s" % (days[-1][:4], days[-1][4:6], days[-1][6:])
    assert da.main(["--date", iso, "--hall", HALL, *base]) == 1
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in lines] == ["OK", "ERROR"]
    assert [r["date"] for r in lines] == days[-2:]
    da._json_index.clear()
    assert da.main(["--all-days", "--hall", HALL, "--no-write", *base]) == 1
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2  # --no-write は追記しない
