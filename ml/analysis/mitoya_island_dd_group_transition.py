"""
みとや大森町店：島別×同一DD末尾グループ内での遷移分析

前回分析(mitoya_same_dd_group_transition.py)は全島混合で「その日の最高セクション/末尾/角番」
を抽出していたため、単価が2.35倍異なる main_mix(AT島)と main_jug(ジャグラー島)を比較すると
「その日どちらの島が勝ったか」という単価差のアーティファクトが「90%交替」として
観測された可能性がある。

本スクリプトは島内で完結させて「島内アンチパターン」を検証する：
- AT島(501-640)内でのセクション/末尾/角番遷移
- ジャグラー島(641-691)内でのセクション/末尾/角番遷移
- バラエティ島(692-755)は除外（既存知見でε²=0、角番効果なしと確認済み）
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import sqlite3
from pathlib import Path
import pandas as pd
import numpy as np

DB_PATH = Path("db/みとや大森町店.db")

ISLANDS = {
    "AT島(main_mix)": (501, 640),
    "ジャグラー島(main_jug)": (641, 691),
}


def load_xday_data():
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql(
        """
        SELECT date, machine_number, last_digit, diff_coins_normalized
        FROM machine_detailed_results
        ORDER BY date, machine_number
        """,
        conn,
    )

    layout = pd.read_sql(
        "SELECT machine_number, section, rank_from_aisle FROM machine_layout",
        conn,
    )
    conn.close()

    df = df.merge(layout, on="machine_number", how="left")

    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date_dt"].dt.day
    df["dd_mod"] = df["dd"] % 10
    df["is_xday"] = df["dd_mod"].isin([4, 7]).astype(int)
    df["dd_group"] = df["dd_mod"].apply(lambda x: "4系" if x == 4 else ("7系" if x == 7 else None))

    df["is_aisle_corner"] = (df["rank_from_aisle"] == 1).astype(int)
    section_max_aisle = df.groupby("section")["rank_from_aisle"].transform("max")
    df["is_far_corner"] = (df["rank_from_aisle"] == section_max_aisle).astype(int)
    df["corner_type"] = df["is_aisle_corner"].apply(lambda x: "通路側" if x == 1 else "奥側")

    return df[(df["dd_group"].notna()) & (df["is_xday"] == 1)].copy()


def transition_rate(best_df, key_col, group_label):
    """同一グループ内での「同じ値が持続」率を計算"""
    sub = best_df[best_df["dd_group"] == group_label].copy().reset_index(drop=True)
    if len(sub) < 2:
        return None, 0

    same_count = 0
    total = 0
    pairs = []
    for i in range(len(sub) - 1):
        prev_v = sub.iloc[i][key_col]
        next_v = sub.iloc[i + 1][key_col]
        same = prev_v == next_v
        same_count += int(same)
        total += 1
        pairs.append({
            "prev_date": sub.iloc[i]["date"],
            "prev_value": prev_v,
            "next_date": sub.iloc[i + 1]["date"],
            "next_value": next_v,
            "same": same,
        })
    return pd.DataFrame(pairs), (same_count / total * 100 if total else 0)


def analyze_island(df, island_name, lo, hi):
    print("\n" + "=" * 80)
    print(f"【{island_name}: 台{lo}-{hi}】 島内アンチパターン検証")
    print("=" * 80)

    df_island = df[(df["machine_number"] >= lo) & (df["machine_number"] <= hi)].copy()
    n_xdays = df_island["date"].nunique()
    print(f"対象イベント日数: {n_xdays}")

    if n_xdays < 6:
        print("データ不足のためスキップ")
        return

    # ---- セクション ----
    daily_section = df_island.groupby(["date", "dd_group", "dd", "section"]).agg(
        diff=("diff_coins_normalized", "mean")
    ).reset_index()
    idx = daily_section.groupby(["date", "dd_group"])["diff"].idxmax()
    best_section = daily_section.loc[idx, ["date", "dd_group", "dd", "section", "diff"]].reset_index(drop=True)
    best_section.columns = ["date", "dd_group", "dd", "value", "diff"]
    best_section["date_dt"] = pd.to_datetime(best_section["date"], format="%Y%m%d")
    best_section = best_section.sort_values("date_dt").reset_index(drop=True)

    print(f"\n--- セクション遷移（島内, n_section={df_island['section'].nunique()}） ---")
    for grp in ["4系", "7系"]:
        pairs, rate = transition_rate(best_section, "value", grp)
        if pairs is not None:
            print(f"  {grp}グループ内: 同一セクション持続 {rate:.1f}% (n={len(pairs)})")
            if len(pairs) > 0:
                for _, r in pairs.iterrows():
                    mark = "持続" if r["same"] else "交替"
                    print(f"    {r['prev_date']}({r['prev_value']}) → {r['next_date']}({r['next_value']}) [{mark}]")

    # ---- 末尾 ----
    daily_digit = df_island.groupby(["date", "dd_group", "dd", "last_digit"]).agg(
        diff=("diff_coins_normalized", "mean")
    ).reset_index()
    idx = daily_digit.groupby(["date", "dd_group"])["diff"].idxmax()
    best_digit = daily_digit.loc[idx, ["date", "dd_group", "dd", "last_digit", "diff"]].reset_index(drop=True)
    best_digit.columns = ["date", "dd_group", "dd", "value", "diff"]
    best_digit["date_dt"] = pd.to_datetime(best_digit["date"], format="%Y%m%d")
    best_digit = best_digit.sort_values("date_dt").reset_index(drop=True)

    print(f"\n--- 末尾遷移（島内） ---")
    for grp in ["4系", "7系"]:
        pairs, rate = transition_rate(best_digit, "value", grp)
        if pairs is not None:
            print(f"  {grp}グループ内: 同一末尾持続 {rate:.1f}% (n={len(pairs)})")

    # ---- 角番 ----
    daily_corner = df_island.groupby(["date", "dd_group", "dd", "corner_type"]).agg(
        diff=("diff_coins_normalized", "mean")
    ).reset_index()
    idx = daily_corner.groupby(["date", "dd_group"])["diff"].idxmax()
    best_corner = daily_corner.loc[idx, ["date", "dd_group", "dd", "corner_type", "diff"]].reset_index(drop=True)
    best_corner.columns = ["date", "dd_group", "dd", "value", "diff"]
    best_corner["date_dt"] = pd.to_datetime(best_corner["date"], format="%Y%m%d")
    best_corner = best_corner.sort_values("date_dt").reset_index(drop=True)

    print(f"\n--- 角番遷移（島内） ---")
    for grp in ["4系", "7系"]:
        pairs, rate = transition_rate(best_corner, "value", grp)
        if pairs is not None:
            print(f"  {grp}グループ内: 同一角番持続 {rate:.1f}% (n={len(pairs)})")


def analyze_cross_island_winner(df):
    """そもそも「全島混合の最高セクション」が常にどちらの島から出ているかを検証"""
    print("\n" + "=" * 80)
    print("検証: 全島混合トップは毎回どちらの島から出ているか（単価差アーティファクト検証）")
    print("=" * 80)

    df["island"] = np.select(
        [
            (df["machine_number"] >= 501) & (df["machine_number"] <= 640),
            (df["machine_number"] >= 641) & (df["machine_number"] <= 691),
        ],
        ["AT島(main_mix)", "ジャグラー島(main_jug)"],
        default="その他(バラエティ等)",
    )

    daily_section = df.groupby(["date", "dd_group", "section", "island"]).agg(
        diff=("diff_coins_normalized", "mean")
    ).reset_index()
    idx = daily_section.groupby(["date", "dd_group"])["diff"].idxmax()
    winner = daily_section.loc[idx, ["date", "dd_group", "section", "island", "diff"]]

    print("\n全島混合「その日の最高セクション」の所属島の内訳:")
    print(winner["island"].value_counts())
    print(f"\n→ 偏りが大きい場合、「90%セクション交替」は単価差による島の勝ち負けの交替であり、")
    print(f"   真のアンチパターン（島内での意図的な配置交替）ではない可能性が高い。")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("みとや大森町店：島別アンチパターン再検証")
    print("（前回分析が全島混合だった問題を島内に限定して再検証）")
    print("=" * 80)

    df = load_xday_data()
    print(f"\nデータ読み込み完了: イベント日 {df['date'].nunique()} 日")

    analyze_cross_island_winner(df)

    for name, (lo, hi) in ISLANDS.items():
        analyze_island(df, name, lo, hi)

    print("\n" + "=" * 80)
    print("分析完了")
    print("=" * 80)
