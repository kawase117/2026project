"""
Event Day vs Non-Event Day Correction Analysis
Compares zorome correction: event days vs non-event days vs weekdays.

Event day definition:
  type7:         day in [7, 17, 27]
  type1:         day in [1, 11, 31]
  type22:        day == 22
  type30:        day == 30
  month_end:     last day of month (if not already covered by above)
  month_eq_day:  month == day  (e.g. 1/1, 2/2 ... 12/12; NOT 1/11)
"""
from __future__ import annotations

import argparse
import calendar
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ml.last_digit.zorome_strategy_simulation import load_machine_level_data
from ml.last_digit.utils import configure_logging, resolve_db_path

logger = logging.getLogger(__name__)

EVENT_TYPE_ORDER = ["month_eq_day", "type22", "type30", "month_end", "type7", "type1"]
MIN_N = 5


# ---------------------------------------------------------------------------
# Event day classification
# ---------------------------------------------------------------------------

def primary_event_type(date: pd.Timestamp) -> str:
    day = date.day
    month = date.month
    last_day = calendar.monthrange(date.year, date.month)[1]

    if month == day:
        return "month_eq_day"
    if day == 22:
        return "type22"
    if day == 30:
        return "type30"
    if day == last_day and day not in [7, 17, 27, 1, 11, 22, 30]:
        return "month_end"
    if day in [7, 17, 27]:
        return "type7"
    if day in [1, 11, 31]:
        return "type1"
    return "non_event"


def add_event_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["event_type"] = df["date"].apply(primary_event_type)
    df["is_event"] = (df["event_type"] != "non_event").astype(int)
    return df


# ---------------------------------------------------------------------------
# Correction table builders
# ---------------------------------------------------------------------------

def _correction_for_group(g: pd.DataFrame) -> dict[str, Any]:
    z = g.loc[g["is_zorome"] == 1, "diff_coins_normalized"]
    nz = g.loc[g["is_zorome"] == 0, "diff_coins_normalized"]
    n_z, n_nz = len(z), len(nz)
    mean_z = float(z.mean()) if n_z >= MIN_N else np.nan
    mean_nz = float(nz.mean()) if n_nz >= MIN_N else np.nan
    correction = mean_z - mean_nz if np.isfinite(mean_z) and np.isfinite(mean_nz) else np.nan
    p_val = np.nan
    if n_z >= MIN_N and n_nz >= MIN_N:
        _, p_val = stats.ttest_ind(z, nz, equal_var=False)
    return {
        "n_zorome": n_z,
        "n_nonzorome": n_nz,
        "mean_zorome": mean_z,
        "mean_nonzorome": mean_nz,
        "correction": correction,
        "p_value": p_val,
    }


def build_correction_table(df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame:
    rows = []
    for keys, g in df.groupby(group_by, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = dict(zip(group_by, keys))
        row.update(_correction_for_group(g))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def pivot_correction(tbl: pd.DataFrame, index_col: str) -> pd.DataFrame:
    agg = tbl.groupby([index_col, "last_digit"])["correction"].mean().reset_index()
    pivot = agg.pivot(index=index_col, columns="last_digit", values="correction")
    pivot.columns = [f"末尾{c}" for c in pivot.columns]
    return pivot.round(1)


def event_vs_weekday_comparison(
    tbl_binary: pd.DataFrame,
    tbl_wd: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for ld in range(10):
        ev = tbl_binary[(tbl_binary["last_digit"] == ld) & (tbl_binary["is_event"] == 1)]
        nev = tbl_binary[(tbl_binary["last_digit"] == ld) & (tbl_binary["is_event"] == 0)]
        wd = tbl_wd[tbl_wd["last_digit"] == ld].copy()

        ev_corr = ev["correction"].mean() if len(ev) else np.nan
        nev_corr = nev["correction"].mean() if len(nev) else np.nan

        best_wd_corr = np.nan
        best_wd_name = ""
        if len(wd) and not wd["correction"].isna().all():
            idx = wd["correction"].idxmax()
            best_wd_corr = wd.loc[idx, "correction"]
            best_wd_name = wd.loc[idx, "weekday"]

        rows.append({
            "last_digit": ld,
            "event_correction": round(ev_corr, 1) if np.isfinite(ev_corr) else np.nan,
            "nonevent_correction": round(nev_corr, 1) if np.isfinite(nev_corr) else np.nan,
            "diff_event_minus_nonevent": round(ev_corr - nev_corr, 1)
                if np.isfinite(ev_corr) and np.isfinite(nev_corr) else np.nan,
            "best_weekday": best_wd_name,
            "best_weekday_correction": round(best_wd_corr, 1) if np.isfinite(best_wd_corr) else np.nan,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Event day zorome correction analysis")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    configure_logging()

    db_path = resolve_db_path(args.db_path)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading data from %s", db_path)
    df = load_machine_level_data(db_path)
    df = add_event_columns(df)

    n_days = df["date"].nunique()
    logger.info("Total days: %d", n_days)

    # --- Event day count summary ---
    day_df = df[["date", "event_type", "is_event"]].drop_duplicates("date")
    counts = day_df.groupby("event_type")["date"].count().reset_index()
    counts.columns = ["event_type", "n_days"]
    counts["pct"] = (counts["n_days"] / n_days * 100).round(1)
    counts = counts.sort_values("n_days", ascending=False).reset_index(drop=True)
    counts.to_csv(out_dir / "event_day_counts.csv", index=False, encoding="utf-8-sig")

    print("\n=== イベント日の内訳 ===")
    print(counts.to_string(index=False))
    print(f"イベント日合計: {day_df['is_event'].sum()} / {n_days} 日 ({day_df['is_event'].mean()*100:.1f}%)")

    # --- Binary correction table ---
    tbl_binary = build_correction_table(df, ["is_event", "last_digit", "group_key"])
    tbl_binary["is_event_label"] = tbl_binary["is_event"].map({1: "イベント日", 0: "非イベント日"})
    tbl_binary.to_csv(out_dir / "correction_event_binary.csv", index=False, encoding="utf-8-sig")

    # --- By event type ---
    tbl_type = build_correction_table(df, ["event_type", "last_digit", "group_key"])
    tbl_type.to_csv(out_dir / "correction_by_event_type.csv", index=False, encoding="utf-8-sig")

    # --- Weekday reference ---
    tbl_wd = build_correction_table(df, ["weekday", "last_digit", "group_key"])
    tbl_wd.to_csv(out_dir / "correction_weekday_reference.csv", index=False, encoding="utf-8-sig")

    # --- Comparison summary ---
    cmp = event_vs_weekday_comparison(tbl_binary, tbl_wd)
    cmp.to_csv(out_dir / "event_vs_weekday_comparison.csv", index=False, encoding="utf-8-sig")

    # --- Print pivots ---
    print("\n=== イベント日 vs 非イベント日 (末尾別 correction 平均) ===")
    pv_binary = pivot_correction(tbl_binary, "is_event_label")
    print(pv_binary.to_string())

    print("\n=== イベント種別 correction (末尾別平均) ===")
    pv_type = pivot_correction(tbl_type, "event_type")
    print(pv_type.to_string())

    print("\n=== 比較サマリ (末尾別) ===")
    print(cmp.to_string(index=False))

    print(f"\n出力先: {out_dir}")
    for p in sorted(out_dir.glob("*.csv")):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
