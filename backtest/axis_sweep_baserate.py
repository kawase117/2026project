# -*- coding: utf-8 -*-
"""軸スイープ（機種/列/末尾/角番/フロア×交互作用）のベースレートと再現性を測る。

なぜ要るか
----------
`scraper/site777/site777_live_brief.py` の軸スイープは、1日のデータに 4指標×7軸 = 28検定をかける。
★(p<0.05) が出ても、毎日どこかに同じくらい立つなら無情報である。判断が変わるのは次の3つ。

  1. ★が出る割合（軸ごとの日次ベースレート）
  2. 当日の最強グループが翌日も最強な率（= 翌日の予測に使えるか）
  3. 再現したときの実効幅（枚）

これを測らずに★を「発見」と呼ぶと、ベースレート不明の主張が積み上がる。
2026-09-16 の楽園蒲田で実際にそれをやったので、フルデイのDBで測り直すために書いた。

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.axis_sweep_baserate --hall 楽園蒲田店 --days 90
    venv/Scripts/python.exe -X utf8 -m backtest.axis_sweep_baserate --all-halls --days 60 --iters 200

出力は標準出力と、--output を渡せば markdown。
"""

from __future__ import annotations

import argparse
import math
import os
import sqlite3
import statistics as st
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DB_DIR = os.path.join(ROOT, "db")
MIN_GAMES = 1000
MIN_N_DEFAULT = 3
ITERS_DEFAULT = 200

AXES = ("機種", "列", "末尾", "角番", "フロア", "機種×列", "機種×末尾", "機種×角番")


def load_rows(conn, since, min_games):
    """日付ごとの配置（valid_from/valid_to）で列・角番を引く。改装をまたいでも正しく割り当てる。"""
    query = """
        select m.date, m.machine_number, m.machine_name,
               m.diff_coins_normalized, m.games_normalized, m.bb_count, m.rb_count,
               l.section, l.rank_from_min, l.rank_from_max
        from machine_detailed_results as m
        join machine_layout_history as l
          on l.machine_number = cast(m.machine_number as int)
         and m.date >= l.valid_from
         and (l.valid_to is null or m.date <= l.valid_to)
        where m.date >= ? and m.games_normalized >= ?
    """
    by_date = defaultdict(list)
    for date, number, name, diff, games, _bb, rb, section, rank_min, rank_max in conn.execute(
        query, (since, min_games)
    ):
        by_date[date].append(
            dict(
                n=int(number),
                name=name,
                d=float(diff),
                g=float(games),
                rb=rb or 0,
                sec=section,
                tail=int(number) % 10,
                kaku=min(rank_min or 99, rank_max or 99),
                floor=str(number)[0] + "F",
            )
        )
    return by_date


def axis_key(axis, row):
    if axis == "機種":
        return row["name"]
    if axis == "列":
        return row["sec"]
    if axis == "末尾":
        return row["tail"]
    if axis == "角番":
        return row["kaku"]
    if axis == "フロア":
        return row["floor"]
    if axis == "機種×列":
        return (row["name"], row["sec"])
    if axis == "機種×末尾":
        return (row["name"], row["tail"])
    if axis == "機種×角番":
        return (row["name"], row["kaku"])
    raise ValueError(axis)


def best_group(values, codes, n_codes, min_n):
    counts = np.bincount(codes, minlength=n_codes)
    sums = np.bincount(codes, weights=values, minlength=n_codes)
    eligible = counts >= min_n
    if not eligible.any():
        return None, None, None
    means = np.where(eligible, sums / np.maximum(counts, 1), -np.inf)
    idx = int(np.argmax(means))
    return idx, float(means[idx]), int(counts[idx])


def permutation_p(values, codes, n_codes, min_n, model_blocks, within_model, rng, iters):
    """最大統計量の並べ替え検定。within_model なら機種内でラベルを入れ替える。"""
    _, observed, _ = best_group(values, codes, n_codes, min_n)
    if observed is None:
        return None
    hits = 0
    work = codes.copy()
    for _ in range(iters):
        if within_model:
            for block in model_blocks:
                if block.size > 1:
                    work[block] = rng.permutation(codes[block])
        else:
            work = rng.permutation(codes)
        _, maximum, _ = best_group(values, work, n_codes, min_n)
        if maximum is not None and maximum >= observed:
            hits += 1
    return (hits + 1) / (iters + 1)


