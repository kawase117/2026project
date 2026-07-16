from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.utils.theory_engine import build_dd_position_matrix, load_hall_config, load_theory_frame, summarize_by  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_dd_lastdigit_hanaban_interaction"
DEFAULT_MIN_CELL_N = 5
DEFAULT_MIN_SEGMENT_MACHINES = 50
EVENT_DDS = {10, 11, 22, 30}
SEGMENT_REPORT_ORDER = ["本館1F_N", "本館2F_N", "本館3F_N", "新館_N", "本館_A", "全体"]
SEGMENT_RELIABILITY_NOTE = {
    "本館1F_N": "参考: 21台の少数セグメント",
}
AXIS_SPECS = {
    "last_digit": {
        "label": "末尾",
        "column": "last_digit",
        "order": list(range(12)),
    },
    "hanaban": {
        "label": "端番",
        "column": "hanaban",
        "order": None,
    },
}


@dataclass(frozen=True)
class AxisAnalysis:
    axis_name: str
    axis_column: str
    all_summary: pd.DataFrame
    segment_summary: pd.DataFrame
    all_matrix_avg: pd.DataFrame
    all_matrix_hit: pd.DataFrame
    kw_all: pd.DataFrame
    kw_segment: pd.DataFrame
    pair_all: pd.DataFrame
    pair_segment: pd.DataFrame
    best_all: pd.DataFrame
    best_segment: pd.DataFrame


