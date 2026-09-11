# -*- coding: utf-8 -*-
"""1ホールの日付条件を、カテゴリ → 機種 → 台番号 と掘り下げる。

なぜ要るか
----------
`date_conditions.py` はホール×条件の全期間集計までしか出さない。2026-09-11 に
蒲田1のA+ATを手で掘ったところ、**全期間の集計が3つの意味で嘘をつく**と分かった。

1. **レジーム変化を隠す。** レヴュースタァライトの月末は全期間 +7.78%(4.8σ) だが、
   四半期で割ると 2025Q3 +16.0% → Q4 +18.5% → 2026Q1 **-11.2%** → Q2 **-7.0%**。
   2026年に入って反転していた。全期間の数字は過去の遺物だった。
2. **撤去済みの機種を混ぜる。** 蒲田1のBTは主力2機種(合計4.2M回転)が
   2026年3月・4月に撤去済み。残りは1台ずつの寄せ集めで、全期間の数字は
   もう存在しない設置構成のもの。
3. **台に割った瞬間、判断できなくなる。** レヴューの現存1台(2139)はゾロ目日
   8台日・-1.0σ。「悪い」ではなく「分からない」だが、断定しかけた。

判定に埋め込んだ規則（今日踏んだ罠から）
----------------------------------------
- **符号反転だけで棄却しない。** 前半→後半の反転はレジーム変化でもある。
  蒲田1は 2026-08-25 店長交代・09-01 投入方針変更があり、実際に動いている。
  判定は「直近が効いているか」で行い、過去との一致は求めない
- **全期間 σ が大きくても、直近2四半期が反転していれば `失効`。** 採用しない
- **台数が少ないことを棄却の理由にしない。** 1台でも法則があれば狙い台。
  ただし台日が足りなければ `判断不能` であって `回避` ではない
- **ボーナスが増えて差枚が減るセルに印を付ける。** 蒲田1のBTは強ゾロ目
  +4.77% で差枚 +42枚（同じ上振れのノーマルは +216枚）。設定が入っていることと
  勝てることは別

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.condition_drilldown "マルハンメガシティ2000-蒲田1"
    venv/Scripts/python.exe -X utf8 -m backtest.condition_drilldown "楽園蒲田店" --category ノーマル
    venv/Scripts/python.exe -X utf8 -m backtest.condition_drilldown "楽園蒲田店" --seats
"""

import argparse
import io
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(ROOT, "db")
sys.path.insert(0, ROOT)

from backtest.date_conditions import CATEGORIES, CONDITIONS  # noqa: E402

MIN_GAMES = 500
MIN_CELL_GAMES = 30_000  # 条件側がこれ未満のセルは測らない
MIN_CELL_DAYS = 15  # 台日がこれ未満なら σ が出ても判断不能とする
STRONG_Z = 2.0
RECENT_QUARTERS = 2  # 「直近」とみなす四半期数


def load(hall, category=None):
    path = os.path.join(DB_DIR, hall + ".db")
    if not os.path.exists(path):
        return None, None
    with sqlite3.connect("file:%s?mode=ro" % path, uri=True) as conn:
        query = "SELECT machine_name_normalized FROM machine_master WHERE bonus_judgeable = 1"
        params = ()
        if category is not None:
            query += " AND spec_category = ?"
            params = (category,)
        try:
            wanted = [row[0] for row in conn.execute(query, params)]
        except sqlite3.Error:
            return None, None
        frame = pd.read_sql(
            "SELECT date, machine_number, machine_name, games_normalized AS games, "
            "       diff_coins_normalized AS diff, bb_count, rb_count "
            "  FROM machine_detailed_results WHERE games_normalized >= ?",
            conn,
            params=(MIN_GAMES,),
        )
    if frame.empty:
        return None, None
    # edge はホール全体（判別可能機種に限らない全台）の同日平均を基準にする。
    # 「その日そのホールで適当に座った場合」との差でないと、実戦の比較にならない。
    frame["edge"] = frame["diff"] - frame.groupby("date")["diff"].transform("mean")
    last_day = frame.date.max()
    installed = frame[frame.date == last_day]
    sub = frame[frame.machine_name.isin(wanted)].copy()
    if sub.empty:
        return None, None
    sub["bonus"] = sub.bb_count + sub.rb_count
    sub["ts"] = pd.to_datetime(sub.date, format="%Y%m%d")
    sub["quarter"] = sub.ts.dt.to_period("Q")
    return sub, installed


