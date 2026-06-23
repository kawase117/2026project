"""
差枚を日次レベルでビニングし、極端な大勝ち/大負けの偶然影響を抑えた指標で
台番号別/機種別の持続性を再検証する。

ビニング方針:
1. 全Xgroup日次データのdiff_coins_normalizedを6分位(設定6段階を意識)に分割し、
   day_score(1=最悪 〜 6=最良)を付与。極端値は1や6に飽和するため、
   生のdiffの大小そのものより影響が抑えられる。
2. 「高回転(games_normalizedが上位25%)かつ最悪ビン(day_score=1)」の日は、
   "不発高設定の取りこぼし"を考慮してday_scoreを3(中立)に補正する
   (adjusted_score)。
3. period(3ヶ月, Xgroup)ごとにday_score / adjusted_scoreの平均を取り、
   従来の差枚合計と同様にクインタイル化してSpearman相関・継続率を比較する。
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
N_BINS = 5
N_SCORE_BINS = 6
WINDOW_MONTHS = 3
GAMES_HIGH_PCTL = 0.75
NEUTRAL_SCORE = 3


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


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    return (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months


def run_persistence(agg: pd.DataFrame, value_col: str, group_col: str) -> dict:
    agg = agg.copy()
    agg["quintile"] = agg.groupby("period")[value_col].transform(
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
        return {"rho": None}

    pooled = pd.concat(all_merged, ignore_index=True)
    rho, pval = spearmanr(pooled["quintile_cur"], pooled["quintile_next"])
    max_q = pooled["quintile_cur"].max()
    min_q = pooled["quintile_cur"].min()
    q5_stay = (pooled.loc[pooled["quintile_cur"] == max_q, "quintile_next"] == max_q).mean()
    q1_stay = (pooled.loc[pooled["quintile_cur"] == min_q, "quintile_next"] == min_q).mean()
    return {
        "n_periods": len(periods),
        "n": len(pooled),
        "rho": rho,
        "pval": pval,
        "q5_stay": q5_stay,
        "q1_stay": q1_stay,
    }


def print_result(label: str, r: dict) -> None:
    baseline = 1.0 / N_BINS
    if r["rho"] is None:
        print(f"  {label}: 遷移不可(サンプル不足)")
        return
    print(
        f"  {label}: n={r['n']} rho={r['rho']:.3f} (p={r['pval']:.3f}) "
        f"Q5stay={r['q5_stay']:.3f} Q1stay={r['q1_stay']:.3f} "
        f"(ランダム期待値={baseline:.3f})"
    )


def main() -> None:
    df = load_data()
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], WINDOW_MONTHS)

    # 1. 日次diffを全体6分位でビニング
    sub["day_score"] = pd.qcut(
        sub["diff_coins_normalized"], N_SCORE_BINS, labels=False, duplicates="drop"
    ) + 1
    print(f"day_score分布:\n{sub['day_score'].value_counts().sort_index().to_string()}")

    bin_edges = pd.qcut(
        sub["diff_coins_normalized"], N_SCORE_BINS, duplicates="drop"
    ).cat.categories
    print(f"\nビン境界:\n{bin_edges}")

    # 2. 高回転(games上位25%)かつ最悪ビンの日をneutralに補正
    games_threshold = sub["games_normalized"].quantile(GAMES_HIGH_PCTL)
    print(f"\ngames_normalized 上位25%閾値: {games_threshold:.0f}")

    is_worst_high_games = (sub["day_score"] == 1) & (sub["games_normalized"] >= games_threshold)
    print(f"補正対象日数(最悪ビン×高回転): {is_worst_high_games.sum()} / {len(sub)}")

    sub["adjusted_score"] = sub["day_score"]
    sub.loc[is_worst_high_games, "adjusted_score"] = NEUTRAL_SCORE

    # 3. period別に集計し持続性検証
    for group_col in ["machine_number", "machine_name"]:
        print(f"\n##### [{group_col}] #####")
        agg = (
            sub.groupby(["period", group_col])
            .agg(
                day_score_mean=("day_score", "mean"),
                adjusted_score_mean=("adjusted_score", "mean"),
                diff_sum=("diff_coins_normalized", "sum"),
            )
            .reset_index()
        )
        print_result("差枚合計(参考)", run_persistence(agg, "diff_sum", group_col))
        print_result("day_score平均(6分位ビニング)", run_persistence(agg, "day_score_mean", group_col))
        print_result("adjusted_score平均(高回転大負け補正)", run_persistence(agg, "adjusted_score_mean", group_col))


if __name__ == "__main__":
    main()
