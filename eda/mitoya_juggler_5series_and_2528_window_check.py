"""
みとや大森町店: 2つの追加仮説を全期間データで検証する。
1. 「5のつく日」(DD=5,15,25)は機種別に見ると強いのか(ホール合算では
   既存instinctで否定済みだが、機種単位では未検証)
2. DD25-28(27のイベント日を含む4日間)にジャグラーへの集中投入傾向があるか
それぞれ vs rest のカイ二乗検定・投資量(games)交絡チェック・前半/後半再現性を確認する。
"""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import chi2_contingency, pearsonr

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"
FIVE_SERIES = {5, 15, 25}
WINDOW_2528 = {25, 26, 27, 28}
MIN_GAMES = 1500


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, games_normalized, rb_count "
        "FROM machine_detailed_results WHERE machine_name LIKE '%ジャグラー%'",
        conn,
    )
    conn.close()
    df["date_dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["day"] = df["date_dt"].dt.day
    df = df[df["games_normalized"] >= MIN_GAMES]
    return df


def evaluate(df: pd.DataFrame, target_days: set, label: str):
    print(f"\n{'=' * 70}\n{label}: target DD={sorted(target_days)}\n{'=' * 70}")

    for machine in sorted(df["machine_name"].unique()):
        sub = df[df["machine_name"] == machine].copy()
        sub["is_target"] = sub["day"].isin(target_days)

        target = sub[sub["is_target"]]
        rest = sub[~sub["is_target"]]
        if target["games_normalized"].sum() == 0 or rest["games_normalized"].sum() == 0:
            continue

        target_rate = target["rb_count"].sum() / target["games_normalized"].sum()
        rest_rate = rest["rb_count"].sum() / rest["games_normalized"].sum()
        n_dates = target["date_dt"].nunique()

        # カイ二乗検定 (target vs rest, 2x2)
        table = [
            [target["rb_count"].sum(), target["games_normalized"].sum() - target["rb_count"].sum()],
            [rest["rb_count"].sum(), rest["games_normalized"].sum() - rest["rb_count"].sum()],
        ]
        try:
            chi2, p, _, _ = chi2_contingency(table)
        except Exception:
            chi2, p = float("nan"), float("nan")

        # 投資量交絡チェック(日付レベル、targetの中でgames_meanとrb_rateの相関)
        daily = (
            target.groupby("date_dt")
            .agg(games_sum=("games_normalized", "sum"), rb_sum=("rb_count", "sum"))
            .reset_index()
        )
        daily["rate"] = daily["rb_sum"] / daily["games_sum"]
        if len(daily) >= 4 and daily["games_sum"].std() > 0:
            r, rp = pearsonr(daily["games_sum"], daily["rate"])
        else:
            r, rp = float("nan"), float("nan")

        flag = " <<<" if p < 0.05 and target_rate > rest_rate else ""
        print(
            f"  {machine}: target_rate={target_rate:.5f}(1/{1 / target_rate:.1f}) "
            f"rest_rate={rest_rate:.5f}(1/{1 / rest_rate:.1f}) diff={target_rate - rest_rate:+.5f} "
            f"n_dates={n_dates} chi2_p={p:.4f} games相関r={r:.3f}(p={rp:.3f}){flag}"
        )


def main():
    df = load_data()
    print(f"データ期間: {df['date_dt'].min().date()} 〜 {df['date_dt'].max().date()}")
    evaluate(df, FIVE_SERIES, "仮説1: 5のつく日(DD5,15,25)")
    evaluate(df, WINDOW_2528, "仮説2: DD25-28の4日間ウィンドウ")

    # 仮説2について、ホール合算(全機種プール)でも見る
    print(f"\n{'=' * 70}\n仮説2 ホール合算版\n{'=' * 70}")
    df["is_target"] = df["day"].isin(WINDOW_2528)
    target = df[df["is_target"]]
    rest = df[~df["is_target"]]
    target_rate = target["rb_count"].sum() / target["games_normalized"].sum()
    rest_rate = rest["rb_count"].sum() / rest["games_normalized"].sum()
    table = [
        [target["rb_count"].sum(), target["games_normalized"].sum() - target["rb_count"].sum()],
        [rest["rb_count"].sum(), rest["games_normalized"].sum() - rest["rb_count"].sum()],
    ]
    chi2, p, _, _ = chi2_contingency(table)
    print(f"  target(DD25-28)_rate={target_rate:.5f}(1/{1 / target_rate:.1f})")
    print(f"  rest_rate={rest_rate:.5f}(1/{1 / rest_rate:.1f})")
    print(f"  diff={target_rate - rest_rate:+.5f}  chi2_p={p:.4f}")


if __name__ == "__main__":
    main()
