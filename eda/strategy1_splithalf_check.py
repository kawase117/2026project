"""
法則①(diff_std>=median & payout_rate>=100% / 102%)のsplit-half時系列頑健性検証

eda/strategy1_threshold_sensitivity.py で、レイトギャップ平和島・金時京急蒲田店・
蒲田7のQ5-Q1正値が境界線上(閾値を僅かにずらすと負転)であり、9ホール表の
「6/9ホールで実用可能」という判定が閾値依存の過大評価ではないか、という
懸念が生じた。

各ホールの対象日数を前半/後半に分割し、walk-forwardのQ5-Q1が両期間で
同方向(正)を維持するかを確認する。前半のみ/後半のみで偶然正になっている
ホールは、時系列的に頑健でないと判断する。

payout_rate閾値は100%と102%の両方で検証する(102%が複数ホールで
より頑健だったため)。diff_std閾値はmedian(50%)固定。
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

COINS_PER_GAME = 3
MIN_DAYS = 10
X_DDS = [4, 7, 14, 17, 24, 27]
PAYOUT_THRESHOLDS = [100, 102]


def load_mitoya() -> pd.DataFrame:
    db_path = DB_DIR / "みとや大森町店.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df[df["dd"].isin(X_DDS)].copy()


def load_kamata(db_name: str, target_weekday: int = 6) -> pd.DataFrame:
    db_path = DB_DIR / f"{db_name}.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_name, diff_coins_normalized, "
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
    return df[is_at & (df["date"].dt.dayofweek == target_weekday)].copy()


def load_xgroup(db_name: str) -> pd.DataFrame:
    db_path = DB_DIR / f"{db_name}.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df[df["dd"].isin(X_DDS)].copy()


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


def run_backtest(sub: pd.DataFrame, payout_th: int) -> pd.DataFrame:
    dates = sorted(sub["date"].unique())
    results = []

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
        cand = agg[(agg["diff_std"] >= median_std) & (agg["payout_rate"] >= payout_th)]
        for mname in cand.index:
            if mname in quintile.index:
                results.append({"date": target_date, "quintile": quintile.loc[mname]})

    return pd.DataFrame(results)


def summarize(res_df: pd.DataFrame, label: str) -> str:
    if res_df.empty or len(res_df) < 10:
        return f"  [{label}] n={len(res_df)} (不足)"
    n = len(res_df)
    q1 = (res_df["quintile"] == 1).mean()
    q5 = (res_df["quintile"] == 5).mean()
    return f"  [{label}] n={n}, Q1={q1:.3f}, Q5={q5:.3f}, Q5-Q1={q5-q1:+.3f}"


def analyze(name: str, sub: pd.DataFrame) -> None:
    dates = sorted(sub["date"].unique())
    mid = dates[len(dates) // 2]
    first = sub[sub["date"] < mid]
    second = sub[sub["date"] >= mid]

    print(f"\n===== {name} (全{len(dates)}日, 前半{first['date'].nunique()}日/後半{second['date'].nunique()}日) =====")
    for payout_th in PAYOUT_THRESHOLDS:
        print(f" -- payout_rate>={payout_th}% --")
        res_full = run_backtest(sub, payout_th)
        res_first = run_backtest(first, payout_th)
        res_second = run_backtest(second, payout_th)
        print(summarize(res_full, "全期間"))
        print(summarize(res_first, "前半"))
        print(summarize(res_second, "後半"))


def main() -> None:
    analyze("みとや大森町店(Xgroup)", load_mitoya())
    analyze("蒲田1(日曜)", load_kamata("マルハンメガシティ2000-蒲田1"))
    analyze("蒲田7(日曜)", load_kamata("マルハンメガシティ2000-蒲田7"))
    analyze("レイトギャップ平和島(Xgroup)", load_xgroup("レイトギャップ平和島"))
    analyze("楽園蒲田店(Xgroup)", load_xgroup("楽園蒲田店"))
    analyze("金時京急蒲田店(Xgroup)", load_xgroup("金時京急蒲田店"))


if __name__ == "__main__":
    main()
