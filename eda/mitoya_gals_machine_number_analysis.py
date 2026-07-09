"""
みとや×ジャグラーガールズ: 台番号別RB確率の全期間分析
- 全期間でのRB確率ランキング（台番号別）
- 持続性検証: 前半期間 vs 後半期間で順位が安定しているか
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import numpy as np
from scipy.stats import spearmanr, chi2_contingency

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def main():
    df = load_data()
    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()
    print(f"全ジャグラーガールズレコード: {len(gals)} rows")
    print(f"期間: {gals['date'].min()} ~ {gals['date'].max()}")
    print(f"台番号一覧: {sorted(gals['machine_number'].unique())}")

    # ========== 1. 台番号別 全期間RB確率ランキング ==========
    print("\n=== 1. 台番号別 全期間RB確率ランキング ===")
    machine_agg = (
        gals.groupby("machine_number")
        .agg(
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
            bb_sum=("bb_count", "sum"),
            n_records=("date", "count"),
            n_dates=("date", "nunique"),
        )
        .reset_index()
    )
    machine_agg["rb_rate"] = machine_agg["rb_sum"] / machine_agg["games_sum"]
    machine_agg["bb_rate"] = machine_agg["bb_sum"] / machine_agg["games_sum"]
    machine_agg = machine_agg.sort_values("rb_rate", ascending=False)

    overall_rb_rate = machine_agg["rb_sum"].sum() / machine_agg["games_sum"].sum()
    print(f"全体平均RB率: {overall_rb_rate:.4f} (1/{1 / overall_rb_rate:.1f})")
    print()
    for idx, row in machine_agg.iterrows():
        print(
            f"  台{row['machine_number']:.0f}: RB率={row['rb_rate']:.4f} (1/{1 / row['rb_rate']:.1f}) "
            f"games={row['games_sum']:.0f}, n_days={row['n_dates']}, "
            f"差={row['rb_rate'] - overall_rb_rate:+.4f}"
        )

    # ========== 2. 統計的有意差検定 ==========
    print("\n=== 2. 台番号間の差は統計的に有意か（カイ二乗検定） ===")
    contingency = machine_agg[["rb_sum"]].copy()
    contingency["non_rb_games"] = machine_agg["games_sum"] - machine_agg["rb_sum"]
    try:
        chi2, p, dof, expected = chi2_contingency(contingency[["rb_sum", "non_rb_games"]].values)
        print(f"  カイ二乗値={chi2:.2f}, p値={p:.4f}, 自由度={dof}")
        if p < 0.05:
            print("  → 統計的に有意な差あり(p<0.05)")
        else:
            print("  → 統計的に有意差なし(p>=0.05) 台間の差はランダム変動の範囲内の可能性")
    except Exception as e:
        print(f"  検定エラー: {e}")

    # ========== 3. 持続性検証: 前半 vs 後半 ==========
    print("\n=== 3. 持続性検証（前半期間 vs 後半期間） ===")
    mid_date = gals["date"].min() + (gals["date"].max() - gals["date"].min()) / 2
    print(f"  分割日: {mid_date.strftime('%Y-%m-%d')}")

    first_half = gals[gals["date"] < mid_date]
    second_half = gals[gals["date"] >= mid_date]

    def calc_machine_rb(sub):
        agg = (
            sub.groupby("machine_number")
            .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
            .reset_index()
        )
        agg["rb_rate"] = agg["rb_sum"] / agg["games_sum"]
        return agg

    fh_agg = calc_machine_rb(first_half)
    sh_agg = calc_machine_rb(second_half)

    merged = fh_agg.merge(sh_agg, on="machine_number", suffixes=("_fh", "_sh"))
    merged["rank_fh"] = merged["rb_rate_fh"].rank(ascending=False)
    merged["rank_sh"] = merged["rb_rate_sh"].rank(ascending=False)

    print(f"\n  台番号別 前半 vs 後半 RB率:")
    for idx, row in merged.sort_values("rank_fh").iterrows():
        print(
            f"    台{row['machine_number']:.0f}: 前半={row['rb_rate_fh']:.4f}(順位{row['rank_fh']:.0f}) "
            f"後半={row['rb_rate_sh']:.4f}(順位{row['rank_sh']:.0f})"
        )

    if len(merged) >= 3:
        rho, pval = spearmanr(merged["rank_fh"], merged["rank_sh"])
        print(f"\n  順位相関(Spearman rho)={rho:.3f} (p={pval:.3f})")
        if rho > 0.5:
            print("  → 順位はある程度持続している（鉄台/弱台の可能性）")
        elif rho < 0:
            print("  → 順位は逆転している（ランダムまたは平均回帰）")
        else:
            print("  → 順位の持続性は弱い（ランダム変動の可能性が高い）")

    # ========== 4. 台番号順のRB率推移（物理配置との関係） ==========
    print("\n=== 4. 台番号順のRB率推移 ===")
    machine_agg_sorted_by_num = machine_agg.sort_values("machine_number")
    for idx, row in machine_agg_sorted_by_num.iterrows():
        bar = "#" * int(row["rb_rate"] * 3000)
        print(f"    台{row['machine_number']:.0f}: {row['rb_rate']:.4f} {bar}")


if __name__ == "__main__":
    main()
