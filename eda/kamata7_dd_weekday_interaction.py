"""
蒲田7 DD x 曜日 交互作用マトリクス

全DD(1-31) x 曜日(月-日) の組み合わせで:
1. 各セルの3指標 (diff, plus_rate, hit104_rate)
2. 曜日ベースライン（非イベント日）からの乖離
3. 交互作用の強い組み合わせ Top/Bottom
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from eda.core import load_hall_df, HALL_EVENT_DIGITS

HALL = "蒲田7"
ANNIVERSARY_MMDD = "0707"
DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
EVENT_DDS = set(HALL_EVENT_DIGITS["蒲田7"])


def main():
    df = load_hall_df(HALL)
    df["payout_rate"] = (1 + df["diff"] / (df["games"] * 3)) * 100
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    mmdd = df["date"].str[4:8]
    n_excl = (mmdd == ANNIVERSARY_MMDD).sum()
    df = df[mmdd != ANNIVERSARY_MMDD].copy()
    print(f"7/7除外: {n_excl:,} rows. 残り: {len(df):,} rows, {df['date'].nunique()} days")

    bl_diff = df["diff"].mean()
    bl_plus = (df["diff"] > 0).mean() * 100
    bl_104 = df["hit104"].mean() * 100
    print(f"全体 baseline: diff={bl_diff:+.0f}, plus={bl_plus:.1f}%, 104%={bl_104:.1f}%\n")

    # ── 1. 曜日ベースライン（非イベント日） ──
    print("=" * 80)
    print("  1. 曜日ベースライン（非イベント日のみ）")
    print("=" * 80)
    non_evt = df[df["is_x_day"] == 0]
    dow_bl = {}
    for dow in DOW_ORDER:
        s = non_evt[non_evt["day_of_week"] == dow]
        dow_bl[dow] = {
            "diff": s["diff"].mean(),
            "plus": (s["diff"] > 0).mean() * 100,
            "hit104": s["hit104"].mean() * 100,
            "n": len(s),
        }
        b = dow_bl[dow]
        print(f"  {dow}: diff={b['diff']:+.0f}, plus={b['plus']:.1f}%, 104%={b['hit104']:.1f}%, n={b['n']:,}")

    # ── 2. DD x 曜日 マトリクス ──
    print("\n" + "=" * 80)
    print("  2. DD x 曜日 マトリクス")
    print("=" * 80)

    matrix_diff = {}
    matrix_plus = {}
    matrix_104 = {}
    matrix_n = {}

    for dd in range(1, 32):
        dd_sub = df[df["dd"] == dd]
        row_diff, row_plus, row_104, row_n = {}, {}, {}, {}
        for dow in DOW_ORDER:
            s = dd_sub[dd_sub["day_of_week"] == dow]
            if len(s) >= 50:
                row_diff[dow] = s["diff"].mean()
                row_plus[dow] = (s["diff"] > 0).mean() * 100
                row_104[dow] = s["hit104"].mean() * 100
            else:
                row_diff[dow] = np.nan
                row_plus[dow] = np.nan
                row_104[dow] = np.nan
            row_n[dow] = len(s)
        matrix_diff[dd] = row_diff
        matrix_plus[dd] = row_plus
        matrix_104[dd] = row_104
        matrix_n[dd] = row_n

    diff_df = pd.DataFrame(matrix_diff).T[DOW_ORDER]
    diff_df.index.name = "DD"
    plus_df = pd.DataFrame(matrix_plus).T[DOW_ORDER]
    h104_df = pd.DataFrame(matrix_104).T[DOW_ORDER]

    print("\n差枚 (avg_diff):")
    print(diff_df.round(0).to_string())

    print("\n104%超え率 (hit104_rate %):")
    print(h104_df.round(1).to_string())

    # ── 3. 曜日ベースラインからの乖離 ──
    print("\n" + "=" * 80)
    print("  3. 曜日ベースライン(非イベント日)からの乖離")
    print("=" * 80)

    dev_diff = diff_df.copy()
    dev_104 = h104_df.copy()
    for dow in DOW_ORDER:
        dev_diff[dow] = diff_df[dow] - dow_bl[dow]["diff"]
        dev_104[dow] = h104_df[dow] - dow_bl[dow]["hit104"]

    print("\n差枚乖離 (DD値 - 曜日baseline):")
    print(dev_diff.round(0).to_string())

    print("\n104%乖離pp (DD値 - 曜日baseline):")
    print(dev_104.round(1).to_string())

    # ── 4. イベントDDハイライト ──
    print("\n" + "=" * 80)
    print(f"  4. イベントDD ({sorted(EVENT_DDS)}) ベースライン乖離サマリ")
    print("=" * 80)

    print(f"\n{'DD':>4} {'evt':>3} |", end="")
    for dow in DOW_ORDER:
        print(f" {dow:>8}", end="")
    print("  | avg_dev")
    print("-" * 85)

    for dd in range(1, 32):
        is_evt = "***" if dd in EVENT_DDS else "   "
        vals = [dev_diff.loc[dd, dow] if dd in dev_diff.index else np.nan for dow in DOW_ORDER]
        valid_vals = [v for v in vals if not np.isnan(v)]
        avg_dev = np.mean(valid_vals) if valid_vals else np.nan

        print(f"DD{dd:02d} {is_evt} |", end="")
        for v in vals:
            if np.isnan(v):
                print("      ---", end="")
            elif v >= 100:
                print(f"  {v:+5.0f}!!", end="")
            elif v <= -100:
                print(f"  {v:+5.0f}--", end="")
            else:
                print(f"  {v:+6.0f} ", end="")
        if np.isnan(avg_dev):
            print(f"  |    ---")
        else:
            print(f"  | {avg_dev:+6.0f}")

    # ── 5. Top/Bottom 15 ──
    print("\n" + "=" * 80)
    print("  5. 曜日baseline乖離 Top15 / Bottom15")
    print("=" * 80)

    records = []
    for dd in range(1, 32):
        is_evt = dd in EVENT_DDS
        for dow in DOW_ORDER:
            d = dev_diff.loc[dd, dow] if dd in dev_diff.index else np.nan
            h = dev_104.loc[dd, dow] if dd in dev_104.index else np.nan
            raw = diff_df.loc[dd, dow] if dd in diff_df.index else np.nan
            raw_104 = h104_df.loc[dd, dow] if dd in h104_df.index else np.nan
            n = matrix_n.get(dd, {}).get(dow, 0)
            if not np.isnan(d) and n >= 50:
                records.append({
                    "DD": f"DD{dd:02d}", "曜日": dow, "evt": "*" if is_evt else "",
                    "diff": int(raw), "dev_diff": int(d),
                    "104%": round(raw_104, 1), "dev_104pp": round(h, 1),
                    "n": n,
                })

    rec_df = pd.DataFrame(records)

    print("\nTop15 (その曜日にしては異常に強い):")
    top = rec_df.sort_values("dev_diff", ascending=False).head(15)
    print(top.to_string(index=False))

    print("\nBottom15 (その曜日にしては異常に弱い):")
    bot = rec_df.sort_values("dev_diff", ascending=True).head(15)
    print(bot.to_string(index=False))

    # ── 6. イベント vs 非イベント 曜日別集約 ──
    print("\n" + "=" * 80)
    print("  6. イベントDD vs 非イベントDD 曜日別集約（全DD統合）")
    print("=" * 80)

    for dow in DOW_ORDER:
        dow_sub = df[df["day_of_week"] == dow]
        evt = dow_sub[dow_sub["is_x_day"] == 1]
        non = dow_sub[dow_sub["is_x_day"] == 0]
        if len(evt) < 100 or len(non) < 100:
            continue
        e_d, e_p, e_h = evt["diff"].mean(), (evt["diff"]>0).mean()*100, evt["hit104"].mean()*100
        n_d, n_p, n_h = non["diff"].mean(), (non["diff"]>0).mean()*100, non["hit104"].mean()*100
        print(f"\n  {dow}曜 (evt n={len(evt):,}, non n={len(non):,}):")
        print(f"    イベント:   diff={e_d:+.0f}, plus={e_p:.1f}%, 104%={e_h:.1f}%")
        print(f"    非イベント: diff={n_d:+.0f}, plus={n_p:.1f}%, 104%={n_h:.1f}%")
        print(f"    差分:       diff={e_d-n_d:+.0f}, plus={e_p-n_p:+.1f}pp, 104%={e_h-n_h:+.1f}pp")


if __name__ == "__main__":
    main()
