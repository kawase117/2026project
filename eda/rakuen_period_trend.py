"""楽園蒲田店: clean列の端番効果を3ヶ月ごとに分割し、時期トレンドを見る。

`eda/rakuen_clean_section_edge_effect.py` で確定した「clean列の端(depth=1)に
ジャグ +1.2pp / 技術介入 +1.4pp」が、時期によって強くなったり弱くなったり
しているかを調べる。`backtest/regime.py` のローリング窓アプローチと違い、
ここでは固定の3ヶ月ブロックで区切って点推定とCIを並べる（トレンドの有無を
目視で追いやすくするため）。

追加指標:
    機械割pp（同日×同機種残差）に加えて、
      * **差枚**（同日×同機種残差、単位: 枚/台。3で割って%にする前の生値）
      * **機械割104%以上ヒット率**（同日×同機種の中で 104% 以上だった日の
        割合の残差）
    を計算する。BB+RB（回/1000G）はAT機では意味を持たないため
    （AT機はBB/RBでなくAT当選で出玉が出る）AT一般の主指標にはならないが、
    差枚と機械割104%はどの機種にも意味を持つため、**AT一般もここで初めて
    正しく評価できる**。

期間の切り方:
    2025-01-01 起点で3ヶ月ずつの固定ブロックに切る。2026-07-01〜05 の端数
    5日はサンプルが薄すぎるため集計から除外する（出力に注記）。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_period_trend
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from eda.rakuen_clean_section_edge_effect import OUT_DIR, load_frame

N_BOOT = 2000
SEED = 20260728
MIN_MACHINES_PER_ARM = 3

PERIODS = [
    ("2025Q1(1-3月)", "20250101", "20250331"),
    ("2025Q2(4-6月)", "20250401", "20250630"),
    ("2025Q3(7-9月)", "20250701", "20250930"),
    ("2025Q4(10-12月)", "20251001", "20251231"),
    ("2026Q1(1-3月)", "20260101", "20260331"),
    ("2026Q2(4-6月)", "20260401", "20260630"),
    # 2026-07-01〜05 は5日のみでサンプル不足のため除外
]


def add_residuals(df: pd.DataFrame) -> pd.DataFrame:
    """同日×同機種平均からの残差を3指標ぶん追加する。1台のみの群は対照が
    取れず残差が恒等的に0になるため除外する。
    """
    df = df.assign(hit104=(df["machine_rate"] >= 104).astype(float))
    grp = df.groupby(["date", "machine_name"])
    df = df.assign(_n_in_group=grp["machine_number"].transform("size"))
    for col in ("machine_rate", "diff_coins", "hit104"):
        df[f"resid_{col}"] = df[col] - grp[col].transform("mean")
    return df.loc[df["_n_in_group"] >= 2].drop(columns="_n_in_group")


def edge_effect(df: pd.DataFrame, metric: str, rng: np.random.Generator) -> dict | None:
    """clean列の depth==1(端) vs depth>=2(非端) を台単位クラスタブートストラップで比較。"""
    unit = df.groupby("machine_number").agg(
        value=(metric, "mean"), is_edge=("is_edge", "first"), n_days=(metric, "size")
    )
    treat = unit.loc[unit["is_edge"]]
    control = unit.loc[~unit["is_edge"]]
    if len(treat) < MIN_MACHINES_PER_ARM or len(control) < MIN_MACHINES_PER_ARM:
        return None

    def weighted(sub: pd.DataFrame) -> float:
        return float(np.average(sub["value"], weights=sub["n_days"]))

    point = weighted(treat) - weighted(control)
    t_val, t_w = treat["value"].to_numpy(), treat["n_days"].to_numpy()
    c_val, c_w = control["value"].to_numpy(), control["n_days"].to_numpy()
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        ti = rng.integers(0, len(t_val), len(t_val))
        ci = rng.integers(0, len(c_val), len(c_val))
        draws[i] = np.average(t_val[ti], weights=t_w[ti]) - np.average(c_val[ci], weights=c_w[ci])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {
        "effect": round(point, 4),
        "ci_lo": round(float(lo), 4),
        "ci_hi": round(float(hi), 4),
        "sig": "*" if (lo > 0 or hi < 0) else "ns",
        "n_edge": int(len(treat)),
        "n_nonedge": int(len(control)),
        "n_rows": int(len(df)),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    df = load_frame()
    df = df.loc[df["group"] == "clean"].copy()
    df = add_residuals(df)
    print(f"clean列・機種内対照あり: {len(df):,}行 / {df['machine_number'].nunique()}台\n")

    metrics = [
        ("resid_machine_rate", "機械割pp"),
        ("resid_diff_coins", "差枚(枚/台)"),
        ("resid_hit104", "機械割104%以上ヒット率"),
    ]
    categories = ["ジャグ", "技術介入", "ハナハナ", "AT一般", "＜全体＞"]

    records = []
    for period_name, start, end in PERIODS:
        period_df = df.loc[(df["date"] >= start) & (df["date"] <= end)]
        for category in categories:
            cat_df = period_df if category == "＜全体＞" else period_df.loc[period_df["category"] == category]
            if cat_df.empty:
                continue
            for metric_col, metric_label in metrics:
                res = edge_effect(cat_df, metric_col, rng)
                if res:
                    records.append(
                        {
                            "period": period_name,
                            "category": category,
                            "metric": metric_label,
                            **res,
                        }
                    )

    result = pd.DataFrame(records)
    result.to_csv(OUT_DIR / "period_trend.csv", index=False, encoding="utf-8-sig")

    for metric_label in ("機械割pp", "差枚(枚/台)", "機械割104%以上ヒット率"):
        print(f"=== {metric_label} ===")
        pivot = result.loc[result["metric"] == metric_label].pivot(index="category", columns="period", values="effect")
        cols = [p[0] for p in PERIODS if p[0] in pivot.columns]
        print(pivot.reindex(columns=cols).reindex(categories).to_string())
        print()

    print("=== 有意フラグ（機械割pp） ===")
    sig_pivot = result.loc[result["metric"] == "機械割pp"].pivot(index="category", columns="period", values="sig")
    cols = [p[0] for p in PERIODS if p[0] in sig_pivot.columns]
    print(sig_pivot.reindex(columns=cols).reindex(categories).to_string())

    print("\n除外: 2026-07-01〜05（5日のみ、サンプル不足）")
    print(f"出力先: {OUT_DIR / 'period_trend.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
