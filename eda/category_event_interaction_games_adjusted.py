"""
category_event_interaction_scan.py の diff リフトを回転数（games）十分位で層別調整し、
交絡（イベント日ほど回転数が伸びる／回転数が伸びるほどdiffの分散も平均も動く）を
除いた上で「長期生存×多台数に既存イベント日ルールの効果が集中する」仮説が残るか検証する。

背景: hit104-and-diff-are-volume-confounded-not-setting-indicators
（document/instincts/2026-07-29-rakuen-event-day-category-decomposition-insights.yaml）
の警告により、category_event_interaction_scan.py の素朴な diff 比較は回転数交絡の
疑いが強いと判断（実測: 蒲田7 long_survivor_multi_unit で event日は非event日比+23%games）。

方法（Mantel-Haenszel型の層別調整）:
  1. ホール内で games を十分位（0-9）に分ける（rakuen_hit104_volume_bias.py と同じ
     pd.qcut(games, 10, duplicates="drop") 方式）
  2. カテゴリ×イベント種ごとに、games十分位×event_flag のセルで平均diffを取る
  3. 層別lift = 各十分位内の (event平均diff - non-event平均diff) を、
     その十分位のn（event/non-eventの調和平均）で重み付け平均する
     → 「回転数が同じくらいの日同士」でしか比較しないので、回転数交絡自体は消える
  4. 素朴なlift（層別しない場合の全体lift）と並記し、調整でどれだけ縮むかを見る
  5. 層別lift の95%CIはブロックブートストラップ（十分位内で独立に事件/非事件をresample）

適用範囲: 全機種（Juggler以外も含む）を対象にするため、BB/RB二項尤度によるp56
（ジャグ専用、dd_setting_posterior_rank.py）は使わない。games十分位層別は
機種を問わず適用できる代わりに、p56ほど「尤度としての正しさ」は保証しない
（層別後もなお games と category が相関する残差交絡が完全には消えない可能性がある）。

出力:
  document/analysis/category_event_interaction/{hall}_games_adjusted.csv
  document/analysis/category_event_interaction/ALL_HALLS_games_adjusted_summary.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.category_event_interaction_scan import (  # noqa: E402
    EVENT_COLUMNS,
    _assign_category,
    _load_and_prepare,
)
from eda.core import HALL_DBS  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

N_GAMES_DECILES = 10
MIN_STRATUM_N = 20
N_BOOTSTRAP = 500
RANDOM_SEED = 42

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "document" / "analysis" / "category_event_interaction"


def _stratified_lift(strata: pd.DataFrame) -> dict:
    """strata: columns [games_decile, diff, event_flag]。層別調整lift・素朴lift・CIを返す。"""
    naive_event = strata.loc[strata["event_flag"], "diff"]
    naive_non_event = strata.loc[~strata["event_flag"], "diff"]
    if len(naive_event) < MIN_STRATUM_N or len(naive_non_event) < MIN_STRATUM_N:
        return None
    lift_naive = float(naive_event.mean() - naive_non_event.mean())

    weighted_lift_sum = 0.0
    weight_sum = 0.0
    stratum_stats = []
    for decile, group in strata.groupby("games_decile"):
        e = group.loc[group["event_flag"], "diff"].to_numpy()
        ne = group.loc[~group["event_flag"], "diff"].to_numpy()
        if len(e) < MIN_STRATUM_N or len(ne) < MIN_STRATUM_N:
            continue
        weight = 2.0 / (1.0 / len(e) + 1.0 / len(ne))  # 調和平均
        lift = e.mean() - ne.mean()
        weighted_lift_sum += weight * lift
        weight_sum += weight
        stratum_stats.append((e, ne, weight))

    if weight_sum == 0 or not stratum_stats:
        return None

    lift_adjusted = weighted_lift_sum / weight_sum

    rng = np.random.default_rng(RANDOM_SEED)
    boot_lifts = []
    for _ in range(N_BOOTSTRAP):
        num = 0.0
        for e, ne, weight in stratum_stats:
            e_s = rng.choice(e, size=len(e), replace=True)
            ne_s = rng.choice(ne, size=len(ne), replace=True)
            num += weight * (e_s.mean() - ne_s.mean())
        boot_lifts.append(num / weight_sum)
    ci_lo, ci_hi = np.percentile(boot_lifts, [2.5, 97.5])

    return {
        "n_strata_used": len(stratum_stats),
        "n_event": int(len(naive_event)),
        "n_non_event": int(len(naive_non_event)),
        "lift_naive": lift_naive,
        "lift_adjusted": float(lift_adjusted),
        "lift_adjusted_ci_lo": float(ci_lo),
        "lift_adjusted_ci_hi": float(ci_hi),
        "shrinkage_pct": float((1 - lift_adjusted / lift_naive) * 100) if lift_naive != 0 else np.nan,
    }


def run_hall(hall: str, output_dir: Path) -> pd.DataFrame:
    df = _load_and_prepare(hall)
    df = _assign_category(df)
    df["games_decile"] = pd.qcut(df["games"], N_GAMES_DECILES, labels=False, duplicates="drop")

    rows = []
    categories = ["new", "long_survivor_multi_unit", "long_survivor_only", "multi_unit_only", "other"]

    for event_name, event_mask_fn in EVENT_COLUMNS.items():
        event_mask = event_mask_fn(df)
        for category in categories:
            cat_mask = df["category"] == category
            sub = df.loc[cat_mask, ["diff", "games_decile"]].copy()
            sub["event_flag"] = event_mask.loc[cat_mask]

            result = _stratified_lift(sub)
            if result is None:
                continue
            result.update({"hall": hall, "event_type": event_name, "category": category})
            rows.append(result)

    out = pd.DataFrame(rows)
    out.to_csv(output_dir / f"{hall}_games_adjusted.csv", index=False, encoding="utf-8-sig")
    print(f"[{hall}] rows={len(out)}")
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="回転数十分位で層別調整したイベント日リフトのカテゴリ別検証。")
    parser.add_argument("--halls", type=str, default=",".join(HALL_DBS.keys()))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    halls = [h.strip() for h in args.halls.split(",") if h.strip()]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = [run_hall(hall, output_dir) for hall in halls]
    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    combined.to_csv(output_dir / "ALL_HALLS_games_adjusted_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\nwrote: {output_dir / 'ALL_HALLS_games_adjusted_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
