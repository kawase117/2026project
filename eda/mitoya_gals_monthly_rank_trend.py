"""
みとや×ジャグラーガールズ: 台番号別RB確率の月次推移とランク推移をJSON出力する
折れ線グラフ描画用のデータ生成スクリプト
"""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUTPUT_PATH = Path(__file__).resolve().parent / "results" / "mitoya_gals_monthly_rank_trend.json"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["year_month"] = df["date"].dt.to_period("M").astype(str)
    return df


def main():
    df = load_data()
    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()

    monthly = (
        gals.groupby(["year_month", "machine_number"])
        .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
        .reset_index()
    )
    monthly["rb_rate"] = monthly["rb_sum"] / monthly["games_sum"]

    monthly["rank"] = monthly.groupby("year_month")["rb_rate"].rank(ascending=False, method="min")

    months = sorted(monthly["year_month"].unique())
    machines = sorted(monthly["machine_number"].unique())

    result = {
        "months": months,
        "machines": [int(m) for m in machines],
        "series": {},
    }
    for m in machines:
        sub = monthly[monthly["machine_number"] == m].set_index("year_month")
        rb_rates = []
        ranks = []
        games = []
        for month in months:
            if month in sub.index:
                rb_rates.append(round(float(sub.loc[month, "rb_rate"]), 5))
                ranks.append(int(sub.loc[month, "rank"]))
                games.append(int(sub.loc[month, "games_sum"]))
            else:
                rb_rates.append(None)
                ranks.append(None)
                games.append(None)
        result["series"][str(int(m))] = {
            "rb_rate": rb_rates,
            "rank": ranks,
            "games": games,
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Saved to {OUTPUT_PATH}")
    print(f"Months: {len(months)}, Machines: {machines}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
