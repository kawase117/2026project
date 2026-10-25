"""RB判別機種のホール別候補をDBから生成し、独立した台帳へ凍結する。"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from backtest import prediction_ledger, prediction_rb

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"
OUT_DIR = Path(__file__).resolve().parent / "rb_candidates"
RB_HALLS = (
    "ARROW池上店",
    "BIGディッパー戸越銀座店",
    "みとや大森町店",
    "マルハンメガシティ2000-蒲田7",
    "レイトギャップ平和島",
    "楽園蒲田店",
)
RB_UNIT_HALLS = {"みとや大森町店", "マルハンメガシティ2000-蒲田7"}
WINDOW_DAYS = 90
MIN_WINDOW_DAYS = 150
MIN_LONG_RUN_DAYS = 60
MIN_CURRENT_UNITS = 3
MIN_FAMILIES = 5
PICK_SHARE = 0.2
MIN_UNIT_DAYS = 25
DOW_LOOKBACK = 8
DOW_REFERENCE_DAYS = 60


def _day(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%d")


def _start(value: str, days: int) -> str:
    return (_day(value) - timedelta(days=days)).strftime("%Y%m%d")


def _data(con: sqlite3.Connection, before: str):
    records = []
    names = defaultdict(set)
    for date, number, name, games, rb in prediction_rb.family_rows(con, before):
        spec = prediction_rb.rb_family(name)
        if spec is not None:
            family, floor, maximum = spec
            records.append((date, int(number), family, float(games), float(rb), floor, maximum))
            names[family].add(name)
    return records, names


def rank_machines(
    con: sqlite3.Connection, target_date: str, asof: str, offsets: dict[str, float], window: int = WINDOW_DAYS
) -> dict:
    records, names = _data(con, target_date)
    comparable = prediction_rb.comparable_families(prediction_rb.family_rows(con, min(target_date, _start(asof, -1))))
    start, recent = _start(target_date, window), _start(target_date, 7)
    current = defaultdict(set)
    for number, name in con.execute(
        "SELECT machine_number, machine_name FROM machine_detailed_results WHERE date = ?", (asof,)
    ):
        spec = prediction_rb.rb_family(name)
        if spec:
            current[spec[0]].add(int(number))
    for (name,) in con.execute("SELECT DISTINCT machine_name FROM machine_detailed_results"):
        spec = prediction_rb.rb_family(name)
        if spec:
            names[spec[0]].add(name)
    totals = defaultdict(lambda: [0, 0.0, 0.0, 0, 0.0, 0.0, 0])
    for date, number, family, games, rb, _, _ in records:
        item = totals[family]
        if date < start:
            item[6] += 1
        else:
            item[0] += 1
            item[1] += games
            item[2] += rb
            if date >= recent:
                item[3] += 1
                item[4] += games
                item[5] += rb
    ranked = []
    for family, item in totals.items():
        if (
            family not in comparable
            or family not in offsets
            or item[0] < MIN_WINDOW_DAYS
            or item[6] < MIN_LONG_RUN_DAYS
            or len(current[family]) < MIN_CURRENT_UNITS
        ):
            continue
        _, _, _, floor, maximum = comparable[family]
        z90 = prediction_rb.zval(item[2], item[1], floor, maximum)
        ranked.append(
            {
                "family_name": family,
                "machine_names": sorted(names[family]),
                "units": len(current[family]),
                "n_w": item[0],
                "n_lr": item[6],
                "z90": z90,
                "adj90": z90 - offsets[family],
                "z7": prediction_rb.zval(item[5], item[4], floor, maximum) if item[4] else None,
            }
        )
    ranked.sort(key=lambda row: (-row["adj90"], row["family_name"]))
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
    if len(ranked) < MIN_FAMILIES:
        return {"status": "skipped", "reason": "few_families", "eligible": ranked, "candidates": [], "avoid": []}
    k = max(1, math.ceil(PICK_SHARE * len(ranked)))
    return {"status": "ok", "reason": None, "eligible": ranked, "candidates": ranked[:k], "avoid": ranked[-k:]}


def rank_units(con: sqlite3.Connection, target_date: str, asof: str, top_families: list[str]) -> dict:
    records, _ = _data(con, target_date)
    current = defaultdict(set)
    for number, name in con.execute(
        "SELECT machine_number, machine_name FROM machine_detailed_results WHERE date = ?", (asof,)
    ):
        spec = prediction_rb.rb_family(name)
        if spec:
            current[spec[0]].add(int(number))
    start = _start(target_date, WINDOW_DAYS)
    totals = defaultdict(lambda: [0, 0.0, 0.0])
    for date, number, family, games, rb, floor, _ in records:
        if family in top_families and date >= start and number in current[family]:
            item = totals[(family, number)]
            item[0] += 1
            item[1] += rb
            item[2] += games * floor
    result = {}
    for family in top_families:
        values = [
            {"machine_number": number, "n_days": value[0], "s1": value[1] / value[2]}
            for (f, number), value in totals.items()
            if f == family and value[0] >= MIN_UNIT_DAYS and value[2] > 0
        ]
        values.sort(key=lambda row: (-row["s1"], row["machine_number"]))
        if len(values) >= 5:
            result[family] = values[: max(1, math.ceil(PICK_SHARE * len(values)))]
    return result


def day_level(con: sqlite3.Connection, date: str, comparable: dict | None = None) -> float | None:
    if comparable is None:
        comparable = prediction_rb.comparable_families(prediction_rb.family_rows(con, date))
    sums = defaultdict(lambda: [0.0, 0.0])
    for name, games, rb in con.execute(
        "SELECT machine_name, games_normalized, rb_count FROM machine_detailed_results "
        "WHERE date = ? AND games_normalized >= ? AND rb_count IS NOT NULL",
        (date, prediction_rb.MIN_GAMES),
    ):
        spec = prediction_rb.rb_family(name)
        if spec and spec[0] in comparable:
            item = sums[spec[0]]
            item[0] += games
            item[1] += rb
    if len(sums) < MIN_FAMILIES:
        return None
    weighted = []
    for family, (games, rb) in sums.items():
        _, _, _, floor, maximum = comparable[family]
        weight = games * (maximum - floor) ** 2 / floor
        weighted.append((weight, prediction_rb.zval(rb, games, floor, maximum)))
    return sum(w * z for w, z in weighted) / sum(w for w, _ in weighted)


def day_flag(con: sqlite3.Connection, target_date: str, asof: str) -> dict | None:
    comparable = prediction_rb.comparable_families(prediction_rb.family_rows(con, _start(asof, -1)))
    dates = [
        row[0]
        for row in con.execute(
            "SELECT DISTINCT date FROM machine_detailed_results WHERE date <= ? ORDER BY date", (asof,)
        )
    ]
    levels = {date: day_level(con, date, comparable) for date in dates}
    weekday = _day(target_date).weekday()

    def dow_mean(before: str) -> float | None:
        values = [levels[d] for d in dates if d < before and _day(d).weekday() == weekday and levels[d] is not None]
        values = values[-DOW_LOOKBACK:]
        return sum(values) / len(values) if len(values) >= 4 else None

    x_dow = dow_mean(target_date)
    if x_dow is None:
        return None
    start = _start(target_date, DOW_REFERENCE_DAYS)
    reference = [dow_mean(d) for d in dates if start <= d < target_date]
    reference = [x for x in reference if x is not None]
    if len(reference) < 30:
        return None
    pct = sum(x <= x_dow for x in reference) / len(reference)
    return {
        "flag": "強め" if pct >= 0.7 else "弱め" if pct <= 0.3 else "普通",
        "x_dow": x_dow,
        "pct": pct,
        "n_reference": len(reference),
    }


def render_section(rows: list[dict]) -> str:
    out = [
        "## RB機種候補（機械出力、DBだけから作成。開店前に自動凍結。人の判断の採点とは別）",
        "",
        "効果は小さく、台と曜日は補助情報です。",
        "補正済みzは機種共通の傾向を引いたホール固有分です。",
        "",
    ]
    for row in rows:
        out += [
            f"### {row['hall']}",
            f"DB最終日: {row['data_asof'] or '-'} / 遅れ: {row['lag_days'] if row['lag_days'] is not None else '-'}日",
        ]
        if row["status"] != "ok":
            out += [f"スキップ: {row['reason']}", ""]
            continue
        for label, key in (("候補", "candidates"), ("避ける候補", "avoid")):
            out += [label, "| 機種 | 台数 | adj90 | z90 | z7 |", "|---|---:|---:|---:|---:|"]
            for item in row[key]:
                z7 = f"{item['z7']:+.3f}" if item["z7"] is not None else "-"
                out.append(
                    f"| {item['family_name']} | {item['units']} | {item['adj90']:+.3f} | {item['z90']:+.3f} | {z7} |"
                )
        if row["units"]:
            out.append(
                "台の補助: "
                + " / ".join(
                    f"{f}: " + ", ".join(str(u["machine_number"]) for u in units) for f, units in row["units"].items()
                )
            )
        flag = row["day_flag"]
        out += [f"日の補助: {flag['flag']} (pct={flag['pct']:.2f})" if flag else "日の補助: 有効値不足", ""]
    return "\n".join(out).rstrip() + "\n"


def generate(
    target_date: str,
    db_dir: Path = DB_DIR,
    out_dir: Path = OUT_DIR,
    md_out: Path | None = None,
    no_freeze: bool = False,
) -> list[dict]:
    db_dir, out_dir = Path(db_dir), Path(out_dir)
    rows = []
    offsets = prediction_rb.family_offsets(db_dir, target_date)
    for hall in RB_HALLS:
        row = {
            "hall": hall,
            "status": "skipped",
            "reason": None,
            "data_asof": None,
            "lag_days": None,
            "candidates": [],
            "avoid": [],
            "units": {},
            "day_flag": None,
        }
        path = db_dir / f"{hall}.db"
        try:
            if not path.exists():
                raise FileNotFoundError("db_missing")
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
                asof_row = con.execute(
                    "SELECT MAX(date) FROM machine_detailed_results WHERE date < ?", (target_date,)
                ).fetchone()
                if not asof_row or not asof_row[0]:
                    raise ValueError("no_prior_data")
                asof = asof_row[0]
                lag = (_day(target_date) - _day(asof)).days - 1
                row.update(data_asof=asof, lag_days=lag)
                if lag > 3:
                    row["reason"] = "data_stale"
                else:
                    rank = rank_machines(con, target_date, asof, offsets)
                    row.update(
                        status=rank["status"], reason=rank["reason"], candidates=rank["candidates"], avoid=rank["avoid"]
                    )
                    if row["status"] == "ok":
                        if hall in RB_UNIT_HALLS:
                            row["units"] = rank_units(
                                con, target_date, asof, [r["family_name"] for r in row["candidates"]]
                            )
                        row["day_flag"] = day_flag(con, target_date, asof)
        except Exception as exc:
            row["reason"] = str(exc)
        rows.append(row)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(prediction_ledger.JST)
    with (out_dir / "RUNS.jsonl").open("a", encoding="utf-8") as fh:
        for row in rows:
            frozen = False
            if row["status"] == "ok" and not no_freeze:
                picks = {
                    "models": sorted({n for r in row["candidates"] for n in r["machine_names"]}),
                    "avoid_models": sorted({n for r in row["avoid"] for n in r["machine_names"]}),
                    "units": sorted({u["machine_number"] for units in row["units"].values() for u in units}),
                    "jug_units": [],
                }
                extra = {k: row[k] for k in ("candidates", "avoid", "units", "day_flag", "data_asof", "lag_days")}
                try:
                    written = prediction_ledger.freeze_rb_auto(row["hall"], target_date, picks, extra, now)
                    frozen = written is not None
                    if not frozen:
                        print(f"{row['hall']}: 既存のためスキップ")
                except Exception as exc:
                    row.update(status="skipped", reason=f"freeze_error: {exc}")
            fh.write(
                json.dumps(
                    {
                        "date": target_date,
                        "hall": row["hall"],
                        "status": row["status"],
                        "reason": row["reason"],
                        "data_asof": row["data_asof"],
                        "lag_days": row["lag_days"],
                        "frozen": frozen,
                        "generated_at": now.isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    (out_dir / f"{target_date}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    section = render_section(rows)
    print(section)
    if md_out is not None:
        path = Path(md_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(section, encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("generate")
    cmd.add_argument("--date", required=True)
    cmd.add_argument("--no-freeze", action="store_true")
    cmd.add_argument("--out-dir", type=Path, default=OUT_DIR)
    cmd.add_argument("--db-dir", type=Path, default=DB_DIR)
    cmd.add_argument("--md-out", type=Path)
    args = parser.parse_args(argv)
    generate(args.date, args.db_dir, args.out_dir, args.md_out, args.no_freeze)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
