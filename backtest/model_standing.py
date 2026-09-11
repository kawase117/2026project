# -*- coding: utf-8 -*-
"""機種がその店でどう扱われているかの一覧。

なぜ要るか
----------
同じ機種でも店によって扱いが正反対になる。2026-09-11 の実測（8ホール、4店以上に
ある70機種）では、機種の強さのうち **約52%がスペック、約48%がその店の方針**だった。

    からくりサーカス2   みとや 99% / 雑色 96%  ⇔  蒲田7 10% / ヒロキ 3%
    沖ドキ!DUO アンコール  平和島 87%          ⇔  楽園 4%
    やじきた道中記参る！   ARROW 100%         ⇔  平和島 3%

「沖ドキDUOは平和島なら打つが楽園では打たない」という判断は、スペック表からは
出てこない。この店のこの機種、という形でしか持てない。

指標
----
`edge` = その機種の差枚 − 同じ日のホール全体の平均差枚（台×日の行を等重み）。
出率は使わない。台日で単純平均すると少回転台の分母が小さく暴れ、その振れを拾う
（順位づけの実測比較で 差枚選び +117枚 / 出率選び +87枚）。

窓は既定60日。日単位ではこの持続性はゼロ（前日→当日の相関 0.03）だが、
月単位では 0.20〜0.62 ある。窓を長くするほど良くなり 60〜120日で頭打ちになるので、
最大値は取らず、方針変更への追随を優先して 60 を既定にしている
（instinct: model-strength-persists-by-term-not-by-day）。

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.model_standing hall "楽園蒲田店"
    venv/Scripts/python.exe -X utf8 -m backtest.model_standing model "沖ドキ!DUO アンコール"
    venv/Scripts/python.exe -X utf8 -m backtest.model_standing spread
"""

import argparse
import io
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(ROOT, "db")
sys.path.insert(0, ROOT)

WINDOW_DAYS = 60
MIN_MACHINE_DAYS = 30  # 窓内でこれ未満しか台日が無い機種は順位に載せない
MIN_MACHINES = 3  # 1〜2台設置の機種は機種平均が台の個性と区別できない
MIN_GAMES = 500
NOT_A_HALL = {"analysis_results", "machine_master"}


def short(hall):
    """一覧に並べるための短いホール名。

    「マルハンメガシティ2000-蒲田1」と「-蒲田7」は先頭14文字が同じで、
    頭を切り詰めるとどちらか分からなくなる。区別が付くのは末尾なので後ろを残す。
    """
    name = str(hall)
    if name.endswith("店"):
        name = name[:-1]
    if "-" in name:
        name = name.rsplit("-", 1)[-1]
    return name[:8]


def hall_names():
    """db/ 配下で machine_detailed_results を持つファイルだけを返す。

    db/ には実験用・集計用の .db も混ざっている。名前で弾くと取りこぼすので
    テーブルの有無で判定する。
    """
    names = []
    for filename in sorted(os.listdir(DB_DIR)):
        if not filename.endswith(".db"):
            continue
        name = os.path.splitext(filename)[0]
        if name in NOT_A_HALL:
            continue
        try:
            with sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, filename), uri=True) as conn:
                found = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='machine_detailed_results'"
                ).fetchone()
        except sqlite3.Error:
            continue
        if found:
            names.append(name)
    return names


def standing(hall, as_of=None, window=WINDOW_DAYS):
    """1ホールぶんの機種一覧を返す。as_of を含む直近 window 日を見る。"""
    path = os.path.join(DB_DIR, hall + ".db")
    if not os.path.exists(path):
        return None
    with sqlite3.connect("file:%s?mode=ro" % path, uri=True) as conn:
        if as_of is None:
            as_of = conn.execute("SELECT MAX(date) FROM machine_detailed_results").fetchone()[0]
        if not as_of:
            return None
        since = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=window - 1)).strftime("%Y%m%d")
        df = pd.read_sql(
            "SELECT date, machine_number, machine_name, games_normalized AS games, "
            "       diff_coins_normalized AS diff, bb_count, rb_count "
            "  FROM machine_detailed_results "
            " WHERE date BETWEEN ? AND ? AND games_normalized >= ?",
            conn,
            params=(since, as_of, MIN_GAMES),
        )
        try:
            judgeable = {
                row[0]
                for row in conn.execute("SELECT machine_name_normalized FROM machine_master WHERE bonus_judgeable = 1")
            }
        except sqlite3.Error:
            judgeable = set()
    if df.empty:
        return None

    df["edge"] = df["diff"] - df.groupby("date")["diff"].transform("mean")
    grouped = df.groupby("machine_name").agg(
        edge=("edge", "mean"),
        machine_days=("edge", "size"),
        machines=("machine_number", "nunique"),
        games=("games", "mean"),
        bb=("bb_count", "sum"),
        rb=("rb_count", "sum"),
        total_games=("games", "sum"),
    )
    out = grouped[(grouped.machine_days >= MIN_MACHINE_DAYS) & (grouped.machines >= MIN_MACHINES)].copy()
    if out.empty:
        return None
    out["games_ratio"] = out["games"] / df["games"].mean()
    out["bonus_rate"] = (out.bb + out.rb) / out.total_games
    out["judgeable"] = out.index.isin(judgeable)
    out["pct"] = out.edge.rank(pct=True)
    out["hall"] = hall
    out["as_of"] = as_of
    return out.sort_values("edge", ascending=False)