def sweep_day(rows, rng, iters, min_n):
    """1日分。戻り値は {(指標, 軸): (p, 最強グループ, n, 平均)}"""
    names = [r["name"] for r in rows]
    model_index = defaultdict(list)
    for i, name in enumerate(names):
        model_index[name].append(i)
    model_blocks = [np.asarray(v) for v in model_index.values()]

    diff = np.asarray([r["d"] for r in rows], dtype=float)
    games = np.asarray([r["g"] for r in rows], dtype=float)
    model_mean_diff = {k: st.mean(diff[v]) for k, v in model_index.items()}
    model_mean_games = {k: st.mean(games[v]) for k, v in model_index.items()}
    diff_res = np.asarray([r["d"] - model_mean_diff[r["name"]] for r in rows], dtype=float)
    games_res = np.asarray([r["g"] - model_mean_games[r["name"]] for r in rows], dtype=float)
    diff_hall = diff - float(np.median(diff))

    metrics = (
        ("差枚残差", diff_res, True),
        ("差枚ホール比", diff_hall, False),
        ("回転数残差", games_res, True),
    )
    result = {}
    for metric_name, values, within in metrics:
        for axis in AXES:
            if within and axis == "機種":
                continue
            if not within and axis.startswith("機種×"):
                continue
            keys = [axis_key(axis, r) for r in rows]
            uniq = {}
            codes = np.empty(len(rows), dtype=int)
            for i, key in enumerate(keys):
                codes[i] = uniq.setdefault(key, len(uniq))
            inverse = {v: k for k, v in uniq.items()}
            idx, mean, count = best_group(values, codes, len(uniq), min_n)
            if idx is None:
                continue
            pval = permutation_p(values, codes, len(uniq), min_n, model_blocks, within, rng, iters)
            result[(metric_name, axis)] = (pval, inverse[idx], count, mean, len(uniq))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hall", default="楽園蒲田店")
    parser.add_argument("--all-halls", action="store_true")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--iters", type=int, default=ITERS_DEFAULT)
    parser.add_argument("--min-n", type=int, default=MIN_N_DEFAULT)
    parser.add_argument("--since", default=None, help="YYYYMMDD。既定は最新日から --days 遡る")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    halls = []
    if args.all_halls:
        for fname in sorted(os.listdir(DB_DIR)):
            if fname.endswith(".db") and not fname.endswith(".bak") and "analysis" not in fname:
                halls.append(fname[:-3])
    else:
        halls = [args.hall]

    lines = []
    for hall in halls:
        path = os.path.join(DB_DIR, hall + ".db")
        if not os.path.exists(path):
            continue
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            newest = conn.execute("select max(date) from machine_detailed_results").fetchone()[0]
        except sqlite3.Error:
            continue
        if not newest:
            continue
        since = args.since
        if not since:
            year, month, day = int(newest[:4]), int(newest[4:6]), int(newest[6:])
            import datetime

            since = (datetime.date(year, month, day) - datetime.timedelta(days=args.days)).strftime("%Y%m%d")
        by_date = load_rows(conn, since, MIN_GAMES)
        dates = sorted(d for d, rows in by_date.items() if len(rows) >= 100)
        if len(dates) < 20:
            lines.append("## %s：日数不足（%d日）" % (hall, len(dates)))
            continue
        rng = np.random.default_rng(0)
        per_day = {}
        for date in dates:
            per_day[date] = sweep_day(by_date[date], rng, args.iters, args.min_n)

        stats = defaultdict(lambda: dict(n=0, star=0, repeat=0, repeat_chance=0.0, pairs=0, next_value=[], cand=[]))
        for i, date in enumerate(dates):
            for key, (pval, group, count, mean, n_cand) in per_day[date].items():
                cell = stats[key]
                cell["n"] += 1
                cell["cand"].append(n_cand)
                if pval is not None and pval < 0.05:
                    cell["star"] += 1
                if i + 1 < len(dates):
                    nxt = per_day[dates[i + 1]].get(key)
                    if nxt:
                        cell["pairs"] += 1
                        cell["repeat_chance"] += 1.0 / max(n_cand, 1)
                        if nxt[1] == group:
                            cell["repeat"] += 1
                        # 当日の最強グループが翌日に出した値
                        rows_next = by_date[dates[i + 1]]
                        axis = key[1]
                        vals = [r for r in rows_next if axis_key(axis, r) == group]
                        if vals:
                            if key[0] == "回転数残差":
                                mm = defaultdict(list)
                                for r in rows_next:
                                    mm[r["name"]].append(r["g"])
                                mu = {k: st.mean(v) for k, v in mm.items()}
                                cell["next_value"].append(st.mean(r["g"] - mu[r["name"]] for r in vals))
                            elif key[0] == "差枚残差":
                                mm = defaultdict(list)
                                for r in rows_next:
                                    mm[r["name"]].append(r["d"])
                                mu = {k: st.mean(v) for k, v in mm.items()}
                                cell["next_value"].append(st.mean(r["d"] - mu[r["name"]] for r in vals))
                            else:
                                med = st.median([r["d"] for r in rows_next])
                                cell["next_value"].append(st.mean(r["d"] - med for r in vals))

        lines.append(
            "## %s（%s〜%s、%d日、並べ替え%d回、min_n=%d）"
            % (hall, dates[0], dates[-1], len(dates), args.iters, args.min_n)
        )
        lines.append("")
        lines.append("| 指標 | 軸 | ★率(p<0.05) | 翌日も同じグループ | 偶然なら | 翌日の実効値 | 候補数 |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for key in sorted(stats, key=lambda k: -stats[k]["star"] / max(stats[k]["n"], 1)):
            cell = stats[key]
            star_rate = 100.0 * cell["star"] / cell["n"]
            repeat = 100.0 * cell["repeat"] / cell["pairs"] if cell["pairs"] else float("nan")
            chance = 100.0 * cell["repeat_chance"] / cell["pairs"] if cell["pairs"] else float("nan")
            nextv = st.mean(cell["next_value"]) if cell["next_value"] else float("nan")
            lines.append(
                "| %s | %s | %.0f%% (%d/%d) | %.0f%% | %.0f%% | %+.0f | %.0f |"
                % (key[0], key[1], star_rate, cell["star"], cell["n"], repeat, chance, nextv, st.mean(cell["cand"]))
            )
        lines.append("")

    text = "\n".join(lines)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write("# 軸スイープのベースレートと再現性\n\n" + text + "\n")
        print("[OK] -> %s" % args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
