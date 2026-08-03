"""ホール別の月末尾・日末尾一致をカテゴリ内の日次 gap で比較する。"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from eda.briefing_common import load_hall_frame, use_utf8_stdout, all_halls


CATEGORIES = ("JUG", "HANA", "OKI", "BT", "AT一般")
HYPOTHESES = ("hit_dd", "hit_mm", "both")
RAKUEN_START_DATE = "20260707"
KNOWN_DAY = "20260802"


def _machine_payout(frame: pd.DataFrame) -> pd.Series:
    """台ごとの機械割を返す。呼び出し側で games > 0 を保証する。"""
    return (frame["games"] * 3 + frame["diff"]) / (frame["games"] * 3) * 100


def prepare_hall(hall: str) -> pd.DataFrame:
    """本分析の明示的な行除外を適用し、末尾一致フラグを追加する。"""
    frame = load_hall_frame(hall)
    frame = frame[(frame["games"] > 0) & (frame["category"] != "UNKNOWN")].copy()
    if hall == "楽園":
        frame = frame[frame["date"] >= RAKUEN_START_DATE].copy()
    if hall == "蒲田7":
        frame = frame[frame["machine_number"] != 2026].copy()

    frame["ld"] = frame["machine_number"] % 10
    frame["month"] = frame["date"].str[4:6].astype(int)
    frame["hit_dd"] = frame["ld"] == (frame["dd"] % 10)
    frame["hit_mm"] = frame["ld"] == (frame["month"] % 10)
    frame["payout"] = _machine_payout(frame)

    # 同日・同カテゴリの基準は必ず games 加重の総和ベースで計算する。
    keys = ["date", "category"]
    total_games = frame.groupby(keys)["games"].transform("sum")
    total_diff = frame.groupby(keys)["diff"].transform("sum")
    frame["category_payout_w"] = (total_games * 3 + total_diff) / (total_games * 3) * 100
    frame["resid"] = frame["payout"] - frame["category_payout_w"]
    return frame


def _hypothesis_masks(
    hypothesis: str,
) -> tuple[Callable[[pd.DataFrame], pd.Series], Callable[[pd.DataFrame], pd.Series]]:
    if hypothesis == "hit_dd":
        return lambda x: x["hit_dd"], lambda x: ~x["hit_dd"]
    if hypothesis == "hit_mm":
        return lambda x: x["hit_mm"], lambda x: ~x["hit_mm"]
    if hypothesis == "both":
        return (
            lambda x: x["hit_dd"] & x["hit_mm"],
            lambda x: ~x["hit_dd"] & ~x["hit_mm"],
        )
    raise ValueError(f"unknown hypothesis: {hypothesis}")


def daily_gaps(frame: pd.DataFrame, hypothesis: str, min_group_size: int = 1) -> pd.Series:
    """日次 gap（一致群 resid 平均 - 対照群 resid 平均）を日付 index で返す。

    min_group_size=1 は既定。日次平均との差を計算できる最小値であり、必要なら
    2 以上にして小さい一致群に起因するノイズを抑えられる。
    """
    if min_group_size < 1:
        raise ValueError("min_group_size must be at least 1")
    group1_mask, group0_mask = _hypothesis_masks(hypothesis)
    records: list[tuple[str, float]] = []
    for date, day in frame.groupby("date", sort=True):
        group1 = day.loc[group1_mask(day), "resid"]
        group0 = day.loc[group0_mask(day), "resid"]
        if len(group1) >= min_group_size and len(group0) >= min_group_size:
            records.append((str(date), float(group1.mean() - group0.mean())))
    return pd.Series(dict(records), dtype=float, name="gap_pp")


def summarize_gaps(gaps: pd.Series) -> dict[str, float | int | str]:
    n_days = len(gaps)
    if not n_days:
        return {
            "gap_pp": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "n_days": 0,
            "positive_rate": np.nan,
            "note": "insufficient",
        }
    mean = float(gaps.mean())
    se = float(gaps.std(ddof=1) / np.sqrt(n_days)) if n_days > 1 else np.nan
    return {
        "gap_pp": mean,
        "ci_low": mean - 1.96 * se if np.isfinite(se) else np.nan,
        "ci_high": mean + 1.96 * se if np.isfinite(se) else np.nan,
        "n_days": n_days,
        "positive_rate": float((gaps > 0).mean() * 100),
        "note": "insufficient" if n_days < 10 else "",
    }


def build_summary(min_group_size: int = 1) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """全ホールの 5 カテゴリ x 3 仮説（both を含む）を集計する。"""
    rows: list[dict[str, object]] = []
    frames: dict[str, pd.DataFrame] = {}
    for hall in all_halls():
        frame = prepare_hall(hall)
        frames[hall] = frame
        for category in CATEGORIES:
            category_frame = frame[frame["category"] == category]
            for hypothesis in HYPOTHESES:
                row: dict[str, object] = {"hall": hall, "category": category, "hypothesis": hypothesis}
                row.update(summarize_gaps(daily_gaps(category_frame, hypothesis, min_group_size)))
                rows.append(row)
    return pd.DataFrame(rows), frames


def known_day_checks(frames: dict[str, pd.DataFrame], min_group_size: int = 1) -> pd.DataFrame:
    """依頼にある 2026-08-02 ヒロキの方向性確認用の日次 gap を返す。"""
    checks = (("AT一般", "hit_dd"), ("JUG", "hit_mm"), ("BT", "hit_mm"))
    day = frames["ヒロキ"].loc[frames["ヒロキ"]["date"] == KNOWN_DAY]
    rows: list[dict[str, object]] = []
    for category, hypothesis in checks:
        gaps = daily_gaps(day[day["category"] == category], hypothesis, min_group_size)
        rows.append(
            {
                "date": KNOWN_DAY,
                "hall": "ヒロキ",
                "category": category,
                "hypothesis": hypothesis,
                "gap_pp": gaps.iloc[0] if len(gaps) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    use_utf8_stdout()
    min_group_size = 1
    summary, frames = build_summary(min_group_size=min_group_size)
    display = summary.copy()
    for column in ("gap_pp", "ci_low", "ci_high", "positive_rate"):
        display[column] = display[column].map(lambda value: f"{value:.3f}" if pd.notna(value) else "NaN")
    print("MM/DD末尾×カテゴリ 日次gap検定")
    print("period=all_available; min_group_size=1; games>0; UNKNOWN除外; 楽園>=20260707; 蒲田7 machine_number!=2026")
    print(display.to_string(index=False))
    print("\n既知日方向性確認（2026-08-02 ヒロキ、正なら手計算と整合）")
    print(known_day_checks(frames, min_group_size=min_group_size).to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
