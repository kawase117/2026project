from __future__ import annotations

import sqlite3
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from .config import ANNIVERSARY_MMDD, DEFAULT_DB_PATH, EVENT_DDS, RESULTS_DIR, VariantConfig, build_variant_configs
from .report_generator import build_report
from .scoring_model import (
    ScoreContext,
    build_score_context,
    candidate_weights,
    clear_v8_lift_cache,
    _score_from_components,
    score_day,
)


SUMMARY_COLUMNS = [
    "variant",
    "window",
    "event_type",
    "avg_diff",
    "avg_diff_other",
    "avg_diff_vs_other",
    "win_rate",
    "payout_rate",
    "hit@10",
    "hit@20",
    "hit@50",
    "lift@10",
    "lift@20",
    "lift@50",
    "hit_t2500",
    "hit_t3500",
    "hit_t4500",
    "lift_t2500",
    "lift_t3500",
    "lift_t4500",
    "n_test_days",
]

DAILY_COLUMNS = [
    "test_date",
    "variant",
    "window",
    "DD",
    "dow",
    "is_event",
    "event_type",
    "avg_diff",
    "avg_diff_other",
    "avg_diff_vs_other",
    "win_rate",
    "payout_rate",
    "hit@10",
    "hit@20",
    "hit@50",
    "lift@10",
    "lift@20",
    "lift@50",
    "hit_t2500",
    "hit_t3500",
    "hit_t4500",
    "lift_t2500",
    "lift_t3500",
    "lift_t4500",
    "n_machines_scored",
    "n_actual_machines",
    "split_period",
    "a_seg_hist_coverage",
    "a_seg_fallback_count",
]

COMPONENT_COLUMNS = [
    "test_date",
    "variant",
    "window",
    "component",
    "event_type",
    "avg_diff",
    "win_rate",
    "payout_rate",
    "hit@50",
    "lift@50",
]

THRESHOLD_CUTS = (2500, 3500, 4500)

WEIGHT_COLUMNS = [
    "test_date",
    "window",
    "w1",
    "w2",
    "w3",
    "w4",
    "w5",
    "w6",
    "avg_lift50",
    "avg_hit50",
    "n_days",
    "selected",
]


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def load_machine_data(db_path: Path) -> pd.DataFrame:
    query = """
        SELECT
            date,
            machine_number,
            machine_name,
            last_digit,
            is_zorome,
            games_normalized,
            diff_coins_normalized
        FROM machine_detailed_results
    """
    with sqlite3.connect(str(db_path)) as conn:
        df = pd.read_sql_query(query, conn)
    df["date"] = df["date"].astype(str)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce").astype("Int64")
    return df.dropna(subset=["date", "machine_number"]).reset_index(drop=True)


def _is_event_date(date_value: pd.Timestamp) -> bool:
    return int(date_value.day) in EVENT_DDS or bool(date_value.is_month_end)


