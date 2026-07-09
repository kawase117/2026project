"""
みとや×ミスタージャグラー: DD21直近3ヶ月分の台番号別RB確率とランクを算出する
"""

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
OUTPUT_PATH = Path(__file__).resolve().parent / "results" / "mitoya_mister_dd21_recent3m_rank.json"


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def main():
    df = load_data()
    mister = df[df["machine_name"].str.contains("ミスタージャグラー", na=False, case=False)].copy()

    last_date = mister["date"].max()
    cutoff = last_date - pd.DateOffset(months=3)
    print(f"データ最終日: {last_date.strftime('%Y-%m-%d')}, 3ヶ月前カットオフ: {cutoff.strftime('%Y-%m-%d')}")

    dd21 = mister[(mister["dd"] == 21) & (mister["date"] > cutoff)].copy()
    dd21["rb_rate"] = dd21["rb_count"] / dd21["games_normalized"]

    dates = sorted(dd21["date"].unique())
    print(f"対象DD21日付: {[pd.Timestamp(d).strftime('%Y-%m-%d') for d in dates]}")

    dd21["rank"] = dd21.groupby("date")["rb_rate"].rank(ascending=False, method="min")
    dd21 = dd21.sort_values(["date", "rank"])

    print("\n=== 日付別・台番号別 RB確率とランク ===")
    for d in dates:
        sub = dd21[dd21["date"] == d].sort_values("rank")
        print(f"\n{pd.Timestamp(d).strftime('%Y-%m-%d')}:")
        for _, row in sub.iterrows():
            inv = f"1/{1 / row['rb_rate']:.1f}" if row["rb_rate"] > 0 else "N/A"
            print(
                f"  台{row['machine_number']:.0f}: RB率={row['rb_rate']:.4f} "
                f"({inv}) games={row['games_normalized']:.0f} "
                f"rb={row['rb_count']:.0f} ランク={row['rank']:.0f}"
            )

    machines = sorted(dd21["machine_number"].unique())
    result = {
        "dates": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates],
        "machines": [int(m) for m in machines],
        "series": {},
    }
    for m in machines:
        sub = dd21[dd21["machine_number"] == m].set_index("date")
        rb_rates, ranks, games = [], [], []
        for d in dates:
            if d in sub.index:
                row = sub.loc[d]
                rb_rates.append(round(float(row["rb_rate"]), 5))
                ranks.append(int(row["rank"]))
                games.append(int(row["games_normalized"]))
            else:
                rb_rates.append(None)
                ranks.append(None)
                games.append(None)
        result["series"][str(int(m))] = {"rb_rate": rb_rates, "rank": ranks, "games": games}

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {OUTPUT_PATH}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
