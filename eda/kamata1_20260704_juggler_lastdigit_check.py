"""
蒲田1 2026-07-04 単日分析:
ジャグラー系 vs 非ジャグラー系 の末尾(0-9)別 hit_104_rate / 勝率 / 平均差枚 / 平均回転数比較。

ユーザー観察仮説: ジャグラー末尾0-4 / 非ジャグラー末尾5-9 に高設定投入。
本スクリプトは一時分析用（本番コードではない）。eda/core.py の定義に準拠。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "マルハンメガシティ2000-蒲田1.db"
TARGET_DATE = "20260704"
MIN_GAMES = 1000  # kamata17_kakuban_payout104_analysis.py に準拠
COINS_PER_GAME = 3  # 同上

pd.set_option("display.unicode.east_asian_width", True)
pd.set_option("display.width", 160)


def load_day(db_path: Path, date: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    query = f"""
    SELECT
        date, machine_name, machine_number, last_digit,
        games_normalized AS games, diff_coins_normalized AS diff
    FROM machine_detailed_results
    WHERE date = '{date}'
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def calc_payout_rate(games: pd.Series, diff: pd.Series) -> pd.Series:
    denom = pd.to_numeric(games, errors="coerce") * COINS_PER_GAME
    denom = denom.replace(0, np.nan)
    return ((denom + pd.to_numeric(diff, errors="coerce")) / denom) * 100


def main():
    raw = load_day(DB_PATH, TARGET_DATE)
    n_raw = len(raw)

    # min_games フィルタは集計前に個別台レベルで適用（CLAUDE.md 指示）
    df = raw[raw["games"] >= MIN_GAMES].copy()
    n_after_min_games = len(df)

    df["payout_rate"] = calc_payout_rate(df["games"], df["diff"])
    df["hit104"] = df["payout_rate"].ge(104.0).astype(int)
    df["win"] = (df["diff"] > 0).astype(int)
    df["last_digit"] = df["last_digit"].astype(str)

    df["is_juggler"] = df["machine_name"].str.contains("ジャグラー", na=False)
    group_label = np.where(df["is_juggler"], "ジャグラー", "非ジャグラー")
    df["group"] = group_label

    print(f"[生データ] {TARGET_DATE} 蒲田1 全台数: {n_raw}")
    print(f"[min_games={MIN_GAMES}フィルタ後] 台数: {n_after_min_games} (除外: {n_raw - n_after_min_games})")
    print()
    print("=== 機種名内訳（ジャグラー/非ジャグラー、フィルタ後）===")
    print(df.groupby("group")["machine_name"].nunique())
    print()
    print("ジャグラー系 機種名一覧:")
    print(sorted(df.loc[df["is_juggler"], "machine_name"].unique()))
    print()

    def summarize(sub: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for d in [str(i) for i in range(10)]:
            g = sub[sub["last_digit"] == d]
            n = len(g)
            if n == 0:
                rows.append(
                    dict(last_digit=d, n=0, hit104_rate=np.nan, win_rate=np.nan, avg_diff=np.nan, avg_games=np.nan)
                )
                continue
            rows.append(
                dict(
                    last_digit=d,
                    n=n,
                    hit104_rate=round(g["hit104"].mean() * 100, 1),
                    win_rate=round(g["win"].mean() * 100, 1),
                    avg_diff=round(g["diff"].mean(), 1),
                    avg_games=round(g["games"].mean(), 1),
                )
            )
        return pd.DataFrame(rows)

    jug = df[df["is_juggler"]]
    non_jug = df[~df["is_juggler"]]

    jug_table = summarize(jug)
    non_jug_table = summarize(non_jug)

    print("=== ジャグラー系 末尾別集計 ===")
    print(jug_table.to_string(index=False))
    print()
    print("=== 非ジャグラー系 末尾別集計 ===")
    print(non_jug_table.to_string(index=False))
    print()

    def half_compare(table: pd.DataFrame, label: str):
        low = table[table["last_digit"].astype(int).between(0, 4)]
        high = table[table["last_digit"].astype(int).between(5, 9)]

        def agg(t):
            n_total = t["n"].sum()
            if n_total == 0:
                return dict(n=0, hit104_rate=np.nan, win_rate=np.nan, avg_diff=np.nan, avg_games=np.nan)
            # n加重平均
            w = t["n"]
            return dict(
                n=int(n_total),
                hit104_rate=round((t["hit104_rate"] * w).sum() / n_total, 1),
                win_rate=round((t["win_rate"] * w).sum() / n_total, 1),
                avg_diff=round((t["avg_diff"] * w).sum() / n_total, 1),
                avg_games=round((t["avg_games"] * w).sum() / n_total, 1),
            )

        low_agg = agg(low)
        high_agg = agg(high)
        print(f"--- {label}: 末尾0-4 vs 5-9 (n加重平均) ---")
        print(
            f"  0-4: n={low_agg['n']:>3}, hit104率={low_agg['hit104_rate']}%, "
            f"勝率={low_agg['win_rate']}%, 平均差枚={low_agg['avg_diff']}, 平均G数={low_agg['avg_games']}"
        )
        print(
            f"  5-9: n={high_agg['n']:>3}, hit104率={high_agg['hit104_rate']}%, "
            f"勝率={high_agg['win_rate']}%, 平均差枚={high_agg['avg_diff']}, 平均G数={high_agg['avg_games']}"
        )
        print()

    half_compare(jug_table, "ジャグラー系")
    half_compare(non_jug_table, "非ジャグラー系")

    # 参考: ホール全体 vs ジャグラー/非ジャグラーの全体差
    print("=== 参考: グループ全体サマリー(min_games後) ===")
    for label, sub in [("ジャグラー系全体", jug), ("非ジャグラー系全体", non_jug)]:
        n = len(sub)
        if n == 0:
            continue
        print(
            f"  {label}: n={n}, hit104率={sub['hit104'].mean() * 100:.1f}%, "
            f"勝率={sub['win'].mean() * 100:.1f}%, 平均差枚={sub['diff'].mean():.1f}, "
            f"平均G数={sub['games'].mean():.1f}"
        )


if __name__ == "__main__":
    main()
