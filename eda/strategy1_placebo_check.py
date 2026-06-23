"""
法則①(diff_std>=median AND payout_rate>=100%)のプラセボ比較

懸念: 「高分散かつ機械割100%超」がQ5予測力を持つという結果が、
実は「diff_std>=medianの高分散機種は分布が広いのでQ1にもQ5にも入りやすい」
という、機械割条件とは無関係な統計的に当然の現象(分散が大きいほど極端な
クインタイルに入りやすいだけ)を観測しているのではないか、という疑問を検証する。

プラセボ: payout_rate条件を外した「diff_std>=median」のみでの
walk-forward Q1/Q5到達率を算出し、戦略1(diff_std>=median & payout>=100%)
と比較する。

判定基準:
  - プラセボでもQ1・Q5が同程度に上振れ(対称)なら、payout>=100%条件は
    Q5方向への偏りに寄与していない(法則①はほぼ分散選択と同義)。
  - 戦略1の方がQ5>Q1の非対称性が大きいなら、payout>=100%条件に
    追加の情報量がある。
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

COINS_PER_GAME = 3
MIN_DAYS = 10


def load_mitoya() -> pd.DataFrame:
    db_path = DB_DIR / "みとや大森町店.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    X_DDS = [4, 7, 14, 17, 24, 27]
    return df[df["dd"].isin(X_DDS)].copy()


def load_kamata(db_name: str, target_weekday: int = 6) -> pd.DataFrame:
    db_path = DB_DIR / f"{db_name}.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    master = pd.read_sql_query(
        "SELECT machine_name_normalized AS machine_name, jug_flag, hana_flag, "
        "oki_flag, bt_flag FROM machine_master",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.merge(master, on="machine_name", how="left")
    is_at = (
        (df["jug_flag"].fillna(0) == 0)
        & (df["hana_flag"].fillna(0) == 0)
        & (df["oki_flag"].fillna(0) == 0)
        & (df["bt_flag"].fillna(0) == 0)
    )
    df = df[is_at & (df["date"].dt.dayofweek == target_weekday)].copy()
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


def run_backtest(sub: pd.DataFrame) -> tuple:
    dates = sorted(sub["date"].unique())
    results_strategy1 = []  # diff_std>=median & payout>=100%
    results_placebo = []  # diff_std>=median のみ

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

        median_std = agg["diff_std"].median()
        high_var = agg[agg["diff_std"] >= median_std]

        cand_s1 = high_var[high_var["payout_rate"] >= 100]
        for mname in cand_s1.index:
            if mname in quintile.index:
                results_strategy1.append({"date": target_date, "machine_name": mname, "quintile": quintile.loc[mname]})

        for mname in high_var.index:
            if mname in quintile.index:
                results_placebo.append({"date": target_date, "machine_name": mname, "quintile": quintile.loc[mname]})

    return pd.DataFrame(results_strategy1), pd.DataFrame(results_placebo)


def summarize(res_df: pd.DataFrame, label: str) -> None:
    if res_df.empty:
        print(f"  [{label}] サンプルなし")
        return
    n = len(res_df)
    q1 = (res_df["quintile"] == 1).mean()
    q5 = (res_df["quintile"] == 5).mean()
    print(f"  [{label}] n={n}, Q1={q1:.3f}, Q5={q5:.3f}, Q5-Q1={q5-q1:+.3f} (期待値: 各0.200, 差0)")


def analyze(name: str, sub: pd.DataFrame) -> None:
    print(f"\n===== {name} (対象日数={sub['date'].nunique()}) =====")
    res_s1, res_placebo = run_backtest(sub)
    summarize(res_s1, "戦略1: diff_std>=median & payout>=100%")
    summarize(res_placebo, "プラセボ: diff_std>=medianのみ(payout条件無し)")


def main() -> None:
    analyze("みとや大森町店(Xgroup)", load_mitoya())
    analyze("蒲田1(日曜)", load_kamata("マルハンメガシティ2000-蒲田1"))
    analyze("蒲田7(日曜)", load_kamata("マルハンメガシティ2000-蒲田7"))


if __name__ == "__main__":
    main()
