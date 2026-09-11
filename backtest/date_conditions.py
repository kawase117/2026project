# -*- coding: utf-8 -*-
"""日付条件（ゾロ目・7のつく日・月末・土日など）が、その店で本当に効くか。

なぜ差枚ではなくボーナス確率か
------------------------------
条件で日を絞ると日数が激減する。強ゾロ目（1/1, 2/2 …）は20か月でわずか20日しかない。
差枚は20日では運に埋もれるが、ボーナス回数なら同じ20日でも数十万Gぶんの情報が残る。
2026-09-11 に差枚で測って「ゾロ目は判断できない」と結論しかけたが、指標を変えたら
8ホール中7で出た。**日数が少ない条件は差枚で測らないこと。**

対象は `bonus_judgeable = 1` の機種（ノーマル / BT / A+AT）のみ。現行設置の約36%。
AT機はボーナス確率で設定を割れないので、この測り方の対象外。

測り方
------
機種ごとに「条件日以外」のボーナス確率を自分の基準とし、条件日のボーナス回数が
そこから何σずれているかを二項分布で出す。日数の少なさは σ に正しく反映される。

⚠️ **σ は効果の大きさではない。** 回転数が多いほど大きく出る。判断には lift(%) を使う。
設定1→6 でボーナス確率はおおむね 15〜25% 上がるので、+4% は設定1段階ぶんに相当する。

何に使えて何に使えないか（2026-09-11 実測）
-------------------------------------------
**使える: どの日に行くか。** 強ゾロ目は8ホール中7でプラス（雑色 +5.0% / 蒲田7 +4.5% /
蒲田1 +2.5% …、平和島のみ -0.8%）。既知の知見も再現した（蒲田7の7のつく日・1のつく日・
月末がすべてプラス、楽園の土曜が -1.3% でマイナス）。

**使えない: どの機種を打つか。** 条件日に機種ごとの反応の差は確かに広がる
（同じ日数の無作為な日付を対照にして 48セル中21セルが有意）。しかし
**その内訳は繰り返さない。** 前半で見つけた機種×条件は後半でほぼ無相関
（曜日 -0.09〜+0.16）で、実際にルールへ足すと成績が下がる
（曜日 -79枚 [-150,-7]、日末尾 -88枚 [-159,-25]）。
機種の選択は [[model-strength-persists-by-term-not-by-day]] のまま、条件を足さない。

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.date_conditions table
    venv/Scripts/python.exe -X utf8 -m backtest.date_conditions day "楽園蒲田店" --date 20260912
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

from backtest.model_standing import hall_names, short  # noqa: E402

# 条件は「当日の日付だけで決まる」ものに限る。実績を見ないと決まらない条件を
# 混ぜると、朝の時点で使えないものが表に載ってしまう。
CONDITIONS = {
    "強ゾロ目": lambda ts: ts.month == ts.day,
    "ゾロ目日": lambda ts: ts.day in (11, 22),
    "7のつく日": lambda ts: ts.day % 10 == 7,
    "1のつく日": lambda ts: ts.day % 10 == 1,
    # ⚠️ 日付をハードコードしない。29日以上にすると2月末(28日)を取りこぼす。
    # 「月末ハードコード」は蒲田7のイベント日定義で繰り返し起きている不具合
    # （feedback: kamata7-event-day-definition-fix）。その月の実際の日数から取る。
    "月末": lambda ts: ts.day >= ts.days_in_month - 1,
    "土日": lambda ts: ts.weekday() >= 5,
}
MIN_DAYS = 10  # 条件日がこれ未満なら測らない
MIN_GAMES = 500
STRONG_LIFT = 1.0  # これ以上の lift(%) を「効く日」とみなす
STRONG_Z = 2.0


def _zscore(k_cond, g_cond, k_other, g_other):
    """条件日以外を基準にしたとき、条件日のボーナス回数が何σ上振れているか。"""
    if g_other <= 0 or g_cond <= 0:
        return np.nan
    p = k_other / g_other
    if not 0 < p < 1:
        return np.nan
    sd = np.sqrt(g_cond * p * (1 - p))
    return (k_cond - g_cond * p) / sd if sd > 0 else np.nan


def measure(hall, category=None):
    """1ホールぶん。条件ごとに lift(%) と σ と日数を返す。

    category を指定すると spec_category（ノーマル / BT / A+AT）で絞る。
    ホールはこの3つを別の役割で使っている（BTは10ホール中9で負、A+ATは
    ホールによって符号が逆）ので、まとめて測ると打ち消し合うことがある。
    """
    path = os.path.join(DB_DIR, hall + ".db")
    if not os.path.exists(path):
        return None
    with sqlite3.connect("file:%s?mode=ro" % path, uri=True) as conn:
        query = "SELECT machine_name_normalized FROM machine_master WHERE bonus_judgeable = 1"
        params = ()
        if category is not None:
            query += " AND spec_category = ?"
            params = (category,)
        try:
            judgeable = [row[0] for row in conn.execute(query, params)]
        except sqlite3.Error:
            return None
        if not judgeable:
            return None
        df = pd.read_sql(
            "SELECT date, machine_name, games_normalized AS games, bb_count, rb_count "
            "  FROM machine_detailed_results WHERE games_normalized >= ?",
            conn,
            params=(MIN_GAMES,),
        )
    df = df[df.machine_name.isin(judgeable)]
    if df.empty:
        return None
    df["bonus"] = df.bb_count + df.rb_count
    stamps = pd.to_datetime(df.date, format="%Y%m%d")

    rows = []
    for label, test in CONDITIONS.items():
        flag = stamps.map(test)
        days = df.loc[flag, "date"].nunique()
        if days < MIN_DAYS:
            continue
        # 機種をまとめて割ってはいけない。機種ごとにボーナス確率の基準が違うので、
        # 設置構成が入れ替わるだけで比が動く（機種数の少ない A+AT で実害が出た。
        # 雑色の月末が +15% と出たが、これは設定ではなく構成の変化だった）。
        # 機種ごとに「自分の非条件日の確率」から期待値を出し、それを足し上げて比べる。
        per = df.groupby([df.machine_name, flag]).agg(bonus=("bonus", "sum"), games=("games", "sum")).unstack()
        if ("games", True) not in per.columns or ("games", False) not in per.columns:
            continue
        per = per.dropna()
        base_rate = per[("bonus", False)] / per[("games", False)]
        expected = (per[("games", True)] * base_rate).sum()
        observed = per[("bonus", True)].sum()
        games_cond = per[("games", True)].sum()
        if expected <= 0 or games_cond <= 0:
            continue
        p_cond = observed / games_cond
        p_other = expected / games_cond
        rows.append(
            {
                "hall": hall,
                "category": category or "すべて",
                "condition": label,
                "days": int(days),
                "models": int(len(per)),
                "games": int(games_cond),
                "lift": 100 * (p_cond / p_other - 1),
                # 期待値は機種別の基準から積み上げたもの。分散も同じ期待値から取る。
                "z": (observed - expected) / np.sqrt(expected * (1 - p_other)),
            }
        )
    return pd.DataFrame(rows) if rows else None


CATEGORIES = ("ノーマル", "BT", "A+AT")
MIN_CONDITION_GAMES = 50_000  # 条件日側の総回転数がこれ未満のセルは数字を出さない


def all_halls(category=None):
    frames = [m for m in (measure(h, category) for h in hall_names()) if m is not None]
    return pd.concat(frames, ignore_index=True) if frames else None


def by_category():
    """ノーマル / BT / A+AT に分けた一覧。回転数が足りないセルは NaN にする。"""
    frames = [all_halls(c) for c in CATEGORIES]
    frames = [f for f in frames if f is not None]
    if not frames:
        return None
    a = pd.concat(frames, ignore_index=True)
    a.loc[a.games < MIN_CONDITION_GAMES, "lift"] = np.nan
    return a


def today_conditions(date):
    """その日付に当てはまる条件名。実績を見ないので朝の時点で確定する。"""
    ts = pd.Timestamp(date)
    return [label for label, test in CONDITIONS.items() if test(ts)]


def day_verdict(hall, date, category=None):
    """今日がこの店にとってどういう日か。(条件名, lift, σ, 日数) の並び。"""
    m = measure(hall, category)
    if m is None:
        return []
    applies = set(today_conditions(date))
    hit = m[m.condition.isin(applies)]
    return [(r.condition, r.lift, r.z, r.days) for r in hit.sort_values("lift", ascending=False).itertuples()]


def print_table():
    a = all_halls()
    if a is None:
        print("   （spec_category 未整備。database/migrate_machine_master_categories.py --apply）")
        return
    a["label"] = a.hall.map(short)
    print("■ 条件日のボーナス確率の上振れ（%）。判別可能機種のみ（ノーマル/BT/A+AT）")
    print(
        a.pivot(index="label", columns="condition", values="lift")
        .reindex(columns=list(CONDITIONS))
        .round(2)
        .to_string()
    )
    print("\n■ 同じものを σ で（測定の精度。効果の大きさではない）")
    print(
        a.pivot(index="label", columns="condition", values="z").reindex(columns=list(CONDITIONS)).round(1).to_string()
    )
    print("\n   条件日数:", a.groupby("condition").days.mean().reindex(list(CONDITIONS)).round(0).to_dict())
    print("   設定1→6 でボーナス確率は 15〜25%% 上がる。+%.0f%% で1段階ぶんの目安" % 4)
    print("   ⚠️ 日を選ぶのには使えるが、機種を選ぶのには使えない（機種別の差は繰り返さない）")


def print_by_category():
    """ノーマル / BT / A+AT に分けて出す。

    ⚠️ 回転数が桁で違う。ノーマルは条件日あたり 1,200万〜5,400万G あるが、
    BT は 18万〜380万G、A+AT は 12万〜1,500万G しかない。同じ「+4%」でも
    ノーマルなら実在、BT なら雑音ということが普通に起きる。**必ず σ と一緒に読む。**
    """
    a = by_category()
    if a is None:
        print("   （spec_category 未整備）")
        return
    a["label"] = a.hall.map(short)
    for category in CATEGORIES:
        sub = a[a.category == category]
        if sub.lift.notna().sum() == 0:
            print("\n■ %s — 回転数が足りず測れない" % category)
            continue
        print("\n■ %s   上振れ%% （σ）" % category)
        print("   %-14s" % "" + "".join("%14s" % c for c in CONDITIONS))
        for label, g in sub.groupby("label"):
            cells = []
            for cond in CONDITIONS:
                row = g[g.condition == cond]
                if row.empty or pd.isna(row.lift.iloc[0]):
                    cells.append("%14s" % "-")
                else:
                    cells.append("%14s" % ("%+.2f (%.1f)" % (row.lift.iloc[0], row.z.iloc[0])))
            print("   %-14s" % label + "".join(cells))
        games = int(sub.games.mean())
        print("   条件日あたりの平均回転数 %s G" % f"{games:,}")

    print("\n■ プラスだったホール数（σ>=2 のみ数える）")
    print("   %-10s" % "" + "".join("%12s" % c for c in CONDITIONS))
    for category in CATEGORIES:
        sub = a[a.category == category]
        cells = []
        for cond in CONDITIONS:
            g = sub[(sub.condition == cond) & sub.lift.notna()]
            up = int(((g.lift > 0) & (g.z >= 2)).sum())
            down = int(((g.lift < 0) & (g.z <= -2)).sum())
            cells.append("%12s" % ("+%d / -%d / %d店" % (up, down, len(g))))
        print("   %-10s" % category + "".join(cells))
    print("\n   空欄は条件日の回転数が %s G 未満で測れないセル" % f"{MIN_CONDITION_GAMES:,}")
    print("   σ は測定の精度。回転数の少ない BT / A+AT では大きな%%でも σ が小さい")


def print_day(hall, date, split=False):
    applies = today_conditions(date)
    print("■ %s  %s" % (hall, date))
    if not applies:
        print("   当てはまる日付条件なし（ふつうの日）")
        return
    print("   当てはまる条件: %s" % " / ".join(applies))
    groups = [(None, "すべて")] + ([(c, c) for c in CATEGORIES] if split else [])
    for category, label in groups:
        verdict = day_verdict(hall, date, category)
        if not verdict:
            if split:
                print("   %-8s （測れていない）" % label)
            continue
        if split:
            print("   [%s]" % label)
        print("   %-12s%9s%8s%8s" % ("条件", "上振れ", "σ", "日数"))
        for name, lift, z, days in verdict:
            mark = "強い日" if lift >= STRONG_LIFT and z >= STRONG_Z else ("弱い日" if lift <= -STRONG_LIFT else "")
            print("   %-12s%+8.2f%%%8.1f%8d  %s" % (name, lift, z, days, mark))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("table", help="全ホール×全条件の一覧")
    sub.add_parser("category", help="ノーマル / BT / A+AT に分けた一覧")
    p_day = sub.add_parser("day", help="その日がその店にとってどういう日か")
    p_day.add_argument("hall")
    p_day.add_argument("--date", required=True)
    p_day.add_argument("--by-category", action="store_true", help="ノーマル/BT/A+AT に分けて出す")
    args = parser.parse_args()
    if args.cmd == "table":
        print_table()
    elif args.cmd == "category":
        print_by_category()
    else:
        print_day(args.hall, args.date, args.by_category)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
