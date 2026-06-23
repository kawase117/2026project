"""
法則①(diff_std>=median AND payout_rate>=100%)の8ホール展開

eda/strategy1_placebo_check.py でみとや・蒲田1・蒲田7の3ホールにおいて
「戦略1(diff_std>=median & payout>=100%)」がプラセボ(diff_std>=medianのみ)
よりQ5-Q1を正方向にシフトさせることを確認した。

これをeda/cross_hall_pattern_verification.pyで検証済みの他6ホール
(ARROW池上店・ザ-シティ-ベルシティ雑色店・ヒロキ東口店・レイトギャップ平和島・
楽園蒲田店・金時京急蒲田店)に展開する。

各ホールの曜日固有パターンは未確立のため、みとやと同じXgroup日定義
(DD in [4,7,14,17,24,27])・全機種(machine_name単位、AT機フィルタ無し)で
walk-forward検証する。
"""
import sqlite3
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

TARGET_HALLS = [
    "ARROW池上店",
    "ザ-シティ-ベルシティ雑色店",
    "ヒロキ東口店",
    "レイトギャップ平和島",
    "楽園蒲田店",
    "金時京急蒲田店",
]

X_DDS = [4, 7, 14, 17, 24, 27]
COINS_PER_GAME = 3
MIN_DAYS = 10


def load_data(db_path: Path) -> pd.DataFrame:
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


def run_backtest(sub: pd.DataFrame) -> tuple:
    dates = sorted(sub["date"].unique())
    results_strategy1 = []
    results_placebo = []

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


def summarize(res_df: pd.DataFrame, label: str) -> str:
    if res_df.empty:
        return f"  [{label}] サンプルなし"
    n = len(res_df)
    q1 = (res_df["quintile"] == 1).mean()
    q5 = (res_df["quintile"] == 5).mean()
    return f"  [{label}] n={n}, Q1={q1:.3f}, Q5={q5:.3f}, Q5-Q1={q5-q1:+.3f}"


def analyze(name: str) -> None:
    db_path = DB_DIR / f"{name}.db"
    if not db_path.exists():
        print(f"\n===== {name}: DBファイルなし、スキップ =====")
        return
    sub = load_data(db_path)
    print(f"\n===== {name} (Xgroup日数={sub['date'].nunique()}) =====")
    res_s1, res_placebo = run_backtest(sub)
    print(summarize(res_s1, "戦略1: diff_std>=median & payout>=100%"))
    print(summarize(res_placebo, "プラセボ: diff_std>=medianのみ"))


def main() -> None:
    for name in TARGET_HALLS:
        analyze(name)


if __name__ == "__main__":
    main()
