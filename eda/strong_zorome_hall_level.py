"""強ゾロ目日(MM=DD)にホール全体の水準が上がるか、機種別に誰が牽引したかを見る。

背景:
    backtest/prereg の みとや3ルールは entry_days（EVENT_DDS={1,4,7,14,17,24,27,30}）で
    2026-08-08 を弾く。しかし告知側は「月ゾロ恒例の9店舗合同」と言っている。
    EVENT_DDS は DD 別の集計から導出されたもので、MM=DD という別軸を含んでいない。
    その食い違いが実データで裏付くかを確認する。

契約:
    機械割は games加重 (Σgames*3 + Σdiff)/(Σgames*3)*100。日別に算出し、
    強ゾロ目日と通常日で比較する。ホール休業日は行が無いだけなので自然に落ちる。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eda.briefing_common import all_halls, load_hall_frame, use_utf8_stdout

RAKUEN_START_DATE = "20260707"
KAMATA7_IRON = 2026
MIN_MACHINES = 3


def prepare(hall: str) -> pd.DataFrame:
    frame = load_hall_frame(hall)
    frame = frame[(frame["games"] > 0) & (frame["category"] != "UNKNOWN")].copy()
    if hall == "楽園":
        frame = frame[frame["date"] >= RAKUEN_START_DATE].copy()
    if hall == "蒲田7":
        frame = frame[frame["machine_number"] != KAMATA7_IRON].copy()
    frame["month"] = frame["date"].str[4:6].astype(int)
    frame["is_strong"] = frame["month"] == frame["dd"]
    return frame


def payout_by(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    grouped = frame.groupby(keys, sort=True).agg(
        games=("games", "sum"), diff=("diff", "sum"), n=("machine_number", "size")
    )
    grouped["payout"] = (grouped["games"] * 3 + grouped["diff"]) / (grouped["games"] * 3) * 100
    grouped["mean_diff"] = grouped["diff"] / grouped["n"]
    return grouped.reset_index()


def _ci(series: pd.Series) -> tuple[float, float, float, int]:
    n = len(series)
    if n == 0:
        return np.nan, np.nan, np.nan, 0
    m = series.mean()
    if n < 2:
        return m, np.nan, np.nan, n
    se = series.std(ddof=1) / np.sqrt(n)
    return m, m - 1.96 * se, m + 1.96 * se, n


def hall_level() -> pd.DataFrame:
    rows = []
    for hall in all_halls():
        frame = prepare(hall)
        if frame.empty:
            continue
        daily = payout_by(frame, ["date"])
        daily["is_strong"] = daily["date"].isin(frame.loc[frame["is_strong"], "date"].unique())
        for col in ("payout", "mean_diff"):
            s_m, s_lo, s_hi, s_n = _ci(daily.loc[daily["is_strong"], col])
            n_m, _, _, n_n = _ci(daily.loc[~daily["is_strong"], col])
            rows.append(
                {
                    "hall": hall,
                    "metric": col,
                    "strong_n": s_n,
                    "strong": s_m,
                    "strong_lo": s_lo,
                    "strong_hi": s_hi,
                    "normal_n": n_n,
                    "normal": n_m,
                    "delta": s_m - n_m,
                }
            )
    return pd.DataFrame(rows)


def hall_model_detail(hall: str, top: int = 12) -> pd.DataFrame:
    """そのホールの強ゾロ目日に、機種別でどれだけ通常日を上回ったか。"""
    frame = prepare(hall)
    if frame.empty:
        return pd.DataFrame()
    agg = payout_by(frame, ["machine_name", "is_strong"])
    agg = agg[agg["n"] >= MIN_MACHINES]
    pivot = agg.pivot(index="machine_name", columns="is_strong", values=["payout", "mean_diff", "n"])
    pivot.columns = [f"{a}_{'strong' if b else 'normal'}" for a, b in pivot.columns]
    pivot = pivot.dropna(subset=["payout_strong", "payout_normal"])
    pivot["delta_payout"] = pivot["payout_strong"] - pivot["payout_normal"]
    pivot["delta_diff"] = pivot["mean_diff_strong"] - pivot["mean_diff_normal"]
    pivot = pivot[pivot["n_strong"] >= 10]
    return pivot.sort_values("delta_diff", ascending=False).head(top).reset_index()


def main() -> None:
    use_utf8_stdout()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 300)
    print("=== 強ゾロ目日(MM=DD) のホール全体水準 ===")
    print(hall_level().round(2).to_string(index=False))
    for hall in ("みとや", "楽園", "ヒロキ", "蒲田7", "蒲田1"):
        print(f"\n=== {hall}: 強ゾロ目日に伸びた機種 top12 (延べ台数>=10) ===")
        detail = hall_model_detail(hall)
        print(detail.round(1).to_string(index=False) if not detail.empty else "(該当なし)")


if __name__ == "__main__":
    main()
