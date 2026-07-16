"""蒲田1 DD14 セクション連続プラス現象(2077-2161, 9セクション)の堅牢性検証。

契約:
- diff_coins_normalized は「枚」(差枚)、games_normalized は正規化済み回転数。
- 集計は「台×日」レコードをsectionでgroupbyした単純平均(日重み付けなし)。
- DD = dateのday成分。games_normalized>=1000でフィルタ。
- 蒲田1は durable_machine_numbers が未定義(空)のため鉄台除外は不要。
- 新台除外用カラムはこのDBスキーマに存在しないため未対応(既知の限界)。

実行: venv\\Scripts\\python.exe eda\\kamata1_dd14_section_streak_robustness.py
"""

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

STREAK_SECTIONS = [
    "2077-2087",
    "2088-2098",
    "2099-2109",
    "2110-2120",
    "2121-2131",
    "2132-2142",
    "2143-2146",
    "2147-2150",
    "2151-2161",
]
TOP2_FLAG_THRESHOLD = 0.80
TOP2_WATCH_THRESHOLD = 0.70


def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    layout = pd.read_sql(
        "SELECT machine_number, section, section_min, section_max, rank_from_min, rank_from_max FROM machine_layout",
        conn,
    )
    res = pd.read_sql(
        "SELECT date, machine_number, diff_coins_normalized, games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    res["date"] = pd.to_datetime(res["date"])
    res["dd"] = res["date"].dt.day
    df = res.merge(layout, on="machine_number", how="left")
    df = df[df["games_normalized"] >= 1000].copy()
    return df


def quarterly_check(d14: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    dates = sorted(d14["date"].unique())
    n = len(dates)
    edges = np.linspace(0, n, 5, dtype=int)  # 4分割、端数は最後のQへ
    rows = []
    for qi in range(4):
        q_dates = dates[edges[qi] : edges[qi + 1]] if qi < 3 else dates[edges[qi] :]
        sub = d14[d14["date"].isin(q_dates)]
        g = sub[sub["section"].isin(STREAK_SECTIONS)].groupby("section")["diff_coins_normalized"].mean()
        g = g.reindex(STREAK_SECTIONS)
        all_positive = bool((g > 0).all()) if g.notna().all() else False
        for sec in STREAK_SECTIONS:
            rows.append(
                {
                    "quarter": f"Q{qi + 1}",
                    "n_dates": len(q_dates),
                    "dates": ",".join(str(d)[:10] for d in q_dates),
                    "section": sec,
                    "mean_diff": g.get(sec, np.nan),
                    "all_9_positive_this_quarter": all_positive,
                }
            )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "quarterly_section_means.csv", index=False, encoding="utf-8-sig")
    return out


def bootstrap_check(d14: pd.DataFrame, out_dir: Path, n_boot: int = 2000, seed: int = 42) -> pd.DataFrame:
    dates = sorted(d14["date"].unique())
    rng = np.random.default_rng(seed)
    all_positive_flags = []
    section_positive_counts = {sec: 0 for sec in STREAK_SECTIONS}
    for _ in range(n_boot):
        sample_dates = rng.choice(dates, size=len(dates), replace=True)
        sub = d14[d14["date"].isin(sample_dates)]
        g = sub[sub["section"].isin(STREAK_SECTIONS)].groupby("section")["diff_coins_normalized"].mean()
        g = g.reindex(STREAK_SECTIONS)
        if g.notna().all():
            all_pos = bool((g > 0).all())
        else:
            all_pos = False
        all_positive_flags.append(all_pos)
        for sec in STREAK_SECTIONS:
            v = g.get(sec, np.nan)
            if pd.notna(v) and v > 0:
                section_positive_counts[sec] += 1

    all_positive_flags = np.array(all_positive_flags)
    ci_all9 = all_positive_flags.mean()
    rows = [
        {
            "metric": "P(all_9_sections_positive)",
            "estimate": ci_all9,
            "n_boot": n_boot,
        }
    ]
    for sec in STREAK_SECTIONS:
        rows.append(
            {
                "metric": f"P(section_positive)::{sec}",
                "estimate": section_positive_counts[sec] / n_boot,
                "n_boot": n_boot,
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "bootstrap_ci.csv", index=False, encoding="utf-8-sig")
    return out


def top2_share_check(d14: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    for sec in STREAK_SECTIONS:
        sub = d14[d14["section"] == sec]
        if sub.empty:
            rows.append(
                {
                    "section": sec,
                    "n_records": 0,
                    "top2_share": np.nan,
                    "top1_machine": np.nan,
                    "top2_machine": np.nan,
                    "verdict": "no_data",
                }
            )
            continue
        per_machine = sub.groupby("machine_number")["diff_coins_normalized"].sum()
        positive_total = per_machine[per_machine > 0].sum()
        if positive_total <= 0:
            rows.append(
                {
                    "section": sec,
                    "n_records": len(sub),
                    "top2_share": np.nan,
                    "top1_machine": np.nan,
                    "top2_machine": np.nan,
                    "verdict": "no_positive_total",
                }
            )
            continue
        top2 = per_machine.sort_values(ascending=False).head(2)
        share = top2.clip(lower=0).sum() / positive_total
        if share >= TOP2_FLAG_THRESHOLD:
            verdict = "flag(machine_specific)"
        elif share >= TOP2_WATCH_THRESHOLD:
            verdict = "watch"
        else:
            verdict = "section_wide"
        rows.append(
            {
                "section": sec,
                "n_records": len(sub),
                "top2_share": share,
                "top1_machine": int(top2.index[0]),
                "top2_machine": int(top2.index[1]) if len(top2) > 1 else np.nan,
                "verdict": verdict,
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / "top2_share.csv", index=False, encoding="utf-8-sig")
    return out


def kakuban_cross_check(d14: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    sub = d14[d14["section"].isin(STREAK_SECTIONS)].copy()
    sub["kakuban_min"] = pd.to_numeric(sub["rank_from_min"], errors="coerce")
    g = sub.groupby("kakuban_min")["diff_coins_normalized"].agg(["mean", "count"]).reset_index()
    g = g.sort_values("kakuban_min")
    g.to_csv(out_dir / "kakuban_cross.csv", index=False, encoding="utf-8-sig")
    return g


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="db/マルハンメガシティ2000-蒲田1.db")
    parser.add_argument("--out-dir", default="ml/analysis/results/kamata1_dd14_section_streak")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_data(args.db)
    d14 = df[df["dd"] == 14].copy()

    q = quarterly_check(d14, out_dir)
    b = bootstrap_check(d14, out_dir)
    t = top2_share_check(d14, out_dir)
    k = kakuban_cross_check(d14, out_dir)

    print("=== Quarterly: all_9_positive per quarter ===")
    print(q[["quarter", "n_dates", "all_9_positive_this_quarter"]].drop_duplicates().to_string(index=False))
    print()
    print("=== Bootstrap P(all 9 sections positive) ===")
    print(b[b["metric"] == "P(all_9_sections_positive)"].to_string(index=False))
    print()
    print("=== top2_share per section ===")
    print(t.to_string(index=False))
    print()
    print("=== kakuban (rank_from_min) cross ===")
    print(k.to_string(index=False))


if __name__ == "__main__":
    main()
