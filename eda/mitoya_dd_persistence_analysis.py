"""
みとや大森町店 DD別グループ × 台番号別 差枚持続性分析

対象日:
- 4group: DD in {4, 14, 24}
- 7group: DD in {7, 17, 27}
- Xgroup: DD in {4, 7, 14, 17, 24, 27}

各グループについて、3ヶ月期間ごとに台番号別の diff_coins_normalized 合計を集計し、
クインタイル(5段階)に分割。期間 N のクインタイル と 期間 N+1 のクインタイルの
関係(持続 or 反転)を Spearman相関と平均クインタイル遷移で確認する。
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

GROUPS = {
    "4group": [4, 14, 24],
    "7group": [7, 17, 27],
    "Xgroup": [4, 7, 14, 17, 24, 27],
}

N_BINS = 5  # クインタイル


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, diff_coins_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def assign_period(dates: pd.Series) -> pd.Series:
    """データ全体を3ヶ月単位の連続期間に分割するラベルを返す。"""
    start = dates.min().to_period("M")
    period_index = (dates.dt.to_period("M") - start).apply(lambda x: x.n) // 3
    return period_index


def analyze_group(df: pd.DataFrame, dd_list: list[int], group_name: str) -> None:
    sub = df[df["dd"].isin(dd_list)].copy()
    sub["period"] = assign_period(sub["date"])

    agg = (
        sub.groupby(["period", "machine_number"])["diff_coins_normalized"]
        .sum()
        .reset_index()
    )

    agg["quintile"] = agg.groupby("period")["diff_coins_normalized"].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )

    periods = sorted(agg["period"].unique())
    print(f"\n===== {group_name} (DD={dd_list}) =====")
    print(f"期間数: {len(periods)}")

    for p in periods:
        n_machines = agg[agg["period"] == p]["machine_number"].nunique()
        print(f"  period {p}: 台数={n_machines}")

    transitions = []
    for p, p_next in zip(periods[:-1], periods[1:]):
        cur = agg[agg["period"] == p][["machine_number", "quintile", "diff_coins_normalized"]]
        nxt = agg[agg["period"] == p_next][["machine_number", "quintile", "diff_coins_normalized"]]
        merged = cur.merge(nxt, on="machine_number", suffixes=("_cur", "_next"))
        if len(merged) < 5:
            continue
        rho, pval = spearmanr(merged["quintile_cur"], merged["quintile_next"])
        transitions.append((p, p_next, len(merged), rho, pval))
        print(
            f"  period {p}->{p_next}: n={len(merged)}, "
            f"Spearman rho={rho:.3f} (p={pval:.3f})"
        )

    if not transitions:
        print("  遷移ペアなし(サンプル不足)")
        return

    all_merged = []
    for p, p_next in zip(periods[:-1], periods[1:]):
        cur = agg[agg["period"] == p][["machine_number", "quintile"]]
        nxt = agg[agg["period"] == p_next][["machine_number", "quintile"]]
        m = cur.merge(nxt, on="machine_number", suffixes=("_cur", "_next"))
        all_merged.append(m)
    pooled = pd.concat(all_merged, ignore_index=True)

    print("\n  [プール遷移] 前期クインタイル別 -> 次期平均クインタイル")
    pivot = pooled.groupby("quintile_cur")["quintile_next"].agg(["mean", "count"])
    print(pivot.to_string())

    rho_all, pval_all = spearmanr(pooled["quintile_cur"], pooled["quintile_next"])
    print(f"\n  [全体] Spearman rho={rho_all:.3f} (p={pval_all:.3f}, n={len(pooled)})")

    # 継続率: 前期Q5(最高)が次期もQ5、前期Q1(最低)が次期もQ1である割合
    baseline = 1.0 / N_BINS
    for q, label in [(N_BINS, "最高(Q5)"), (1, "最低(Q1)")]:
        cur_q = pooled[pooled["quintile_cur"] == q]
        if len(cur_q) == 0:
            continue
        stay_rate = (cur_q["quintile_next"] == q).mean()
        print(
            f"  継続率 {label}->{label}: {stay_rate:.3f} "
            f"(ランダム期待値={baseline:.3f}, n={len(cur_q)})"
        )


def main() -> None:
    df = load_data()
    for name, dd_list in GROUPS.items():
        analyze_group(df, dd_list, name)


if __name__ == "__main__":
    main()
