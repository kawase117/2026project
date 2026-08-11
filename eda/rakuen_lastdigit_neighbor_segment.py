"""楽園蒲田の末尾効果を「予告末尾の±1が本命」という仮説の観点でセグメント別に測る。

背景（ユーザー提供の仮説、2026-08-11）:
    「最近は予告した末尾のプラス・マイナス1の範囲が本命になることが多い」。

なぜ2本立てか:
    予告末尾が announce に記録されているのは 2026-08-07（末尾7）と 2026-08-10（末尾0）の
    2日しかない。n=2 で「±1が本命」の的中率は測れないので、

    (A) その2日の末尾効果をセグメント別に出して、D-1 / D / D+1 が10末尾中どこに並ぶかを見る
        （観察であって検定ではない）
    (B) 仮説が成り立つ機構 — ホールが高設定を台番号の連続ブロックで置く — を、
        予告の有無と無関係に90日で測る。ブロック配置なら隣接末尾の効果は正相関する。
        相関がゼロなら、±1が本命という話は機構的な裏付けを失う。

    (B) が本体である。(A) は2日ぶんの挿絵にすぎない。
    なお同じ 2026-08-10 の取材内容には「3台並び⑤⑥×10か所以上」「5台並び×2か所以上」
    「10台並び⑤⑥」が含まれており、ブロック配置はホール自身が明言している。
    (B) はその配置が末尾軸に漏れ出しているかを測っていることになる。

セグメント分割は必須（instinct: feedback-lastdigit-kakuban-segment-split）。
2026-08-07 楽園で、末尾7の効果はプールで −35枚（6位）なのに JUG では +1,191枚（1位）だった。
最大セグメントの AT が JUG/HANA を打ち消す。プールの数字で結論を出してはならない。

末尾効果の定義は announce.py の position_rule と揃える:
    残差 = 台の差枚 − 同日同機種の差枚平均（機種構成の混入を除く）
    効果 = 当該末尾の残差平均 − それ以外の残差平均
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.announce import assign_segment
from backtest.run_backtest import load_frame

HALL = "楽園蒲田店"
DIGITS = [str(i) for i in range(10)]

# announce に記録されている予告末尾。事後に増やしてはいけない（選択バイアス）。
ANNOUNCED = {"20260807": "7", "20260810": "0"}


def neighbors(d: str) -> list[str]:
    """末尾は 9 の次が 0 に戻る環状。台番号 xx9 と xy0 は物理的に隣接する。"""
    i = int(d)
    return [str((i - 1) % 10), d, str((i + 1) % 10)]


def digit_effects(day: pd.DataFrame) -> pd.DataFrame:
    """1日ぶんの、セグメント×末尾の残差効果。台数が少ない枠も隠さず返す。"""
    sub = day.dropna(subset=["last_digit"]).copy()
    sub["resid"] = sub["diff_coins_normalized"] - sub.groupby("machine_name")["diff_coins_normalized"].transform("mean")
    sub["segment"] = assign_segment(sub)

    rows = []
    for seg, g in list(sub.groupby("segment")) + [("ALL(pooled)", sub)]:
        for d in DIGITS:
            tgt, oth = g[g["last_digit"] == d], g[g["last_digit"] != d]
            if tgt.empty or oth.empty:
                continue
            rows.append(
                {
                    "segment": str(seg),
                    "digit": d,
                    "n_target": int(len(tgt)),
                    "effect": float(tgt["resid"].mean() - oth["resid"].mean()),
                    "median_diff": float(tgt["diff_coins_normalized"].median()),
                    "plus_rate": float((tgt["diff_coins_normalized"] > 0).mean()),
                }
            )
    return pd.DataFrame(rows)


def observed_days(df: pd.DataFrame) -> dict:
    """(A) 予告のあった日の、セグメント別末尾ランキングと ±1 帯の位置。"""
    out = {}
    for date, d in ANNOUNCED.items():
        day = df[df["date"] == date]
        if day.empty:
            continue
        eff = digit_effects(day)
        band = neighbors(d)
        per_seg = []
        for seg, g in eff.groupby("segment"):
            g = g.sort_values("effect", ascending=False).reset_index(drop=True)
            rank = {r["digit"]: i + 1 for i, r in g.iterrows()}
            per_seg.append(
                {
                    "segment": seg,
                    "announced_digit": d,
                    "band": band,
                    "band_ranks": [rank.get(x) for x in band],
                    "band_mean_effect": round(float(g[g["digit"].isin(band)]["effect"].mean()), 1),
                    "other_mean_effect": round(float(g[~g["digit"].isin(band)]["effect"].mean()), 1),
                    "rows": [
                        {
                            "digit": r["digit"],
                            "n": int(r["n_target"]),
                            "effect": round(r["effect"], 1),
                            "median": round(r["median_diff"], 1),
                            "plus_rate": round(r["plus_rate"], 3),
                            "in_band": r["digit"] in band,
                        }
                        for _, r in g.iterrows()
                    ],
                }
            )
        out[date] = per_seg
    return out


def adjacency_correlation(df: pd.DataFrame, days: int, end: str) -> dict:
    """(B) 隣接末尾の効果が正相関するか。ブロック配置なら正、無関係ならゼロ。

    各日・各セグメントについて10末尾の効果ベクトルを作り、環状ラグ1の自己相関
    corr(e[d], e[d+1]) を日ごとに出して分布を見る。日をまたいで効果を平均してから
    相関を取るのではなく日ごとに取るのは、日によって本命末尾が違ってよいからである
    （先に平均すると打ち消えて何も残らない）。

    比較対象として、末尾ラベルを日ごとにシャッフルした帰無分布も出す。10要素の環状
    ラグ1相関は独立でも平均 -1/9 ≒ -0.111 に偏るので、0 と比べてはいけない。
    """
    d1 = pd.Timestamp(end)
    lo = d1 - pd.Timedelta(days=days)
    hist = df[(df["dt"] >= lo) & (df["dt"] <= d1)]

    rng = np.random.default_rng(0)
    real: dict[str, list[float]] = {}
    null: dict[str, list[float]] = {}

    for _, day in hist.groupby("date"):
        eff = digit_effects(day)
        for seg, g in eff.groupby("segment"):
            g = g.set_index("digit").reindex(DIGITS)
            v = g["effect"].to_numpy(dtype=float)
            if np.isnan(v).any() or np.nanstd(v) == 0:
                continue
            real.setdefault(str(seg), []).append(float(np.corrcoef(v, np.roll(v, -1))[0, 1]))
            for _ in range(20):
                s = rng.permutation(v)
                null.setdefault(str(seg), []).append(float(np.corrcoef(s, np.roll(s, -1))[0, 1]))

    out = {}
    for seg, vals in real.items():
        a, b = np.array(vals), np.array(null[seg])
        out[seg] = {
            "n_days": len(a),
            "lag1_corr_mean": round(float(a.mean()), 4),
            "lag1_corr_median": round(float(np.median(a)), 4),
            "null_mean": round(float(b.mean()), 4),
            "null_sd": round(float(b.std()), 4),
            # 実データ平均が帰無分布の平均から何 SE 離れているか（SE は実データ日数で割る）
            "z_vs_null": round(float((a.mean() - b.mean()) / (b.std() / np.sqrt(len(a)))), 2),
        }
    return out


def main() -> None:
    df = load_frame(HALL)
    res = {
        "hall": HALL,
        "data_max": str(df["date"].max()),
        "announced_days": observed_days(df),
        "adjacency_lag1": adjacency_correlation(df, days=90, end="20260810"),
    }
    out = Path(__file__).resolve().parent / "out" / "rakuen_lastdigit_neighbor_segment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
