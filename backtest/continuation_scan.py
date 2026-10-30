"""示唆続行台の検証: AT機で回転数の多い台に、結果ツイートの台が集まるか(2026-10 振り返り 作業5の1)。

なぜ見るか:
    今の店は6,000〜7,000Gあたりで答え合わせのトロフィーなどの示唆を出す(ジャグラーなど出ない機種もある)。
    1日の最大は約1万Gなので、AT機で7,000G以上回った台は、朝から期待され、途中で示唆を見て打ち続けられた
    可能性が高い(ユーザー指摘 2026-10-31)。差枚だけで採点すると、その台を外れと数える。

何を比べるか:
    結果ツイートで台番号が挙がった台(result_corpus の external_result_machines と RESULT_CHECKS.jsonl)を
    「結果の台」とし、AT機の回転数が閾値以上の台と未満の台で、結果の台に入る割合を比べる。
    - 層は同じ日・同じ機種。結果ツイートは機種単位で台を挙げることが多く、機種をまたぐと
      「結果に入った機種がよく回る」ことを拾ってしまう。結果の台が1台以上あり、閾値の上下に1台以上ずつある
      機種×日だけを使い、Mantel-Haenszel の割合比を出す。
    - 差枚がマイナスの台だけでも同じ比を出す。発信者が差枚で台を選ぶなら、マイナスの台は結果に入らない。
      入るなら、差枚の外の情報(示唆・ホール公表)で挙がっている。**判断はこの行で行う。**
    - 新台(導入0〜6日)と、稼働の高い日(土日・イベント日)を分ける。新台は設定不問で高回転する。

注意:
    - 結果ツイートが出た日だけの集計で、出る日は強い日に偏る。
    - 画像の誤った紐付けがあるので、抽出名が当日の実在機種と折り合わない台(name_agrees=0)は除く。

使い方:
    venv\\Scripts\\python.exe -m backtest.continuation_scan [--since 20260801] [--out path.md]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "db"
ANALYSIS_DB = DB_DIR / "analysis_results.db"
RESULT_CHECKS = ROOT / "document" / "registry" / "RESULT_CHECKS.jsonl"
HALLS = ("マルハンメガシティ2000-蒲田1", "マルハンメガシティ2000-蒲田7", "楽園蒲田店")
THRESHOLDS = (6000, 7000, 8000)
# machine_master.game_type のうち AT として扱うもの(ノーマル・A+RT は除く)
AT_TYPES = ("AT", "ART", "A+AT", "A+ART")
NEW_DAYS = 6


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def at_models(con: sqlite3.Connection) -> set[str]:
    marks = ",".join("?" * len(AT_TYPES))
    sql = f"SELECT machine_name_normalized FROM machine_master WHERE game_type IN ({marks})"
    return {name for (name,) in con.execute(sql, AT_TYPES)}


def load_labels(hall: str, analysis_db: Path = ANALYSIS_DB, result_checks: Path = RESULT_CHECKS) -> dict[str, set[int]]:
    """営業日 → 結果ツイートで挙がった台番号。"""
    labels: dict[str, set[int]] = defaultdict(set)
    if analysis_db.exists():
        with closing(_ro(analysis_db)) as con:
            for date, number in con.execute(
                "SELECT business_date, machine_number FROM external_result_machines "
                "WHERE hall_name = ? AND (name_agrees IS NULL OR name_agrees != 0)",
                (hall,),
            ):
                labels[date].add(int(number))
    if result_checks.exists():
        for line in result_checks.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line) if line.strip() else {}
            if rec.get("hall") == hall and rec.get("status") == "linked" and rec.get("result_units"):
                labels[rec["business_date"]] |= {int(u) for u in rec["result_units"]}
    return dict(labels)


def busy_dates(hall: str) -> set[str]:
    try:
        from backtest import event_days

        return {r["date"] for r in event_days.active(event_days.load()) if r.get("hall") == hall}
    except Exception:
        return set()


def unit_rows(hall: str, dates: list[str], db_dir: Path = DB_DIR) -> list[dict]:
    """結果の出た日の AT 機の台。age は機種のDB初出からの日数。"""
    out = []
    with closing(_ro(db_dir / f"{hall}.db")) as con:
        at = at_models(con)
        first = dict(con.execute("SELECT machine_name, MIN(date) FROM machine_detailed_results GROUP BY machine_name"))
        for date in dates:
            for number, name, games, diff in con.execute(
                "SELECT machine_number, machine_name, games_normalized, diff_coins_normalized "
                "FROM machine_detailed_results WHERE date = ? AND games_normalized IS NOT NULL",
                (date,),
            ):
                if name not in at:
                    continue
                age = (datetime.strptime(date, "%Y%m%d") - datetime.strptime(first[name], "%Y%m%d")).days
                out.append(
                    {
                        "date": date,
                        "number": int(number),
                        "model": name,
                        "games": float(games),
                        "diff": None if diff is None else float(diff),
                        "age": age,
                    }
                )
    return out


def mh_ratio(rows: list[dict], threshold: int) -> dict:
    """機種×日の層で、閾値以上の台が結果に入る割合 ÷ 閾値未満の割合(Mantel-Haenszel)。"""
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        strata[(r["date"], r["model"])].append(r)
    num = den = 0.0
    hi_n = hi_hit = lo_n = lo_hit = n_strata = 0
    for members in strata.values():
        hi = [r for r in members if r["games"] >= threshold]
        lo = [r for r in members if r["games"] < threshold]
        if not hi or not lo or not any(r["labeled"] for r in members):
            continue
        a, b = sum(r["labeled"] for r in hi), sum(r["labeled"] for r in lo)
        n = len(hi) + len(lo)
        num += a * len(lo) / n
        den += b * len(hi) / n
        hi_n, hi_hit, lo_n, lo_hit, n_strata = hi_n + len(hi), hi_hit + a, lo_n + len(lo), lo_hit + b, n_strata + 1
    return {
        "strata": n_strata,
        "hi_n": hi_n,
        "hi_hit": hi_hit,
        "lo_n": lo_n,
        "lo_hit": lo_hit,
        "hi_rate": hi_hit / hi_n if hi_n else None,
        "lo_rate": lo_hit / lo_n if lo_n else None,
        "ratio": num / den if den > 0 else None,
    }


def _minus(r: dict) -> bool:
    return r["diff"] is not None and r["diff"] < 0


SEGMENTS = (
    ("全体", lambda r: True),
    ("差枚マイナス", _minus),
    ("新台(導入0〜6日)", lambda r: r["age"] <= NEW_DAYS),
    ("新台以外", lambda r: r["age"] > NEW_DAYS),
    ("新台以外・差枚マイナス", lambda r: r["age"] > NEW_DAYS and _minus(r)),
    ("土日・イベント日", lambda r: r["busy"]),
    ("土日・イベント日・差枚マイナス", lambda r: r["busy"] and _minus(r)),
    ("平日の通常日", lambda r: not r["busy"]),
    ("平日の通常日・差枚マイナス", lambda r: not r["busy"] and _minus(r)),
)


def scan(hall: str, since: str | None = None, db_dir: Path = DB_DIR, analysis_db: Path = ANALYSIS_DB) -> dict:
    labels = load_labels(hall, analysis_db)
    dates = sorted(d for d in labels if not since or d >= since)
    busy = busy_dates(hall)
    rows = unit_rows(hall, dates, db_dir) if dates else []
    for r in rows:
        r["labeled"] = r["number"] in labels[r["date"]]
        r["busy"] = r["date"] in busy or datetime.strptime(r["date"], "%Y%m%d").weekday() >= 5
    # AT 機の結果の台が1台もない日は、その発信者が AT 機を挙げなかった日なので除く
    labeled_dates = {r["date"] for r in rows if r["labeled"]}
    rows = [r for r in rows if r["date"] in labeled_dates]
    if not rows:
        return {"hall": hall, "dates": 0, "rows": {}}
    out = {name: {t: mh_ratio([r for r in rows if keep(r)], t) for t in THRESHOLDS} for name, keep in SEGMENTS}
    return {
        "hall": hall,
        "dates": len(labeled_dates),
        "first": min(labeled_dates),
        "last": max(labeled_dates),
        "rows": out,
    }


def _f(v, fmt):
    return "—" if v is None else format(v, fmt)


def render(results: list[dict]) -> str:
    out = [
        "# 示唆続行台の検証(AT機の回転数 × 結果ツイートの台)",
        "",
        "比 = 閾値以上の台が結果に入る割合 ÷ 閾値未満の台の割合。同じ日・同じ機種の層で Mantel-Haenszel。"
        "**判断は差枚マイナスの行で読む**(発信者が差枚で台を選ぶなら、マイナスの台は回転数によらず結果に入らない)。",
        "",
    ]
    for res in results:
        if not res["rows"]:
            out += [f"## {res['hall']}", "", "AT機の結果の台が無い。", ""]
            continue
        out += [
            f"## {res['hall']}(結果のある日 {res['dates']}日、{res['first']}〜{res['last']})",
            "",
            "| 区分 | 閾値 | 層 | 閾値以上 入/台 | 割合 | 閾値未満 入/台 | 割合 | 比 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for seg, by_t in res["rows"].items():
            for t, s in by_t.items():
                out.append(
                    f"| {seg} | {t:,} | {s['strata']} | {s['hi_hit']}/{s['hi_n']} | {_f(s['hi_rate'], '.1%')} | "
                    f"{s['lo_hit']}/{s['lo_n']} | {_f(s['lo_rate'], '.1%')} | {_f(s['ratio'], '.2f')} |"
                )
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    md = render([scan(h, args.since) for h in HALLS])
    print(md)
    if args.out:
        args.out.write_text(md + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
