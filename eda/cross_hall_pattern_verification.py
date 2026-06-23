"""
みとや大森町店で発見された法則性が他ホールでも成立するかを検証する。

検証対象:
1. 機種別持続性 vs 台番号別持続性 (Spearman rho, 3ヶ月期間 -> 次期間)
   + 機種効果を除いた台番号別の残差持続性
2. Q1(最低)/Q5(最高)継続率
3. クインタイル別の機械割(payout_rate)・diff分散・稼働量
4. 物理配置(x座標)とdiff_coins合計の相関
5. 稼働量(games)とdiff合計の相関

対象ホール: みとや大森町店を除く、machine_layoutテーブルを持つ全ホール
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_DIR = Path(__file__).resolve().parents[1] / "db"

TARGET_HALLS = [
    "ARROW池上店",
    "ザ-シティ-ベルシティ雑色店",
    "ヒロキ東口店",
    "マルハンメガシティ2000-蒲田1",
    "マルハンメガシティ2000-蒲田7",
    "レイトギャップ平和島",
    "楽園蒲田店",
    "金時京急蒲田店",
]

N_BINS = 5
COINS_PER_GAME = 3
WINDOW_MONTHS = 3


def load_data(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df


def load_layout(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT machine_number, x, y FROM machine_layout", conn)
    except Exception:
        df = pd.DataFrame(columns=["machine_number", "x", "y"])
    conn.close()
    return df


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    return (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months


def quintile(df: pd.DataFrame, value_col: str) -> pd.Series:
    return df.groupby("period")[value_col].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )


def persistence(agg: pd.DataFrame, group_col: str):
    periods = sorted(agg["period"].unique())
    if len(periods) < 2:
        return None
    pooled = []
    for p, p_next in zip(periods[:-1], periods[1:]):
        cur = agg[agg["period"] == p][[group_col, "quintile"]]
        nxt = agg[agg["period"] == p_next][[group_col, "quintile"]]
        m = cur.merge(nxt, on=group_col, suffixes=("_cur", "_next"))
        pooled.append(m)
    pooled = pd.concat(pooled, ignore_index=True)
    if len(pooled) < 5:
        return None
    rho, pval = spearmanr(pooled["quintile_cur"], pooled["quintile_next"])
    q5_stay = (pooled[pooled["quintile_cur"] == 5]["quintile_next"] == 5).mean()
    q1_stay = (pooled[pooled["quintile_cur"] == 1]["quintile_next"] == 1).mean()
    return {
        "n_periods": len(periods),
        "n_pairs": len(pooled),
        "rho": rho,
        "pval": pval,
        "q5_stay": q5_stay,
        "q1_stay": q1_stay,
    }


def analyze_hall(name: str) -> None:
    db_path = DB_DIR / f"{name}.db"
    if not db_path.exists():
        print(f"\n===== {name}: DBファイルなし、スキップ =====")
        return

    df = load_data(db_path)
    df["period"] = assign_period(df["date"], WINDOW_MONTHS)

    print(f"\n===== {name} =====")
    print(f"期間: {df['date'].min().date()} ~ {df['date'].max().date()}, "
          f"3ヶ月期間数={df['period'].nunique()}, "
          f"台番号数={df['machine_number'].nunique()}, "
          f"機種数={df['machine_name'].nunique()}")

    if df["period"].nunique() < 2:
        print("  期間数不足のためスキップ")
        return

    # ① 機種別 / 台番号別 持続性
    for group_col in ["machine_name", "machine_number"]:
        agg = (
            df.groupby(["period", group_col])
            .agg(
                diff_sum=("diff_coins_normalized", "sum"),
                games_sum=("games_normalized", "sum"),
            )
            .reset_index()
        )
        agg["quintile"] = quintile(agg, "diff_sum")
        result = persistence(agg, group_col)
        if result is None:
            print(f"  [{group_col}] サンプル不足")
            continue
        print(
            f"  [{group_col}] rho={result['rho']:.3f} (p={result['pval']:.3f}, "
            f"n={result['n_pairs']}), Q5stay={result['q5_stay']:.3f}, "
            f"Q1stay={result['q1_stay']:.3f}"
        )

        # ② Q1〜Q5の機械割（payout_rate）+ diff分散 + 稼働量
        agg["payout_rate"] = (
            (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
            / (agg["games_sum"] * COINS_PER_GAME)
            * 100
        )
        q_stats = agg.groupby("quintile").agg(
            payout_rate_mean=("payout_rate", "mean"),
            diff_std=("diff_sum", "std"),
            games_mean=("games_sum", "mean"),
        )
        print("    クインタイル別統計 (機械割%/diff_std/games_mean):")
        print(q_stats.to_string())

    # ① 機種名効果を除いた台番号別残差持続性
    agg_num = (
        df.groupby(["period", "machine_number", "machine_name"])
        .agg(diff_sum=("diff_coins_normalized", "sum"))
        .reset_index()
    )
    type_total = (
        df.groupby(["period", "machine_name"])["diff_coins_normalized"]
        .sum()
        .reset_index()
        .rename(columns={"diff_coins_normalized": "type_total"})
    )
    type_count = (
        df.groupby(["period", "machine_name"])["machine_number"]
        .nunique()
        .reset_index()
        .rename(columns={"machine_number": "type_n"})
    )
    agg_num = agg_num.merge(type_total, on=["period", "machine_name"]).merge(
        type_count, on=["period", "machine_name"]
    )
    agg_num["type_avg"] = agg_num["type_total"] / agg_num["type_n"]
    agg_num["residual"] = agg_num["diff_sum"] - agg_num["type_avg"]
    agg_num["quintile"] = agg_num.groupby("period")["residual"].transform(
        lambda x: pd.qcut(x, N_BINS, labels=False, duplicates="drop") + 1
    )
    result_resid = persistence(agg_num, "machine_number")
    if result_resid:
        print(
            f"  [台番号(機種効果除去後)] rho={result_resid['rho']:.3f} "
            f"(p={result_resid['pval']:.3f}, n={result_resid['n_pairs']})"
        )

    # ④ 物理配置(x座標)との相関
    layout = load_layout(db_path)
    if not layout.empty:
        overall = (
            df.groupby("machine_number")["diff_coins_normalized"].sum().reset_index()
        )
        merged = overall.merge(layout, on="machine_number")
        if len(merged) >= 5:
            rho_x, pval_x = spearmanr(merged["x"], merged["diff_coins_normalized"])
            print(f"  [x座標 vs diff合計] Spearman rho={rho_x:.3f} (p={pval_x:.3f}, n={len(merged)})")

    # ⑤ 稼働量(games)とdiff合計の相関 (全期間, machine_number単位)
    overall_agg = (
        df.groupby("machine_number")
        .agg(diff_sum=("diff_coins_normalized", "sum"), games_sum=("games_normalized", "sum"))
        .reset_index()
    )
    if len(overall_agg) >= 5:
        rho_g, pval_g = spearmanr(overall_agg["games_sum"], overall_agg["diff_sum"])
        print(f"  [games合計 vs diff合計(台番号別,全期間)] Spearman rho={rho_g:.3f} (p={pval_g:.3f}, n={len(overall_agg)})")


def main() -> None:
    for name in TARGET_HALLS:
        analyze_hall(name)


if __name__ == "__main__":
    main()
