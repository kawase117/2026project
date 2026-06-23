"""
機種内角番(同一機種の台番号グループにおける最小/最大台番号からの距離)と
差枚(機種効果除去後の残差)の関係を検証する。

「機種内角台(同一機種が並ぶ島の端の台番号)は差枚が良い/悪い」という仮説の検証。

手法:
1. Xgroup(DD4/7/14/17/24/27)・3ヶ月windowでperiod別に台番号ごとのdiff合計を集計
2. period内でmachine_nameが同じ台番号群をグループ化し、各グループの
   machine_number最小値/最大値を求める
3. edge_distance = min(自分の番号 - グループ最小, グループ最大 - 自分の番号)
   (0 = 角台, 値が大きいほど中央寄り)
4. 機種効果除去後の残差(diff - period内machine_name平均)とedge_distanceの
   Spearman相関、および角台(edge_distance=0) vs 非角台の残差平均を比較
"""
import sqlite3
from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

DB_PATH = Path(__file__).resolve().parents[1] / "db" / "みとや大森町店.db"

X_DDS = [4, 7, 14, 17, 24, 27]
WINDOW_MONTHS = 3


def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, diff_coins_normalized "
        "FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df


def assign_period(dates: pd.Series, window_months: int) -> pd.Series:
    start = dates.min().to_period("M")
    return (dates.dt.to_period("M") - start).apply(lambda x: x.n) // window_months


def main() -> None:
    df = load_data()
    sub = df[df["dd"].isin(X_DDS)].copy()
    sub["period"] = assign_period(sub["date"], WINDOW_MONTHS)

    agg = (
        sub.groupby(["period", "machine_number"])
        .agg(
            diff=("diff_coins_normalized", "sum"),
            machine_name=("machine_name", "first"),
        )
        .reset_index()
    )

    type_mean = agg.groupby(["period", "machine_name"])["diff"].transform("mean")
    agg["residual"] = agg["diff"] - type_mean

    grp = agg.groupby(["period", "machine_name"])["machine_number"]
    agg["grp_min"] = grp.transform("min")
    agg["grp_max"] = grp.transform("max")
    agg["grp_size"] = grp.transform("size")

    agg = agg[agg["grp_size"] >= 3].copy()

    agg["edge_distance"] = agg[["machine_number", "grp_min", "grp_max"]].apply(
        lambda r: min(r["machine_number"] - r["grp_min"], r["grp_max"] - r["machine_number"]),
        axis=1,
    )
    agg["is_edge"] = agg["edge_distance"] == 0

    print(f"対象レコード数: {len(agg)} (グループ数: {agg.groupby(['period','machine_name']).ngroups})")

    rho, pval = spearmanr(agg["edge_distance"], agg["residual"])
    print(f"\n[全体] edge_distance vs 残差(機種効果除去後diff): rho={rho:.3f} (p={pval:.3f})")

    print("\n[角台(edge_distance=0) vs 非角台] 残差の平均")
    print(agg.groupby("is_edge")["residual"].agg(["mean", "count"]).to_string())

    print("\n[edge_distance別] 残差の平均 (0〜5)")
    for d in range(0, 6):
        rows = agg[agg["edge_distance"] == d]
        if len(rows) == 0:
            continue
        print(f"  edge_distance={d}: mean_residual={rows['residual'].mean():.1f} n={len(rows)}")

    agg["edge_type"] = "middle"
    agg.loc[agg["machine_number"] == agg["grp_min"], "edge_type"] = "min_edge"
    agg.loc[agg["machine_number"] == agg["grp_max"], "edge_type"] = "max_edge"
    print("\n[edge_type別] 残差の平均")
    print(agg.groupby("edge_type")["residual"].agg(["mean", "count"]).to_string())


if __name__ == "__main__":
    main()