def cell(sub, mask, min_games=MIN_CELL_GAMES):
    """条件側 vs それ以外。(上振れ%, σ, 差枚差, 台日, 条件側回転数) か None。

    ⚠️ **機種をまとめて割ってはいけない。** 機種ごとにボーナス確率の基準が違うので、
    設置構成が入れ替わるだけで比が動く。機種ごとに「自分の非条件日の確率」から
    期待値を出し、それを足し上げてから比べる。雑色のA+AT月末はこれを怠ると
    +15.47% と出るが、直すと +4.02% になる（差は全部構成の変化）。
    """
    hit, rest = sub[mask], sub[~mask]
    g_hit, g_rest = hit.games.sum(), rest.games.sum()
    if g_hit < min_games or g_rest < min_games:
        return None
    base_by_model = rest.groupby("machine_name").apply(
        lambda g: g.bonus.sum() / g.games.sum() if g.games.sum() else np.nan, include_groups=False
    )
    per_model_games = hit.groupby("machine_name").games.sum()
    shared = per_model_games.index.intersection(base_by_model.dropna().index)
    if shared.empty:
        return None
    expected = float((per_model_games[shared] * base_by_model[shared]).sum())
    observed = float(hit.loc[hit.machine_name.isin(shared), "bonus"].sum())
    games_used = float(per_model_games[shared].sum())
    if expected <= 0 or games_used <= 0:
        return None
    base = expected / games_used
    lift = 100 * (observed / games_used / base - 1)
    z = (observed - expected) / np.sqrt(expected * (1 - base))
    return lift, z, hit.edge.mean() - rest.edge.mean(), len(hit), int(games_used)


def verdict(sub, mask, quarters):
    """採用 / 失効 / 要確認 / 回避 / 要注意 / 判断不能 を返す。

    直近の確認は「最後の N 四半期」ではなく「**測れた四半期のうち最後の N 個**」で行う。
    カレンダー基準にすると、台数が減って回転数が落ちた機種ほど確認セルが埋まらず、
    失効判定をすり抜ける。データが細っている機種こそ死にかけているので、
    そこを見逃すのがいちばんまずい（レヴュースタァライトの月末で実際に起きた）。
    """
    whole = cell(sub, mask)
    if whole is None:
        return "判断不能", None, "回転数不足"
    lift, z, coins, days, _ = whole
    if days < MIN_CELL_DAYS:
        return "判断不能", whole, "台日 %d" % days

    measured = []
    for q in quarters:
        part = sub[sub.quarter == q]
        if part.empty:
            continue
        got = cell(part, mask.loc[part.index], min_games=10_000)
        if got:
            measured.append((q, got[0]))
    if len(measured) < RECENT_QUARTERS:
        # 直近が生きているか確かめられない。全期間の数字だけで採用してはいけない。
        return "要確認", whole, "四半期で確認できるのが%d期だけ" % len(measured)

    recent = [v for _, v in measured[-RECENT_QUARTERS:]]
    stale = measured[-1][0] != quarters[-1]
    if all(v < 0 for v in recent) and lift > 0:
        return "失効", whole, "測れた直近%d期が反転" % RECENT_QUARTERS
    if z <= -STRONG_Z and coins < 0:
        return "回避", whole, ""
    if z < STRONG_Z:
        return "判断不能", whole, "%.1fσ" % z
    if coins <= 0:
        # ボーナスは増えているのに枚数が付いてこない。設定と勝ちは別。
        return "要注意", whole, "ボーナス↑だが差枚 %+.0f枚" % coins
    if stale:
        return "要確認", whole, "最後に測れたのが %s" % measured[-1][0]
    return "採用", whole, ""


