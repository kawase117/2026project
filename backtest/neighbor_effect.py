"""末尾指定の予告（例: 「末尾7が1/2⑤⑥」）に対して、対象末尾の台の物理的な両隣
（machine_number ±1）に仕掛けが漏れているかを検定する。

なぜ末尾グループ（announce.py の position_rule）と別に要るか:
    position_rule は「末尾7の台」をホール全体の末尾グループとして扱い、機種内残差の
    平均を末尾7 vs それ以外で比較する。これは「ホールが末尾7という属性を狙ったか」を
    測る指標であって、「末尾7の台の隣の座席」を測る指標ではない。
    machine_number は概ね物理的な設置順（同一機種のブロックが連番で並ぶ）なので、
    「隣」は末尾グループとは別の母集団になる。2026-08-17 楽園蒲田で確認したところ、
    末尾7の台（59台）の左右隣接枠118のうち75.4%が同一機種だった。

    この違いが実務的な意味を持つのは「朝の入場で対象末尾の台に座れなかったとき、
    隣の台に座る価値があるか」という立ち回りの判断だからである。末尾グループ全体の
    強さではなく、対象末尾の台そのものの物理的な隣接席が強いかを見る必要がある。

2026-08-17時点の暫定結果（楽園蒲田・対象末尾7・7つく取材日8日）:
    隣接効果(neighbor_resid - other_resid) は8日中6日で正（90日ベースレート
    p_positive=0.477 とほぼコイン投げ）。直近2日(8/7, 8/17)は90日で観測されたことの
    ない大きさの正の値。本命(末尾7)の強さと隣接効果には相関 -0.607（本命が弱い日
    ほど隣が伸びる）。ただし n=8 で 6/17 に明確な反例（隣接効果 -320.5）があり、
    確定した法則ではない。次回7つく取材日（8/27付近）で再現するかを見ること。
    instinct: rakuen-nanatsuku-neighbor-digit-spillover

使い方:
    venv\\Scripts\\python.exe -m backtest.neighbor_effect 楽園蒲田店 --target-digit 7 \
        --event-days 20260607,20260617,20260627,20260707,20260717,20260727,20260807,20260817 \
        --baseline-before 20260817 --baseline-days 90
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from backtest.run_backtest import load_frame


def _day_resid(day: pd.DataFrame) -> pd.DataFrame:
    """1日分のフレームに machine_number(int) と機種内残差を付けて返す。"""
    d = day.copy()
    d["num"] = d["machine_number"].astype(int)
    d["ld"] = d["last_digit"].astype(str)
    d["resid"] = d["diff_coins_normalized"] - d.groupby("machine_name")["diff_coins_normalized"].transform("mean")
    return d


def neighbor_stats(day: pd.DataFrame, target_digit: str) -> dict:
    """対象末尾の台の左右隣接台(machine_number±1)と、それ以外の残差平均を返す。

    対象末尾の台どうしが隣接するケース（連番で末尾が同じにはならないので
    通常起きないが、欠番混在時の保険として）は隣接台の対象から除く。
    """
    d = _day_resid(day)
    byidx = d.set_index("num")

    target_nums = set(d[d["ld"] == target_digit]["num"])
    left_nums = {n - 1 for n in target_nums if (n - 1) in byidx.index and (n - 1) not in target_nums}
    right_nums = {n + 1 for n in target_nums if (n + 1) in byidx.index and (n + 1) not in target_nums}
    neighbor_nums = left_nums | right_nums
    other_nums = set(d["num"]) - target_nums - neighbor_nums

    def stat(nums: set[int]) -> tuple[float | None, int]:
        sub = d[d["num"].isin(nums)]
        if sub.empty:
            return (None, 0)
        return (round(float(sub["resid"].mean()), 1), len(sub))

    return {
        "target": stat(target_nums),
        "neighbor": stat(neighbor_nums),
        "other": stat(other_nums),
        "left": stat(left_nums),
        "right": stat(right_nums),
    }


def event_day_report(hall: str, target_digit: str, event_days: list[str]) -> pd.DataFrame:
    """指定した日付リスト（例: 過去の7つく取材日）について隣接統計を並べる。"""
    df = load_frame(hall)
    rows = []
    for d in event_days:
        day = df[df["date"] == d]
        if day.empty:
            continue
        r = neighbor_stats(day, target_digit)
        rows.append(
            {
                "date": d,
                "target_resid": r["target"][0],
                "n_target": r["target"][1],
                "neighbor_resid": r["neighbor"][0],
                "n_neighbor": r["neighbor"][1],
                "other_resid": r["other"][0],
                "n_other": r["other"][1],
                "left_resid": r["left"][0],
                "right_resid": r["right"][0],
                "gap": None
                if r["neighbor"][0] is None or r["other"][0] is None
                else round(r["neighbor"][0] - r["other"][0], 1),
            }
        )
    return pd.DataFrame(rows)


def baseline(hall: str, target_digit: str, before: str, days: int) -> dict:
    """対象日より前のデータから「隣接効果(gap)」のベースレートを出す。"""
    df = load_frame(hall)
    d0 = pd.Timestamp(before)
    lo = d0 - pd.Timedelta(days=days)
    hist = df[(df["dt"] >= lo) & (df["dt"] < d0)]

    gaps = []
    for date, day in hist.groupby("date"):
        r = neighbor_stats(day, target_digit)
        if r["neighbor"][0] is None or r["other"][0] is None:
            continue
        gaps.append(r["neighbor"][0] - r["other"][0])
    g = np.array(gaps)
    return {
        "hall": hall,
        "target_digit": target_digit,
        "window": [str(lo.date()), str(d0.date())],
        "n_days": int(len(g)),
        "mean": round(float(g.mean()), 1),
        "median": round(float(np.median(g)), 1),
        "sd": round(float(g.std()), 1),
        "p_positive": round(float((g > 0).mean()), 3),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("hall")
    p.add_argument("--target-digit", required=True, help="予告が名指しした末尾（例: 7）")
    p.add_argument("--event-days", help="カンマ区切りの日付リスト（例: 20260607,20260617,...）")
    p.add_argument("--baseline-before", help="ベースレート計算の基準日（この日より前を使う）")
    p.add_argument("--baseline-days", type=int, default=90)
    args = p.parse_args(argv)

    if args.event_days:
        days = args.event_days.split(",")
        t = event_day_report(args.hall, args.target_digit, days)
        print(t.to_string(index=False))
        if not t.empty:
            n_pos = int((t["gap"] > 0).sum())
            print(f"\n隣接gapが正の日: {n_pos}/{len(t)}")
            corr = t[["target_resid", "gap"]].dropna().corr().iloc[0, 1]
            print(f"本命残差とgapの相関: {round(float(corr), 3)}")

    if args.baseline_before:
        b = baseline(args.hall, args.target_digit, args.baseline_before, args.baseline_days)
        print("\n=== ベースレート ===")
        print(b)

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
