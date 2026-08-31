"""
みとや×ジャグラーガールズ: 直近のDD9(2026-08-09)・DD24(2026-07-24)の実測値確認
既存instinct(dd9=投資量交絡で否定, dd24=n=12で弱い支持・未確定)が
直近の実測日でどう出ているかを台番号別に確認する。
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
TARGET_DATES = ["20260809", "20260724"]


def main():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count, bb_count, "
        "diff_coins_normalized FROM machine_detailed_results WHERE date IN (?, ?)",
        conn,
        params=TARGET_DATES,
    )
    conn.close()

    gals = df[df["machine_name"].str.contains("ジャグラーガールズ", na=False, case=False)].copy()
    gals["date_fmt"] = pd.to_datetime(gals["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d(%a)")

    for d in TARGET_DATES:
        sub = gals[gals["date"] == d].sort_values("machine_number")
        if sub.empty:
            print(f"\n=== {d}: データなし ===")
            continue
        label = sub["date_fmt"].iloc[0]
        print(f"\n=== {label} ===")
        for _, row in sub.iterrows():
            games = row["games_normalized"]
            rb_rate = row["rb_count"] / games if games else 0
            rate_str = f"RB率={rb_rate:.4f}(1/{1 / rb_rate:.1f})" if rb_rate else "RB率=--"
            print(
                f"  台{row['machine_number']:.0f}: games={games:.0f} "
                f"差枚={row['diff_coins_normalized']:+.0f} "
                f"BB={row['bb_count']:.0f} RB={row['rb_count']:.0f} {rate_str}"
            )
        games_sum = sub["games_normalized"].sum()
        rb_sum = sub["rb_count"].sum()
        pooled_rate = rb_sum / games_sum if games_sum else 0
        if pooled_rate:
            print(
                f"  --- 島合算: games={games_sum:.0f}, RB={rb_sum:.0f}, RB率={pooled_rate:.4f}(1/{1 / pooled_rate:.1f})"
            )
        print(
            f"  --- 島合算差枚: {sub['diff_coins_normalized'].sum():+.0f} (平均{sub['diff_coins_normalized'].mean():+.0f})"
        )


if __name__ == "__main__":
    main()
