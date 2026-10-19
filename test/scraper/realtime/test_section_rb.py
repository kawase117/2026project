"""列・島ごとの合算RB: RB判別できる台だけを列単位で合算し、偶然の確率を出す。"""

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest.bonus_specs import load_specs
from scraper.realtime.rank import build_ranking, format_final
from scraper.realtime.schema import SnapshotRow
from scraper.realtime.section_rb import section_rb

NOW = datetime(2026, 10, 19, 13, tzinfo=ZoneInfo("Asia/Tokyo"))
HALL = "テスト店"
MODEL = "マイジャグラーV"
SECTION = "1001-1012"


def row(unit, games=5000, rb=30, model=MODEL, hall=HALL):
    return SnapshotRow(
        hall=hall,
        observed_at=NOW.isoformat(),
        source_updated_at=None,
        unit=unit,
        model=model,
        model_raw=model,
        games=games,
        rb=rb,
    )


def make_db(tmp_path, units, section=SECTION, hall=HALL):
    con = sqlite3.connect(tmp_path / f"{hall}.db")
    con.execute("create table machine_layout (machine_number integer, section text)")
    con.executemany("insert into machine_layout values (?, ?)", [(u, section) for u in units])
    con.commit()
    con.close()


def run(rows, tmp_path, **kwargs):
    return section_rb(rows, db_dir=tmp_path, specs_by_hall={HALL: load_specs()}, audit={}, **kwargs)


def test_section_far_above_expectation_is_reported(tmp_path):
    units = list(range(1001, 1006))
    make_db(tmp_path, units)
    data = run([row(u) for u in units], tmp_path)
    (entry,) = data[HALL]
    assert entry["kind"] == "section" and entry["n"] == 5 and entry["units"] == units
    assert entry["total_games"] == 25000 and entry["total_rb"] == 150
    assert abs(entry["rb_one_in"] - 25000 / 150) < 1e-9
    assert entry["p_avg"] < 0.1 and entry["p_low"] <= entry["p_avg"]
    assert entry["better_than_high"] == 5  # 30/5000は設定6(1/229)より良い
    assert entry["models"] == [MODEL]


def test_fewer_than_three_judgeable_units_is_not_reported(tmp_path):
    make_db(tmp_path, [1001, 1002, 1003])
    assert run([row(1001), row(1002)], tmp_path)[HALL] == []


def test_unjudgeable_machines_are_excluded_from_totals(tmp_path):
    units = [1001, 1002, 1003, 1004]
    make_db(tmp_path, units)
    rows = [row(1001), row(1002), row(1003), row(1004, model="存在しない機種XYZ")]
    (entry,) = run(rows, tmp_path)[HALL]
    assert entry["n"] == 3 and entry["units"] == [1001, 1002, 1003] and entry["total_games"] == 15000


def test_zero_rb_units_do_not_divide_by_zero(tmp_path):
    units = [1001, 1002, 1003]
    make_db(tmp_path, units)
    (entry,) = run([row(u, rb=0) for u in units], tmp_path)[HALL]
    assert entry["total_rb"] == 0 and entry["rb_one_in"] is None
    assert entry["p_avg"] == 1.0 and entry["better_than_high"] == 0


def test_missing_or_empty_db_returns_empty_without_error(tmp_path):
    rows = [row(u) for u in (1001, 1002, 1003)]
    assert run(rows, tmp_path)[HALL] == []  # DBなし
    (tmp_path / f"{HALL}.db").write_bytes(b"")  # サイズ0
    assert run(rows, tmp_path)[HALL] == []
    sqlite3.connect(tmp_path / "別店.db").close()  # machine_layoutなし
    other = [row(u, hall="別店") for u in (1001, 1002, 1003)]
    assert section_rb(other, db_dir=tmp_path, specs_by_hall={"別店": load_specs()}, audit={})["別店"] == []


def test_overlapping_candidates_are_dropped(tmp_path):
    units = list(range(1001, 1013))
    make_db(tmp_path, units)
    data = run([row(u, rb=30 if u % 2 else 20) for u in units], tmp_path)[HALL]
    assert data
    sets = [set(e["units"]) for e in data]
    for i, a in enumerate(sets):
        for b in sets[i + 1 :]:
            assert not (a <= b or b <= a)


def test_window_reports_a_strong_half_row_inside_a_weak_section(tmp_path):
    units = list(range(1001, 1013))
    make_db(tmp_path, units)
    rows = [row(u, rb=40) for u in units[:6]] + [row(u, rb=5) for u in units[6:]]
    first = run(rows, tmp_path)[HALL][0]
    assert first["kind"] == "window" and first["units"] == units[:6]
    assert first["p_avg"] < 1e-6


def test_build_ranking_adds_section_rb_and_final_prints_it(tmp_path):
    units = list(range(1001, 1006))
    make_db(tmp_path, units)
    rows = [row(u) for u in units]
    kwargs = dict(db_dir=tmp_path, specs_by_hall={HALL: load_specs()}, audit={})
    data = build_ranking(rows, **kwargs)
    assert data["section_rb"][HALL][0]["n"] == 5
    text = format_final(data)
    assert "列・島ごとの合算RB" in text and f"【{HALL}】" in text and "1001〜1005" in text
    # 本表(総合ランキング)は変えない・無効化すれば節も出ない
    off = build_ranking(rows, section_rb=False, **kwargs)
    assert off["section_rb"] == {} and "列・島ごとの合算RB" not in format_final(off)
    assert [r["unit"] for r in off["ranked"]] == [r["unit"] for r in data["ranked"]]
