"""
みとや・レイトギャップ平和島で、games十分位調整後も残った
x_day × long_survivor_multi_unit の正リフト（みとや+164, レイトギャップ+72）を深掘りする。

疑問1: is_x_day は「dd in event_digits」「is_month_end」「is_mmdd_zorome(強ゾロ目)」の
       3種の理由を束ねた合成フラグ（eda/core.py load_hall_df）。どの理由が効いているのか。
       event_digits はホール固有の個別日付（例: レイトギャップ=[6,16,26]）まで分解する。
       document/lategap_theory.md に既存知見「DD6/26は反応, DD16は無反応(一致率55%)」が
       あり、独立手法（カテゴリ限定・回転数十分位調整）で再現するか確認する。

疑問2: 特定の1-2機種がリフトを牽引しているだけではないか
       （feedback_2026_05_28_analysis_methodology: 上位2台を除いた感度分析を1行添える）。

方法: eda.category_event_interaction_games_adjusted の層別調整（games十分位、
      調和平均重み付け、ブロックブートストラップCI）をそのまま再利用する。
      category は long_survivor_multi_unit に固定。

出力:
  document/analysis/category_event_interaction/{hall}_xday_reason_breakdown.csv
  document/analysis/category_event_interaction/{hall}_xday_machine_sensitivity.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.category_event_interaction_games_adjusted import N_GAMES_DECILES, _stratified_lift  # noqa: E402
from eda.category_event_interaction_scan import _assign_category, _load_and_prepare  # noqa: E402
from eda.core import HALL_EVENT_DIGITS  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_HALLS = ["みとや", "レイトギャップ"]
TARGET_CATEGORY = "long_survivor_multi_unit"
OUTPUT_DIR = PROJECT_ROOT / "document" / "analysis" / "category_event_interaction"
TOP_N_MACHINES_SENSITIVITY = 3


def _reason_breakdown(df: pd.DataFrame, hall: str) -> pd.DataFrame:
    event_digits = HALL_EVENT_DIGITS[hall]
    base = df.loc[df["category"] == TARGET_CATEGORY].copy()

    rows = []
    for digit in event_digits:
        reason_mask = (base["dd"] == digit) & (base["is_month_end"] == 0) & (base["is_mmdd_zorome"] == 0)
        non_event_mask = base["is_x_day"] == 0
        sub = base.loc[reason_mask | non_event_mask, ["diff", "games_decile"]].copy()
        sub["event_flag"] = reason_mask.loc[reason_mask | non_event_mask]
        result = _stratified_lift(sub)
        if result is None:
            continue
        result.update({"hall": hall, "reason": f"digit_{digit}"})
        rows.append(result)

    for reason_name, reason_col in [("month_end", "is_month_end"), ("mmdd_zorome", "is_mmdd_zorome")]:
        reason_mask = (base[reason_col] == 1) & (~base["dd"].isin(event_digits))
        non_event_mask = base["is_x_day"] == 0
        sub = base.loc[reason_mask | non_event_mask, ["diff", "games_decile"]].copy()
        sub["event_flag"] = reason_mask.loc[reason_mask | non_event_mask]
        result = _stratified_lift(sub)
        if result is None:
            continue
        result.update({"hall": hall, "reason": reason_name})
        rows.append(result)

    return pd.DataFrame(rows)


def _machine_sensitivity(df: pd.DataFrame, hall: str) -> pd.DataFrame:
    base = df.loc[df["category"] == TARGET_CATEGORY].copy()
    event_mask = base["is_x_day"] == 1

    contribution = base.loc[event_mask].groupby("machine_name")["diff"].sum().sort_values(ascending=False)
    top_machines = contribution.head(TOP_N_MACHINES_SENSITIVITY).index.tolist()

    full_sub = base[["diff", "games_decile"]].copy()
    full_sub["event_flag"] = event_mask
    full_result = _stratified_lift(full_sub)

    excl_base = base.loc[~base["machine_name"].isin(top_machines)]
    excl_sub = excl_base[["diff", "games_decile"]].copy()
    excl_sub["event_flag"] = excl_base["is_x_day"] == 1
    excl_result = _stratified_lift(excl_sub)

    rows = [
        {
            "hall": hall,
            "scope": "all_machines",
            "top_machines_excluded": "",
            "lift_adjusted": full_result["lift_adjusted"] if full_result else np.nan,
            "lift_adjusted_ci_lo": full_result["lift_adjusted_ci_lo"] if full_result else np.nan,
            "lift_adjusted_ci_hi": full_result["lift_adjusted_ci_hi"] if full_result else np.nan,
        },
        {
            "hall": hall,
            "scope": f"excluding_top_{TOP_N_MACHINES_SENSITIVITY}",
            "top_machines_excluded": ", ".join(top_machines),
            "lift_adjusted": excl_result["lift_adjusted"] if excl_result else np.nan,
            "lift_adjusted_ci_lo": excl_result["lift_adjusted_ci_lo"] if excl_result else np.nan,
            "lift_adjusted_ci_hi": excl_result["lift_adjusted_ci_hi"] if excl_result else np.nan,
        },
    ]
    return pd.DataFrame(rows)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for hall in TARGET_HALLS:
        df = _load_and_prepare(hall)
        df = _assign_category(df)
        df["games_decile"] = pd.qcut(df["games"], N_GAMES_DECILES, labels=False, duplicates="drop")

        reason_df = _reason_breakdown(df, hall)
        reason_df.to_csv(OUTPUT_DIR / f"{hall}_xday_reason_breakdown.csv", index=False, encoding="utf-8-sig")

        sensitivity_df = _machine_sensitivity(df, hall)
        sensitivity_df.to_csv(OUTPUT_DIR / f"{hall}_xday_machine_sensitivity.csv", index=False, encoding="utf-8-sig")

        print(f"[{hall}] reasons={len(reason_df)} sensitivity_rows={len(sensitivity_df)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