def report(hall, category=None, seats=False):
    categories = [category] if category else list(CATEGORIES)
    print("=" * 78)
    print("  %s  日付条件の掘り下げ" % hall)
    print("=" * 78)
    for cat in categories:
        sub, installed = load(hall, cat)
        if sub is None:
            print("\n■ %s — データなし" % cat)
            continue
        last_day = installed.date.max()
        live = set(installed.machine_name)
        print("\n" + "─" * 78)
        print(
            "■ %s   %d機種 / %.2fM回転 / %s 時点" % (cat, sub.machine_name.nunique(), sub.games.sum() / 1e6, last_day)
        )

        # 1) 設置の顔ぶれ。撤去済みが混ざっていないかを最初に見る。
        rows = []
        for name, g in sub.groupby("machine_name"):
            n_now = installed.loc[installed.machine_name == name, "machine_number"].nunique()
            rows.append(
                (
                    name,
                    g.games.sum(),
                    g.date.min(),
                    g.date.max(),
                    g.edge.mean(),
                    "%d台" % n_now if name in live else "撤去",
                )
            )
        rows.sort(key=lambda r: -r[1])
        print("   %-30s%9s%20s%9s%8s" % ("機種", "総回転", "在籍", "差枚", "現在"))
        for name, games, first, last, edge, now in rows:
            print(
                "   %-30s%8.2fM%20s%+9.0f%8s"
                % (str(name)[:30], games / 1e6, "%s〜%s" % (first[2:], last[2:]), edge, now)
            )

        # 2) 四半期推移。全期間の集計に騙されないための本体。
        quarters = sorted(sub.quarter.unique())
        print("\n   四半期ごとの上振れ%")
        print("   %-10s" % "" + "".join("%11s" % c for c in CONDITIONS) + "%9s" % "回転")
        for q in quarters:
            part = sub[sub.quarter == q]
            cells = []
            for label, test in CONDITIONS.items():
                got = cell(part, part.ts.map(test), min_games=10_000)
                cells.append("%11s" % ("-" if got is None else "%+.1f%%" % got[0]))
            print("   %-10s" % str(q) + "".join(cells) + "%9s" % ("%.2fM" % (part.games.sum() / 1e6)))

        # 3) カテゴリ全体の判定
        print("\n   %-10s%12s%8s%10s%8s%12s%s" % ("条件", "上振れ", "σ", "差枚差", "台日", "判定", "  補足"))
        for label, test in CONDITIONS.items():
            mask = sub.ts.map(test)
            state, got, note = verdict(sub, mask, quarters)
            if got is None:
                print("   %-10s%12s%8s%10s%8s%12s  %s" % (label, "-", "-", "-", "-", state, note))
                continue
            lift, z, coins, days, _ = got
            print("   %-10s%+11.2f%%%8.1f%+10.0f%8d%12s  %s" % (label, lift, z, coins, days, state, note))

        # 4) 現存機種だけ、機種別に。撤去済みは載せない（座れないので判断に要らない）。
        live_models = [n for n, *_, now in rows if now != "撤去"]
        if live_models:
            print("\n   現存機種のみ（撤去済みは載せない）")
        for name in live_models:
            part = sub[sub.machine_name == name]
            hits = []
            for label, test in CONDITIONS.items():
                mask = part.ts.map(test)
                state, got, note = verdict(part, mask, quarters)
                if got is None:
                    continue
                hits.append((label, state, got, note))
            if not hits:
                print("   ・%-28s （回転数不足で測れない）" % str(name)[:28])
                continue
            print("   ・%s" % name)
            for label, state, (lift, z, coins, days, _), note in hits:
                print("       %-10s%+11.2f%%%8.1f%+10.0f%8d%12s  %s" % (label, lift, z, coins, days, state, note))

        # 5) 台番号まで割る。割ると判断不能になることが多いので既定では出さない。
        if seats:
            print("\n   現存機種を台番号で分解（多くは判断不能になる。それを隠さない）")
            for name in live_models:
                part = sub[sub.machine_name == name]
                for mn, g in part.groupby("machine_number"):
                    if mn not in set(installed.machine_number):
                        continue
                    line = []
                    for label, test in CONDITIONS.items():
                        got = cell(g, g.ts.map(test), min_games=10_000)
                        if got is None:
                            continue
                        flag = "" if abs(got[1]) >= STRONG_Z and got[3] >= MIN_CELL_DAYS else "?"
                        line.append("%s %+.1f%%(%.1fσ,%d日)%s" % (label, got[0], got[1], got[3], flag))
                    print("       台%-6d %-24s %s" % (mn, str(name)[:24], "  ".join(line) if line else "測れない"))
            print("       ? = σ<2 または台日<%d で判断不能。『悪い』ではない" % MIN_CELL_DAYS)

    print("\n" + "─" * 78)
    print("  採用    測れた直近%d期が反転しておらず σ>=2 かつ差枚差プラス" % RECENT_QUARTERS)
    print("  要確認  直近を確認できない（回転数が落ちて四半期のセルが埋まらない）。")
    print("          台数を削られた機種ほどここに落ちる。全期間の数字だけで採用しない")
    print("  失効    全期間はプラスだが直近%d四半期が反転。過去の遺物なので使わない" % RECENT_QUARTERS)
    print("  回避    σ<=-2 かつ差枚差マイナス")
    print("  要注意  ボーナスは増えているが差枚が付いてこない（設定と勝ちは別）")
    print("  判断不能 回転数・台日が足りない。『効果なし』ではない")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hall")
    parser.add_argument("--category", choices=CATEGORIES, help="1カテゴリだけ見る")
    parser.add_argument("--seats", action="store_true", help="台番号まで分解する")
    args = parser.parse_args()
    report(args.hall, args.category, args.seats)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
