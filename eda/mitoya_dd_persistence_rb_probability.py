"""
差枚(diff_coins_normalized)ではなくRB確率(rb_count/games_normalized)を指標として
台番号別/機種別の持続性を再検証する。

理由: BBよりRBの方が設定差が大きく出やすく、差枚は短期的な分散(偶然)の影響が
大きいため、設定の強さを反映する指標としてRB確率の方が適切と考えられる。

集計方法: period内でrb_count・games_normalizedをそれぞれ合計し、
rb_rate = sum(rb_count) / sum(games_normalized) として算出(日次比率の平均ではなく
分子・分母を合算してから比率を取る)。
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
N_BINS = 5
WINDOW_MONTHS = 3


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized, "
        "games_normalized, rb_count, bb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    return (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months


def run_persistence(agg: pd.DataFrame, value_col: str, group_col: str) -> dict:
    agg = agg.copy()
    agg["quintile"] = agg.groupby("period")[value_col].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )

    periods = sorted(agg["period"].unique())
    all_merged = []
    for p, p_next in zip(periods[:-1], periods[1:]):
        cur = agg[agg["period"] == p][[group_col, "quintile"]]
        nxt = agg[agg["period"] == p_next][[group_col, "quintile"]]
        m = cur.merge(nxt, on=group_col, suffixes=("_cur", "_next"))
        if len(m) >= 5:
            all_merged.append(m)

    if not all_merged:
        return {"rho": None}

    pooled = pd.concat(all_merged, ignore_index=True)
    rho, pval = spearmanr(pooled["quintile_cur"], pooled["quintile_next"])
    max_q = pooled["quintile_cur"].max()
    min_q = pooled["quintile_cur"].min()
    q5_stay = (pooled.loc[pooled["quintile_cur"] == max_q, "quintile_next"] == max_q).mean()
    q1_stay = (pooled.loc[pooled["quintile_cur"] == min_q, "quintile_next"] == min_q).mean()
    return {
        "n_periods": len(periods),
        "n": len(pooled),
        "rho": rho,
        "pval": pval,
        "q5_stay": q5_stay,
        "q1_stay": q1_stay,
    }


def print_result(label: str, r: dict) -> None:
    baseline = 1.0 / N_BINS
    if r["rho"] is None:
        print(f"  {label}: 遷移不可(サンプル不足)")
        return
    print(
        f"  {label}: n={r['n']} rho={r['rho']:.3f} (p={r['pval']:.3f}) "
        f"Q5stay={r['q5_stay']:.3f} Q1stay={r['q1_stay']:.3f} "
        f"(ランダム期待値={baseline:.3f})"
    )


def main() -> None:
    df = load_data()
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], WINDOW_MONTHS)

    print("##### RB確率(rb_rate=sum(rb_count)/sum(games)) 持続性 (Xgroup, 3ヶ月) #####")
    for group_col in ["machine_number", "machine_name"]:
        base = (
            sub.groupby(["period", group_col])
            .agg(
                games_sum=("games_normalized", "sum"),
                rb_sum=("rb_count", "sum"),
                bb_sum=("bb_count", "sum"),
                diff_sum=("diff_coins_normalized", "sum"),
            )
            .reset_index()
        )
        base["rb_rate"] = base["rb_sum"] / base["games_sum"]
        base["bb_rate"] = base["bb_sum"] / base["games_sum"]

        print(f"\n[{group_col}]")
        print_result("RB確率(rb_rate)", run_persistence(base, "rb_rate", group_col))
        print_result("BB確率(bb_rate)", run_persistence(base, "bb_rate", group_col))
        print_result("差枚合計(比較用)", run_persistence(base, "diff_sum", group_col))

    # 機種効果除去後のRB確率残差(台番号別)
    print("\n[machine_number] 機種効果除去後の残差")
    base = (
        sub.groupby(["period", "machine_number"])
        .agg(
            games_sum=("games_normalized", "sum"),
            rb_sum=("rb_count", "sum"),
            bb_sum=("bb_count", "sum"),
            machine_name=("machine_name", "first"),
        )
        .reset_index()
    )
    base["rb_rate"] = base["rb_sum"] / base["games_sum"]
    base["bb_rate"] = base["bb_sum"] / base["games_sum"]

    for col, label in [("rb_rate", "RB確率(rb_rate)"), ("bb_rate", "BB確率(bb_rate)")]:
        type_mean = base.groupby(["period", "machine_name"])[col].transform("mean")
        base[f"{col}_resid"] = base[col] - type_mean
        print_result(f"{label} 残差", run_persistence(base, f"{col}_resid", "machine_number"))


if __name__ == "__main__":
    main()
