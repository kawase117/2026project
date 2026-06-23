"""
みとや大森町店 持続性分析の拡張検証

eda/mitoya_dd_persistence_analysis.py の結果(Xgroupで弱い持続性, rho=0.123)に対し:

1. 期間の長さ(1/2/3/4/6ヶ月)を変えても傾向は同じか
2. 曜日別にグルーピングした場合はどうか(DD別ではなく曜日別)
3. 台番号別ではなく機種別(machine_name)で集計した場合はどうか
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
N_BINS = 5
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized "
        "FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    df["weekday"] = df["date"].dt.dayofweek
    return df


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    period_index = (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months
    return period_index


def run_persistence(sub: pd.DataFrame, window_months: int, group_col: str) -> dict:
    sub = sub.copy()
    sub["period"] = assign_period(sub["date"], window_months)

    agg = (
        sub.groupby(["period", group_col])["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    agg["quintile"] = agg.groupby("period")["diff_coins_normalized"].transform(
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
        return {
            "n_periods": len(periods),
            "n_transitions": 0,
            "n": 0,
            "rho": None,
            "pval": None,
            "q5_stay": None,
            "q1_stay": None,
        }

    pooled = pd.concat(all_merged, ignore_index=True)
    rho, pval = spearmanr(pooled["quintile_cur"], pooled["quintile_next"])

    max_q = pooled["quintile_cur"].max()
    min_q = pooled["quintile_cur"].min()
    q5 = pooled[pooled["quintile_cur"] == max_q]
    q1 = pooled[pooled["quintile_cur"] == min_q]
    q5_stay = (q5["quintile_next"] == max_q).mean() if len(q5) else None
    q1_stay = (q1["quintile_next"] == min_q).mean() if len(q1) else None

    return {
        "n_periods": len(periods),
        "n_transitions": len(all_merged),
        "n": len(pooled),
        "rho": rho,
        "pval": pval,
        "q5_stay": q5_stay,
        "q1_stay": q1_stay,
    }


def section_window_sizes(df: pd.DataFrame) -> None:
    print("\n##### 1. 期間長さの感度分析 (Xgroup, 台番号別) #####")
    sub = df[df["dd"].isin(X_DDS)]
    baseline = 1.0 / N_BINS
    for w in [1, 2, 3, 4, 6]:
        r = run_persistence(sub, w, "machine_number")
        if r["rho"] is None:
            print(f"  window={w}ヶ月: 期間数={r['n_periods']} 遷移不可(サンプル不足)")
            continue
        print(
            f"  window={w}ヶ月: 期間数={r['n_periods']} 遷移数={r['n_transitions']} "
            f"n={r['n']} rho={r['rho']:.3f} (p={r['pval']:.3f}) "
            f"Q5stay={r['q5_stay']:.3f} Q1stay={r['q1_stay']:.3f} "
            f"(ランダム期待値={baseline:.3f})"
        )


def section_weekday(df: pd.DataFrame, window_months: int = 3) -> None:
    print(f"\n##### 2. 曜日別グルーピング (window={window_months}ヶ月, 台番号別) #####")
    baseline = 1.0 / N_BINS
    for wd in range(7):
        sub = df[df["weekday"] == wd]
        r = run_persistence(sub, window_months, "machine_number")
        if r["rho"] is None:
            print(f"  {WEEKDAY_JP[wd]}曜日: 期間数={r['n_periods']} 遷移不可")
            continue
        print(
            f"  {WEEKDAY_JP[wd]}曜日: 期間数={r['n_periods']} n={r['n']} "
            f"rho={r['rho']:.3f} (p={r['pval']:.3f}) "
            f"Q5stay={r['q5_stay']:.3f} Q1stay={r['q1_stay']:.3f} "
            f"(ランダム期待値={baseline:.3f})"
        )


def section_machine_type(df: pd.DataFrame, window_months: int = 3) -> None:
    print(f"\n##### 3. 機種別集計 (Xgroup, window={window_months}ヶ月, machine_name) #####")
    baseline = 1.0 / N_BINS
    sub = df[df["dd"].isin(X_DDS)]
    r = run_persistence(sub, window_months, "machine_name")
    if r["rho"] is None:
        print(f"  期間数={r['n_periods']} 遷移不可(サンプル不足)")
        return
    print(
        f"  期間数={r['n_periods']} 遷移数={r['n_transitions']} n={r['n']} "
        f"rho={r['rho']:.3f} (p={r['pval']:.3f}) "
        f"Q5stay={r['q5_stay']:.3f} Q1stay={r['q1_stay']:.3f} "
        f"(ランダム期待値={baseline:.3f})"
    )

    n_types = sub["machine_name"].nunique()
    print(f"  機種数: {n_types}")


def section_machine_number_residual(df: pd.DataFrame, window_months: int = 3) -> None:
    print(
        f"\n##### 4. 機種効果を除去した台番号別持続性 "
        f"(Xgroup, window={window_months}ヶ月) #####"
    )
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], window_months)

    agg = (
        sub.groupby(["period", "machine_number"])
        .agg(diff_coins_normalized=("diff_coins_normalized", "sum"),
             machine_name=("machine_name", "first"))
        .reset_index()
    )

    type_mean = agg.groupby(["period", "machine_name"])["diff_coins_normalized"].transform("mean")
    agg["residual"] = agg["diff_coins_normalized"] - type_mean

    agg["quintile"] = agg.groupby("period")["residual"].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )

    periods = sorted(agg["period"].unique())
    all_merged = []
    for p, p_next in zip(periods[:-1], periods[1:]):
        cur = agg[agg["period"] == p][["machine_number", "quintile"]]
        nxt = agg[agg["period"] == p_next][["machine_number", "quintile"]]
        m = cur.merge(nxt, on="machine_number", suffixes=("_cur", "_next"))
        if len(m) >= 5:
            all_merged.append(m)

    if not all_merged:
        print("  遷移不可(サンプル不足)")
        return

    pooled = pd.concat(all_merged, ignore_index=True)
    rho, pval = spearmanr(pooled["quintile_cur"], pooled["quintile_next"])
    max_q = pooled["quintile_cur"].max()
    min_q = pooled["quintile_cur"].min()
    q5_stay = (pooled.loc[pooled["quintile_cur"] == max_q, "quintile_next"] == max_q).mean()
    q1_stay = (pooled.loc[pooled["quintile_cur"] == min_q, "quintile_next"] == min_q).mean()

    baseline = 1.0 / N_BINS
    print(
        f"  期間数={len(periods)} 遷移数={len(all_merged)} n={len(pooled)} "
        f"rho={rho:.3f} (p={pval:.3f}) "
        f"Q5stay={q5_stay:.3f} Q1stay={q1_stay:.3f} (ランダム期待値={baseline:.3f})"
    )
    print("  (比較) 機種補正前の台番号別: rho=0.123, Q5stay=0.328, Q1stay=0.307")


def main() -> None:
    df = load_data()
    section_window_sizes(df)
    section_weekday(df)
    section_machine_type(df)
    section_machine_number_residual(df)


if __name__ == "__main__":
    main()
