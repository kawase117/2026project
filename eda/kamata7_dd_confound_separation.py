"""
蒲田7 DD別戦略探索 Phase 2 -- DD07-12 / DD25-31 交絡分離

目的: イベント日効果 vs 曜日効果 を分離する
- 7/7（全台設定6）は外れ値として除外
- 各DDについて曜日分布を確認し、曜日の偏りで見かけの差が出ていないか検証
- 同一曜日内でイベント日 vs 非イベント日を比較（曜日を統制した純粋なイベント効果）

3指標: 差枚, 勝率(plus_rate), 機械割104超え(hit104_rate)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu

sys.path.insert(0, str(Path(__file__).parent.parent))
from eda.core import load_hall_df, _epsilon_squared

HALL = "蒲田7"
ANNIVERSARY_MMDD = "0707"


def prepare_data() -> pd.DataFrame:
    df = load_hall_df(HALL)
    df["payout_rate"] = (1 + df["diff"] / (df["games"] * 3)) * 100
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    mmdd = df["date"].str[4:8]
    n_0707 = (mmdd == ANNIVERSARY_MMDD).sum()
    df = df[mmdd != ANNIVERSARY_MMDD].copy()
    print(f"7/7 除外: {n_0707:,} rows removed")

    return df


def mw_test(a: np.ndarray, b: np.ndarray) -> dict:
    if len(a) < 5 or len(b) < 5:
        return {"U": np.nan, "p": np.nan}
    try:
        U, p = mannwhitneyu(a, b, alternative="two-sided")
        return {"U": round(U, 0), "p": round(p, 4)}
    except Exception:
        return {"U": np.nan, "p": np.nan}


def print_section(title: str):
    print(f"\n{'='*75}")
    print(f"  {title}")
    print(f"{'='*75}")


def stats_line(label: str, sub: pd.DataFrame) -> str:
    if len(sub) == 0:
        return f"  {label}: n=0"
    d = sub["diff"].mean()
    p = (sub["diff"] > 0).mean() * 100
    h = sub["hit104"].mean() * 100
    return f"  {label}: diff={d:+.0f}, plus={p:.1f}%, 104%={h:.1f}%, n={len(sub):,}"


def analyze_bin(df: pd.DataFrame, dd_range: range, bin_label: str):
    sub = df[df["dd"].isin(dd_range)].copy()
    print_section(f"{bin_label} (7/7除外後)")
    print(f"全体: n={len(sub):,}, days={sub['date'].nunique()}")

    # ── A. DD別 基本統計（3指標） ──
    print(f"\n--- A. DD別 基本統計 ---")
    for dd in sorted(dd_range):
        dd_sub = sub[sub["dd"] == dd]
        evt = dd_sub[dd_sub["is_x_day"] == 1]
        non = dd_sub[dd_sub["is_x_day"] == 0]
        print(f"\n  DD{dd:02d} (n={len(dd_sub):,}, is_x_day={len(evt):,}/{len(dd_sub):,})")
        print(stats_line("    全体    ", dd_sub))
        if len(evt) > 0:
            print(stats_line("    イベント", evt))
        if len(non) > 0:
            print(stats_line("    非イベント", non))

    # ── B. 曜日分布の偏りチェック ──
    print(f"\n--- B. 曜日分布 (DD別) ---")
    dow_order = ["月", "火", "水", "木", "金", "土", "日"]
    for dd in sorted(dd_range):
        dd_sub = sub[sub["dd"] == dd]
        dow_counts = dd_sub.groupby("day_of_week")["date"].nunique()
        total_days = dow_counts.sum()
        parts = []
        for d in dow_order:
            cnt = dow_counts.get(d, 0)
            pct = cnt / total_days * 100 if total_days > 0 else 0
            parts.append(f"{d}:{cnt}({pct:.0f}%)")
        print(f"  DD{dd:02d}: {', '.join(parts)}")

    # ── C. 曜日統制: 同一曜日内でDD間比較 ──
    print(f"\n--- C. 曜日統制: 曜日別に各DDの差枚を比較 ---")
    for dow in dow_order:
        dow_sub = sub[sub["day_of_week"] == dow]
        if len(dow_sub) < 50:
            continue
        dd_stats = []
        for dd in sorted(dd_range):
            dd_dow = dow_sub[dow_sub["dd"] == dd]
            if len(dd_dow) >= 10:
                dd_stats.append({
                    "dd": dd,
                    "diff": dd_dow["diff"].mean(),
                    "plus": (dd_dow["diff"] > 0).mean() * 100,
                    "hit104": dd_dow["hit104"].mean() * 100,
                    "n": len(dd_dow),
                })
        if len(dd_stats) < 2:
            continue
        dd_df = pd.DataFrame(dd_stats).sort_values("diff", ascending=False)
        best = dd_df.iloc[0]
        worst = dd_df.iloc[-1]
        spread = best["diff"] - worst["diff"]
        event_dds = {1, 7, 11, 17, 22, 27, 30, 31}
        print(f"\n  {dow}曜 (spread={spread:+.0f}):")
        for _, r in dd_df.iterrows():
            marker = " *" if int(r["dd"]) in event_dds else ""
            print(f"    DD{int(r['dd']):02d}: diff={r['diff']:+.0f}, plus={r['plus']:.1f}%, 104%={r['hit104']:.1f}%, n={int(r['n'])}{marker}")

    # ── D. イベント効果の純粋抽出 ──
    print(f"\n--- D. イベント効果の純粋抽出 ---")
    print(f"  同一曜日で is_x_day=1 vs is_x_day=0 を比較")
    dow_order_all = ["月", "火", "水", "木", "金", "土", "日"]
    for dow in dow_order_all:
        dow_sub = sub[sub["day_of_week"] == dow]
        evt = dow_sub[dow_sub["is_x_day"] == 1]
        non = dow_sub[dow_sub["is_x_day"] == 0]
        if len(evt) < 30 or len(non) < 30:
            continue
        mw_diff = mw_test(evt["diff"].values, non["diff"].values)
        mw_104 = mw_test(evt["hit104"].values, non["hit104"].values)

        e_d = evt["diff"].mean()
        e_p = (evt["diff"] > 0).mean() * 100
        e_h = evt["hit104"].mean() * 100
        n_d = non["diff"].mean()
        n_p = (non["diff"] > 0).mean() * 100
        n_h = non["hit104"].mean() * 100

        print(f"\n  {dow}曜:")
        print(f"    イベント:   diff={e_d:+.0f}, plus={e_p:.1f}%, 104%={e_h:.1f}%, n={len(evt):,}")
        print(f"    非イベント: diff={n_d:+.0f}, plus={n_p:.1f}%, 104%={n_h:.1f}%, n={len(non):,}")
        print(f"    差分:       diff={e_d-n_d:+.0f}, plus={e_p-n_p:+.1f}pp, 104%={e_h-n_h:+.1f}pp")
        print(f"    MW検定:     差枚 p={mw_diff['p']}, 104% p={mw_104['p']}")

    # ── E. 曜日効果の純粋抽出 (非イベント日のみ) ──
    print(f"\n--- E. 曜日効果の純粋抽出 (非イベント日のみ) ---")
    non_event = sub[sub["is_x_day"] == 0]
    if len(non_event) > 100:
        dow_stats = []
        for dow in dow_order_all:
            dow_sub = non_event[non_event["day_of_week"] == dow]
            if len(dow_sub) >= 20:
                dow_stats.append({
                    "曜日": dow,
                    "diff": int(dow_sub["diff"].mean()),
                    "plus": round((dow_sub["diff"] > 0).mean() * 100, 1),
                    "hit104": round(dow_sub["hit104"].mean() * 100, 1),
                    "n": len(dow_sub),
                })
        if dow_stats:
            dow_df = pd.DataFrame(dow_stats).sort_values("diff", ascending=False)
            print(dow_df.to_string(index=False))

            groups = [non_event[non_event["day_of_week"] == d]["diff"].values
                      for d in dow_order_all
                      if len(non_event[non_event["day_of_week"] == d]) >= 10]
            if len(groups) >= 2:
                H, p = kruskal(*groups)
                print(f"  KW (非イベント日のみ): H={H:.3f}, p={p:.4f}")


def main():
    print("蒲田7 DD別戦略探索 Phase 2 -- イベント日 vs 曜日 交絡分離")
    print(f"7/7 (anniversary, 全台設定6) を除外して分析\n")

    df = prepare_data()

    analyze_bin(df, range(1, 7), "DD01-06")
    analyze_bin(df, range(7, 13), "DD07-12")
    analyze_bin(df, range(13, 19), "DD13-18")
    analyze_bin(df, range(19, 25), "DD19-24")
    analyze_bin(df, range(25, 32), "DD25-31")


if __name__ == "__main__":
    main()
