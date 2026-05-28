"""
Lightweight multi-tier strategy evaluator for last_digit topk artifacts.

Usage:
  python -m ml.last_digit.strategy_eval_multitier
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from ml.last_digit.tail_ltr_split_rule_wf import aggregate_mode, build_base_rows, resolve_db_path


MODEL_FILES: dict[str, str] = {
    "ndcg_v2": "ml/last_digit/reports/digit_lag_v2_withinexpert_xgb_ranker_ndcg_testperiod_topk.csv",
    "ndcg": "db/experiments/model_comparison/tail_ltr_xgb_ndcg_xgb_ranker_ndcg_testperiod_topk.csv",
    "pairwise": "db/experiments/model_comparison/tail_ltr_xgb_pairwise_xgb_ranker_pairwise_testperiod_topk.csv",
    "lgbm": "db/experiments/model_comparison/tail_ltr_lgbm_lambdarank_lgbm_ranker_lambdarank_testperiod_topk.csv",
    "catboost_v2": "db/experiments/model_comparison/tail_ltr_catboost_pairlogit_v2_catboost_ranker_pairlogit_testperiod_topk.csv",
}

OUT_PATH = Path("ml/last_digit/exploratory/kamata7_only/strategy_eval_multitier.txt")
EXPERT_ORDER = ["2F_N", "3F_N", "3F_A"]


@dataclass
class ActualRank:
    top1_tail: str
    top2_tail: str
    top3_tail: str
    top1_diff: float
    top2_diff: float
    top3_diff: float


def _tail_str(value: Any) -> str:
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def _build_actual_rank_map() -> dict[tuple[pd.Timestamp, str], ActualRank]:
    raw = build_base_rows(db_path=resolve_db_path(), a_weight=0.4, non_a_weight=1.3)
    agg = aggregate_mode(raw, mode="floor_atype4").copy()
    agg["date"] = pd.to_datetime(agg["date"])
    agg["group_key"] = agg["group_key"].astype(str)
    agg["last_digit"] = agg["last_digit"].astype(str)

    rank_map: dict[tuple[pd.Timestamp, str], ActualRank] = {}
    for (dt, expert), group in agg.groupby(["date", "group_key"], sort=False):
        ranked = group.sort_values(["total_diff_coins", "last_digit"], ascending=[False, True]).reset_index(drop=True)
        if len(ranked) < 3:
            continue
        rank_map[(pd.Timestamp(dt), str(expert))] = ActualRank(
            top1_tail=str(ranked.loc[0, "last_digit"]),
            top2_tail=str(ranked.loc[1, "last_digit"]),
            top3_tail=str(ranked.loc[2, "last_digit"]),
            top1_diff=float(ranked.loc[0, "total_diff_coins"]),
            top2_diff=float(ranked.loc[1, "total_diff_coins"]),
            top3_diff=float(ranked.loc[2, "total_diff_coins"]),
        )
    return rank_map


def _load_model_topk(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    req = {"date", "expert", "top1_tail", "top2_tail"}
    miss = req - set(df.columns)
    if miss:
        raise ValueError(f"Missing required columns in {path}: {sorted(miss)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["expert"] = df["expert"].astype(str)
    df["top1_tail"] = df["top1_tail"].map(_tail_str)
    df["top2_tail"] = df["top2_tail"].map(_tail_str)
    if "top1_actual_raw_diff" in df.columns:
        df["top1_actual_raw_diff"] = pd.to_numeric(df["top1_actual_raw_diff"], errors="coerce")
    if "top2_actual_raw_diff" in df.columns:
        df["top2_actual_raw_diff"] = pd.to_numeric(df["top2_actual_raw_diff"], errors="coerce")
    if "hit_at_3" in df.columns:
        df["hit_at_3"] = pd.to_numeric(df["hit_at_3"], errors="coerce")
    return df


def _attach_actual(df: pd.DataFrame, rank_map: dict[tuple[pd.Timestamp, str], ActualRank]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        key = (pd.Timestamp(row.date), str(row.expert))
        actual = rank_map.get(key)
        if actual is None:
            continue
        out = row._asdict()
        out.update(
            {
                "actual_top1_tail": actual.top1_tail,
                "actual_top2_tail": actual.top2_tail,
                "actual_top3_tail": actual.top3_tail,
                "actual_top1_diff": actual.top1_diff,
                "actual_top2_diff": actual.top2_diff,
                "actual_top3_diff": actual.top3_diff,
            }
        )
        rows.append(out)
    return pd.DataFrame(rows)


def _pct(series: pd.Series) -> float:
    if len(series) == 0:
        return float("nan")
    return float(series.mean() * 100.0)


def _build_step1_table(scored_by_model: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, df in scored_by_model.items():
        actual_top2 = [set([r.actual_top1_tail, r.actual_top2_tail]) for r in df.itertuples(index=False)]
        actual_top3 = [set([r.actual_top1_tail, r.actual_top2_tail, r.actual_top3_tail]) for r in df.itertuples(index=False)]

        hit1_top1 = df["top1_tail"] == df["actual_top1_tail"]
        hit1_top2 = [pred in top2 for pred, top2 in zip(df["top1_tail"], actual_top2, strict=False)]
        hit1_top3 = [pred in top3 for pred, top3 in zip(df["top1_tail"], actual_top3, strict=False)]
        cluster23_top2 = [pred in top2 for pred, top2 in zip(df["top2_tail"], actual_top2, strict=False)]

        rows.append(
            {
                "model": model,
                "n_pairs": len(df),
                "hit1_top1": _pct(pd.Series(hit1_top1, dtype=float)),
                "hit1_top2": _pct(pd.Series(hit1_top2, dtype=float)),
                "hit1_top3": _pct(pd.Series(hit1_top3, dtype=float)),
                "cluster23_top2": _pct(pd.Series(cluster23_top2, dtype=float)),
                "hit3_top3_proxy": _pct(df["hit_at_3"]) if "hit_at_3" in df.columns else float("nan"),
            }
        )
    return pd.DataFrame(rows).sort_values("model").reset_index(drop=True)


def _eval_ndcg_v2_rank2_rank3_proxy(df: pd.DataFrame) -> tuple[dict[str, float], str]:
    if "top2_actual_raw_diff" not in df.columns:
        return {}, "N/A (top2_actual_raw_diff missing)"
    rank2 = pd.to_numeric(df["top2_actual_raw_diff"], errors="coerce").dropna()
    top1_actual = pd.to_numeric(df["actual_top1_diff"], errors="coerce").dropna()
    if len(rank2) == 0:
        return {}, "N/A (rank2 series empty)"
    # rank3_actual_proxy: use actual top3 diff as a stable lower benchmark when pred rank3 is unavailable in topk CSV.
    rank3_proxy = pd.to_numeric(df["actual_top3_diff"], errors="coerce").dropna()
    n = int(min(len(rank2), len(rank3_proxy)))
    if n == 0:
        return {}, "N/A (rank3 proxy empty)"
    rank2v = rank2.iloc[:n]
    rank3v = rank3_proxy.iloc[:n]
    pvalue = float(stats.ttest_rel(rank2v, rank3v, nan_policy="omit").pvalue)
    result = {
        "rank2_median": float(rank2v.median()),
        "rank2_mean": float(rank2v.mean()),
        "rank3_proxy_median": float(rank3v.median()),
        "rank3_proxy_mean": float(rank3v.mean()),
        "actual_top1_median": float(top1_actual.median()) if len(top1_actual) > 0 else float("nan"),
        "pvalue_rank2_vs_rank3_proxy": pvalue,
        "n": n,
    }
    note = "rank3 is unavailable in testperiod_topk; actual_top3_diff is used as proxy."
    return result, note


def _scenario_value(row: pd.Series, p_taken: float, rng: np.random.Generator) -> tuple[float, float, float]:
    rank1 = float(row["top1_actual_raw_diff"]) if np.isfinite(row.get("top1_actual_raw_diff", np.nan)) else float("nan")
    rank2 = float(row["top2_actual_raw_diff"]) if np.isfinite(row.get("top2_actual_raw_diff", np.nan)) else float("nan")
    top1 = float(row["actual_top1_diff"])
    top3 = float(row["actual_top3_diff"])
    if np.isnan(rank1):
        rank1 = top3
    if np.isnan(rank2):
        rank2 = top3
    take_rank1 = bool(rng.random() >= p_taken)
    a = rank1
    b = rank1 if take_rank1 else rank2
    c = rank1 if take_rank1 else (rank2 if rng.random() < 0.5 else top3)
    d = top1
    return a, b, c, d


def _build_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for p in [0.10, 0.30, 0.50]:
        rng = np.random.default_rng(42)
        a_vals: list[float] = []
        b_vals: list[float] = []
        c_vals: list[float] = []
        d_vals: list[float] = []
        for _, row in df.iterrows():
            a, b, c, d = _scenario_value(row, p, rng)
            a_vals.append(a)
            b_vals.append(b)
            c_vals.append(c)
            d_vals.append(d)
        rows.append(
            {
                "taken_prob": int(p * 100),
                "scenario_a_rank1_fixed": float(np.median(a_vals)),
                "scenario_b_rank1_then_rank2": float(np.median(b_vals)),
                "scenario_c_rank1_then_random_23proxy": float(np.median(c_vals)),
                "scenario_d_theoretical_top1": float(np.median(d_vals)),
            }
        )
    return pd.DataFrame(rows)


def _fmt_pct(value: float) -> str:
    if np.isnan(value):
        return "N/A"
    return f"{value:.1f}%"


def _render_report(
    *,
    step1: pd.DataFrame,
    ndcg_rank23: dict[str, float],
    ndcg_rank23_note: str,
    sensitivity: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("=== Step 1: Strategy Metrics (rank3-unrequired) ===")
    header = "metric | ndcg_v2 | ndcg | pairwise | lgbm | catboost_v2"
    lines.append(header)
    lines.append("---|---:|---:|---:|---:|---:")
    metric_rows = [
        ("hit@1->top1", "hit1_top1"),
        ("hit@1->top2", "hit1_top2"),
        ("hit@1->top3", "hit1_top3"),
        ("cluster23->top2 (rank2 proxy)", "cluster23_top2"),
        ("hit@3->top3 (from topk hit_at_3)", "hit3_top3_proxy"),
    ]
    models = ["ndcg_v2", "ndcg", "pairwise", "lgbm", "catboost_v2"]
    by_model = {r["model"]: r for r in step1.to_dict(orient="records")}
    for label, key in metric_rows:
        vals = [_fmt_pct(float(by_model[m][key])) if m in by_model else "N/A" for m in models]
        lines.append(f"{label} | {vals[0]} | {vals[1]} | {vals[2]} | {vals[3]} | {vals[4]}")

    lines.append("")
    lines.append("=== Step 2: rank2 vs rank3 (ndcg_v2 proxy analysis) ===")
    if ndcg_rank23:
        lines.append(f"n={int(ndcg_rank23['n'])}")
        lines.append(f"rank2 actual diff median: {ndcg_rank23['rank2_median']:.1f}")
        lines.append(f"rank2 actual diff mean:   {ndcg_rank23['rank2_mean']:.1f}")
        lines.append(f"rank3 proxy median:       {ndcg_rank23['rank3_proxy_median']:.1f}")
        lines.append(f"rank3 proxy mean:         {ndcg_rank23['rank3_proxy_mean']:.1f}")
        lines.append(f"actual top1 median:       {ndcg_rank23['actual_top1_median']:.1f}")
        lines.append(f"paired t-test p-value (rank2 vs rank3 proxy): {ndcg_rank23['pvalue_rank2_vs_rank3_proxy']:.6g}")
    lines.append(f"note: {ndcg_rank23_note}")

    lines.append("")
    lines.append("=== Step 3: Sensitivity Analysis (ndcg_v2) ===")
    lines.append("taken_prob | scenarioA_rank1 | scenarioB_rank1_to_rank2 | scenarioC_rank1_to_random23proxy | scenarioD_theoretical_top1")
    lines.append("---|---:|---:|---:|---:")
    for row in sensitivity.to_dict(orient="records"):
        lines.append(
            f"{int(row['taken_prob'])}% | "
            f"{row['scenario_a_rank1_fixed']:.1f} | "
            f"{row['scenario_b_rank1_then_rank2']:.1f} | "
            f"{row['scenario_c_rank1_then_random_23proxy']:.1f} | "
            f"{row['scenario_d_theoretical_top1']:.1f}"
        )
    lines.append("(unit: diff_coins median)")
    return "\n".join(lines) + "\n"


def main() -> int:
    rank_map = _build_actual_rank_map()
    scored_by_model: dict[str, pd.DataFrame] = {}
    for model_name, path in MODEL_FILES.items():
        src = Path(path)
        if not src.exists():
            continue
        model_df = _load_model_topk(str(src))
        scored = _attach_actual(model_df, rank_map)
        if scored.empty:
            continue
        scored_by_model[model_name] = scored

    if "ndcg_v2" not in scored_by_model:
        raise RuntimeError("ndcg_v2 data could not be prepared.")

    step1 = _build_step1_table(scored_by_model)
    ndcg_rank23, ndcg_rank23_note = _eval_ndcg_v2_rank2_rank3_proxy(scored_by_model["ndcg_v2"])
    sensitivity = _build_sensitivity(scored_by_model["ndcg_v2"])
    report = _render_report(
        step1=step1,
        ndcg_rank23=ndcg_rank23,
        ndcg_rank23_note=ndcg_rank23_note,
        sensitivity=sensitivity,
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