def _format_value(value: object, *, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def _markdown_table(frame: pd.DataFrame, *, columns: list[str] | None = None, float_digits: int = 3) -> str:
    work = frame.copy()
    if columns is not None:
        work = work.loc[:, columns]
    if work.empty:
        return "No rows."
    headers = [str(col) for col in work.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(_format_value(row[col], digits=float_digits) for col in work.columns) + " |")
    return "\n".join(lines)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _to_int64(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _prepare_frame(db_path: Path) -> pd.DataFrame:
    frame = load_theory_frame(db_path)
    if frame.empty:
        raise ValueError(f"failed to load theory frame from {db_path}")

    work = frame.copy()
    work["date_dt"] = pd.to_datetime(work["date_dt"], errors="coerce")
    work["dd"] = _to_int64(work["dd"])
    work["last_digit"] = _to_int64(work["last_digit"])
    work["hanaban"] = _to_int64(work["hanaban"])
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["hit104"] = pd.to_numeric(work["hit104"], errors="coerce")
    work["is_event_day"] = work["is_event_day"].fillna(False).astype(bool)
    work["segment"] = work["segment"].fillna("対象外/不明").astype(str)
    work = work.dropna(subset=["date_dt", "dd", "diff_coins_normalized", "games_normalized"]).reset_index(drop=True)
    return work


def _segment_machine_counts(frame: pd.DataFrame) -> pd.DataFrame:
    return (
        frame.groupby("segment", dropna=False)
        .agg(machine_count=("machine_number", "nunique"), row_count=("machine_number", "size"))
        .reset_index()
        .sort_values(["machine_count", "segment"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )


def _valid_segments(frame: pd.DataFrame) -> list[str]:
    counts = _segment_machine_counts(frame)
    return counts.loc[counts["segment"].ne("対象外/不明") & counts["machine_count"].gt(0), "segment"].tolist()


def _cell_summary(frame: pd.DataFrame, axis_column: str, *, min_n: int) -> pd.DataFrame:
    summary = summarize_by(frame, ["dd", axis_column], min_n=min_n)
    if summary.empty:
        return summary
    summary = summary.copy()
    summary = summary.dropna(subset=["dd", axis_column]).copy()
    summary["dd"] = summary["dd"].astype(int)
    summary[axis_column] = summary[axis_column].astype(int)
    summary["is_event_day"] = summary["dd"].isin(EVENT_DDS)
    return summary.sort_values(["dd", axis_column], kind="mergesort").reset_index(drop=True)


def _wide_matrix(summary: pd.DataFrame, axis_column: str, axis_order: list[int] | None) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    matrix = summary.pivot(index="dd", columns=axis_column, values="avg_diff").sort_index()
    if axis_order is not None:
        matrix = matrix.reindex(columns=axis_order)
    return matrix


def _kw_row(dd_value: int, dd_frame: pd.DataFrame, axis_column: str) -> dict[str, object] | None:
    groups: list[pd.Series] = []
    group_sizes: list[int] = []
    for axis_value, axis_group in dd_frame.groupby(axis_column, dropna=False):
        if pd.isna(axis_value):
            continue
        values = pd.to_numeric(axis_group["diff_coins_normalized"], errors="coerce").dropna()
        if len(values) < DEFAULT_MIN_CELL_N:
            continue
        groups.append(values)
        group_sizes.append(int(len(values)))
    if len(groups) < 2:
        return None
    try:
        stat, p_value = kruskal(*groups)
    except ValueError:
        return None
    n_total = int(sum(group_sizes))
    if n_total <= 1:
        return None
    return {
        "dd": int(dd_value),
        "n_groups": int(len(groups)),
        "n_samples": n_total,
        "statistic": float(stat),
        "p_value": float(p_value),
        "epsilon_sq": float(stat / (n_total - 1)),
    }


def _kw_significance(frame: pd.DataFrame, axis_column: str, *, segment: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    work = frame.copy()
    if segment != "全体":
        work = work[work["segment"].eq(segment)].copy()
    for dd_value, dd_frame in work.groupby("dd", dropna=False):
        if pd.isna(dd_value):
            continue
        row = _kw_row(int(dd_value), dd_frame, axis_column)
        if row is None:
            continue
        row["segment"] = segment
        row["axis"] = axis_column
        row["is_event_day"] = bool(dd_frame["is_event_day"].iloc[0])
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=[
                "segment",
                "axis",
                "dd",
                "is_event_day",
                "n_groups",
                "n_samples",
                "statistic",
                "p_value",
                "epsilon_sq",
            ]
        )
    out = pd.DataFrame(rows)
    out["dd"] = out["dd"].astype(int)
    out["n_groups"] = out["n_groups"].astype(int)
    out["n_samples"] = out["n_samples"].astype(int)
    out["is_event_day"] = out["is_event_day"].astype(bool)
    return out.sort_values(["dd", "segment"], kind="mergesort").reset_index(drop=True)


def _segment_order_for(frame: pd.DataFrame, *, include_all: bool = True) -> list[str]:
    values = frame["segment"].dropna().astype(str).tolist()
    present = [segment for segment in SEGMENT_REPORT_ORDER if segment in values]
    if include_all and "全体" in values and "全体" not in present:
        present.append("全体")
    extras = [segment for segment in pd.Index(values).unique().tolist() if segment not in present]
    return present + extras


def _ordered_kw_table(frame: pd.DataFrame, *, include_all: bool = True) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    work["segment"] = work["segment"].astype(str)
    order = _segment_order_for(work, include_all=include_all)
    work["segment"] = pd.Categorical(work["segment"], categories=order, ordered=True)
    return work.sort_values(["segment", "dd"], kind="mergesort").reset_index(drop=True)


def _top_segment_kw_rows(kw_table: pd.DataFrame, *, top_n: int = 5) -> pd.DataFrame:
    columns = ["segment", "segment_rank", "dd", "n_samples", "p_value", "epsilon_sq", "is_event_day", "note"]
    if kw_table.empty:
        return pd.DataFrame(columns=columns)
    work = kw_table.copy()
    work = work[work["segment"].ne("全体")].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)
    work["segment"] = work["segment"].astype(str)
    work["segment"] = pd.Categorical(
        work["segment"], categories=_segment_order_for(work, include_all=False), ordered=True
    )
    work = work.sort_values(
        ["segment", "epsilon_sq", "p_value", "n_samples", "dd"],
        ascending=[True, False, True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    work["segment_rank"] = work.groupby("segment", dropna=False).cumcount() + 1
    work = work[work["segment_rank"].le(top_n)].copy()
    work["note"] = work["segment"].astype(str).map(SEGMENT_RELIABILITY_NOTE).fillna("")
    work["segment"] = work["segment"].astype(str)
    return work.loc[:, columns].reset_index(drop=True)


def _segment_dd_consistency_table(segment_kw: pd.DataFrame, all_kw: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "dd",
        "best_segment",
        "best_n_samples",
        "best_p_value",
        "best_epsilon_sq",
        "all_p_value",
        "all_epsilon_sq",
        "epsilon_gap",
        "epsilon_ratio",
        "segment_count",
        "sig_segment_count",
        "strong_segment_count",
    ]
    if segment_kw.empty:
        return pd.DataFrame(columns=columns)
    work = segment_kw.copy()
    work = work[work["segment"].ne("全体")].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)
    work = work.sort_values(
        ["dd", "epsilon_sq", "p_value", "segment"],
        ascending=[True, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    best = work.groupby("dd", dropna=False).head(1).copy()
    stats = (
        work.groupby("dd", dropna=False)
        .agg(
            segment_count=("segment", "nunique"),
            sig_segment_count=("p_value", lambda series: int((series < 0.05).sum())),
            strong_segment_count=("epsilon_sq", lambda series: int((series >= 0.005).sum())),
        )
        .reset_index()
    )
    all_work = all_kw[all_kw["segment"].eq("全体")].copy()
    all_lookup = all_work.loc[:, ["dd", "p_value", "epsilon_sq"]].rename(
        columns={"p_value": "all_p_value", "epsilon_sq": "all_epsilon_sq"}
    )
    out = best.loc[:, ["dd", "segment", "n_samples", "p_value", "epsilon_sq"]].rename(
        columns={
            "segment": "best_segment",
            "n_samples": "best_n_samples",
            "p_value": "best_p_value",
            "epsilon_sq": "best_epsilon_sq",
        }
    )
    out = out.merge(all_lookup, on="dd", how="left").merge(stats, on="dd", how="left")
    out["epsilon_gap"] = out["best_epsilon_sq"] - out["all_epsilon_sq"]
    out["epsilon_ratio"] = out["best_epsilon_sq"] / out["all_epsilon_sq"].replace({0: np.nan})
    return out.sort_values(
        ["best_epsilon_sq", "sig_segment_count", "segment_count", "dd"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _segment_hidden_pattern_table(segment_kw: pd.DataFrame, all_kw: pd.DataFrame) -> pd.DataFrame:
    consistency = _segment_dd_consistency_table(segment_kw, all_kw)
    if consistency.empty:
        return consistency
    work = consistency.copy()
    all_signal = work["all_p_value"].ge(0.05) | work["all_epsilon_sq"].lt(0.001)
    work = work[work["best_p_value"].lt(0.05) & (all_signal | work["epsilon_gap"].ge(0.003))].copy()
    if work.empty:
        return consistency.iloc[0:0].copy()
    return work.sort_values(
        ["epsilon_gap", "best_epsilon_sq", "sig_segment_count", "dd"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _rank_table(summary: pd.DataFrame, axis_column: str, segment: str) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(
            columns=["segment", "dd", axis_column, "n", "avg_diff", "hit104_rate", "rank", "is_event_day"]
        )
    work = summary.copy()
    work["rank"] = work.groupby("dd", dropna=False)["avg_diff"].rank(method="first", ascending=False)
    work["segment"] = segment
    return work.sort_values(["dd", "rank", axis_column], kind="mergesort").reset_index(drop=True)


def _pairwise_stability(rank_table: pd.DataFrame, axis_column: str) -> pd.DataFrame:
    if rank_table.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "axis",
                "pair_type",
                "pairs",
                "mean_spearman_rho",
                "median_spearman_rho",
                "top1_match_rate",
                "mean_shared_axes",
            ]
        )

    axis_values = sorted(rank_table[axis_column].dropna().unique().tolist())
    dd_values = sorted(rank_table["dd"].dropna().unique().tolist())
    top1_map = (
        rank_table.sort_values(["dd", "rank", axis_column], ascending=[True, True, True], kind="mergesort")
        .groupby("dd", dropna=False)
        .head(1)
        .set_index("dd")[axis_column]
        .to_dict()
    )
    event_map = rank_table.groupby("dd", dropna=False)["is_event_day"].max().to_dict()

    rows: list[dict[str, object]] = []
    for dd_a, dd_b in itertools.combinations(dd_values, 2):
        a = rank_table[rank_table["dd"].eq(dd_a)].set_index(axis_column)
        b = rank_table[rank_table["dd"].eq(dd_b)].set_index(axis_column)
        common = [value for value in axis_values if value in a.index and value in b.index]
        if len(common) < 3:
            continue
        valid = pd.DataFrame(
            {
                "a": pd.to_numeric(a.loc[common, "rank"], errors="coerce"),
                "b": pd.to_numeric(b.loc[common, "rank"], errors="coerce"),
            }
        ).dropna()
        if len(valid) < 3:
            continue
        rho, _ = spearmanr(valid["a"], valid["b"])
        if pd.isna(rho):
            continue
        if event_map.get(dd_a, False) and event_map.get(dd_b, False):
            pair_type = "event-event"
        elif event_map.get(dd_a, False) or event_map.get(dd_b, False):
            pair_type = "mixed"
        else:
            pair_type = "non-event"
        rows.append(
            {
                "pair_type": pair_type,
                "dd_a": int(dd_a),
                "dd_b": int(dd_b),
                "rho": float(rho),
                "shared_axes": int(len(valid)),
                "top1_match": bool(top1_map.get(dd_a) == top1_map.get(dd_b)),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "segment",
                "axis",
                "pair_type",
                "pairs",
                "mean_spearman_rho",
                "median_spearman_rho",
                "top1_match_rate",
                "mean_shared_axes",
            ]
        )

    pair_df = pd.DataFrame(rows)
    summary = (
        pair_df.groupby("pair_type", dropna=False)
        .agg(
            pairs=("rho", "size"),
            mean_spearman_rho=("rho", "mean"),
            median_spearman_rho=("rho", "median"),
            top1_match_rate=("top1_match", "mean"),
            mean_shared_axes=("shared_axes", "mean"),
        )
        .reset_index()
    )
    summary["segment"] = rank_table["segment"].iloc[0]
    summary["axis"] = axis_column
    return (
        summary.loc[
            :,
            [
                "segment",
                "axis",
                "pair_type",
                "pairs",
                "mean_spearman_rho",
                "median_spearman_rho",
                "top1_match_rate",
                "mean_shared_axes",
            ],
        ]
        .sort_values(["segment", "axis", "pair_type"], kind="mergesort")
        .reset_index(drop=True)
    )


def _best_axis_table(summary: pd.DataFrame, axis_column: str, segment: str) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame(
            columns=["segment", "dd", "is_event_day", "best_axis", "best_avg_diff", "best_hit104_rate", "n_cells"]
        )
    rows: list[dict[str, object]] = []
    for dd_value, dd_frame in summary.groupby("dd", dropna=False):
        if dd_frame.empty:
            continue
        best = dd_frame.sort_values(
            ["avg_diff", "hit104_rate", "n"], ascending=[False, False, False], kind="mergesort"
        ).iloc[0]
        rows.append(
            {
                "segment": segment,
                "dd": int(dd_value),
                "is_event_day": bool(best["is_event_day"]),
                "best_axis": int(best[axis_column]),
                "best_avg_diff": float(best["avg_diff"]),
                "best_hit104_rate": float(best["hit104_rate"]),
                "n_cells": int(dd_frame.shape[0]),
            }
        )
    return pd.DataFrame(rows).sort_values(["dd"], kind="mergesort").reset_index(drop=True)


def _segment_contrast_summary(pair_df: pd.DataFrame, best_df: pd.DataFrame) -> pd.DataFrame:
    if pair_df.empty or best_df.empty:
        return pd.DataFrame(
            columns=[
                "segment",
                "event_event_pairs",
                "event_event_mean_rho",
                "event_event_top1_match",
                "non_event_pairs",
                "non_event_mean_rho",
                "non_event_top1_match",
                "event_best_axis_diversity",
                "non_event_best_axis_diversity",
            ]
        )

    rows: list[dict[str, object]] = []
    for segment in sorted(best_df["segment"].dropna().unique().tolist()):
        seg_pair = pair_df[pair_df["segment"].eq(segment)].copy()
        seg_best = best_df[best_df["segment"].eq(segment)].copy()
        event_best = seg_best[seg_best["is_event_day"].eq(True)]
        non_best = seg_best[seg_best["is_event_day"].eq(False)]

        def _metrics(kind: str) -> tuple[int, float, float]:
            sub = seg_pair[seg_pair["pair_type"].eq(kind)]
            if sub.empty:
                return 0, float("nan"), float("nan")
            return int(sub["pairs"].sum()), float(sub["mean_spearman_rho"].mean()), float(sub["top1_match_rate"].mean())

        event_pairs, event_rho, event_top1 = _metrics("event-event")
        non_pairs, non_rho, non_top1 = _metrics("non-event")
        rows.append(
            {
                "segment": segment,
                "event_event_pairs": event_pairs,
                "event_event_mean_rho": event_rho,
                "event_event_top1_match": event_top1,
                "non_event_pairs": non_pairs,
                "non_event_mean_rho": non_rho,
                "non_event_top1_match": non_top1,
                "event_best_axis_diversity": int(event_best["best_axis"].nunique()) if not event_best.empty else 0,
                "non_event_best_axis_diversity": int(non_best["best_axis"].nunique()) if not non_best.empty else 0,
            }
        )
    return pd.DataFrame(rows).sort_values("segment", kind="mergesort").reset_index(drop=True)


def _floor_split_judgement(frame: pd.DataFrame) -> pd.DataFrame:
    groups = [
        ("本館_N", ["本館1F", "本館2F", "本館3F"]),
        ("新館_N", ["新館1F", "新館2F"]),
    ]
    rows: list[dict[str, object]] = []
    for segment_name, floors in groups:
        seg = frame[frame["floor"].isin(floors) & frame["family"].eq("N")].copy()
        if seg.empty:
            continue
        floor_counts = (
            seg.groupby("floor", dropna=False)
            .agg(machine_count=("machine_number", "nunique"), row_count=("machine_number", "size"))
            .reset_index()
        )
        floor_counts["floor"] = pd.Categorical(floor_counts["floor"], categories=floors, ordered=True)
        floor_counts = floor_counts.sort_values("floor", kind="mergesort").reset_index(drop=True)
        groups_data = [
            pd.to_numeric(seg.loc[seg["floor"].eq(floor), "diff_coins_normalized"], errors="coerce").dropna().to_numpy()
            for floor in floors
            if seg["floor"].eq(floor).any()
        ]
        if len(groups_data) < 2:
            continue
        statistic, p_value = kruskal(*groups_data)
        n_obs = int(sum(len(values) for values in groups_data))
        epsilon_sq = float(statistic / (n_obs - 1)) if n_obs > 1 else float("nan")
        rows.append(
            {
                "segment_group": segment_name,
                "floors": " / ".join(floors),
                "machine_counts": ", ".join(
                    f"{row['floor']}={int(row['machine_count'])}" for _, row in floor_counts.iterrows()
                ),
                "row_counts": ", ".join(
                    f"{row['floor']}={int(row['row_count'])}" for _, row in floor_counts.iterrows()
                ),
                "n_groups": int(len(groups_data)),
                "n_obs": n_obs,
                "statistic": float(statistic),
                "p_value": float(p_value),
                "epsilon_sq": epsilon_sq,
                "judgement": "split" if (segment_name == "本館_N" and epsilon_sq >= 0.001) else "keep merged",
            }
        )
    return pd.DataFrame(rows).sort_values("segment_group", kind="mergesort").reset_index(drop=True)


def _build_axis_analysis(
    frame: pd.DataFrame, *, axis_name: str, axis_spec: dict[str, object], valid_segments: list[str], min_n: int
) -> AxisAnalysis:
    axis_column = str(axis_spec["column"])
    axis_order = axis_spec["order"]

    all_summary = _cell_summary(frame, axis_column, min_n=min_n)
    all_summary["segment"] = "全体"
    all_summary["axis"] = axis_name

    segment_summaries: list[pd.DataFrame] = []
    kw_segment_rows: list[pd.DataFrame] = []
    pair_segment_rows: list[pd.DataFrame] = []
    best_segment_rows: list[pd.DataFrame] = []
    for segment in valid_segments:
        seg_frame = frame[frame["segment"].eq(segment)].copy()
        seg_summary = _cell_summary(seg_frame, axis_column, min_n=min_n)
        if seg_summary.empty:
            continue
        seg_summary["segment"] = segment
        seg_summary["axis"] = axis_name
        segment_summaries.append(seg_summary)
        kw_segment_rows.append(_kw_significance(seg_frame, axis_column, segment=segment))
        rank_table = _rank_table(seg_summary, axis_column, segment)
        pair_segment_rows.append(_pairwise_stability(rank_table, axis_column))
        best_segment_rows.append(_best_axis_table(seg_summary, axis_column, segment))

    all_matrix_avg = _wide_matrix(all_summary, axis_column, axis_order)
    all_matrix_hit = all_summary.pivot(index="dd", columns=axis_column, values="hit104_rate").sort_index()
    if axis_order is not None:
        all_matrix_hit = all_matrix_hit.reindex(columns=axis_order)

    kw_all = _kw_significance(frame, axis_column, segment="全体")
    pair_all = _pairwise_stability(_rank_table(all_summary, axis_column, "全体"), axis_column)
    best_all = _best_axis_table(all_summary, axis_column, "全体")

    kw_segment = (
        pd.concat(kw_segment_rows, ignore_index=True) if kw_segment_rows else pd.DataFrame(columns=kw_all.columns)
    )
    pair_segment = (
        pd.concat(pair_segment_rows, ignore_index=True) if pair_segment_rows else pd.DataFrame(columns=pair_all.columns)
    )
    best_segment = (
        pd.concat(best_segment_rows, ignore_index=True) if best_segment_rows else pd.DataFrame(columns=best_all.columns)
    )
    segment_summary = pd.concat(segment_summaries, ignore_index=True) if segment_summaries else pd.DataFrame()

    return AxisAnalysis(
        axis_name=axis_name,
        axis_column=axis_column,
        all_summary=all_summary,
        segment_summary=segment_summary,
        all_matrix_avg=all_matrix_avg,
        all_matrix_hit=all_matrix_hit,
        kw_all=kw_all,
        kw_segment=kw_segment,
        pair_all=pair_all,
        pair_segment=pair_segment,
        best_all=best_all,
        best_segment=best_segment,
    )


def _event_comparison_table(pair_df: pd.DataFrame) -> pd.DataFrame:
    if pair_df.empty:
        return pd.DataFrame(
            columns=[
                "pair_type",
                "pairs",
                "mean_spearman_rho",
                "median_spearman_rho",
                "top1_match_rate",
                "mean_shared_axes",
            ]
        )
    return (
        pair_df.groupby("pair_type", dropna=False)
        .agg(
            pairs=("pairs", "sum"),
            mean_spearman_rho=("mean_spearman_rho", "mean"),
            median_spearman_rho=("median_spearman_rho", "mean"),
            top1_match_rate=("top1_match_rate", "mean"),
            mean_shared_axes=("mean_shared_axes", "mean"),
        )
        .reset_index()
        .sort_values("pair_type", kind="mergesort")
        .reset_index(drop=True)
    )


def _segment_kw_section(title: str, analysis: AxisAnalysis) -> list[str]:
    top_rows = _top_segment_kw_rows(analysis.kw_segment, top_n=5)
    consistency = _segment_dd_consistency_table(analysis.kw_segment, analysis.kw_all)
    hidden = _segment_hidden_pattern_table(analysis.kw_segment, analysis.kw_all)

    lines: list[str] = []
    lines.append(f"### {title}")
    lines.append("- セグメントごとに、全体と同じKW検定ロジックをそのまま適用した。")
    lines.append("- p値だけで切らず、ε²の大きさと全体との差分も併記した。")
    lines.append("- 本館1F_N は 21台の少数セグメントなので参考扱いだが、報告からは外していない。")
    lines.append("")
    lines.append("**セグメント別トップDD**")
    lines.append(_markdown_table(top_rows, float_digits=6))
    lines.append("")
    lines.append("**DD別の勝ちセグメント**")
    lines.append(_markdown_table(consistency, float_digits=6))
    lines.append("")
    lines.append("**全体では見えにくかったDD**")
    lines.append(_markdown_table(hidden, float_digits=6))
    lines.append("")
    return lines


def _build_report(
    *,
    db_path: Path,
    frame: pd.DataFrame,
    segment_counts: pd.DataFrame,
    floor_judgement: pd.DataFrame,
    valid_segments: list[str],
    lastdigit: AxisAnalysis,
    hanaban: AxisAnalysis,
) -> str:
    lines: list[str] = []
    lines.append("# 楽園蒲田店 DD×末尾 / DD×端番 交互作用分析")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- 期間: {frame['date_dt'].min().date()} から {frame['date_dt'].max().date()} まで")
    lines.append(f"- 行数: {len(frame):,}")
    lines.append(f"- イベント日: `event_dds = {sorted(EVENT_DDS)}` + `use_strong_mmdd = true`")
    lines.append(f"- セグメント有効条件: ユニーク台数 >= {DEFAULT_MIN_SEGMENT_MACHINES}")
    lines.append(f"- 末尾: `last_digit`, 端番: `hanaban = min(rank_from_min, rank_from_max)`")
    lines.append("- KW効果量: ε² = H / (n - 1)")
    lines.append("")
    lines.append("### セグメント台数")
    lines.append(_markdown_table(segment_counts, float_digits=4))
    lines.append("")
    lines.append("### 本館/新館 floor 分割判定")
    lines.append(_markdown_table(floor_judgement, float_digits=6))
    lines.append("")
    lines.append("- 本館_N は 1F/2F/3F の差が大きいため分割を採用した。")
    lines.append("- 新館_N は p は有意でも epsilon^2 が極小なので、1F+2F を統合したまま維持した。")
    lines.append("- 本館1F_N は 21 台で 50 台基準未満のため、統計解釈は参考値として扱う。")
    lines.append("")
    if valid_segments:
        lines.append(f"### 有効セグメント: {', '.join(valid_segments)}")
    else:
        lines.append("### 有効セグメント: No valid segments")
    lines.append("")

    def render_axis_section(result_heading: str, segment_heading: str, analysis: AxisAnalysis) -> list[str]:
        block: list[str] = []
        block.append(f"## {result_heading}")
        block.append("**avg_diff matrix**")
        block.append(
            _markdown_table(analysis.all_matrix_avg.reset_index().rename(columns={"index": "dd"}), float_digits=4)
        )
        block.append("")
        block.append("**hit104_rate matrix**")
        block.append(
            _markdown_table(analysis.all_matrix_hit.reset_index().rename(columns={"index": "dd"}), float_digits=4)
        )
        block.append("")
        block.append("**DD別 top axis**")
        block.append(_markdown_table(analysis.best_all, float_digits=4))
        block.append("")
        block.append("**DD別 KW検定**")
        block.append(_markdown_table(analysis.kw_all, float_digits=6))
        block.append("")

        block.append(f"## {segment_heading}")
        block.append("**segment別 pairwise rank stability**")
        block.append(_markdown_table(analysis.pair_segment, float_digits=4))
        block.append("")
        block.append("**segment別 top axis / event diversity**")
        block.append(
            _markdown_table(_segment_contrast_summary(analysis.pair_segment, analysis.best_segment), float_digits=4)
        )
        block.append("")
        focus_segments = ["本館1F_N", "本館2F_N", "本館3F_N"]
        focus_pair = analysis.pair_segment.loc[analysis.pair_segment["segment"].isin(focus_segments)].copy()
        if not focus_pair.empty:
            block.append("**本館フロア比較**")
            block.append(
                _markdown_table(
                    focus_pair.loc[
                        :,
                        [
                            "segment",
                            "axis",
                            "pair_type",
                            "pairs",
                            "mean_spearman_rho",
                            "top1_match_rate",
                            "mean_shared_axes",
                        ],
                    ],
                    float_digits=4,
                )
            )
            block.append("")
        block.append("**segment別 DD top axis**")
        block.append(_markdown_table(analysis.best_segment, float_digits=4))
        block.append("")
        block.append("**segment別 KW検定**")
        block.append(_markdown_table(analysis.kw_segment, float_digits=6))
        block.append("")
        return block

    lines.extend(
        render_axis_section(
            "2. DD×末尾: 全体結果",
            "3. DD×末尾: セグメント別・交互作用の有無",
            lastdigit,
        )
    )
    lines.extend(
        render_axis_section(
            "4. DD×端番: 全体結果",
            "5. DD×端番: セグメント別・交互作用の有無",
            hanaban,
        )
    )

    lines.append("## 6. イベント日 vs 非イベント日での比較")
    lines.append("### 末尾")
    lines.append(_markdown_table(_event_comparison_table(lastdigit.pair_all), float_digits=4))
    lines.append("")
    lines.append("### 端番")
    lines.append(_markdown_table(_event_comparison_table(hanaban.pair_all), float_digits=4))
    lines.append("")

    lines.append("## 7. 結論（真の交互作用は存在するか、それとも周辺効果の重ね合わせか）")
    lastdigit_event = lastdigit.pair_all[lastdigit.pair_all["pair_type"].eq("event-event")]["mean_spearman_rho"].mean()
    lastdigit_non = lastdigit.pair_all[lastdigit.pair_all["pair_type"].eq("non-event")]["mean_spearman_rho"].mean()
    hanaban_event = hanaban.pair_all[hanaban.pair_all["pair_type"].eq("event-event")]["mean_spearman_rho"].mean()
    hanaban_non = hanaban.pair_all[hanaban.pair_all["pair_type"].eq("non-event")]["mean_spearman_rho"].mean()
    lines.append(
        f"- 末尾: event-event の平均順位相関={_format_value(lastdigit_event, digits=3)}, "
        f"non-event={_format_value(lastdigit_non, digits=3)}"
    )
    lines.append(
        f"- 端番: event-event の平均順位相関={_format_value(hanaban_event, digits=3)}, "
        f"non-event={_format_value(hanaban_non, digits=3)}"
    )
    if pd.notna(lastdigit_event) and pd.notna(lastdigit_non) and pd.notna(hanaban_event) and pd.notna(hanaban_non):
        if (lastdigit_event < lastdigit_non) or (hanaban_event < hanaban_non):
            lines.append("- 暫定判定: 真の交互作用の兆候がある")
        else:
            lines.append("- 暫定判定: 周辺効果の重ね合わせが主")
    else:
        lines.append("- 暫定判定: 交互作用判定に十分な比較が確保できませんでした")
    lines.append("")
    lines.append("## 8. セグメント別のDD×末尾/端番KW検定")
    lines.append("- 5セグメントに加えて全体も含めた6区分で、DDごとのKW検定とε²を見直した。")
    lines.append("- ここでは p値だけで二分せず、ε²が相対的に大きいDDとセグメント間の一貫性を重視した。")
    lines.append("- 本館1F_N は少数セグメントなので参考扱いだが、除外せずに掲載する。")
    lines.append("")
    lines.extend(_segment_kw_section("8.1 末尾のセグメント別KW", lastdigit))
    lines.extend(_segment_kw_section("8.2 端番のセグメント別KW", hanaban))
    lines.append("### 8.3 セグメント横断の見取り図")
    lines.append(
        "- `DD別の勝ちセグメント` で `sig_segment_count` が2以上のDDは、複数セグメントで同方向の差が反復している候補として見る。"
    )
    lines.append("- `全体では見えにくかったDD` に残る行は、全体プールだと希釈されるが、セグメントを切ると浮く候補。")
    lines.append("- 末尾/端番の両軸で同じDDが上位に残るかを合わせて見ると、単発ではなく構造的な偏りかを判断しやすい。")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_outputs(db_path: Path, output_dir: Path, *, min_n: int) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    frame = _prepare_frame(db_path)
    segment_counts = _segment_machine_counts(frame)
    valid_segments = _valid_segments(frame)
    floor_judgement = _floor_split_judgement(frame)

    lastdigit = _build_axis_analysis(
        frame, axis_name="last_digit", axis_spec=AXIS_SPECS["last_digit"], valid_segments=valid_segments, min_n=min_n
    )
    hanaban = _build_axis_analysis(
        frame, axis_name="hanaban", axis_spec=AXIS_SPECS["hanaban"], valid_segments=valid_segments, min_n=min_n
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(
        lastdigit.all_summary.loc[
            :, ["segment", "axis", "dd", "last_digit", "n", "avg_diff", "hit104_rate", "is_event_day"]
        ],
        output_dir / "dd_lastdigit_matrix_all.csv",
    )
    _write_csv(
        lastdigit.segment_summary.loc[
            :, ["segment", "axis", "dd", "last_digit", "n", "avg_diff", "hit104_rate", "is_event_day"]
        ],
        output_dir / "dd_lastdigit_matrix_by_segment.csv",
    )
    _write_csv(
        hanaban.all_summary.loc[
            :, ["segment", "axis", "dd", "hanaban", "n", "avg_diff", "hit104_rate", "is_event_day"]
        ],
        output_dir / "dd_hanaban_matrix_all.csv",
    )
    _write_csv(
        hanaban.segment_summary.loc[
            :, ["segment", "axis", "dd", "hanaban", "n", "avg_diff", "hit104_rate", "is_event_day"]
        ],
        output_dir / "dd_hanaban_matrix_by_segment.csv",
    )
    lastdigit_kw = _ordered_kw_table(pd.concat([lastdigit.kw_segment, lastdigit.kw_all], ignore_index=True))
    hanaban_kw = _ordered_kw_table(pd.concat([hanaban.kw_segment, hanaban.kw_all], ignore_index=True))
    _write_csv(lastdigit_kw, output_dir / "lastdigit_kw_significance.csv")
    _write_csv(hanaban_kw, output_dir / "hanaban_kw_significance.csv")

    report = _build_report(
        db_path=db_path,
        frame=frame,
        segment_counts=segment_counts,
        floor_judgement=floor_judgement,
        valid_segments=valid_segments,
        lastdigit=lastdigit,
        hanaban=hanaban,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return lastdigit_kw, hanaban_kw, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rakuen Kamata DD x last_digit / hanaban interaction analysis")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--min-n", type=int, default=DEFAULT_MIN_CELL_N, help="Minimum cell sample count")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not load_hall_config("rakuen"):
        raise ValueError("rakuen hall config is missing or invalid")
    db_path = Path(args.db_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    lastdigit_kw, hanaban_kw, report = build_outputs(db_path, Path(args.output_dir), min_n=int(args.min_n))
    print(f"[OK] lastdigit_kw rows: {len(lastdigit_kw)}")
    print(f"[OK] hanaban_kw rows: {len(hanaban_kw)}")
    print(f"[OK] report saved: {Path(args.output_dir) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
