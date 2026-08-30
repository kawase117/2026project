"""
既存の日付系ルール（ホール固有イベント日 is_x_day / 週末 is_weekend / dd_group）が、
機種カテゴリ（新台 / 多台数 / 長期生存 / その他）によって効果量が違うかを
全ホール横断で検証する。

背景（ユーザー、2026-08-11）: 「新台、メイン機種（多台数）、人気機種などで台の扱いは
異なる」「長く生き残っている機種は最低でも月一回は高設定を入れる工夫をしないと
客が座らなくなる」。既存のイベント日ルールは全機種込みで検証されており、
カテゴリ別の効果量差は未検証。

粒度: 台×日（machine_detailed_results 1行）。日付系ルールは機種を問わずホール全体に
一様に適用される前提のルール（is_x_day 等）なので、台単位のままカテゴリでグルーピング
して比較する（周期保証・連続回避スキャンとは異なり機種単位に集約しない）。

カテゴリ（行単位、排他・優先順位あり）:
  1. new             : pre_existing=False かつ days_since_debut < NEW_MACHINE_DAYS
  2. long_survivor_multi_unit : 機種レベルで lifespan>=365日かつ現役 かつ 平均稼働台数>=8
  3. long_survivor_only       : 機種レベルで lifespan>=365日かつ現役（多台数でない）
  4. multi_unit_only          : 機種レベルで平均稼働台数>=8（長期生存でない）
  5. other            : 上記いずれでもない

  周期保証・連続回避スキャン(eda/periodicity_hazard_scan.py)と異なり、新台助走期間の
  行を除外せず「new」カテゴリとして残す（新台の扱いそのものを検証対象にするため）。

比較する日付系ルール: is_x_day（ホール固有イベント日）, is_weekend, dd_group=='4系',
dd_group=='7系'。これらは eda.core.load_hall_df が既に計算済みの列を使う。

指標: diff（差枚）の平均・中央値・プラス率の3点セット
（feedback_2026_05_28_analysis_methodology の規約通り、平均単独では書かない）。
lift = イベント日平均diff - 非イベント日平均diff。lift の 95% bootstrap CI と
Mann-Whitney U 検定の p 値を付す。

多重検定: 9ホール×4イベント種×5カテゴリ=180検定になるため、
Benjamini-Hochberg 法で FDR 補正した p_adj も出力する
（前回の周期保証スキャンで生p値の大半が補正で消えた教訓）。

出力:
  document/analysis/category_event_interaction/{hall}_interaction.csv
  document/analysis/category_event_interaction/ALL_HALLS_summary.csv（p_adj_bh 付き）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
from statsmodels.stats.multitest import multipletests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, compute_debut_features, load_hall_df  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

NEW_MACHINE_DAYS = 30
LONG_SURVIVOR_MIN_LIFESPAN_DAYS = 365
STILL_ACTIVE_GRACE_DAYS = 30
MULTI_UNIT_THRESHOLD = 8.0
N_BOOTSTRAP = 1000
RANDOM_SEED = 42

EVENT_COLUMNS = {
    "x_day": lambda df: df["is_x_day"] == 1,
    "weekend": lambda df: df["is_weekend"] == 1,
    "dd_group_4": lambda df: df["dd_group"] == "4系",
    "dd_group_7": lambda df: df["dd_group"] == "7系",
}

HALL_EXCLUDE_DATES: dict[str, list[str]] = {
    "蒲田7": ["20260707"],
}

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "document" / "analysis" / "category_event_interaction"


def _load_and_prepare(hall: str) -> pd.DataFrame:
    raw = load_hall_df(hall)
    df = compute_debut_features(raw, db_start_grace_days=0)

    exclude_dates = HALL_EXCLUDE_DATES.get(hall, [])
    if exclude_dates:
        df = df.loc[~df["date"].isin(exclude_dates)].copy()
    return df


def _machine_level_labels(df: pd.DataFrame) -> pd.DataFrame:
    db_last_date = pd.to_datetime(df["date"], format="%Y%m%d").max()
    rows = []
    for machine_name, group in df.groupby("machine_name", sort=False):
        dates = pd.to_datetime(group["date"], format="%Y%m%d")
        lifespan_days = int((dates.max() - dates.min()).days)
        still_active = bool((db_last_date - dates.max()).days <= STILL_ACTIVE_GRACE_DAYS)
        avg_units = float(group.groupby("date")["machine_number"].nunique().mean())
        rows.append(
            {
                "machine_name": machine_name,
                "is_long_survivor": bool(lifespan_days >= LONG_SURVIVOR_MIN_LIFESPAN_DAYS and still_active),
                "is_multi_unit": bool(avg_units >= MULTI_UNIT_THRESHOLD),
            }
        )
    return pd.DataFrame(rows)


def _assign_category(df: pd.DataFrame) -> pd.DataFrame:
    labels = _machine_level_labels(df)
    df = df.merge(labels, on="machine_name", how="left")

    is_new = (
        df["pre_existing"].fillna(False).eq(False)
        & df["days_since_debut"].notna()
        & (df["days_since_debut"] < NEW_MACHINE_DAYS)
    )

    category = np.select(
        [
            is_new,
            df["is_long_survivor"] & df["is_multi_unit"],
            df["is_long_survivor"] & ~df["is_multi_unit"],
            ~df["is_long_survivor"] & df["is_multi_unit"],
        ],
        ["new", "long_survivor_multi_unit", "long_survivor_only", "multi_unit_only"],
        default="other",
    )
    df["category"] = category
    return df


def _bootstrap_lift_ci(event_vals: np.ndarray, non_event_vals: np.ndarray) -> tuple[float, float]:
    if len(event_vals) < 3 or len(non_event_vals) < 3:
        return np.nan, np.nan
    rng = np.random.default_rng(RANDOM_SEED)
    lifts = []
    for _ in range(N_BOOTSTRAP):
        e_sample = rng.choice(event_vals, size=len(event_vals), replace=True)
        n_sample = rng.choice(non_event_vals, size=len(non_event_vals), replace=True)
        lifts.append(e_sample.mean() - n_sample.mean())
    lo, hi = np.percentile(lifts, [2.5, 97.5])
    return float(lo), float(hi)


def _compare_group(event_vals: pd.Series, non_event_vals: pd.Series) -> dict:
    event_vals = pd.to_numeric(event_vals, errors="coerce").dropna().to_numpy()
    non_event_vals = pd.to_numeric(non_event_vals, errors="coerce").dropna().to_numpy()

    if len(event_vals) < 5 or len(non_event_vals) < 5:
        return None

    mean_event = float(event_vals.mean())
    mean_non_event = float(non_event_vals.mean())
    lift = mean_event - mean_non_event
    ci_lo, ci_hi = _bootstrap_lift_ci(event_vals, non_event_vals)

    try:
        _, p_value = mannwhitneyu(event_vals, non_event_vals, alternative="two-sided")
    except ValueError:
        p_value = np.nan

    return {
        "n_event": int(len(event_vals)),
        "n_non_event": int(len(non_event_vals)),
        "mean_diff_event": mean_event,
        "mean_diff_non_event": mean_non_event,
        "median_diff_event": float(np.median(event_vals)),
        "median_diff_non_event": float(np.median(non_event_vals)),
        "plus_rate_event": float((event_vals > 0).mean()),
        "plus_rate_non_event": float((non_event_vals > 0).mean()),
        "lift": lift,
        "lift_ci_lo": ci_lo,
        "lift_ci_hi": ci_hi,
        "p_value": float(p_value) if pd.notna(p_value) else np.nan,
    }


def run_hall(hall: str, output_dir: Path) -> pd.DataFrame:
    df = _load_and_prepare(hall)
    df = _assign_category(df)

    rows = []
    categories = ["new", "long_survivor_multi_unit", "long_survivor_only", "multi_unit_only", "other"]

    for event_name, event_mask_fn in EVENT_COLUMNS.items():
        event_mask = event_mask_fn(df)
        for category in categories:
            cat_mask = df["category"] == category
            event_vals = df.loc[cat_mask & event_mask, "diff"]
            non_event_vals = df.loc[cat_mask & ~event_mask, "diff"]

            result = _compare_group(event_vals, non_event_vals)
            if result is None:
                continue
            result.update({"hall": hall, "event_type": event_name, "category": category})
            rows.append(result)

    out = pd.DataFrame(rows)
    out.to_csv(output_dir / f"{hall}_interaction.csv", index=False, encoding="utf-8-sig")
    print(f"[{hall}] rows={len(out)}")
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="既存の日付系ルールをカテゴリ別に検証する。")
    parser.add_argument("--halls", type=str, default=",".join(HALL_DBS.keys()))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    halls = [h.strip() for h in args.halls.split(",") if h.strip()]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    for hall in halls:
        all_rows.append(run_hall(hall, output_dir))

    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    if not combined.empty:
        valid = combined.dropna(subset=["p_value"]).copy()
        rej, p_adj, _, _ = multipletests(valid["p_value"], alpha=0.05, method="fdr_bh")
        valid["p_adj_bh"] = p_adj
        valid["significant_after_correction"] = rej
        combined = combined.merge(
            valid[["hall", "event_type", "category", "p_adj_bh", "significant_after_correction"]],
            on=["hall", "event_type", "category"],
            how="left",
        )

    combined.to_csv(output_dir / "ALL_HALLS_summary.csv", index=False, encoding="utf-8-sig")
    n_sig = int(combined["significant_after_correction"].sum()) if "significant_after_correction" in combined else 0
    print(f"\nn_tests={len(combined)} n_sig_after_correction={n_sig}")
    print(f"wrote: {output_dir / 'ALL_HALLS_summary.csv'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