def _assign_split_period(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return daily_results
    out = daily_results.copy()
    unique_dates = sorted(pd.to_datetime(out["test_date"], errors="coerce").dropna().dt.normalize().unique())
    if not unique_dates:
        out["split_period"] = "front"
        return out
    midpoint = max(1, len(unique_dates) // 2)
    front_dates = {pd.Timestamp(value).strftime("%Y-%m-%d") for value in unique_dates[:midpoint]}
    out["split_period"] = out["test_date"].astype(str).map(lambda value: "front" if value in front_dates else "back")
    return out


def _summarize_metrics(rows: pd.DataFrame, actual: pd.DataFrame) -> dict[str, float]:
    if rows.empty:
        return {
            "avg_diff": 0.0,
            "avg_diff_other": 0.0,
            "avg_diff_vs_other": 0.0,
            "win_rate": 0.0,
            "payout_rate": 0.0,
            "hit@10": 0.0,
            "hit@20": 0.0,
            "hit@50": 0.0,
            "lift@10": 0.0,
            "lift@20": 0.0,
            "lift@50": 0.0,
            "hit_t2500": 0.0,
            "hit_t3500": 0.0,
            "hit_t4500": 0.0,
            "lift_t2500": 0.0,
            "lift_t3500": 0.0,
            "lift_t4500": 0.0,
        }
    actual_sorted = actual.sort_values("diff_coins_normalized", ascending=False).reset_index(drop=True)
    top = rows.head(min(50, len(rows))).copy()
    other = actual[~actual["machine_number"].isin(top["machine_number"])]
    top_n = len(top)
    total_n = max(len(actual), 1)
    metrics = {
        "avg_diff": float(top["diff_coins_normalized"].mean()) if len(top) else 0.0,
        "avg_diff_other": float(other["diff_coins_normalized"].mean()) if len(other) else 0.0,
        "win_rate": float((top["diff_coins_normalized"] > 0).mean() * 100) if len(top) else 0.0,
        "payout_rate": float((((top["games_normalized"] * 3 + top["diff_coins_normalized"]) / (top["games_normalized"] * 3)) * 100).mean())
        if len(top)
        else 0.0,
    }
    metrics["avg_diff_vs_other"] = metrics["avg_diff"] - metrics["avg_diff_other"]
    for n in (10, 20, 50):
        actual_n = actual_sorted.head(min(n, len(actual_sorted)))
        hits = len(set(top["machine_number"]) & set(actual_n["machine_number"]))
        expected = (min(n, len(actual_sorted)) * len(top) / total_n) if total_n else 0.0
        metrics[f"hit@{n}"] = float(hits)
        metrics[f"lift@{n}"] = float(hits / expected) if expected else 0.0
    for threshold in THRESHOLD_CUTS:
        actual_threshold = actual[actual["diff_coins_normalized"] >= threshold]
        hits = len(set(top["machine_number"]) & set(actual_threshold["machine_number"]))
        expected = (len(actual_threshold) * len(top) / total_n) if total_n else 0.0
        metrics[f"hit_t{threshold}"] = float(hits)
        metrics[f"lift_t{threshold}"] = float(hits / expected) if expected else 0.0
    return metrics


def _threshold_metric_aggs() -> dict[str, tuple[str, str]]:
    return {
        "hit_t2500": ("hit_t2500", "mean"),
        "hit_t3500": ("hit_t3500", "mean"),
        "hit_t4500": ("hit_t4500", "mean"),
        "lift_t2500": ("lift_t2500", "mean"),
        "lift_t3500": ("lift_t3500", "mean"),
        "lift_t4500": ("lift_t4500", "mean"),
    }


def _aggregate_daily_results(daily_results: pd.DataFrame) -> pd.DataFrame:
    if daily_results.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    by_group = (
        daily_results.groupby(["variant", "window", "event_type"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            avg_diff_other=("avg_diff_other", "mean"),
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            win_rate=("win_rate", "mean"),
            payout_rate=("payout_rate", "mean"),
            hit_10=("hit@10", "mean"),
            hit_20=("hit@20", "mean"),
            hit_50=("hit@50", "mean"),
            lift_10=("lift@10", "mean"),
            lift_20=("lift@20", "mean"),
            lift_50=("lift@50", "mean"),
            n_test_days=("test_date", "nunique"),
            **_threshold_metric_aggs(),
        )
        .rename(
            columns={
                "hit_10": "hit@10",
                "hit_20": "hit@20",
                "hit_50": "hit@50",
                "lift_10": "lift@10",
                "lift_20": "lift@20",
                "lift_50": "lift@50",
            }
        )
    )
    all_group = (
        daily_results.groupby(["variant", "window"], as_index=False)
        .agg(
            avg_diff=("avg_diff", "mean"),
            avg_diff_other=("avg_diff_other", "mean"),
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            win_rate=("win_rate", "mean"),
            payout_rate=("payout_rate", "mean"),
            hit_10=("hit@10", "mean"),
            hit_20=("hit@20", "mean"),
            hit_50=("hit@50", "mean"),
            lift_10=("lift@10", "mean"),
            lift_20=("lift@20", "mean"),
            lift_50=("lift@50", "mean"),
            n_test_days=("test_date", "nunique"),
            **_threshold_metric_aggs(),
        )
        .assign(event_type="all")
        .rename(
            columns={
                "hit_10": "hit@10",
                "hit_20": "hit@20",
                "hit_50": "hit@50",
                "lift_10": "lift@10",
                "lift_20": "lift@20",
                "lift_50": "lift@50",
            }
        )
    )
    grouped = pd.concat([by_group, all_group], ignore_index=True)
    grouped = grouped.sort_values(["window", "variant", "event_type"]).reset_index(drop=True)
    return grouped[SUMMARY_COLUMNS]


def _select_test_dates(df: pd.DataFrame, windows: Iterable[int], test_dates: Iterable[pd.Timestamp] | None) -> list[pd.Timestamp]:
    if test_dates is not None:
        return [pd.Timestamp(value).normalize() for value in test_dates]
    sorted_dates = sorted(pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").dropna().dt.normalize().unique())
    if not sorted_dates:
        return []
    max_window = max(windows)
    earliest = sorted_dates[0] + timedelta(days=max_window)
    return [date for date in sorted_dates if date >= earliest]


def _prepare_source(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["date"].astype(str)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out = out[out["date"].str[4:8] != ANNIVERSARY_MMDD].copy()
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce").astype("Int64")
    out = out[out["machine_number"].ne(2026)].copy()
    out["games_normalized"] = pd.to_numeric(out["games_normalized"], errors="coerce")
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    return out.dropna(subset=["date_dt", "machine_number"]).reset_index(drop=True)


def _optimization_candidates_for_window(
    train: pd.DataFrame,
    actual_dates: list[pd.Timestamp],
    variant: VariantConfig,
    context: ScoreContext,
) -> tuple[tuple[float, float, float, float, float, float], pd.DataFrame]:
    rows: list[dict[str, object]] = []
    best_weights = variant.component_weights
    best_score = -np.inf
    candidates = candidate_weights()
    if len(actual_dates) < 2:
        return best_weights, pd.DataFrame(columns=WEIGHT_COLUMNS)

    split = max(1, int(len(actual_dates) * 0.8))
    inner_dates = actual_dates[:split]
    val_dates = actual_dates[split:]
    if not val_dates:
        val_dates = actual_dates[-1:]
        inner_dates = actual_dates[:-1] or actual_dates[:1]

    inner_train = train[train["date_dt"].isin(inner_dates)].copy()
    validation = train[train["date_dt"].isin(val_dates)].copy()
    validation_frames: list[tuple[pd.Timestamp, pd.DataFrame, pd.DataFrame]] = []
    for test_date in val_dates:
        train_fold = inner_train[inner_train["date_dt"] < test_date].copy()
        actual_fold = validation[validation["date_dt"] == test_date].copy()
        if train_fold.empty or actual_fold.empty:
            continue
        scored = score_day(
            train_fold,
            actual_fold,
            variant,
            test_date=test_date,
            context=context,
            weight_override=variant.component_weights,
            full_train=train,
        )
        if scored.empty:
            continue
        validation_frames.append((test_date, scored, actual_fold))

    for weights in candidates:
        metrics_rows: list[dict[str, float]] = []
        for _, scored_base, actual_fold in validation_frames:
            scored = scored_base.copy()
            scored["composite"] = _score_from_components(scored, weights)
            scored = scored.sort_values(["composite", "diff_coins_normalized", "machine_number"], ascending=[False, False, True]).reset_index(drop=True)
            metrics_rows.append(_summarize_metrics(scored, actual_fold))
        if not metrics_rows:
            continue
        avg_lift50 = float(np.mean([row["lift@50"] for row in metrics_rows]))
        avg_hit50 = float(np.mean([row["hit@50"] for row in metrics_rows]))
        rows.append(
            {
                "w1": weights[0],
                "w2": weights[1],
                "w3": weights[2],
                "w4": weights[3],
                "w5": weights[4],
                "w6": weights[5],
                "avg_lift50": avg_lift50,
                "avg_hit50": avg_hit50,
                "n_days": len(metrics_rows),
            }
        )
        if avg_lift50 > best_score:
            best_score = avg_lift50
            best_weights = weights

    table = pd.DataFrame(
        rows,
        columns=["w1", "w2", "w3", "w4", "w5", "w6", "avg_lift50", "avg_hit50", "n_days"],
    )
    if not table.empty:
        table["selected"] = False
        best_mask = (
            table["w1"].eq(best_weights[0])
            & table["w2"].eq(best_weights[1])
            & table["w3"].eq(best_weights[2])
            & table["w4"].eq(best_weights[3])
            & table["w5"].eq(best_weights[4])
            & table["w6"].eq(best_weights[5])
        )
        table.loc[best_mask, "selected"] = True
    return best_weights, table


def _compute_correlation_matrix(scored_rows: pd.DataFrame) -> pd.DataFrame:
    columns = ["c1", "c2", "c3", "c4", "c5", "c6", "hist_diff", "hist_payout", "hist_winrate", "hist_hit_an"]
    if scored_rows.empty:
        return pd.DataFrame(index=columns, columns=columns)
    return scored_rows[columns].corr(method="spearman").round(4)


def _cluster_islands(scored_rows: pd.DataFrame) -> pd.DataFrame:
    if scored_rows.empty:
        return pd.DataFrame(columns=["section", "cluster", "mean_composite", "mean_diff"])
    section_profile = (
        scored_rows.groupby("section", as_index=False)
        .agg(
            c1=("c1", "mean"),
            c2=("c2", "mean"),
            c3=("c3", "mean"),
            c4=("c4", "mean"),
            c5=("c5", "mean"),
            c6=("c6", "mean"),
            mean_composite=("composite", "mean"),
            mean_diff=("diff_coins_normalized", "mean"),
        )
        .reset_index(drop=True)
    )
    if len(section_profile) < 3:
        section_profile["cluster"] = 1
        return section_profile[["section", "cluster", "mean_composite", "mean_diff"]]
    features = section_profile[["c1", "c2", "c3", "c4", "c5", "c6"]].to_numpy(dtype=float)
    linkage_matrix = linkage(pdist(features, metric="euclidean"), method="average")
    section_profile["cluster"] = fcluster(linkage_matrix, t=3, criterion="maxclust")
    return section_profile[["section", "cluster", "mean_composite", "mean_diff"]]


def _adjacency_effect(scored_rows: pd.DataFrame) -> pd.DataFrame:
    if scored_rows.empty:
        return pd.DataFrame(columns=["section", "adjacent_gap", "n_pairs"])
    rows: list[dict[str, object]] = []
    for section, group in scored_rows.groupby("section"):
        ordered = group.sort_values("kakuban")
        if len(ordered) < 2:
            continue
        diffs = ordered["diff_coins_normalized"].diff().abs().dropna()
        rows.append(
            {
                "section": section,
                "adjacent_gap": float(diffs.mean()) if len(diffs) else 0.0,
                "n_pairs": int(len(diffs)),
            }
        )
    return pd.DataFrame(rows)


def _segment_best_variant(daily_segment_results: pd.DataFrame) -> pd.DataFrame:
    if daily_segment_results.empty:
        return pd.DataFrame(columns=["segment", "best_variant", "best_window", "avg_diff"])
    summary = (
        daily_segment_results.groupby(["segment", "variant", "window"], as_index=False)
        .agg(avg_diff=("avg_diff", "mean"), hit50=("hit@50", "mean"))
        .sort_values(["segment", "avg_diff", "hit50"], ascending=[True, False, False])
    )
    return summary.groupby("segment", as_index=False).head(1).reset_index(drop=True)


def run_backtest(
    df: pd.DataFrame,
    *,
    output_dir: Path = RESULTS_DIR,
    variants: Iterable[str] | None = None,
    windows: Iterable[int] = (90, 180, 365),
    test_dates: Iterable[pd.Timestamp] | None = None,
    resume: bool = False,
    min_actual_machines: int = 50,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_v8_lift_cache()
    context = build_score_context()
    source = _prepare_source(df)
    variant_map = build_variant_configs()
    selected_variants = list(variants) if variants is not None else list(variant_map.keys())
    selected_windows = [int(value) for value in windows]
    dates = _select_test_dates(source, selected_windows, test_dates)

    daily_path = output_dir / "daily_results.csv"
    component_path = output_dir / "component_analysis.csv"
    weight_path = output_dir / "weight_optimization.csv"

    if resume and daily_path.exists():
        existing_daily = pd.read_csv(daily_path, encoding="utf-8-sig")
    else:
        existing_daily = pd.DataFrame(columns=DAILY_COLUMNS)

    existing_keys = set()
    if not existing_daily.empty:
        for row in existing_daily.itertuples(index=False):
            existing_keys.add((str(row.test_date), str(row.variant), int(row.window)))

    daily_rows: list[dict[str, object]] = existing_daily.to_dict("records") if not existing_daily.empty else []
    component_rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    segment_rows: list[dict[str, object]] = []
    scored_pool: list[pd.DataFrame] = []

    t0 = time.time()
    processed_count = 0
    total_tasks = len(selected_windows) * len(dates) * len(selected_variants)

    for window in selected_windows:
        window_delta = timedelta(days=window)
        for date_idx, test_date in enumerate(dates):
            actual = source[source["date_dt"] == test_date].copy()
            train = source[(source["date_dt"] >= test_date - window_delta) & (source["date_dt"] < test_date)].copy()
            if train.empty or actual.empty or len(actual) < min_actual_machines:
                continue
            for variant_id in selected_variants:
                variant = variant_map[variant_id]
                key = (test_date.strftime("%Y-%m-%d"), variant_id, int(window))
                if key in existing_keys:
                    continue
                weights_override = None
                if variant.optimize_weights:
                    train_dates = sorted(train["date_dt"].dropna().dt.normalize().unique().tolist())
                    weights_override, weight_table = _optimization_candidates_for_window(train, train_dates, variant, context)
                    if not weight_table.empty:
                        table = weight_table.copy()
                        table.insert(0, "test_date", test_date.strftime("%Y-%m-%d"))
                        table.insert(1, "window", int(window))
                        weight_rows.extend(table.to_dict("records"))
                scored = score_day(
                    train,
                    actual,
                    variant,
                    test_date=test_date,
                    context=context,
                    weight_override=weights_override,
                    full_train=source,
                )
                if scored.empty:
                    continue
                scored_pool.append(scored.assign(test_date=test_date.strftime("%Y-%m-%d"), window=int(window), variant=variant_id))
                metrics = _summarize_metrics(scored, actual)
                daily_rows.append(
                    {
                        "test_date": test_date.strftime("%Y-%m-%d"),
                        "variant": variant_id,
                        "window": int(window),
                        "DD": int(test_date.day),
                        "dow": int(test_date.dayofweek),
                        "is_event": bool(_is_event_date(test_date)),
                        "event_type": "event" if _is_event_date(test_date) else "non_event",
                        **metrics,
                        "n_machines_scored": int(len(scored)),
                        "n_actual_machines": int(len(actual)),
                        "a_seg_hist_coverage": float(scored.loc[scored["seg"].eq("A"), "a_seg_hist_coverage"].mean())
                        if "a_seg_hist_coverage" in scored.columns and scored["seg"].eq("A").any()
                        else 0.0,
                        "a_seg_fallback_count": int(scored.loc[scored["seg"].eq("A"), "a_seg_fallback_count"].sum())
                        if "a_seg_fallback_count" in scored.columns
                        else 0,
                    }
                )
                existing_keys.add(key)

                for component in ["c1", "c2", "c3", "c4", "c5", "c6", "hist_diff", "hist_payout", "hist_winrate", "hist_hit_an"]:
                    comp_rows = scored.copy()
                    comp_rows = comp_rows.sort_values(component, ascending=False).reset_index(drop=True)
                    comp_metrics = _summarize_metrics(comp_rows, actual)
                    component_rows.append(
                        {
                            "test_date": test_date.strftime("%Y-%m-%d"),
                            "variant": variant_id,
                            "window": int(window),
                            "component": component,
                            "event_type": "event" if _is_event_date(test_date) else "non_event",
                            "avg_diff": comp_metrics["avg_diff"],
                            "win_rate": comp_metrics["win_rate"],
                            "payout_rate": comp_metrics["payout_rate"],
                            "hit@50": comp_metrics["hit@50"],
                            "lift@50": comp_metrics["lift@50"],
                        }
                    )

                segment_daily = (
                    scored.groupby("segment", as_index=False)
                    .apply(lambda group: pd.Series(_summarize_metrics(group.sort_values("composite", ascending=False), actual)))
                    .reset_index()
                )
                segment_daily["test_date"] = test_date.strftime("%Y-%m-%d")
                segment_daily["variant"] = variant_id
                segment_daily["window"] = int(window)
                segment_daily["event_type"] = "event" if _is_event_date(test_date) else "non_event"
                segment_rows.extend(segment_daily.to_dict("records"))

                processed_count += 1
                if processed_count % 50 == 0:
                    elapsed = time.time() - t0
                    rate = processed_count / elapsed if elapsed > 0 else 0
                    remaining = (total_tasks - processed_count) / rate if rate > 0 else 0
                    print(
                        f"[Progress] {processed_count}/{total_tasks} "
                        f"({processed_count*100//total_tasks}%) "
                        f"elapsed={elapsed:.0f}s remaining≈{remaining:.0f}s "
                        f"date={test_date.strftime('%Y-%m-%d')} window={window} variant={variant_id}",
                        file=sys.stderr,
                        flush=True,
                    )
                    _write_csv(pd.DataFrame(daily_rows, columns=DAILY_COLUMNS), daily_path)

    daily_df = pd.DataFrame(daily_rows, columns=DAILY_COLUMNS)
    daily_df = _assign_split_period(daily_df)
    component_df = pd.DataFrame(component_rows, columns=COMPONENT_COLUMNS)
    weight_df = pd.DataFrame(weight_rows, columns=WEIGHT_COLUMNS)
    if not weight_df.empty and "selected" not in weight_df.columns:
        weight_df["selected"] = False

    summary_df = _aggregate_daily_results(daily_df)
    correlation_df = _compute_correlation_matrix(pd.concat(scored_pool, ignore_index=True) if scored_pool else pd.DataFrame())
    island_df = _cluster_islands(pd.concat(scored_pool, ignore_index=True) if scored_pool else pd.DataFrame())
    adjacency_df = _adjacency_effect(pd.concat(scored_pool, ignore_index=True) if scored_pool else pd.DataFrame())
    segment_df = _segment_best_variant(pd.DataFrame(segment_rows))
    split_df = (
        daily_df.groupby(["window", "split_period"], as_index=False)
        .agg(
            avg_diff_vs_other=("avg_diff_vs_other", "mean"),
            lift50=("lift@50", "mean"),
            n_test_days=("test_date", "nunique"),
            avg_a_seg_hist_coverage=("a_seg_hist_coverage", "mean"),
            avg_a_seg_fallback_count=("a_seg_fallback_count", "mean"),
        )
        .sort_values(["window", "split_period"])
        if not daily_df.empty
        else pd.DataFrame(columns=["window", "split_period", "avg_diff_vs_other", "lift50", "n_test_days", "avg_a_seg_hist_coverage", "avg_a_seg_fallback_count"])
    )

    _write_csv(daily_df, daily_path)
    _write_csv(component_df, component_path)
    _write_csv(weight_df, weight_path)
    _write_csv(summary_df, output_dir / "summary.csv")
    _write_csv(correlation_df.reset_index().rename(columns={"index": "component"}), output_dir / "correlation_matrix.csv")
    segment_daily_df = pd.DataFrame(segment_rows)
    _write_csv(segment_daily_df, output_dir / "segment_daily_results.csv")

    extra_checks = {
        "Island Clustering": island_df,
        "Sensitivity": weight_df.sort_values(["window", "avg_lift50"], ascending=[True, False]).head(15) if not weight_df.empty else weight_df,
        "Adjacency Effect": adjacency_df,
        "Segment Best Variant": segment_df,
        "Front/Back Split Verification": split_df,
    }
    report = build_report(
        summary=summary_df,
        daily_results=daily_df,
        component_analysis=component_df,
        weight_optimization=weight_df,
        correlation_matrix=correlation_df,
        extra_checks=extra_checks,
        output_dir=output_dir,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {
        "summary": summary_df,
        "daily_results": daily_df,
        "component_analysis": component_df,
        "weight_optimization": weight_df,
        "correlation_matrix": correlation_df,
        "extra_checks": pd.DataFrame(),
        "segment_daily_results": segment_daily_df,
    }
