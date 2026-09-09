"""角番ピークと並び箇所数を日次で計算し、analysis_results.db に貯める。

再計算できる派生値なので、定義を変えたら version を上げて入れ直す。
既存の行は書き換えない（過去の結論がどの定義で出たかを残すため）。

⚠️ 角番ピークは「その日いちばん残差平均が高かった角番」であって、
ホールが実際に仕掛けた角番ではない。速報が番号を公表した日だけが正解ラベルで、
それは observed_facts 側に入る。両者を突き合わせて初めて的中率が出る。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database import analysis_store as store  # noqa: E402

DB_DIR = PROJECT_ROOT / "db"
NORMAL = ("ジャグラー", "ハナハナ", "ハナビ")

KAKUBAN_PARAMS = {
    "residual": "同日同機種の平均差枚を引いた残差",
    "min_per_rank": 12,
    "rank_source": "MIN(rank_from_min, rank_from_max)",
    "segments": ["AT等", "ノーマル", "全館", "2F全体", "3F全体", "AT@2F", "AT@3F"],
}
NARABI_PARAMS = {
    "block_size": 4,
    "block_mean_threshold": 1800.0,
    "all_above": "ホール中央値",
    "same_section_required": True,
    "overlap": "平均の高い方だけを採る",
    "frozen_in": "backtest/announce/rakuen__20260908__kawasakislot.json",
}


def segment_of(name):
    return "ノーマル" if any(w in (name or "") for w in NORMAL) else "AT等"


def kakuban_rows(connection, date):
    rows = connection.execute(
        "SELECT m.machine_number, m.machine_name, MIN(l.rank_from_min, l.rank_from_max), "
        "m.diff_coins_normalized FROM machine_detailed_results m "
        "JOIN machine_layout l ON l.machine_number = m.machine_number "
        "WHERE m.date=? AND m.games_normalized>0 AND l.rank_from_min IS NOT NULL",
        (date,),
    ).fetchall()
    if not rows:
        return []
    blocks = defaultdict(list)
    for number, name, k, diff in rows:
        blocks[name].append((number, k, diff))
    buckets = defaultdict(lambda: defaultdict(list))
    for name, items in blocks.items():
        avg = mean(d for _n, _k, d in items)
        for number, k, diff in items:
            resid = diff - avg
            floor = "2F" if str(number).startswith("2") else "3F"
            seg = segment_of(name)
            for key in ("全館", seg, floor + "全体"):
                buckets[key][k].append(resid)
            if seg == "AT等":
                buckets["AT@" + floor][k].append(resid)

    out = []
    for segment, groups in buckets.items():
        usable = {k: v for k, v in groups.items() if len(v) >= KAKUBAN_PARAMS["min_per_rank"]}
        if len(usable) < 3:
            continue
        means = {k: mean(v) for k, v in usable.items()}
        peak = max(means, key=means.get)
        for k, value in means.items():
            out.append({"segment": segment, "item": "角%s" % k, "value_num": round(value, 1), "n": len(usable[k])})
        out.append(
            {
                "segment": segment,
                "item": "peak",
                "value_text": "角%s" % peak,
                "value_num": round(means[peak], 1),
                "n": sum(len(v) for v in usable.values()),
            }
        )
    return out


def narabi_rows(connection, date):
    from backtest.narabi import find_blocks, load_day

    machines = load_day(connection, date)
    if not machines:
        return []
    blocks = find_blocks(machines, NARABI_PARAMS["block_size"], NARABI_PARAMS["block_mean_threshold"])
    seg_counts = defaultdict(int)
    for b in blocks:
        seg_counts["＋".join(b["segments"])] += 1
    rows = [{"segment": "", "item": "count", "value_num": len(blocks), "n": len(machines)}]
    for segment, count in seg_counts.items():
        rows.append({"segment": segment, "item": "count", "value_num": count, "n": len(machines)})
    for b in blocks:
        rows.append(
            {
                "segment": "＋".join(b["segments"]),
                "item": "block_%d" % b["start"],
                "value_num": round(b["mean_diff"], 1),
                "value_text": "/".join(n[:20] for n in b["names"]),
                "n": NARABI_PARAMS["block_size"],
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="20260601")
    parser.add_argument("--halls", default="", help="カンマ区切り。既定は db/ の全ホール")
    args = parser.parse_args()

    st = store.connect()
    kaku_id = store.register_definition(
        st,
        "kakuban_residual",
        "v1",
        KAKUBAN_PARAMS,
        "角番別の残差平均とピーク。残差は同日同機種の平均差枚を引いたもの。",
    )
    narabi_id = store.register_definition(
        st, "narabi_blocks", "v1", NARABI_PARAMS, "連番4台ブロックの成立数。閾値は 2026-09-08 の予告登録時に凍結。"
    )

    halls = [h.strip() for h in args.halls.split(",") if h.strip()]
    if not halls:
        halls = [
            p.stem
            for p in sorted(DB_DIR.glob("*.db"))
            if p.stem not in {"pachinko", "pachinko_data", "poco_analysis", "楽園転田店", "analysis_results"}
        ]
    total = 0
    for hall in halls:
        path = DB_DIR / (hall + ".db")
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            dates = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT date FROM machine_detailed_results WHERE date>=? ORDER BY date", (args.since,)
                )
            ]
        except sqlite3.Error:
            con.close()
            continue
        written = 0
        for date in dates:
            for definition_id, rows in ((kaku_id, kakuban_rows(con, date)), (narabi_id, narabi_rows(con, date))):
                if rows:
                    written += store.put_values(st, hall, date, definition_id, rows)
        con.close()
        print("%-32s %3d日  %5d行" % (hall, len(dates), written))
        total += written
    print("\n合計 %d 行" % total)
    st.close()


if __name__ == "__main__":
    raise SystemExit(main())
