from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import chi2_contingency, kruskal

from eda.core import _epsilon_squared
from eda.machine_axis_pattern_scan import DD_BIN_EDGES
from eda.machine_name_significance_scan import _cramers_v_bias_corrected


INTERACTION_AXIS_OPTIONS = [
    "segment",
    "dd",
    "dd_bin",
    "hanaban_min",
    "hanaban_max",
    "kakuban",
    "machine_tail",
    "event_day",
    "family",
    "section",
    "machine_name",
    "machine_name_current",
]
INTERACTION_METRIC_OPTIONS = ["avg_diff", "win_rate", "hit104_rate"]
DEFAULT_EFFECT_SIZE_THRESHOLD = 0.1
DEFAULT_MIN_CELL_N = 5
DEFAULT_SOURCE = "document/plans/2026-07-10-dashboard-refactoring-plan.md#phase-3"

DD_BIN_LABELS = [label for _, _, label in DD_BIN_EDGES]


@dataclass(frozen=True)
class InteractionPairStats:
    axis_a: str
    axis_b: str
    metric: str
    test: str
    statistic: float
    p_value: float
    effect_size: float
    n_groups: int
    n_obs: int
    n_sparse_groups: int
    sparse_warning: bool
    note: str


def attach_interaction_axes(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the auxiliary axes used by the explorer UI."""

    if frame.empty:
        return frame.copy()

    work = frame.copy()
    if "dd" in work.columns and "dd_bin" not in work.columns:
        dd = pd.to_numeric(work["dd"], errors="coerce")
        work["dd_bin"] = pd.cut(
            dd,
            bins=[0, 7, 14, 21, 28, 31],
            labels=DD_BIN_LABELS,
            include_lowest=True,
            right=True,
            ordered=True,
        )
    if "machine_number" in work.columns and "machine_tail" not in work.columns:
        work["machine_tail"] = pd.to_numeric(work["machine_number"], errors="coerce").mod(10).astype("Int64")
    if "is_event_day" in work.columns and "event_day" not in work.columns:
        work["event_day"] = work["is_event_day"].fillna(False).astype(bool)
    return work


def axis_series(frame: pd.DataFrame, axis: str) -> pd.Series:
    if axis not in INTERACTION_AXIS_OPTIONS:
        raise KeyError(axis)

    if axis == "segment":
        return frame.get("segment", pd.Series(index=frame.index, dtype="object")).fillna("unknown").astype("string")
    if axis == "dd":
        source = frame.get("dd", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce").astype("Int64")
    if axis == "dd_bin":
        if "dd_bin" in frame.columns:
            series = frame["dd_bin"]
            return series.astype("string").fillna("unknown")
        dd = pd.to_numeric(frame.get("dd"), errors="coerce")
        return pd.cut(
            dd,
            bins=[0, 7, 14, 21, 28, 31],
            labels=DD_BIN_LABELS,
            include_lowest=True,
            right=True,
            ordered=True,
        ).astype("string")
    if axis == "hanaban_min":
        source = frame.get("rank_from_min", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce").astype("Int64")
    if axis == "hanaban_max":
        source = frame.get("rank_from_max", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce").astype("Int64")
    if axis == "kakuban":
        source = frame.get("kakuban", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce").astype("Int64")
    if axis == "machine_tail":
        if "machine_tail" in frame.columns:
            return pd.to_numeric(frame["machine_tail"], errors="coerce").astype("Int64")
        source = frame.get("machine_number", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce").mod(10).astype("Int64")
    if axis == "event_day":
        if "event_day" in frame.columns:
            return frame["event_day"].fillna(False).astype(bool)
        return frame.get("is_event_day", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    if axis == "family":
        return frame.get("family", pd.Series(index=frame.index, dtype="object")).fillna("N").astype("string")
    if axis == "section":
        return frame.get("section", pd.Series(index=frame.index, dtype="object")).fillna("不明").astype("string")
    if axis == "machine_name":
        return frame.get("machine_name", pd.Series(index=frame.index, dtype="object")).fillna("不明").astype("string")
    if axis == "machine_name_current":
        names = frame.get("machine_name", pd.Series(index=frame.index, dtype="object"))
        dates = frame.get("date_dt", pd.Series(pd.NaT, index=frame.index))
        latest_date = dates.max()
        if pd.isna(latest_date):
            return pd.Series(pd.NA, index=frame.index, dtype="string")
        current_names = set(names.loc[dates.eq(latest_date)].dropna().unique())
        return names.where(names.isin(current_names)).astype("string")
    raise KeyError(axis)


def sorted_axis_values(values: pd.Series, axis: str) -> list[object]:
    observed = pd.Series(values.dropna().tolist())
    if observed.empty:
        return []
    if axis in {"dd", "hanaban_min", "hanaban_max", "kakuban", "machine_tail"}:
        numeric = pd.to_numeric(observed, errors="coerce").dropna().astype(int)
        return sorted(numeric.unique().tolist())
    if axis == "dd_bin":
        order = {name: idx for idx, name in enumerate(DD_BIN_LABELS)}
        return sorted(observed.unique().tolist(), key=lambda value: (order.get(str(value), 99), str(value)))
    if axis == "event_day":
        return [False, True]
    return sorted(observed.astype(str).unique().tolist())


def metric_series(frame: pd.DataFrame, metric: str) -> pd.Series:
    if metric == "avg_diff":
        source = frame.get("diff_coins_normalized", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce")
    if metric == "win_rate":
        source = pd.to_numeric(
            frame.get("diff_coins_normalized", pd.Series(np.nan, index=frame.index)), errors="coerce"
        )
        return source.gt(0).astype(float).where(source.notna())
    if metric == "hit104_rate":
        source = frame.get("hit104", pd.Series(np.nan, index=frame.index))
        return pd.to_numeric(source, errors="coerce")
    raise KeyError(metric)


def summarize_cells(
    frame: pd.DataFrame,
    axes: list[str],
    *,
    metric: str,
    facet_axis: str | None = None,
) -> pd.DataFrame:
    if frame.empty or len(axes) not in {2, 3}:
        return pd.DataFrame()

    work = frame.copy()
    for axis in axes + ([facet_axis] if facet_axis else []):
        if axis is None or axis in INTERACTION_AXIS_OPTIONS:
            continue
        raise KeyError(axis)

    axis_columns = axes + ([facet_axis] if facet_axis else [])
    value_columns = [f"_{axis}" for axis in axis_columns]
    for axis, col in zip(axis_columns, value_columns, strict=True):
        work[col] = axis_series(work, axis)

    group_cols = value_columns
    grouped = (
        work.groupby(group_cols, dropna=False)
        .agg(
            n=("machine_number", "size"),
            avg_diff=("diff_coins_normalized", "mean"),
            win_rate=(
                "diff_coins_normalized",
                lambda s: (
                    float(pd.to_numeric(s, errors="coerce").dropna().gt(0).mean())
                    if pd.to_numeric(s, errors="coerce").notna().any()
                    else np.nan
                ),
            ),
            hit104_rate=(
                "hit104",
                lambda s: float(pd.to_numeric(s, errors="coerce").dropna().mean()) if s.notna().any() else np.nan,
            ),
        )
        .reset_index()
    )
    grouped["metric_value"] = pd.to_numeric(grouped[metric], errors="coerce")
    grouped["axes"] = [tuple(axis_columns)] * len(grouped)
    rename_map = {col: axis for col, axis in zip(value_columns, axis_columns, strict=True)}
    grouped = grouped.rename(columns=rename_map)
    return grouped.sort_values(["metric_value", "n"], ascending=[False, False], kind="mergesort").reset_index(drop=True)


def run_pairwise_axis_test(
    frame: pd.DataFrame,
    axis_a: str,
    axis_b: str,
    *,
    metric: str,
    min_n: int = DEFAULT_MIN_CELL_N,
) -> InteractionPairStats:
    if frame.empty:
        return InteractionPairStats(
            axis_a, axis_b, metric, "kruskal", np.nan, np.nan, np.nan, 0, 0, 0, False, "empty frame"
        )

    work = frame.copy()
    work["_axis_a"] = axis_series(work, axis_a)
    work["_axis_b"] = axis_series(work, axis_b)
    cell_sizes = work.groupby(["_axis_a", "_axis_b"], dropna=False).size()
    sparse_groups = int((cell_sizes < int(min_n)).sum())

    if metric == "avg_diff":
        groups: list[np.ndarray] = []
        for _, cell in work.groupby(["_axis_a", "_axis_b"], dropna=False):
            values = pd.to_numeric(cell["diff_coins_normalized"], errors="coerce").dropna().to_numpy()
            if len(values) >= int(min_n):
                groups.append(values)
        n_obs = int(sum(len(group) for group in groups))
        if len(groups) < 2:
            note = "fewer than two groups with n>=min_n"
            return InteractionPairStats(
                axis_a,
                axis_b,
                metric,
                "kruskal",
                np.nan,
                np.nan,
                np.nan,
                len(groups),
                n_obs,
                sparse_groups,
                sparse_groups > 0,
                note,
            )

        statistic, p_value = kruskal(*groups)
        effect_size = _epsilon_squared(float(statistic), len(groups), n_obs)
        return InteractionPairStats(
            axis_a=axis_a,
            axis_b=axis_b,
            metric=metric,
            test="kruskal",
            statistic=float(statistic),
            p_value=float(p_value),
            effect_size=float(effect_size),
            n_groups=len(groups),
            n_obs=n_obs,
            n_sparse_groups=sparse_groups,
            sparse_warning=sparse_groups > 0,
            note="",
        )

    outcome = metric_series(work, metric)
    contingency = pd.crosstab([work["_axis_a"], work["_axis_b"]], outcome)
    contingency = contingency.reindex(columns=[0.0, 1.0], fill_value=0)
    n_obs = int(contingency.to_numpy().sum())
    if contingency.empty or contingency.shape[0] < 2 or contingency.shape[1] < 2 or n_obs == 0:
        return InteractionPairStats(
            axis_a,
            axis_b,
            metric,
            "chi2",
            np.nan,
            np.nan,
            np.nan,
            int(contingency.shape[0]),
            n_obs,
            sparse_groups,
            sparse_groups > 0,
            "insufficient contingency table",
        )

    if (contingency.sum(axis=0) == 0).any() or (contingency.sum(axis=1) == 0).any():
        return InteractionPairStats(
            axis_a,
            axis_b,
            metric,
            "chi2",
            np.nan,
            np.nan,
            np.nan,
            int(contingency.shape[0]),
            n_obs,
            sparse_groups,
            sparse_groups > 0,
            "insufficient contingency table",
        )

    chi2, p_value, _, expected = chi2_contingency(contingency, correction=False)
    sparse_ratio = float((expected < 5).mean())
    note = ""
    if sparse_ratio > 0.2:
        note = f"warning: {sparse_ratio:.1%} of expected cells are below 5"
    effect_size = _cramers_v_bias_corrected(float(chi2), n_obs, contingency.shape[0], contingency.shape[1])
    return InteractionPairStats(
        axis_a=axis_a,
        axis_b=axis_b,
        metric=metric,
        test="chi2",
        statistic=float(chi2),
        p_value=float(p_value),
        effect_size=float(effect_size),
        n_groups=int(contingency.shape[0]),
        n_obs=n_obs,
        n_sparse_groups=sparse_groups,
        sparse_warning=(sparse_ratio > 0.2) or (sparse_groups > 0),
        note=note,
    )


def build_claim_draft(
    row: pd.Series,
    *,
    hall_key: str,
    metric: str,
    source: str = DEFAULT_SOURCE,
    last_reviewed: str,
) -> str:
    axes = [value for value in row.get("axes", []) if isinstance(value, str)]
    segment: dict[str, Any] = {}
    for axis in axes:
        value = row.get(axis)
        if axis == "dd_bin":
            text = str(value)
            if text in DD_BIN_LABELS:
                index = DD_BIN_LABELS.index(text)
                lo, hi, _ = DD_BIN_EDGES[index]
                segment["dd"] = list(range(int(lo), int(hi) + 1))
            else:
                segment["dd_bin"] = [text]
        elif axis == "event_day":
            segment["event_day"] = bool(value)
        elif axis in {"dd", "hanaban_min", "hanaban_max", "kakuban", "machine_tail"}:
            try:
                segment_key = {"hanaban_min": "rank_from_min", "hanaban_max": "rank_from_max"}.get(axis, axis)
                segment[segment_key] = [int(value)]
            except Exception:
                segment_key = {"hanaban_min": "rank_from_min", "hanaban_max": "rank_from_max"}.get(axis, axis)
                segment[segment_key] = [value]
        elif axis == "segment":
            segment["segment"] = [str(value)]
        elif axis == "family":
            segment["family"] = [str(value)]
        elif axis == "section":
            segment["section"] = [str(value)]
        elif axis == "machine_name":
            segment["machine_name"] = [str(value)]
        elif axis == "machine_name_current":
            segment["machine_name"] = [str(value)]
        else:
            segment[axis] = [value]

    delta = pd.to_numeric(pd.Series([row.get("delta", np.nan)]), errors="coerce").iloc[0]
    if pd.notna(delta):
        direction = "up" if float(delta) >= 0 else "down"
    elif metric == "avg_diff":
        direction = "up" if float(row.get(metric, np.nan)) >= 0 else "down"
    else:
        overall = float(row.get("overall_metric", np.nan))
        current = float(row.get(metric, np.nan))
        direction = "up" if pd.notna(current) and pd.notna(overall) and current >= overall else "down"

    claim = {
        "id": row.get("claim_id", f"{hall_key}-{metric}-{int(row.get('n', 0))}"),
        "title": row.get("claim_title", f"{hall_key} {metric} interaction"),
        "status": "watching",
        "segment": segment,
        "metric": metric,
        "direction": direction,
        "baseline": "hall_all",
        "min_n": int(row.get("min_n", DEFAULT_MIN_CELL_N)),
        "source": source,
        "last_reviewed": last_reviewed,
    }
    return yaml.safe_dump(claim, sort_keys=False, allow_unicode=True)
