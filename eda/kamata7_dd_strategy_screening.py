"""
蒲田7 DD別戦略探索 Phase 1 — DDBin × Which軸 網羅スクリーニング

既存5bin [1-6, 7-12, 13-18, 19-24, 25-31] で Which軸を一括スキャン。
各DDBinで「どのWhich軸に有意な分散があるか」を特定する。

出力:
  1. DDBin別 基本統計（N, avg_diff, plus_rate）
  2. DDBin × 末尾
  3. DDBin × 曜日
  4. DDBin × セグメント(A/N) — machine_master JOIN
  5. DDBin × イベント/非イベント
  6. DDBin内 個別DD分散チェック
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

sys.path.insert(0, str(Path(__file__).parent.parent))
from eda.core import load_hall_df, _epsilon_squared

HALL = "蒲田7"
DD_BINS = [0, 6, 12, 18, 24, 31]
DD_LABELS = ["DD01-06", "DD07-12", "DD13-18", "DD19-24", "DD25-31"]


def add_dd_bin(df: pd.DataFrame) -> pd.DataFrame:
    df["dd_bin"] = pd.cut(
        df["dd"], bins=DD_BINS, labels=DD_LABELS, right=True
    )
    return df


def add_segment(df: pd.DataFrame) -> pd.DataFrame:
    import sqlite3
    db_path = Path(__file__).parent.parent / "db" / "マルハンメガシティ2000-蒲田7.db"
    conn = sqlite3.connect(db_path)
    try:
        master = pd.read_sql_query(
            "SELECT machine_name_normalized, jug_flag, hana_flag, bt_flag "
            "FROM machine_master", conn
        )
    except Exception:
        df["segment"] = "unknown"
        return df
    finally:
        conn.close()

    for col in ["jug_flag", "hana_flag", "bt_flag"]:
        master[col] = pd.to_numeric(master[col], errors="coerce").fillna(0).astype(int)

    name_map = master.set_index("machine_name_normalized")[["jug_flag", "hana_flag", "bt_flag"]]
    name_map = name_map[~name_map.index.duplicated(keep="first")]

    df = df.merge(name_map, left_on="machine_name", right_index=True, how="left")
    for col in ["jug_flag", "hana_flag", "bt_flag"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = df[col].fillna(0).astype(int)

    df["segment"] = np.where(
        (df["jug_flag"] == 1) | (df["hana_flag"] == 1), "A", "N"
    )
    return df


METRICS = ["diff", "plus", "hit104"]


def kruskal_test(df: pd.DataFrame, group_col: str, metric: str = "diff") -> dict:
    groups = [grp[metric].values for _, grp in df.groupby(group_col) if len(grp) >= 2]
    if len(groups) < 2:
        return {"H": np.nan, "p": np.nan, "eps2": np.nan}
    try:
        H, p = kruskal(*groups)
        k = len(groups)
        n = sum(len(g) for g in groups)
        return {"H": round(H, 3), "p": round(p, 4), "eps2": round(_epsilon_squared(H, k, n), 4)}
    except Exception:
        return {"H": np.nan, "p": np.nan, "eps2": np.nan}


def kw_3metrics(df: pd.DataFrame, group_col: str) -> dict:
    return {m: kruskal_test(df, group_col, m) for m in METRICS}


def summarize_group(df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    agg = (
        df.groupby(group_cols)
        .agg(
            n=("diff", "count"),
            avg_diff=("diff", "mean"),
            median_diff=("diff", "median"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    agg["avg_diff"] = agg["avg_diff"].round(0).astype(int)
    agg["median_diff"] = agg["median_diff"].round(0).astype(int)
    agg["plus_rate"] = (agg["plus_rate"] * 100).round(1)
    agg["hit104_rate"] = (agg["hit104_rate"] * 100).round(1)
    return agg


def fmt_kw3(kw3: dict) -> str:
    parts = []
    for m, label in [("diff", "差枚"), ("plus", "勝率"), ("hit104", "104%")]:
        k = kw3[m]
        p_str = f"{k['p']:.4f}" if not np.isnan(k["p"]) else "nan"
        parts.append(f"{label} p={p_str}")
    return " | ".join(parts)


def print_section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    print("蒲田7 DD別戦略探索 Phase 1 — DDBin × Which軸 網羅スクリーニング")
    print(f"DDBin: {DD_LABELS}")

    df = load_hall_df(HALL)
    df = add_dd_bin(df)
    df = add_segment(df)

    # 機械割・hit104 計算
    df["payout_rate"] = (1 + df["diff"] / (df["games"] * 3)) * 100
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    print(f"データ: {len(df):,} rows, {df['date'].nunique()} days")
    print(f"期間: {df['date'].min()} ~ {df['date'].max()}")
    print(f"セグメント分布: A={len(df[df['segment']=='A']):,}, N={len(df[df['segment']=='N']):,}")

    baseline_plus = (df["diff"] > 0).mean() * 100
    baseline_diff = df["diff"].mean()
    baseline_104 = df["hit104"].mean() * 100
    print(f"全体 baseline: avg_diff={baseline_diff:.0f}, plus_rate={baseline_plus:.1f}%, hit104={baseline_104:.1f}%")

    # ── 1. DDBin基本統計 ──
    print_section("1. DDBin 基本統計 (3指標)")
    bin_stats = summarize_group(df, ["dd_bin"])
    kw3 = kw_3metrics(df, "dd_bin")
    print(bin_stats.to_string(index=False))
    print(f"\nKruskal-Wallis: {fmt_kw3(kw3)}")

    # ── 2. DDBin × 末尾 ──
    print_section("2. DDBin x 台末尾 (machine_digit)")
    for bin_label in DD_LABELS:
        sub = df[df["dd_bin"] == bin_label]
        kw3 = kw_3metrics(sub, "machine_digit")
        stats = summarize_group(sub, ["machine_digit"]).sort_values("avg_diff", ascending=False)
        top3, bot3 = stats.head(3), stats.tail(3)
        print(f"\n--- {bin_label} (n={len(sub):,})")
        print(f"  {fmt_kw3(kw3)}")
        print("  Top3:")
        for _, r in top3.iterrows():
            print(f"    末尾{r['machine_digit']}: diff={r['avg_diff']:+,}, plus={r['plus_rate']}%, 104%={r['hit104_rate']}%, n={r['n']}")
        print("  Bottom3:")
        for _, r in bot3.iterrows():
            print(f"    末尾{r['machine_digit']}: diff={r['avg_diff']:+,}, plus={r['plus_rate']}%, 104%={r['hit104_rate']}%, n={r['n']}")

    # ── 3. DDBin × 曜日 ──
    print_section("3. DDBin x 曜日")
    for bin_label in DD_LABELS:
        sub = df[df["dd_bin"] == bin_label]
        kw3 = kw_3metrics(sub, "day_of_week")
        top3 = summarize_group(sub, ["day_of_week"]).sort_values("avg_diff", ascending=False).head(3)
        print(f"\n--- {bin_label}")
        print(f"  {fmt_kw3(kw3)}")
        for _, r in top3.iterrows():
            print(f"    {r['day_of_week']}: diff={r['avg_diff']:+,}, plus={r['plus_rate']}%, 104%={r['hit104_rate']}%, n={r['n']}")

    # ── 4. DDBin × セグメント(A/N) ──
    print_section("4. DDBin x セグメント (A/N)")
    cross = summarize_group(df, ["dd_bin", "segment"])
    print(cross.to_string(index=False))
    for bin_label in DD_LABELS:
        sub = df[df["dd_bin"] == bin_label]
        kw3 = kw_3metrics(sub, "segment")
        print(f"  {bin_label}: {fmt_kw3(kw3)}")

    # ── 5. DDBin × イベント/非イベント ──
    print_section("5. DDBin x イベント (is_x_day) / MMDDゾロ目")
    for bin_label in DD_LABELS:
        sub = df[df["dd_bin"] == bin_label]
        for label, mask_col, mask_val in [
            ("イベント日", "is_x_day", 1), ("非イベント日", "is_x_day", 0),
            ("MMDDゾロ目", "is_mmdd_zorome", 1),
        ]:
            subset = sub[sub[mask_col] == mask_val]
            if len(subset) > 0:
                avg = subset["diff"].mean()
                plus = (subset["diff"] > 0).mean() * 100
                h104 = subset["hit104"].mean() * 100
                print(f"  {bin_label} {label}: diff={avg:+.0f}, plus={plus:.1f}%, 104%={h104:.1f}%, n={len(subset):,}")
            else:
                print(f"  {bin_label} {label}: n=0")

    # ── 6. DDBin内 個別DD分散チェック ──
    print_section("6. DDBin内 個別DD分散 (Bin内で特定DDに集中？)")
    for bin_label in DD_LABELS:
        sub = df[df["dd_bin"] == bin_label]
        dd_stats = summarize_group(sub, ["dd"]).sort_values("avg_diff", ascending=False)
        kw3 = kw_3metrics(sub, "dd")

        print(f"\n--- {bin_label}")
        print(f"  {fmt_kw3(kw3)}")
        for _, r in dd_stats.iterrows():
            print(f"  DD{int(r['dd']):02d}: diff={r['avg_diff']:+,}, plus={r['plus_rate']}%, 104%={r['hit104_rate']}%, n={r['n']}")

    # ── サマリ ──
    print_section("SUMMARY: 3指標 p-value マトリクス")
    for metric, metric_label in [("diff", "差枚"), ("plus", "勝率"), ("hit104", "104%超え")]:
        results = []
        for axis_name, group_col in [
            ("末尾", "machine_digit"), ("曜日", "day_of_week"),
            ("セグメント", "segment"), ("DD個別", "dd"),
        ]:
            for bin_label in DD_LABELS:
                sub = df[df["dd_bin"] == bin_label]
                kw = kruskal_test(sub, group_col, metric)
                results.append({
                    "DDBin": bin_label, "Which軸": axis_name,
                    "KW_p": kw["p"], "eps2": kw["eps2"],
                })
        summary = pd.DataFrame(results)
        print(f"\n--- {metric_label} ---")
        pivot = summary.pivot_table(index="DDBin", columns="Which軸", values="KW_p")
        print(pivot.round(4).to_string())

        sig = summary[summary["KW_p"] < 0.10].sort_values("KW_p")
        if len(sig) > 0:
            print(f"  有意 (p<0.10): {len(sig)}件")
        else:
            print("  有意な組み合わせなし")


if __name__ == "__main__":
    main()
