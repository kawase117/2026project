"""強ゾロ目日(MM=DD)に「末尾一致」「台番号末尾ゾロ目」が効くホールを探す。

契約:
    比較単位は「同日内の gap」。日ごとに 対象群 と 非対象群 の games加重機械割を出し、
    その差(pp)を1標本とする。ホール全体の水準変動・季節性はこの日内差分で相殺される。

    - 末尾一致(hit_ld): machine_number % 10 == dd % 10。MM=DD日は mm%10 とも一致するので
      hit_dd / hit_mm の区別がつかない。この日の「末尾一致」は両者の合流とみなす。
    - 台番号末尾ゾロ目(zorome): 台番号の下2桁が同一（00,11,...,99）。
      machine_detailed_results.is_zorome と同じ定義を台番号から再計算する。

    強ゾロ目日の gap 平均を、通常日の gap 平均と比較する（増幅されているか）。
    n が1桁台のセルが出るため、点推定だけで結論せず必ず n と CI を併記する。

楽園の改装（2026-07-07）を切らない理由:
    eda/lastdigit_mm_dd_category_scan.py は楽園を 20260707 以降に限定している
    （RAKUEN_START_DATE。理由はコード側に記載が無い）。本スクリプトは初版でこれを
    無批判に踏襲し、楽園の強ゾロ目日 19日のうち 18日を落としてしまった。

    末尾・ゾロ目は「台番号の位置」に依存する仮説なので、切るべきかは番号体系が
    改装をまたいで連続しているかで決まる。実測すると改装前(20260705)の 567台は
    全て改装後(20260807)にも同じ番号で在籍し、消えた台は 0、20台が増設されただけ
    だった（末尾ゾロ目台 57→59）。番号の振り直しは起きていない。

    機種構成は入れ替わっている（106→120機種、共通88）が、本分析の指標は同日内の
    gap であってホール水準ではないため、水準のレジーム変化は差分で相殺される。
    よって位置仮説については改装前を含めるのが正しい。ERA_SPLITS で期を分けて
    併記し、判断材料は残す。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eda.briefing_common import all_halls, load_hall_frame, use_utf8_stdout

KAMATA7_IRON = 2026

# 期を分けて併記するホール。値は「その日以降を後期とする」境界日。
# 楽園 20260707 は改装日（台番号は保存されているので除外はしない。docstring 参照）。
ERA_SPLITS = {"楽園": "20260707"}


def prepare(hall: str) -> pd.DataFrame:
    frame = load_hall_frame(hall)
    frame = frame[(frame["games"] > 0) & (frame["category"] != "UNKNOWN")].copy()
    if hall == "蒲田7":
        frame = frame[frame["machine_number"] != KAMATA7_IRON].copy()

    frame["month"] = frame["date"].str[4:6].astype(int)
    frame["ld"] = frame["machine_number"] % 10
    frame["hit_ld"] = frame["ld"] == (frame["dd"] % 10)
    last2 = frame["machine_number"] % 100
    frame["zorome"] = (last2 // 10) == (last2 % 10)
    frame["is_strong"] = frame["month"] == frame["dd"]
    return frame


def _payout(sub: pd.DataFrame) -> float:
    """games加重機械割。台別に割ってから平均すると低回転台が外れ値を作るため使わない。"""
    denom = sub["games"].sum() * 3
    if denom <= 0:
        return np.nan
    return (denom + sub["diff"].sum()) / denom * 100


def daily_gaps(frame: pd.DataFrame, flag: str, min_group: int = 3) -> pd.DataFrame:
    """日ごとに (対象群 - 非対象群) の機械割差(pp)を返す。"""
    rows = []
    for date, day in frame.groupby("date", sort=True):
        hit = day[day[flag]]
        miss = day[~day[flag]]
        if len(hit) < min_group or len(miss) < min_group:
            continue
        p_hit, p_miss = _payout(hit), _payout(miss)
        if np.isnan(p_hit) or np.isnan(p_miss):
            continue
        rows.append(
            {
                "date": date,
                "gap": p_hit - p_miss,
                "n_hit": len(hit),
                "is_strong": bool(day["is_strong"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def summarize(gaps: pd.Series) -> dict[str, float]:
    n = len(gaps)
    if n == 0:
        return {"n": 0, "mean": np.nan, "lo": np.nan, "hi": np.nan, "plus_rate": np.nan}
    mean = gaps.mean()
    if n < 2:
        return {"n": n, "mean": mean, "lo": np.nan, "hi": np.nan, "plus_rate": float(gaps.gt(0).mean())}
    se = gaps.std(ddof=1) / np.sqrt(n)
    return {
        "n": n,
        "mean": mean,
        "lo": mean - 1.96 * se,
        "hi": mean + 1.96 * se,
        "plus_rate": float(gaps.gt(0).mean()),
    }


def main() -> None:
    use_utf8_stdout()
    out = []
    detail = []
    for hall in all_halls():
        frame = prepare(hall)
        if frame.empty:
            continue
        for flag, label in (("hit_ld", "末尾一致"), ("zorome", "末尾ゾロ目")):
            gaps = daily_gaps(frame, flag)
            if gaps.empty:
                continue
            split = ERA_SPLITS.get(hall)
            eras = [("全期間", gaps)]
            if split is not None:
                eras += [
                    (f"〜{split}前", gaps[gaps["date"] < split]),
                    (f"{split}〜", gaps[gaps["date"] >= split]),
                ]
            for era, part in eras:
                strong = summarize(part.loc[part["is_strong"], "gap"])
                normal = summarize(part.loc[~part["is_strong"], "gap"])
                out.append(
                    {
                        "hall": hall,
                        "era": era,
                        "hypothesis": label,
                        "strong_n": strong["n"],
                        "strong_mean": strong["mean"],
                        "strong_lo": strong["lo"],
                        "strong_hi": strong["hi"],
                        "strong_plus": strong["plus_rate"],
                        "normal_n": normal["n"],
                        "normal_mean": normal["mean"],
                        "amplify": strong["mean"] - normal["mean"],
                    }
                )
            for _, r in gaps[gaps["is_strong"]].iterrows():
                detail.append(
                    {"hall": hall, "hypothesis": label, "date": r["date"], "gap": r["gap"], "n_hit": r["n_hit"]}
                )

    summary = pd.DataFrame(out).sort_values(["hypothesis", "strong_mean"], ascending=[True, False])
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    print("=== 強ゾロ目日(MM=DD) vs 通常日 の日内gap(pp) ===")
    print(summary.round(3).to_string(index=False))
    print()
    print("=== 強ゾロ目日ごとの内訳 ===")
    print(pd.DataFrame(detail).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
