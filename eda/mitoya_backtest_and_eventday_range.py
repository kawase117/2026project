"""
みとや大森町店: 「みとやのみ深堀り」優先度2・3

優先度2: payout/diff_stdスクリーニング(法則②)のバックテスト
  - 各Xgroup日について、その日より前のXgroupデータ(machine_name単位)で
    payout_rate>=100% & diff_std<median のスクリーニングを行い、
    選ばれた機種が当日Q5(上位クインタイル)に入っていたかを検証する。

優先度3: イベント日の範囲再検討
  - X_DDS=[4,7,14,17,24,27] と 確定イベント日[1,4,7,14,17,24,27,30] で
    machine_name単位のpayout_rate/diff_std split-half持続性を比較する。
"""
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
EVENT_DDS_FULL = [1, 4, 7, 14, 17, 24, 27, 30]
COINS_PER_GAME = 3
MIN_DAYS = 10


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def compute_history_agg(hist: pd.DataFrame) -> pd.DataFrame:
    agg = (
        hist.groupby("machine_name")
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_days=("diff_coins_normalized", "size"),
        )
    )
    agg = agg[agg["n_days"] >= MIN_DAYS].copy()
    if agg.empty:
        return agg
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    daily_std = (
        hist.groupby(["machine_name", "date"])["diff_coins_normalized"]
        .sum()
        .groupby("machine_name")
        .std()
    )
    agg["diff_std"] = daily_std
    return agg


def evaluate_strategy(res_df: pd.DataFrame, label: str) -> None:
    if res_df.empty:
        print(f"  [{label}] 検証可能なサンプルなし")
        return
    n = len(res_df)
    n_q = res_df["quintile"].nunique()
    baseline = 1.0 / n_q
    print(f"\n  [{label}] n={n} (対象日数={res_df['date'].nunique()})")
    for q in sorted(res_df["quintile"].unique()):
        rate = (res_df["quintile"] == q).mean()
        print(f"    Q{q}到達率: {rate:.3f} (期待値={baseline:.3f})")
    q1_rate = (res_df["quintile"] == res_df["quintile"].min()).mean()
    q5_rate = (res_df["quintile"] == res_df["quintile"].max()).mean()
    top2_rate = (res_df["quintile"] >= res_df["quintile"].max() - 1).mean()
    bottom2_rate = (res_df["quintile"] <= res_df["quintile"].min() + 1).mean()
    print(f"    Q1(最下位)到達率: {q1_rate:.3f} (期待値={baseline:.3f})")
    print(f"    Q5(最上位)到達率: {q5_rate:.3f} (期待値={baseline:.3f})")
    print(f"    Q4+Q5到達率: {top2_rate:.3f} (期待値={2*baseline:.3f})")
    print(f"    Q1+Q2到達率: {bottom2_rate:.3f} (期待値={2*baseline:.3f})")


def section_backtest(df: pd.DataFrame) -> None:
    print("\n##### 優先度2: 法則②スクリーニングのバックテスト (Xgroup, machine_name単位) #####")
    sub = df[df["dd"].isin(X_DDS)].copy()
    dates = sorted(sub["date"].unique())

    if len(dates) <= MIN_DAYS:
        print("  サンプル不足")
        return

    results = []
    for target_date in dates:
        hist = sub[sub["date"] < target_date]
        if hist["date"].nunique() < MIN_DAYS:
            continue

        agg = compute_history_agg(hist)
        if len(agg) < 5:
            continue

        median_std = agg["diff_std"].median()
        candidates = agg[(agg["payout_rate"] >= 100) & (agg["diff_std"] < median_std)]
        if candidates.empty:
            continue

        today = sub[sub["date"] == target_date]
        today_agg = today.groupby("machine_name")["diff_coins_normalized"].sum()
        if len(today_agg) < 5:
            continue
        quintile = pd.qcut(today_agg, 5, labels=False, duplicates="drop") + 1

        for name in candidates.index:
            if name in quintile.index:
                results.append({
                    "date": target_date,
                    "machine_name": name,
                    "quintile": quintile.loc[name],
                })

    res_df = pd.DataFrame(results)
    evaluate_strategy(res_df, "法則② diff_std<median & payout>=100%")
    if not res_df.empty:
        print("\n  [機種別集計]")
        by_name = res_df.groupby("machine_name").agg(
            n=("quintile", "size"),
            mean_quintile=("quintile", "mean"),
        ).sort_values("mean_quintile", ascending=False)
        print(by_name.to_string())


def backtest_alt_strategies(sub: pd.DataFrame, dates: list) -> tuple:
    results_reversed = []  # diff_std>=median & payout>=100 (高分散候補)
    results_payout_top = []  # payout_rate上位20%のみ(diff_stdフィルタ無し)

    for target_date in dates:
        hist = sub[sub["date"] < target_date]
        if hist["date"].nunique() < MIN_DAYS:
            continue

        agg = compute_history_agg(hist)
        if len(agg) < 5:
            continue

        today = sub[sub["date"] == target_date]
        today_agg = today.groupby("machine_name")["diff_coins_normalized"].sum()
        if len(today_agg) < 5:
            continue
        quintile = pd.qcut(today_agg, 5, labels=False, duplicates="drop") + 1

        # 戦略1: 高分散側(diff_std>=median) & payout>=100
        median_std = agg["diff_std"].median()
        cand_rev = agg[(agg["payout_rate"] >= 100) & (agg["diff_std"] >= median_std)]
        for name in cand_rev.index:
            if name in quintile.index:
                results_reversed.append({
                    "date": target_date, "machine_name": name, "quintile": quintile.loc[name],
                })

        # 戦略2: payout_rate上位20%(diff_stdフィルタ無し)
        payout_threshold = agg["payout_rate"].quantile(0.8)
        cand_payout = agg[agg["payout_rate"] >= payout_threshold]
        for name in cand_payout.index:
            if name in quintile.index:
                results_payout_top.append({
                    "date": target_date, "machine_name": name, "quintile": quintile.loc[name],
                })

    return pd.DataFrame(results_reversed), pd.DataFrame(results_payout_top)


