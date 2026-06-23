"""
法則①(diff_std>=median(高分散) & payout_rate>=100%)の閾値感度分析

document/instincts/2026-06-14-strategy1-9hall-validation.yaml で
「戦略1自体のQ5-Q1>0(実用可能)」と確認された6ホール
(みとや・蒲田1・蒲田7・レイトギャップ平和島・楽園蒲田・金時京急蒲田)について、
payout_rate閾値とdiff_std閾値(パーセンタイル)を変化させ、
Q5-Q1がどの閾値で最大化されるか、また100%/medianという初期選択が
妥当だったかを確認する。

- payout_rate閾値: 95, 98, 100, 102, 105
- diff_std閾値(パーセンタイル): 50(median), 60, 70, 75

各組み合わせをwalk-forwardで評価し、Q5-Q1のヒートマップ的な表を出力する。
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

COINS_PER_GAME = 3
MIN_DAYS = 10
X_DDS = [4, 7, 14, 17, 24, 27]

PAYOUT_THRESHOLDS = [95, 98, 100, 102, 105]
STD_PERCENTILES = [50, 60, 70, 75]


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


def run_grid_backtest(sub: pd.DataFrame) -> dict:
    """各(payout_th, std_pct)組み合わせごとに quintile結果リストを返す"""
    dates = sorted(sub["date"].unique())
    results = {
        (p, s): [] for p in PAYOUT_THRESHOLDS for s in STD_PERCENTILES
    }

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

        for std_pct in STD_PERCENTILES:
            std_th = agg["diff_std"].quantile(std_pct / 100)
            high_var = agg[agg["diff_std"] >= std_th]
            for payout_th in PAYOUT_THRESHOLDS:
                cand = high_var[high_var["payout_rate"] >= payout_th]
                for mname in cand.index:
                    if mname in quintile.index:
                        results[(payout_th, std_pct)].append(quintile.loc[mname])

    return results


def summarize_grid(results: dict) -> pd.DataFrame:
    rows = []
    for (payout_th, std_pct), quints in results.items():
        if len(quints) < 20:
            rows.append({
                "payout_th": payout_th, "std_pct": std_pct,
                "n": len(quints), "q1": None, "q5": None, "q5_q1": None,
            })
            continue
        s = pd.Series(quints)
        q1 = (s == 1).mean()
        q5 = (s == 5).mean()
        rows.append({
            "payout_th": payout_th, "std_pct": std_pct,
            "n": len(quints), "q1": q1, "q5": q5, "q5_q1": q5 - q1,
        })
    return pd.DataFrame(rows)


def analyze(name: str, sub: pd.DataFrame) -> None:
    print(f"\n===== {name} (対象日数={sub['date'].nunique()}) =====")
    results = run_grid_backtest(sub)
    grid = summarize_grid(results)
    pivot = grid.pivot(index="std_pct", columns="payout_th", values="q5_q1")
    print("Q5-Q1 (行=diff_std percentile閾値, 列=payout_rate閾値):")
    print(pivot.round(3).to_string())
    n_pivot = grid.pivot(index="std_pct", columns="payout_th", values="n")
    print("\nサンプル数n:")
    print(n_pivot.to_string())


def main() -> None:
    analyze("みとや大森町店(Xgroup)", load_mitoya())
    analyze("蒲田1(日曜)", load_kamata("マルハンメガシティ2000-蒲田1"))
    analyze("蒲田7(日曜)", load_kamata("マルハンメガシティ2000-蒲田7"))
    analyze("レイトギャップ平和島(Xgroup)", load_xgroup("レイトギャップ平和島"))
    analyze("楽園蒲田店(Xgroup)", load_xgroup("楽園蒲田店"))
    analyze("金時京急蒲田店(Xgroup)", load_xgroup("金時京急蒲田店"))


if __name__ == "__main__":
    main()