def all_halls(window=WINDOW_DAYS):
    """全ホールを縦に並べる。

    as_of はホールごとに自分の最終収録日を使う。取り込みの進み方が店で違うため
    一律の日付を渡すと、遅れている店だけ窓が短くなって順位が不当に振れる。
    順位（pct）はホール内で取るので、日付が数日ずれていても比較は成立する。
    """
    frames = [s for s in (standing(h, None, window) for h in hall_names()) if s is not None]
    if not frames:
        return None
    return pd.concat(frames).reset_index()


def print_hall(hall, window=WINDOW_DAYS, top=12):
    s = standing(hall, window=window)
    if s is None:
        print("   （データが足りない）")
        return
    print("=" * 78)
    print("  %s  直近%d日（%s まで）  %d機種" % (hall, window, s.as_of.iloc[0], len(s)))
    print("=" * 78)
    print("\n【打つ側】")
    _rows(s.head(top))
    print("\n【避ける側】")
    _rows(s.tail(6).iloc[::-1])
    print("\n  差枚 = 同じ日のホール平均との差。回転数比 = ホール平均に対する回り方")
    print("  ボーナス = 設定を判別できる機種のみ（ノーマル/BT/A+AT）")


def _rows(frame):
    print("   %-30s%9s%7s%8s%9s%10s" % ("機種", "差枚", "位置", "台数", "回転数比", "ボーナス"))
    for name, r in frame.iterrows():
        bonus = "1/%.0f" % (1 / r.bonus_rate) if r.judgeable and r.bonus_rate > 0 else "-"
        print(
            "   %-30s%+9.0f%6.0f%%%8d%9.2f%10s"
            % (str(name)[:30], r.edge, 100 * r.pct, r.machines, r.games_ratio, bonus)
        )


def print_model(model, window=WINDOW_DAYS):
    a = all_halls(window=window)
    if a is None:
        print("   （データが足りない）")
        return
    hit = a[a.machine_name.astype(str).str.contains(model, regex=False, na=False)]
    if hit.empty:
        print("   『%s』に一致する機種が、どのホールでも条件を満たしていない" % model)
        return
    for name, g in hit.groupby("machine_name"):
        print("\n■ %s  （直近%d日、%d店）" % (name, window, len(g)))
        print("   %-28s%9s%7s%8s%9s" % ("ホール", "差枚", "位置", "台数", "回転数比"))
        for _, r in g.sort_values("pct", ascending=False).iterrows():
            print("   %-28s%+9.0f%6.0f%%%8d%9.2f" % (short(r.hall), r.edge, 100 * r.pct, r.machines, r.games_ratio))
        if len(g) >= 3:
            spread = 100 * (g.pct.max() - g.pct.min())
            verdict = "店によって扱いが違う" if spread >= 50 else "どの店でも似た扱い"
            print("   → 位置の開き %.0f ポイント: %s" % (spread, verdict))


def print_spread(window=WINDOW_DAYS, min_halls=3, top=15):
    """店によって扱いが大きく違う機種。ここが「店を間違えると真逆」になる機種。"""
    a = all_halls(window=window)
    if a is None:
        print("   （データが足りない）")
        return
    g = a.groupby("machine_name").agg(lo=("pct", "min"), hi=("pct", "max"), halls=("pct", "size"))
    g = g[g.halls >= min_halls]
    g["spread"] = g.hi - g.lo
    print("■ 店によって扱いが違う機種（%d店以上に設置、直近%d日）" % (min_halls, window))
    print("   開きが大きいほど、店を間違えると結果が真逆になる\n")
    for name, r in g.sort_values("spread", ascending=False).head(top).iterrows():
        detail = a[a.machine_name == name].sort_values("pct", ascending=False)
        line = "  ".join("%s %.0f%%" % (short(h), 100 * p) for h, p in zip(detail.hall, detail.pct))
        print("   %-26s 開き %3.0f\n      %s" % (str(name)[:26], 100 * r.spread, line))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_hall = sub.add_parser("hall", help="1ホールの機種一覧")
    p_hall.add_argument("hall")
    p_hall.add_argument("--window", type=int, default=WINDOW_DAYS)
    p_model = sub.add_parser("model", help="1機種が各ホールでどう扱われているか")
    p_model.add_argument("model")
    p_model.add_argument("--window", type=int, default=WINDOW_DAYS)
    p_spread = sub.add_parser("spread", help="店によって扱いが違う機種")
    p_spread.add_argument("--window", type=int, default=WINDOW_DAYS)
    p_spread.add_argument("--min-halls", type=int, default=3)
    args = parser.parse_args()

    if args.cmd == "hall":
        print_hall(args.hall, args.window)
    elif args.cmd == "model":
        print_model(args.model, args.window)
    else:
        print_spread(args.window, args.min_halls)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
