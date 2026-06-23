"""
みとや大森町店 持続性分析: 指標(差枚/機械割/勝率)の比較 + 522番の代替台検証

1. 差枚(diff_coins_normalized)に加え、機械割(payout rate)・勝率(win rate)でも
   台番号別/機種別の持続性が同様に出るかを確認する。
2. 522番(マギレコ角台)が低クインタイルになった期間に、近隣台番号で
   高クインタイルになる台があるか(代替/シーソー仮説)をXgroup・3ヶ月windowで確認する。
   ※期間数が6しかないため検出力は非常に低い参考値。
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
N_BINS = 5
WINDOW_MONTHS = 3
COINS_PER_GAME = 3


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


def section_metric_comparison(df: pd.DataFrame) -> None:
    print("\n##### 指標別の持続性比較 (Xgroup, window=3ヶ月) #####")
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], WINDOW_MONTHS)

    for group_col in ["machine_number", "machine_name"]:
        print(f"\n[{group_col}]")
        base = (
            sub.groupby(["period", group_col])
            .agg(
                diff_sum=("diff_coins_normalized", "sum"),
                games_sum=("games_normalized", "sum"),
                win_days=("diff_coins_normalized", lambda x: (x > 0).sum()),
                total_days=("diff_coins_normalized", "size"),
            )
            .reset_index()
        )
        base["payout_rate"] = (
            (base["games_sum"] * COINS_PER_GAME + base["diff_sum"])
            / (base["games_sum"] * COINS_PER_GAME)
            * 100
        )
        base["win_rate"] = base["win_days"] / base["total_days"]

        print_result("差枚合計", run_persistence(base, "diff_sum", group_col))
        print_result("機械割(payout_rate)", run_persistence(base, "payout_rate", group_col))
        print_result("勝率(win_rate)", run_persistence(base, "win_rate", group_col))


def section_522_substitution(df: pd.DataFrame, radius: int = 5) -> None:
    print(f"\n##### 522番と近隣台番号(±{radius})の差枚クインタイル相関 (Xgroup, 3ヶ月) #####")
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], WINDOW_MONTHS)

    agg = (
        sub.groupby(["period", "machine_number"])["diff_coins_normalized"]
        .sum()
        .reset_index()
    )
    agg["quintile"] = agg.groupby("period")["diff_coins_normalized"].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )

    target = agg[agg["machine_number"] == 522].set_index("period")["quintile"]
    print(f"  522番 期間別クインタイル: {target.to_dict()}")

    neighbors = [n for n in range(522 - radius, 522 + radius + 1) if n != 522]
    rows = []
    for m in neighbors:
        other = agg[agg["machine_number"] == m].set_index("period")["quintile"]
        common = target.index.intersection(other.index)
        if len(common) < 3:
            continue
        rho, pval = spearmanr(target.loc[common], other.loc[common])
        rows.append((m, len(common), rho, pval))

    rows.sort(key=lambda x: x[2])
    for m, n, rho, pval in rows:
        print(f"  522 vs {m}: n={n} rho={rho:.3f} (p={pval:.3f})")


def main() -> None:
    df = load_data()
    section_metric_comparison(df)
    section_522_substitution(df)


if __name__ == "__main__":
    main()
