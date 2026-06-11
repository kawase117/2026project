"""
Weekday vs Event Day Priority Analysis for Zorome Strategy

Answers: when weekday correction and event correction conflict,
which signal better predicted actual zorome advantage?

Approach (exploratory, uses all data):
  1. Build weekday correction table and event binary correction table from all data
  2. For each (date, last_digit, group_key): look up both signals
  3. Classify days: agree_pos / agree_neg / conflict_wd_pos / conflict_wd_neg
  4. Compute actual realized zorome correction per category
  5. Score which signal was directionally correct on conflict days
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ml.last_digit.event_day_correction_analysis import add_event_columns, build_correction_table
from ml.last_digit.zorome_strategy_simulation import load_machine_level_data
from ml.last_digit.utils import configure_logging, resolve_db_path

logger = logging.getLogger(__name__)


def compute_daily_realized_correction(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (date, ld, gk), g in df.groupby(["date", "last_digit", "group_key"]):
        z = g.loc[g["is_zorome"] == 1, "diff_coins_normalized"]
        nz = g.loc[g["is_zorome"] == 0, "diff_coins_normalized"]
        if len(z) < 1 or len(nz) < 3:
            continue
        rows.append({
            "date": date,
            "last_digit": int(ld),
            "group_key": gk,
            "realized_correction": float(z.mean()) - float(nz.mean()),
        })
    return pd.DataFrame(rows)


def interaction_table(df: pd.DataFrame) -> pd.DataFrame:
    agg_rows = []
    for (wd, ev, gk), g in df.groupby(["weekday", "is_event", "group_key"]):
        z = g.loc[g["is_zorome"] == 1, "diff_coins_normalized"]
        nz = g.loc[g["is_zorome"] == 0, "diff_coins_normalized"]
        if len(z) < 3 or len(nz) < 5:
            continue
        agg_rows.append({
            "weekday": wd,
            "is_event": ev,
            "group_key": gk,
            "correction": float(z.mean()) - float(nz.mean()),
        })
    tbl = pd.DataFrame(agg_rows)
    agg = tbl.groupby(["weekday", "is_event"])["correction"].mean().reset_index()
    pivot = agg.pivot(index="weekday", columns="is_event", values="correction")
    pivot.columns = ["非イベント", "イベント"]
    pivot["差(イベント-非イベント)"] = (pivot["イベント"] - pivot["非イベント"]).round(1)
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return pivot.reindex([w for w in order if w in pivot.index]).round(1)


def conflict_resolution(df: pd.DataFrame, realized: pd.DataFrame) -> dict:
    tbl_wd = build_correction_table(df, ["weekday", "last_digit", "group_key"])
    tbl_ev = build_correction_table(df, ["is_event", "last_digit", "group_key"])

    wd_map = {
        (r.weekday, int(r.last_digit), r.group_key): r.correction
        for r in tbl_wd.itertuples()
    }
    ev_map = {
        (int(r.is_event), int(r.last_digit), r.group_key): r.correction
        for r in tbl_ev.itertuples()
    }

    date_event = df.drop_duplicates("date").set_index("date")["is_event"].to_dict()

    records = []
    for row in realized.itertuples():
        wd = row.date.day_name()
        is_ev = date_event.get(row.date)
        if is_ev is None:
            continue
        wd_corr = wd_map.get((wd, int(row.last_digit), row.group_key), np.nan)
        ev_corr = ev_map.get((int(is_ev), int(row.last_digit), row.group_key), np.nan)
        if np.isnan(wd_corr) or np.isnan(ev_corr):
            continue

        wd_sign = 1 if wd_corr > 0 else -1
        ev_sign = 1 if ev_corr > 0 else -1
        actual_sign = 1 if row.realized_correction > 0 else -1

        if wd_sign == ev_sign:
            category = "agree_pos" if wd_sign > 0 else "agree_neg"
        elif wd_sign > 0 and ev_sign < 0:
            category = "conflict: 曜日+ イベント-"
        else:
            category = "conflict: 曜日- イベント+"

        records.append({
            "date": row.date,
            "last_digit": row.last_digit,
            "group_key": row.group_key,
            "weekday": wd,
            "is_event": is_ev,
            "wd_correction": wd_corr,
            "ev_correction": ev_corr,
            "realized_correction": row.realized_correction,
            "category": category,
            "wd_correct": int(wd_sign == actual_sign),
            "ev_correct": int(ev_sign == actual_sign),
        })

    detail = pd.DataFrame(records)
    if detail.empty:
        return {"detail": detail, "summary": pd.DataFrame(), "conflict_score": pd.DataFrame()}

    summary = detail.groupby("category").agg(
        n=("realized_correction", "count"),
        mean_realized=("realized_correction", "mean"),
        wd_accuracy=("wd_correct", "mean"),
        ev_accuracy=("ev_correct", "mean"),
    ).reset_index().round(3)

    conflict = detail[detail["category"].str.startswith("conflict")].copy()
    if len(conflict):
        score = conflict.groupby("category").agg(
            n=("realized_correction", "count"),
            mean_realized=("realized_correction", "mean"),
            wd_win_rate=("wd_correct", "mean"),
            ev_win_rate=("ev_correct", "mean"),
        ).reset_index().round(3)
        score["winner"] = score.apply(
            lambda r: "曜日優先" if r.wd_win_rate > r.ev_win_rate
            else ("イベント優先" if r.ev_win_rate > r.wd_win_rate else "引き分け"),
            axis=1,
        )
    else:
        score = pd.DataFrame()

    return {"detail": detail, "summary": summary, "conflict_score": score}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    configure_logging()
    db_path = resolve_db_path(args.db_path)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_machine_level_data(db_path)
    df = add_event_columns(df)

    print("\n=== 曜日×イベント日 interaction correction（全末尾平均）===")
    inter = interaction_table(df)
    print(inter.to_string())
    inter.to_csv(out_dir / "weekday_event_interaction.csv", encoding="utf-8-sig")

    realized = compute_daily_realized_correction(df)

    result = conflict_resolution(df, realized)
    summary = result["summary"]
    conflict_score = result["conflict_score"]

    print("\n=== カテゴリ別サマリ（agree / conflict）===")
    if not summary.empty:
        print(summary.to_string(index=False))
    summary.to_csv(out_dir / "conflict_category_summary.csv", index=False, encoding="utf-8-sig")

    print("\n=== 矛盾日での勝敗スコア ===")
    if not conflict_score.empty:
        print(conflict_score.to_string(index=False))
        print()
        for _, r in conflict_score.iterrows():
            print(
                f"  {r['category']}: "
                f"曜日正解率={r['wd_win_rate']:.1%} / イベント正解率={r['ev_win_rate']:.1%} "
                f"→ {r['winner']}"
            )
    else:
        print("  矛盾日データなし")
    conflict_score.to_csv(out_dir / "conflict_resolution_score.csv", index=False, encoding="utf-8-sig")
    result["detail"].to_csv(out_dir / "conflict_detail.csv", index=False, encoding="utf-8-sig")

    print(f"\n出力先: {out_dir}")


if __name__ == "__main__":
    main()