def section_alternative_strategies(df: pd.DataFrame) -> None:
    print("\n##### 追加検証: 代替スクリーニング戦略のバックテスト (Xgroup, machine_name単位) #####")
    sub = df[df["dd"].isin(X_DDS)].copy()
    dates = sorted(sub["date"].unique())

    if len(dates) <= MIN_DAYS:
        print("  サンプル不足")
        return

    res_rev, res_payout = backtest_alt_strategies(sub, dates)
    evaluate_strategy(res_rev, "戦略1: diff_std>=median(高分散) & payout>=100%")
    evaluate_strategy(res_payout, "戦略2: payout_rate上位20%(diff_stdフィルタ無し)")


def section_alt_strategies_split_half(df: pd.DataFrame) -> None:
    print("\n##### 追加検証: 戦略1/2のsplit-half再現性検証 (Xgroup, machine_name単位) #####")
    sub = df[df["dd"].isin(X_DDS)].copy()
    dates = sorted(sub["date"].unique())

    if len(dates) <= MIN_DAYS * 2:
        print("  サンプル不足")
        return

    mid = len(dates) // 2
    first_half_dates = dates[:mid]
    second_half_dates = dates[mid:]

    for label_half, half_dates in [("前半", first_half_dates), ("後半", second_half_dates)]:
        print(f"\n  === {label_half} (バックテスト対象日数={len(half_dates)}) ===")
        res_rev, res_payout = backtest_alt_strategies(sub, half_dates)
        evaluate_strategy(res_rev, f"[{label_half}] 戦略1: diff_std>=median(高分散) & payout>=100%")
        evaluate_strategy(res_payout, f"[{label_half}] 戦略2: payout_rate上位20%")


def split_half_persistence(sub: pd.DataFrame, label: str) -> None:
    sub = sub.copy()
    dates = sorted(sub["date"].unique())
    mid = len(dates) // 2
    sub["half"] = sub["date"].apply(lambda d: 0 if d <= dates[mid - 1] else 1)

    agg = (
        sub.groupby(["half", "machine_name"])
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_days=("diff_coins_normalized", "size"),
        )
        .reset_index()
    )
    agg = agg[agg["n_days"] >= MIN_DAYS].copy()
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    daily_std = (
        sub.groupby(["half", "machine_name", "date"])["diff_coins_normalized"]
        .sum()
        .groupby(["half", "machine_name"])
        .std()
        .reset_index(name="diff_std")
    )
    agg = agg.merge(daily_std, on=["half", "machine_name"])

    cur = agg[agg["half"] == 0]
    nxt = agg[agg["half"] == 1]
    m = cur.merge(nxt, on="machine_name", suffixes=("_1", "_2"))

    n_days_total = len(dates)
    print(f"\n  [{label}] 日数={n_days_total} (前半{mid}/後半{len(dates)-mid}) n_machines={len(m)}")
    if len(m) < 5:
        print("    サンプル不足")
        return

    for col in ["payout_rate", "diff_std"]:
        rho, pval = spearmanr(m[f"{col}_1"], m[f"{col}_2"])
        print(f"    {col}: rho={rho:.3f} (p={pval:.3f})")


def section_eventday_range(df: pd.DataFrame) -> None:
    print("\n##### 優先度3: イベント日範囲の再検討 (machine_name単位 split-half) #####")
    sub_x = df[df["dd"].isin(X_DDS)].copy()
    sub_full = df[df["dd"].isin(EVENT_DDS_FULL)].copy()
    sub_1_30 = df[df["dd"].isin([1, 30])].copy()

    split_half_persistence(sub_x, "X_DDS=[4,7,14,17,24,27]")
    split_half_persistence(sub_full, "確定イベント日=[1,4,7,14,17,24,27,30]")

    print(f"\n  [DD1・DD30のみ] 日数={sub_1_30['date'].nunique()}")
    if sub_1_30["date"].nunique() >= 2 * MIN_DAYS:
        split_half_persistence(sub_1_30, "DD1+DD30のみ")
    else:
        print("    日数不足のためsplit-half不可。X_DDSとの単純比較のみ可能")

    print("\n  [DD別 payout_rate (machine_name単位, 全期間集計)]")
    for dd_set, label in [
        (X_DDS, "X_DDS(4,7,14,17,24,27)"),
        ([1], "DD1"),
        ([30], "DD30"),
        (EVENT_DDS_FULL, "確定イベント日全体"),
    ]:
        s = df[df["dd"].isin(dd_set)]
        diff_sum = s["diff_coins_normalized"].sum()
        games_sum = s["games_normalized"].sum()
        payout = (games_sum * COINS_PER_GAME + diff_sum) / (games_sum * COINS_PER_GAME) * 100
        print(f"    {label}: n_days={s['date'].nunique()} payout_rate={payout:.2f}%")


def main() -> None:
    df = load_data()
    section_backtest(df)
    section_alternative_strategies(df)
    section_alt_strategies_split_half(df)
    section_eventday_range(df)


if __name__ == "__main__":
    main()
