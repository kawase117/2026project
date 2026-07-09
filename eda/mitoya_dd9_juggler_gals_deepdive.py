"""
みとや×ジャグラーガールズ: DD9の RB確率の高さを解析する
- 曜日パターン
- サンプルサイズの偏り（1日だけ高いか、複数日で一貫しているか）
- 回転数レベル別（小数 vs 大数）
- 日付の詳細な実績
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"


def load_data() -> pd.DataFrame:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    df["dow"] = df["date"].dt.day_name()  # 曜日
    df["dow_num"] = df["date"].dt.dayofweek  # 0=月, 6=日
    return df


def main():
    df = load_data()

    # みとや×ジャグラーガールズ に限定
    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()
    print(f"全ジャグラーガールズ: {len(gals)} rows")

    # DD9に限定
    dd9 = gals[gals["dd"] == 9].copy()
    print(f"DD9データ: {len(dd9)} rows (期間: {dd9['date'].min()} ~ {dd9['date'].max()})")

    if len(dd9) < 10:
        print("サンプルが少ないため分析不可")
        return

    # RB確率を計算
    dd9["rb_rate"] = dd9["rb_count"] / dd9["games_normalized"]

    # ========== 1. 曜日別集計 ==========
    print("\n=== 1. 曜日別 RB確率 ===")
    dow_agg = (
        dd9.groupby("dow_num")
        .agg(
            dow_name=("dow", "first"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
            n_days=("date", "nunique"),
            n_machines=("machine_number", "count"),
        )
        .reset_index()
    )
    dow_agg["rb_rate"] = dow_agg["rb_sum"] / dow_agg["games_sum"]
    dow_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
    dow_agg["dow_ja"] = dow_agg["dow_num"].map(dow_map)

    # 曜日順でソート
    for idx, row in dow_agg.iterrows():
        print(
            f"  {row['dow_ja']}({row['dow_num']}): "
            f"RB率={row['rb_rate']:.4f} (n={row['n_machines']}, "
            f"games={row['games_sum']:.0f}, rb={row['rb_sum']:.0f}, "
            f"異なる日={row['n_days']})"
        )

    # ========== 2. 日付別（複数年の9日）集計 ==========
    print("\n=== 2. 日付別（年跨ぎで複数の9日） RB確率 ===")
    date_agg = (
        dd9.groupby("date")
        .agg(
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
            n_machines=("machine_number", "count"),
        )
        .reset_index()
    )
    date_agg["rb_rate"] = date_agg["rb_sum"] / date_agg["games_sum"]
    date_agg = date_agg.sort_values("rb_rate", ascending=False)

    print(f"最高RB率: {date_agg['rb_rate'].max():.4f} (日付: {date_agg.iloc[0]['date'].strftime('%Y-%m-%d')})")
    print(f"最低RB率: {date_agg['rb_rate'].min():.4f} (日付: {date_agg.iloc[-1]['date'].strftime('%Y-%m-%d')})")
    print(f"中央値: {date_agg['rb_rate'].median():.4f}")
    print(f"標準偏差: {date_agg['rb_rate'].std():.4f}")
    print(f"\n上位5日:")
    for idx, row in date_agg.head(5).iterrows():
        print(
            f"  {row['date'].strftime('%Y-%m-%d (%a)')}: "
            f"RB率={row['rb_rate']:.4f} (n={row['n_machines']}, games={row['games_sum']:.0f})"
        )

    # ========== 3. 回転数レベル別（サンプルサイズ分析） ==========
    print("\n=== 3. 回転数レベル別（小数サンプルか大数か） ===")
    dd9["games_level"] = pd.cut(
        dd9["games_normalized"],
        bins=[0, 100, 500, 1000, 2000, np.inf],
        labels=["0-100", "100-500", "500-1k", "1k-2k", "2k+"],
    )
    games_agg = (
        dd9.groupby("games_level")
        .agg(
            n_records=("games_normalized", "count"),
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
            rb_rate_mean=("rb_rate", "mean"),
            rb_rate_std=("rb_rate", "std"),
        )
        .reset_index()
    )
    games_agg["rb_rate_pooled"] = games_agg["rb_sum"] / games_agg["games_sum"]

    for idx, row in games_agg.iterrows():
        print(
            f"  {row['games_level']}: n={row['n_records']}, "
            f"pooled RB率={row['rb_rate_pooled']:.4f}, "
            f"平均RB率={row['rb_rate_mean']:.4f}±{row['rb_rate_std']:.4f}"
        )

    # ========== 4. 機械別詳細（複数機械の寄与度） ==========
    print("\n=== 4. 機械別（複数台の寄与） ===")
    machine_agg = (
        dd9.groupby("machine_number")
        .agg(
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
            n_records=("date", "count"),
            n_dates=("date", "nunique"),
        )
        .reset_index()
    )
    machine_agg["rb_rate"] = machine_agg["rb_sum"] / machine_agg["games_sum"]
    machine_agg = machine_agg.sort_values("rb_rate", ascending=False)

    print(f"ジャグラーガールズ台数: {len(machine_agg)}")
    print(f"\n上位5台:")
    for idx, row in machine_agg.head(5).iterrows():
        print(
            f"  台{row['machine_number']}: RB率={row['rb_rate']:.4f} "
            f"(games={row['games_sum']:.0f}, n={row['n_records']}, 異なる日={row['n_dates']})"
        )

    # ========== 5. イベント日仮説（DD9が特別な日か） ==========
    print("\n=== 5. イベント日の可能性検証 ===")
    # 通常日のDD5,12,19,26 (ゾロ目以外の9日以外) と比較
    normal_dds = [5, 12, 19, 26]
    normal = gals[gals["dd"].isin(normal_dds)].copy()
    normal["rb_rate"] = normal["rb_count"] / normal["games_normalized"]

    dd9_pool_rb_rate = dd9["rb_count"].sum() / dd9["games_normalized"].sum()
    normal_pool_rb_rate = normal["rb_count"].sum() / normal["games_normalized"].sum()

    print(f"  DD9 RB率(プール): {dd9_pool_rb_rate:.4f}")
    print(f"  通常日(DD5,12,19,26) RB率(プール): {normal_pool_rb_rate:.4f}")
    print(f"  差分: {dd9_pool_rb_rate - normal_pool_rb_rate:+.4f}")

    # ========== 6. RB確率の安定性（日ごとのばらつき） ==========
    print("\n=== 6. RB確率の日ごとばらつき ===")
    print(
        f"  複数日の9日で計算: n日={len(date_agg)}, "
        f"平均RB率={date_agg['rb_rate'].mean():.4f}, "
        f"最高={date_agg['rb_rate'].max():.4f}, "
        f"最低={date_agg['rb_rate'].min():.4f}"
    )
    print(f"  変動幅(max-min): {date_agg['rb_rate'].max() - date_agg['rb_rate'].min():.4f} ")

    # ========== 結論 ==========
    print("\n=== 結論・仮説 ===")
    # 曜日に大きな差があるか
    dow_diff = dow_agg["rb_rate"].max() - dow_agg["rb_rate"].min()
    if dow_diff > 0.005:
        print(f"✓ 曜日による差異あり（{dow_diff:.4f}、有意かもしれない）")
    else:
        print(f"✗ 曜日による差異は小さい（{dow_diff:.4f}）")

    # 1日だけ高いか
    top_date_contrib = date_agg.iloc[0]["rb_sum"] / date_agg["rb_sum"].sum()
    if top_date_contrib > 0.3:
        print(f"✓ 特定1日に集中（最高日シェア={top_date_contrib:.1%}） → まぐれの可能性高い")
    else:
        print(f"✗ 複数日に分散（最高日シェア={top_date_contrib:.1%}）")

    # 小数サンプル効果か
    small_games = games_agg[games_agg["games_level"].isin(["0-100", "100-500"])]
    if len(small_games) > 0:
        small_contrib = small_games["rb_sum"].sum() / games_agg["rb_sum"].sum()
        if small_contrib > 0.5:
            print(f"✓ 小数サンプル支配（0-500games{small_contrib:.1%}） → 分散による可能性高い")
        else:
            print(f"✗ 大数サンプル（0-500gamesは{small_contrib:.1%}）")
    else:
        print("✗ 小数サンプル区間にデータなし")


if __name__ == "__main__":
    main()
