"""
みとや×ジャグラーガールズ: DD14（毎月14日）限定の台番号別分析
- DD14のみを抽出し、台番号別RB率ランキング
- カイ二乗検定で台間差の有意性
- 前半/後半での順位持続性（Spearman）
- 参考として全期間ランキングとの比較（DD14だけの過学習でないか）
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr, chi2_contingency

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count, diff_coins_normalized "
        "FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def rb_rank(sub: pd.DataFrame) -> pd.DataFrame:
    agg = (
        sub.groupby("machine_number")
        .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
        .reset_index()
    )
    agg["rb_rate"] = agg["rb_sum"] / agg["games_sum"]
    return agg


def main():
    df = load_data()
    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()
    gals["day"] = gals["date"].dt.day
    gals["weekday"] = gals["date"].dt.day_name()

    dd14 = gals[gals["day"] == 14].copy()
    print(f"DD14レコード数: {len(dd14)} rows / 全体 {len(gals)} rows")
    print(f"DD14 対象日数: {dd14['date'].nunique()}日")
    print(f"DD14 対象日一覧: {sorted(dd14['date'].dt.strftime('%Y-%m-%d').unique())}")
    print(f"曜日内訳:\n{dd14.groupby('weekday').agg(n_days=('date', 'nunique'))}")

    dd14_filtered = dd14[dd14["games_normalized"] >= 1500]
    print(f"\ngames>=1500フィルタ後: {len(dd14_filtered)} rows")

    # ========== 1. DD14限定 台番号別RB率ランキング ==========
    print("\n=== 1. DD14限定 台番号別RB率ランキング ===")
    machine_agg = rb_rank(dd14_filtered).sort_values("rb_rate", ascending=False)
    overall_rb_rate = machine_agg["rb_sum"].sum() / machine_agg["games_sum"].sum()
    print(f"DD14全体平均RB率: {overall_rb_rate:.4f} (1/{1 / overall_rb_rate:.1f})")

    diff_agg = (
        dd14_filtered.groupby("machine_number")
        .agg(
            n_days=("date", "nunique"),
            games_mean=("games_normalized", "mean"),
            diff_mean=("diff_coins_normalized", "mean"),
            diff_median=("diff_coins_normalized", "median"),
            plus_rate=("diff_coins_normalized", lambda x: (x > 0).mean()),
        )
        .reset_index()
    )
    merged = machine_agg.merge(diff_agg, on="machine_number")
    merged = merged.sort_values("rb_rate", ascending=False)
    for _, row in merged.iterrows():
        print(
            f"  台{row['machine_number']:.0f}: RB率={row['rb_rate']:.4f}(1/{1 / row['rb_rate']:.1f}) "
            f"差={row['rb_rate'] - overall_rb_rate:+.4f} | "
            f"平均差枚={row['diff_mean']:+.0f} 中央値={row['diff_median']:+.0f} プラス率={row['plus_rate']:.2f} | "
            f"n_days={row['n_days']:.0f} games_mean={row['games_mean']:.0f}"
        )

    # ========== 2. 有意性検定 ==========
    print("\n=== 2. カイ二乗検定（台間RB率差の有意性） ===")
    if len(machine_agg) >= 2:
        contingency = machine_agg[["rb_sum"]].copy()
        contingency["non_rb_games"] = machine_agg["games_sum"] - machine_agg["rb_sum"]
        try:
            chi2, p, dof, _ = chi2_contingency(contingency[["rb_sum", "non_rb_games"]].values)
            print(f"  カイ二乗値={chi2:.2f}, p値={p:.4f}, 自由度={dof}")
            print(
                "  → 有意差あり(p<0.05)"
                if p < 0.05
                else "  → 有意差なし(p>=0.05): 台間差はランダム変動の範囲内の可能性"
            )
        except Exception as e:
            print(f"  検定エラー: {e}")

    # ========== 3. サンプル数の警告 ==========
    n_dd14_days = dd14_filtered["date"].nunique()
    print(f"\n=== 3. サンプルサイズの警告 ===")
    print(f"  DD14は月1回しか来ない。対象期間で{n_dd14_days}日分しかない。")
    print("  →機種平均は日次でも数百G単位のばらつきが出るため、台番号1台あたりのサンプルはさらに少ない。")

    # ========== 4. DD14ランキング vs 全期間ランキングの相関 ==========
    print("\n=== 4. DD14順位 vs 全期間順位の相関（DD14固有か、恒常的な鉄/弱台かの切り分け） ===")
    all_period = rb_rank(gals[gals["games_normalized"] >= 1500])
    cmp = machine_agg.merge(all_period, on="machine_number", suffixes=("_dd14", "_all"))
    cmp["rank_dd14"] = cmp["rb_rate_dd14"].rank(ascending=False)
    cmp["rank_all"] = cmp["rb_rate_all"].rank(ascending=False)
    for _, row in cmp.sort_values("rank_dd14").iterrows():
        print(
            f"  台{row['machine_number']:.0f}: DD14順位={row['rank_dd14']:.0f}(RB率{row['rb_rate_dd14']:.4f}) "
            f"全期間順位={row['rank_all']:.0f}(RB率{row['rb_rate_all']:.4f})"
        )
    if len(cmp) >= 3:
        rho, pval = spearmanr(cmp["rank_dd14"], cmp["rank_all"])
        print(f"\n  Spearman rho={rho:.3f}(p={pval:.3f})")
        if rho > 0.5:
            print("  → DD14の強い台は全期間でも強い＝台固有(鉄/弱台)の可能性。DD14固有の法則ではないかもしれない。")
        else:
            print("  → DD14順位と全期間順位に強い相関なし＝DD14固有パターンの可能性、またはノイズ。")


if __name__ == "__main__":
    main()
