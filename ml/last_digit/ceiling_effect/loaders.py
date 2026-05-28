from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.last_digit.tail_ltr_split_rule_wf import aggregate_mode, build_base_rows, resolve_db_path

REQUIRED_TOPK_COLS = {
    "date",
    "expert",
    "top1_tail",
    "top2_tail",
    "hit_at_2",
    "pred_span_top12",
}


@dataclass
class ActualRankInfo:
    top1_tail: str
    top2_tail: str
    top3_tail: str
    top1_diff: float
    top2_diff: float
    top3_diff: float
    tail_to_diff: dict[str, float]
    top1_machine_count: float = float("nan")
    top2_machine_count: float = float("nan")
    top3_machine_count: float = float("nan")
    tail_to_machine_count: dict[str, float] = field(default_factory=dict)


def _tail_str(value: Any) -> str:
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _load_hall_daily_anomaly_frame(db_path: Path) -> pd.DataFrame:
    con = sqlite3.connect(str(db_path))
    q = """
    SELECT date, avg_diff_per_machine
    FROM daily_hall_summary
    GROUP BY date
    ORDER BY date
    """
    hall = pd.read_sql_query(q, con)
    con.close()
    if hall.empty:
        return pd.DataFrame(columns=["date", "rolling_median", "zscore", "is_anomaly", "anomaly_direction"])
    hall["date"] = pd.to_datetime(hall["date"], format="%Y%m%d", errors="coerce")
    hall["avg_diff_per_machine"] = pd.to_numeric(hall["avg_diff_per_machine"], errors="coerce").fillna(0.0)
    hall = hall.sort_values("date").reset_index(drop=True)
    hall["rolling_median"] = hall["avg_diff_per_machine"].rolling(28, min_periods=7).median()
    hall["rolling_std"] = hall["avg_diff_per_machine"].rolling(28, min_periods=7).std()
    denom = hall["rolling_std"].replace(0.0, np.nan)
    hall["zscore"] = (hall["avg_diff_per_machine"] - hall["rolling_median"]) / denom
    hall["zscore"] = hall["zscore"].fillna(0.0)
    hall["is_anomaly"] = (hall["zscore"].abs() >= 1.5).astype(int)
    hall["anomaly_direction"] = np.where(
        hall["is_anomaly"] == 0,
        "normal",
        np.where(hall["zscore"] >= 0, "high_anomaly", "low_anomaly"),
    )
    return hall[["date", "rolling_median", "zscore", "is_anomaly", "anomaly_direction"]]


def load_topk_with_conditions(topk_csv: str | Path, *, db_path: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(topk_csv, encoding="utf-8-sig")
    missing = REQUIRED_TOPK_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in topk CSV: {sorted(missing)}")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["expert"] = out["expert"].astype(str)
    out["top1_tail"] = out["top1_tail"].map(_tail_str)
    out["top2_tail"] = out["top2_tail"].map(_tail_str)
    out["hit_at_2"] = pd.to_numeric(out["hit_at_2"], errors="coerce").fillna(0.0)
    out["pred_span_top12"] = pd.to_numeric(out["pred_span_top12"], errors="coerce").fillna(0.0)
    if "weekday" not in out.columns:
        out["weekday"] = out["date"].dt.day_name()
    out["weekday"] = out["weekday"].astype(str)
    out["pred_span_quartile"] = pd.qcut(
        out["pred_span_top12"],
        q=4,
        labels=["Q1", "Q2", "Q3", "Q4"],
        duplicates="drop",
    ).astype(str)

    if db_path is None:
        db_path = resolve_db_path()
    hall = _load_hall_daily_anomaly_frame(db_path)
    out = out.merge(hall, on="date", how="left")
    out["is_anomaly"] = pd.to_numeric(out["is_anomaly"], errors="coerce").fillna(0).astype(int)
    out["anomaly_direction"] = out["anomaly_direction"].fillna("normal").astype(str)
    out["rolling_median"] = pd.to_numeric(out["rolling_median"], errors="coerce")
    out["zscore"] = pd.to_numeric(out["zscore"], errors="coerce").fillna(0.0)

    per_day_hit_min = out.groupby("date", sort=False)["hit_at_2"].transform("min")
    out["is_hit_rate_miss_day"] = (per_day_hit_min < 1.0).astype(int)
    out["difficulty_failure"] = np.where(out["is_hit_rate_miss_day"] == 1, "miss_day", "hit_day")
    return out


def build_actual_rank_map(*, db_path: Path | None = None) -> dict[tuple[pd.Timestamp, str], ActualRankInfo]:
    if db_path is None:
        db_path = resolve_db_path()
    raw = build_base_rows(db_path=db_path, a_weight=0.4, non_a_weight=1.3)
    agg = aggregate_mode(raw, mode="floor_atype4").copy()
    agg["date"] = pd.to_datetime(agg["date"])
    agg["group_key"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)
    agg["total_diff_coins"] = pd.to_numeric(agg["total_diff_coins"], errors="coerce").fillna(0.0)
    agg["machine_count"] = pd.to_numeric(agg["machine_count"], errors="coerce").fillna(0.0)

    rank_map: dict[tuple[pd.Timestamp, str], ActualRankInfo] = {}
    for (dt, expert), group in agg.groupby(["date", "group_key"], sort=False):
        ranked = group.sort_values(["total_diff_coins", "last_digit"], ascending=[False, True]).reset_index(drop=True)
        if ranked.empty:
            continue
        tail_to_diff = {str(r.last_digit): float(r.total_diff_coins) for r in ranked.itertuples(index=False)}
        tail_to_machine_count = {str(r.last_digit): float(r.machine_count) for r in ranked.itertuples(index=False)}
        top1 = ranked.iloc[0]
        top2 = ranked.iloc[1] if len(ranked) > 1 else ranked.iloc[0]
        top3 = ranked.iloc[2] if len(ranked) > 2 else ranked.iloc[min(1, len(ranked) - 1)]
        rank_map[(pd.Timestamp(dt), str(expert))] = ActualRankInfo(
            top1_tail=str(top1["last_digit"]),
            top2_tail=str(top2["last_digit"]),
            top3_tail=str(top3["last_digit"]),
            top1_diff=float(top1["total_diff_coins"]),
            top2_diff=float(top2["total_diff_coins"]),
            top3_diff=float(top3["total_diff_coins"]),
            tail_to_diff=tail_to_diff,
            top1_machine_count=float(top1["machine_count"]),
            top2_machine_count=float(top2["machine_count"]),
            top3_machine_count=float(top3["machine_count"]),
            tail_to_machine_count=tail_to_machine_count,
        )
    return rank_map
