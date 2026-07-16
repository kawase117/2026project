from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.utils.interaction_analysis import attach_interaction_axes  # noqa: E402
from dashboard.utils.theory_engine import filter_theory_frame, load_hall_config, load_theory_frame, summarize_by  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "results" / "rakuen_event_vs_nonevent_tail_hanaban"
DEFAULT_MIN_CELL_N = 5
DEFAULT_MIN_GAMES = 2000
SEGMENT_ORDER = ["本館_A", "本館1F_N", "本館2F_N", "本館3F_N", "新館_N"]
SEGMENT_ORDER = ["本館_A", "本館_N", "新館_N"]
EVENT_LABEL = "event"
NON_EVENT_LABEL = "non_event"
SEGMENT_ORDER = ["本館_A", "本館1F_N", "本館2F_N", "本館3F_N", "新館_N"]

AXES = {
    "lastdigit": {
        "column": "machine_tail",
        "label": "末尾",
        "file_prefix": "lastdigit",
    },
    "hanaban": {
        "column": "hanaban",
        "label": "端番(対称版)",
        "file_prefix": "hanaban",
    },
    "hanaban_min": {
        "column": "rank_from_min",
        "label": "hanaban_min(非対称版)",
        "file_prefix": "hanaban_min",
    },
}


@dataclass(frozen=True)
class AxisOutputs:
    axis_name: str
    axis_label: str
    summary: pd.DataFrame
    kw_by_eventtype: pd.DataFrame
    rank_correlation: pd.DataFrame
    watching_candidates: pd.DataFrame


def _format_value(value: object, *, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, bool):
        return "true" if value else "false"
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


def _safe_sign(value: object) -> int:
    if value is None or pd.isna(value):
        return 0
    numeric = float(value)
    if math.isclose(numeric, 0.0, abs_tol=1e-12):
        return 0
    return 1 if numeric > 0 else -1


def _safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    valid = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(valid) < 2:
        return float("nan"), float("nan")
    if valid["x"].nunique() < 2 or valid["y"].nunique() < 2:
        return float("nan"), float("nan")
    rho, p_value = spearmanr(valid["x"], valid["y"])
    if pd.isna(rho):
        return float("nan"), float("nan")
    return float(rho), float(p_value)


def _prepare_frame(db_path: Path, *, min_games: int) -> pd.DataFrame:
    frame = load_theory_frame(db_path)
    if frame.empty:
        raise ValueError(f"failed to load theory frame from {db_path}")

    work = filter_theory_frame(frame, min_games=int(min_games))
    if work.empty:
        raise ValueError(f"no rows left after applying games_normalized >= {min_games}")

    work = attach_interaction_axes(work)
    work["segment"] = work["segment"].fillna("unknown").astype(str)
    work["event_type"] = np.where(work["event_day"].fillna(False).astype(bool), EVENT_LABEL, NON_EVENT_LABEL)
    work["machine_tail"] = pd.to_numeric(work["machine_tail"], errors="coerce").astype("Int64")
    work["rank_from_min"] = pd.to_numeric(work["rank_from_min"], errors="coerce").astype("Int64")
    work["hanaban"] = pd.to_numeric(work["hanaban"], errors="coerce").astype("Int64")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["hit104"] = pd.to_numeric(work["hit104"], errors="coerce")
    work = work.dropna(subset=["diff_coins_normalized", "games_normalized"]).reset_index(drop=True)
    return work


def _summarize_axis_scope(
    frame: pd.DataFrame, axis_column: str, *, scope: str, event_type: str, min_n: int
) -> pd.DataFrame:
    subset = frame.loc[frame["event_type"].eq(event_type)].copy()
    if subset.empty or axis_column not in subset.columns:
        return pd.DataFrame()
    summary = summarize_by(subset, [axis_column], min_n=min_n)
    if summary.empty:
        return summary
    summary = summary.copy()
    summary = summary.rename(columns={axis_column: "level"})
    summary["scope"] = scope
    summary["event_type"] = event_type
    summary["axis"] = axis_column
    summary["level"] = pd.to_numeric(summary["level"], errors="coerce").astype("Int64")
    summary = summary.dropna(subset=["level"]).copy()
    if summary.empty:
        return summary
    summary["level"] = summary["level"].astype(int)
    summary["avg_diff_rank"] = summary["avg_diff"].rank(method="average", ascending=False)
    summary["hit104_rank"] = summary["hit104_rate"].rank(method="average", ascending=False)
    summary = summary.sort_values(
        ["avg_diff", "hit104_rate", "n", "level"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    summary["sort_rank"] = np.arange(1, len(summary) + 1, dtype=int)
    return summary.loc[
        :,
        [
            "scope",
            "event_type",
            "axis",
            "level",
            "n",
            "avg_diff",
            "hit104_rate",
            "avg_games",
            "win_rate",
            "avg_diff_rank",
            "hit104_rank",
            "sort_rank",
        ],
    ]


def _summarize_scope(frame: pd.DataFrame, axis_column: str, *, scope: str, min_n: int) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for event_type in [EVENT_LABEL, NON_EVENT_LABEL]:
        summary = _summarize_axis_scope(frame, axis_column, scope=scope, event_type=event_type, min_n=min_n)
        if not summary.empty:
            parts.append(summary)
    if not parts:
        return pd.DataFrame(
            columns=[
                "scope",
                "event_type",
                "axis",
                "level",
                "n",
                "avg_diff",
                "hit104_rate",
                "avg_games",
                "win_rate",
                "avg_diff_rank",
                "hit104_rank",
                "sort_rank",
            ]
        )
    return pd.concat(parts, ignore_index=True)


def _kw_row(
    frame: pd.DataFrame, axis_column: str, *, scope: str, event_type: str, min_n: int
) -> dict[str, object] | None:
    subset = frame.loc[frame["event_type"].eq(event_type)].copy()
    if subset.empty or axis_column not in subset.columns:
        return None
    groups: list[np.ndarray] = []
    level_count = 0
    for level, group in subset.groupby(axis_column, dropna=False):
        if pd.isna(level):
            continue
        values = pd.to_numeric(group["diff_coins_normalized"], errors="coerce").dropna().to_numpy()
        if len(values) < int(min_n):
            continue
        groups.append(values)
        level_count += 1
    if len(groups) < 2:
        return None
    try:
        statistic, p_value = kruskal(*groups)
    except ValueError:
        return None
    n_samples = int(sum(len(values) for values in groups))
    if n_samples <= 1:
        return None
    epsilon_sq = float(statistic / (n_samples - 1))
    return {
        "scope": scope,
        "event_type": event_type,
        "axis": axis_column,
        "n_levels": int(level_count),
        "n_samples": n_samples,
        "statistic": float(statistic),
        "p_value": float(p_value),
        "epsilon_sq": epsilon_sq,
    }


def _kw_by_eventtype(frame: pd.DataFrame, axis_column: str, *, scope: str, min_n: int) -> pd.DataFrame:
    rows = []
    for event_type in [EVENT_LABEL, NON_EVENT_LABEL]:
        row = _kw_row(frame, axis_column, scope=scope, event_type=event_type, min_n=min_n)
        if row is not None:
            rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=["scope", "event_type", "axis", "n_levels", "n_samples", "statistic", "p_value", "epsilon_sq"]
        )
    return pd.DataFrame(rows).sort_values(["scope", "event_type"], kind="mergesort").reset_index(drop=True)


def _rank_correlation(
    event_summary: pd.DataFrame, nonevent_summary: pd.DataFrame, *, scope: str, axis: str
) -> dict[str, object]:
    if event_summary.empty or nonevent_summary.empty:
        return {
            "scope": scope,
            "axis": axis,
            "n_event_levels": int(event_summary["level"].nunique()) if not event_summary.empty else 0,
            "n_nonevent_levels": int(nonevent_summary["level"].nunique()) if not nonevent_summary.empty else 0,
            "n_shared_levels": 0,
            "spearman_rho": float("nan"),
            "spearman_p_value": float("nan"),
            "top1_event_level": "",
            "top1_nonevent_level": "",
            "top1_match": False,
            "mean_abs_rank_shift": float("nan"),
        }

    event_ranked = event_summary.loc[:, ["level", "avg_diff_rank", "sort_rank", "avg_diff", "hit104_rate"]].copy()
    nonevent_ranked = nonevent_summary.loc[:, ["level", "avg_diff_rank", "sort_rank", "avg_diff", "hit104_rate"]].copy()
    merged = event_ranked.merge(
        nonevent_ranked,
        on="level",
        how="inner",
        suffixes=("_event", "_non_event"),
    )
    if merged.empty:
        return {
            "scope": scope,
            "axis": axis,
            "n_event_levels": int(event_summary["level"].nunique()),
            "n_nonevent_levels": int(nonevent_summary["level"].nunique()),
            "n_shared_levels": 0,
            "spearman_rho": float("nan"),
            "spearman_p_value": float("nan"),
            "top1_event_level": int(event_summary.iloc[0]["level"]) if not event_summary.empty else "",
            "top1_nonevent_level": int(nonevent_summary.iloc[0]["level"]) if not nonevent_summary.empty else "",
            "top1_match": False,
            "mean_abs_rank_shift": float("nan"),
        }

    rho, p_value = _safe_spearman(merged["avg_diff_rank_event"], merged["avg_diff_rank_non_event"])
    top1_event_level = int(event_summary.iloc[0]["level"])
    top1_nonevent_level = int(nonevent_summary.iloc[0]["level"])
    mean_abs_rank_shift = float((merged["avg_diff_rank_event"] - merged["avg_diff_rank_non_event"]).abs().mean())
    return {
        "scope": scope,
        "axis": axis,
        "n_event_levels": int(event_summary["level"].nunique()),
        "n_nonevent_levels": int(nonevent_summary["level"].nunique()),
        "n_shared_levels": int(len(merged)),
        "spearman_rho": rho,
        "spearman_p_value": p_value,
        "top1_event_level": top1_event_level,
        "top1_nonevent_level": top1_nonevent_level,
        "top1_match": bool(top1_event_level == top1_nonevent_level),
        "mean_abs_rank_shift": mean_abs_rank_shift,
    }


def _build_delta_table(
    event_summary: pd.DataFrame,
    nonevent_summary: pd.DataFrame,
    *,
    scope: str,
    axis_name: str,
) -> pd.DataFrame:
    if event_summary.empty or nonevent_summary.empty:
        return pd.DataFrame(
            columns=[
                "axis",
                "scope",
                "level",
                "event_avg_diff",
                "non_event_avg_diff",
                "delta_avg_diff",
                "event_hit104_rate",
                "non_event_hit104_rate",
                "delta_hit104_rate",
                "event_n",
                "non_event_n",
                "total_n",
                "event_avg_rank",
                "non_event_avg_rank",
                "rank_shift",
            ]
        )

    merged = event_summary.merge(
        nonevent_summary,
        on="level",
        how="inner",
        suffixes=("_event", "_non_event"),
    )
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "axis",
                "scope",
                "level",
                "event_avg_diff",
                "non_event_avg_diff",
                "delta_avg_diff",
                "event_hit104_rate",
                "non_event_hit104_rate",
                "delta_hit104_rate",
                "event_n",
                "non_event_n",
                "total_n",
                "event_avg_rank",
                "non_event_avg_rank",
                "rank_shift",
            ]
        )
    merged["axis"] = axis_name
    merged["scope"] = scope
    merged["event_avg_diff"] = merged["avg_diff_event"]
    merged["non_event_avg_diff"] = merged["avg_diff_non_event"]
    merged["delta_avg_diff"] = merged["event_avg_diff"] - merged["non_event_avg_diff"]
    merged["event_hit104_rate"] = merged["hit104_rate_event"]
    merged["non_event_hit104_rate"] = merged["hit104_rate_non_event"]
    merged["delta_hit104_rate"] = merged["event_hit104_rate"] - merged["non_event_hit104_rate"]
    merged["event_n"] = merged["n_event"]
    merged["non_event_n"] = merged["n_non_event"]
    merged["total_n"] = merged["event_n"] + merged["non_event_n"]
    merged["event_avg_rank"] = merged["avg_diff_rank_event"]
    merged["non_event_avg_rank"] = merged["avg_diff_rank_non_event"]
    merged["rank_shift"] = (merged["event_avg_rank"] - merged["non_event_avg_rank"]).abs()
    return (
        merged.loc[
            :,
            [
                "axis",
                "scope",
                "level",
                "event_avg_diff",
                "non_event_avg_diff",
                "delta_avg_diff",
                "event_hit104_rate",
                "non_event_hit104_rate",
                "delta_hit104_rate",
                "event_n",
                "non_event_n",
                "total_n",
                "event_avg_rank",
                "non_event_avg_rank",
                "rank_shift",
            ],
        ]
        .sort_values(["delta_avg_diff", "level"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )


def _segment_consistency(delta_table: pd.DataFrame, segment_deltas: pd.DataFrame) -> pd.DataFrame:
    if delta_table.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    segment_names = [segment for segment in SEGMENT_ORDER if segment in set(segment_deltas["scope"].unique())]
    if not segment_names and not segment_deltas.empty:
        segment_names = sorted(
            [scope for scope in segment_deltas["scope"].dropna().unique().tolist() if scope != "all"]
        )
    for _, row in delta_table.iterrows():
        axis = str(row["axis"])
        level = int(row["level"])
        subset = segment_deltas.loc[(segment_deltas["axis"].eq(axis)) & (segment_deltas["level"].eq(level))].copy()
        subset = subset.loc[subset["scope"].isin(segment_names)].copy()
        subset = subset.dropna(subset=["delta_avg_diff"])
        if subset.empty:
            rows.append(
                {
                    "axis": axis,
                    "level": level,
                    "segment_total_count": 0,
                    "segment_same_sign_count": 0,
                    "segment_same_sign_rate": float("nan"),
                    "segment_consistency": "insufficient",
                    "segment_deltas": "",
                }
            )
            continue
        overall_sign = _safe_sign(row["delta_avg_diff"])
        if overall_sign == 0:
            same_sign = int(subset["delta_avg_diff"].apply(_safe_sign).eq(0).sum())
        else:
            same_sign = int(subset["delta_avg_diff"].apply(_safe_sign).eq(overall_sign).sum())
        detail = "; ".join(
            f"{scope}:{_format_value(delta, digits=2)}"
            for scope, delta in zip(subset["scope"], subset["delta_avg_diff"], strict=True)
        )
        rows.append(
            {
                "axis": axis,
                "level": level,
                "segment_total_count": int(len(subset)),
                "segment_same_sign_count": same_sign,
                "segment_same_sign_rate": float(same_sign / len(subset)) if len(subset) else float("nan"),
                "segment_consistency": f"{same_sign}/{len(subset)} same sign",
                "segment_deltas": detail,
            }
        )
    return pd.DataFrame(rows)


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


def _build_axis_outputs(
    frame: pd.DataFrame, *, axis_name: str, axis_spec: dict[str, object], min_n: int
) -> AxisOutputs:
    axis_column = str(axis_spec["column"])
    axis_label = str(axis_spec["label"])

    summary_parts: list[pd.DataFrame] = []
    kw_parts: list[pd.DataFrame] = []
    rank_rows: list[dict[str, object]] = []
    delta_rows: list[pd.DataFrame] = []

    scope_order = ["all", *SEGMENT_ORDER]
    for scope in scope_order:
        scope_frame = frame if scope == "all" else frame.loc[frame["segment"].eq(scope)].copy()
        if scope_frame.empty:
            continue
        scope_summary = _summarize_scope(scope_frame, axis_column, scope=scope, min_n=min_n)
        if not scope_summary.empty:
            summary_parts.append(scope_summary)
        scope_kw = _kw_by_eventtype(scope_frame, axis_column, scope=scope, min_n=min_n)
        if not scope_kw.empty:
            kw_parts.append(scope_kw)

        event_summary = (
            scope_summary.loc[scope_summary["event_type"].eq(EVENT_LABEL)].copy()
            if not scope_summary.empty
            else pd.DataFrame()
        )
        nonevent_summary = (
            scope_summary.loc[scope_summary["event_type"].eq(NON_EVENT_LABEL)].copy()
            if not scope_summary.empty
            else pd.DataFrame()
        )
        if not event_summary.empty and not nonevent_summary.empty:
            rank_rows.append(_rank_correlation(event_summary, nonevent_summary, scope=scope, axis=axis_name))
            delta_table = _build_delta_table(event_summary, nonevent_summary, scope=scope, axis_name=axis_name)
            if not delta_table.empty:
                delta_rows.append(delta_table)
        else:
            rank_rows.append(
                {
                    "scope": scope,
                    "axis": axis_name,
                    "n_event_levels": int(event_summary["level"].nunique()) if not event_summary.empty else 0,
                    "n_nonevent_levels": int(nonevent_summary["level"].nunique()) if not nonevent_summary.empty else 0,
                    "n_shared_levels": 0,
                    "spearman_rho": float("nan"),
                    "spearman_p_value": float("nan"),
                    "top1_event_level": int(event_summary.iloc[0]["level"]) if not event_summary.empty else "",
                    "top1_nonevent_level": int(nonevent_summary.iloc[0]["level"]) if not nonevent_summary.empty else "",
                    "top1_match": False,
                    "mean_abs_rank_shift": float("nan"),
                }
            )

    summary = pd.concat(summary_parts, ignore_index=True) if summary_parts else pd.DataFrame()
    kw_by_eventtype = pd.concat(kw_parts, ignore_index=True) if kw_parts else pd.DataFrame()
    rank_correlation = pd.DataFrame(rank_rows).sort_values(["axis", "scope"], kind="mergesort").reset_index(drop=True)
    if delta_rows:
        delta_table = pd.concat(delta_rows, ignore_index=True)
        overall_delta = delta_table.loc[delta_table["scope"].eq("all")].copy()
        if overall_delta.empty:
            overall_delta = delta_table.groupby(["axis", "level"], dropna=False, as_index=False).first()
        overall_delta = overall_delta.sort_values(
            ["delta_avg_diff", "level"], ascending=[False, True], kind="mergesort"
        ).reset_index(drop=True)
        top = overall_delta.head(5).copy()
        bottom = (
            overall_delta.tail(5)
            .copy()
            .sort_values(["delta_avg_diff", "level"], ascending=[True, True], kind="mergesort")
        )
        top["bucket"] = "top"
        top["bucket_rank"] = np.arange(1, len(top) + 1, dtype=int)
        bottom["bucket"] = "bottom"
        bottom["bucket_rank"] = np.arange(1, len(bottom) + 1, dtype=int)
        watching_candidates = pd.concat([top, bottom], ignore_index=True)
        watching_candidates = watching_candidates.merge(
            _segment_consistency(overall_delta, delta_table),
            on=["axis", "level"],
            how="left",
        )
        watching_candidates = watching_candidates.sort_values(
            ["bucket", "bucket_rank"],
            ascending=[True, True],
            kind="mergesort",
        ).reset_index(drop=True)
    else:
        watching_candidates = pd.DataFrame(
            columns=[
                "axis",
                "scope",
                "level",
                "event_avg_diff",
                "non_event_avg_diff",
                "delta_avg_diff",
                "event_hit104_rate",
                "non_event_hit104_rate",
                "delta_hit104_rate",
                "event_n",
                "non_event_n",
                "total_n",
                "event_avg_rank",
                "non_event_avg_rank",
                "rank_shift",
                "bucket",
                "bucket_rank",
                "segment_total_count",
                "segment_same_sign_count",
                "segment_same_sign_rate",
                "segment_consistency",
                "segment_deltas",
            ]
        )

    return AxisOutputs(
        axis_name=axis_name,
        axis_label=axis_label,
        summary=summary,
        kw_by_eventtype=kw_by_eventtype,
        rank_correlation=rank_correlation,
        watching_candidates=watching_candidates,
    )


def _top_levels(summary: pd.DataFrame, *, scope: str, event_type: str, n: int = 5) -> pd.DataFrame:
    subset = summary.loc[summary["scope"].eq(scope) & summary["event_type"].eq(event_type)].copy()
    if subset.empty:
        return pd.DataFrame(
            columns=["level", "n", "avg_diff", "hit104_rate", "avg_games", "win_rate", "avg_diff_rank", "hit104_rank"]
        )
    return subset.head(n).loc[
        :, ["level", "n", "avg_diff", "hit104_rate", "avg_games", "win_rate", "avg_diff_rank", "hit104_rank"]
    ]


def _axis_report_section(axis_outputs: AxisOutputs, *, section_number: int, scope_label: str = "all") -> list[str]:
    lines: list[str] = []
    axis_name = axis_outputs.axis_label
    rank_rows = axis_outputs.rank_correlation.loc[axis_outputs.rank_correlation["scope"].eq(scope_label)].copy()
    kw_rows = axis_outputs.kw_by_eventtype.loc[axis_outputs.kw_by_eventtype["scope"].eq(scope_label)].copy()
    scope_summary = axis_outputs.summary.loc[axis_outputs.summary["scope"].eq(scope_label)].copy()
    event_top = _top_levels(axis_outputs.summary, scope=scope_label, event_type=EVENT_LABEL, n=5)
    non_event_top = _top_levels(axis_outputs.summary, scope=scope_label, event_type=NON_EVENT_LABEL, n=5)

    lines.append(f"## {section_number}. {axis_name} : イベント日vs非イベント日")
    lines.append("### 順位相関")
    lines.append(
        _markdown_table(
            rank_rows.loc[
                :,
                [
                    "scope",
                    "axis",
                    "n_event_levels",
                    "n_nonevent_levels",
                    "n_shared_levels",
                    "spearman_rho",
                    "spearman_p_value",
                    "top1_event_level",
                    "top1_nonevent_level",
                    "top1_match",
                    "mean_abs_rank_shift",
                ],
            ],
            float_digits=4,
        )
    )
    lines.append("")
    lines.append("### KW検定")
    lines.append(
        _markdown_table(
            kw_rows.loc[
                :, ["scope", "event_type", "axis", "n_levels", "n_samples", "statistic", "p_value", "epsilon_sq"]
            ],
            float_digits=6,
        )
    )
    lines.append("")
    lines.append("### event / non_event の上位5水準")
    lines.append("**event**")
    lines.append(_markdown_table(event_top, float_digits=4))
    lines.append("")
    lines.append("**non_event**")
    lines.append(_markdown_table(non_event_top, float_digits=4))
    lines.append("")
    if not scope_summary.empty:
        lines.append("### 補足")
        lines.append(
            f"- scope={scope_label} の有効水準数: event={int(rank_rows.iloc[0]['n_event_levels']) if not rank_rows.empty else 0}, "
            f"non_event={int(rank_rows.iloc[0]['n_nonevent_levels']) if not rank_rows.empty else 0}, "
            f"shared={int(rank_rows.iloc[0]['n_shared_levels']) if not rank_rows.empty else 0}"
        )
        lines.append(
            f"- top1一致: {bool(rank_rows.iloc[0]['top1_match']) if not rank_rows.empty else False}, "
            f"平均順位差={_format_value(rank_rows.iloc[0]['mean_abs_rank_shift'] if not rank_rows.empty else float('nan'), digits=3)}"
        )
    lines.append("")
    return lines


def _build_report(
    *,
    db_path: Path,
    frame: pd.DataFrame,
    output_dir: Path,
    floor_judgement: pd.DataFrame,
    axis_outputs: dict[str, AxisOutputs],
) -> str:
    lines: list[str] = []
    lines.append("# 楽園蒲田店 イベント日 vs 非イベント日 末尾・端番比較")
    lines.append("")
    lines.append("## 1. 手法概要")
    lines.append(f"- DB: `{db_path}`")
    lines.append(f"- フィルタ: `games_normalized >= {DEFAULT_MIN_GAMES}`")
    lines.append(f"- 対象イベント日: `DD∈{{10,11,22,30}} + 強ゾロ目`")
    lines.append(f"- 末尾: `machine_tail = machine_number % 10`")
    lines.append(f"- 端番(対称版): `hanaban = min(rank_from_min, rank_from_max)`")
    lines.append(f"- hanaban_min(非対称版): `rank_from_min`")
    lines.append(f"- 最小セル数: `min_n = {DEFAULT_MIN_CELL_N}`")
    lines.append(
        "- 比較軸ごとに event / non_event を分け、内部で `summarize_by()` を使って `avg_diff` と `hit104_rate` を集計"
    )
    lines.append(
        "- ランキングは `avg_diff` の降順を基準にし、`avg_diff` の Spearman 順位相関で event / non_event の並び替わりを確認"
    )
    lines.append("- p値だけで切らず、順位相関とセグメント一貫性を合わせて読む")
    lines.append("")
    lines.append("### データ規模")
    size_table = pd.DataFrame(
        {
            "scope": ["all", *SEGMENT_ORDER],
            "rows": [len(frame)] + [int(frame["segment"].eq(scope).sum()) for scope in SEGMENT_ORDER],
            "event_rows": [int(frame["event_day"].eq(True).sum())]
            + [int((frame["segment"].eq(scope) & frame["event_day"].eq(True)).sum()) for scope in SEGMENT_ORDER],
        }
    )
    lines.append(_markdown_table(size_table, float_digits=4))
    lines.append("")
    lines.append("### 本館/新館 floor 分割判定")
    lines.append(_markdown_table(floor_judgement, float_digits=6))
    lines.append("")
    lines.append("- 本館_N は 1F/2F/3F を分割したほうが Simpson's Paradox を解消しやすいので分割を採用した。")
    lines.append("- 新館_N は p は有意でも epsilon^2 が極小なので、1F+2F を統合したまま維持した。")
    lines.append("- 本館1F_N は 21 台で 50 台基準未満のため、統計解釈は参考値として扱う。")
    lines.append("")

    lines.extend(_axis_report_section(axis_outputs["lastdigit"], section_number=2))
    lines.extend(_axis_report_section(axis_outputs["hanaban"], section_number=3))
    lines.extend(_axis_report_section(axis_outputs["hanaban_min"], section_number=4))

    lines.append("## 5. セグメント別の一貫性")
    rank_all = pd.concat([value.rank_correlation for value in axis_outputs.values()], ignore_index=True)
    lines.append(
        _markdown_table(
            rank_all.loc[
                :,
                [
                    "axis",
                    "scope",
                    "n_event_levels",
                    "n_nonevent_levels",
                    "n_shared_levels",
                    "spearman_rho",
                    "top1_match",
                    "mean_abs_rank_shift",
                ],
            ],
            float_digits=4,
        )
    )
    lines.append("")
    focus_scopes = ["本館1F_N", "本館2F_N", "本館3F_N"]
    focus_rank = rank_all.loc[rank_all["scope"].isin(focus_scopes)].copy()
    if not focus_rank.empty:
        lines.append("### 本館フロア比較")
        lines.append(
            _markdown_table(
                focus_rank.loc[
                    :,
                    [
                        "axis",
                        "scope",
                        "n_event_levels",
                        "n_nonevent_levels",
                        "n_shared_levels",
                        "spearman_rho",
                        "top1_match",
                        "mean_abs_rank_shift",
                    ],
                ],
                float_digits=4,
            )
        )
        lines.append("")
    lines.append("- `spearman_rho` が低いほど、event と non_event で水準の強弱順が入れ替わっている")
    lines.append("- `top1_match = false` は、最上位水準が event / non_event で変わっていることを意味する")
    lines.append(
        "- segment 別に `mean_abs_rank_shift` が大きい場合は、その segment だけで順位入れ替わりが起きている可能性がある"
    )
    lines.append("")

    lines.append("## 6. watching候補リスト（上位/下位各5件）")
    watching = pd.concat([value.watching_candidates for value in axis_outputs.values()], ignore_index=True)
    if watching.empty:
        lines.append("No rows.")
    else:
        cols = [
            "axis",
            "bucket",
            "bucket_rank",
            "level",
            "delta_avg_diff",
            "event_n",
            "non_event_n",
            "total_n",
            "segment_same_sign_count",
            "segment_total_count",
            "segment_same_sign_rate",
            "segment_consistency",
            "segment_deltas",
        ]
        lines.append(_markdown_table(watching.loc[:, cols], float_digits=4))
    lines.append("")

    lines.append("## 7. 総括")
    overall_rank = rank_all.loc[rank_all["scope"].eq("all")].copy()
    lines.append(
        "- event 日の内部と non_event 日の内部を分けて見ると、同じ軸でも強い水準の並びが変わるかを直接確認できる"
    )
    if not overall_rank.empty:
        for _, row in overall_rank.iterrows():
            rho = row["spearman_rho"]
            if pd.isna(rho):
                rho_text = "NaN"
            else:
                rho_text = f"{float(rho):.3f}"
            lines.append(
                f"- {str(row['axis'])}: scope=all の順位相関 rho={rho_text}, top1一致={bool(row['top1_match'])}, mean_abs_rank_shift={_format_value(row['mean_abs_rank_shift'], digits=3)}"
            )
    lines.append("- watching候補は差分の大きさだけでなく、segment ごとの符号が揃うかを併記して判断する")
    lines.append(f"- 生成物は `{output_dir}` 配下に保存")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_outputs(db_path: Path, output_dir: Path, *, min_n: int) -> tuple[dict[str, AxisOutputs], str]:
    frame = _prepare_frame(db_path, min_games=DEFAULT_MIN_GAMES)
    if "segment" not in frame.columns:
        raise ValueError("segment column is missing after theory frame preparation")

    axis_outputs: dict[str, AxisOutputs] = {}
    for axis_name, axis_spec in AXES.items():
        axis_outputs[axis_name] = _build_axis_outputs(frame, axis_name=axis_name, axis_spec=axis_spec, min_n=min_n)
    floor_judgement = _floor_split_judgement(frame)

    output_dir.mkdir(parents=True, exist_ok=True)

    for axis_name, axis_spec in AXES.items():
        axis_result = axis_outputs[axis_name]
        prefix = str(axis_spec["file_prefix"])
        _write_csv(axis_result.summary, output_dir / f"{prefix}_event_vs_nonevent.csv")
        _write_csv(axis_result.kw_by_eventtype, output_dir / f"{prefix}_kw_by_eventtype.csv")
    rank_summary = pd.concat([value.rank_correlation for value in axis_outputs.values()], ignore_index=True)
    _write_csv(rank_summary, output_dir / "rank_correlation_summary.csv")
    watching = pd.concat([value.watching_candidates for value in axis_outputs.values()], ignore_index=True)
    _write_csv(watching, output_dir / "watching_candidates.csv")

    report = _build_report(
        db_path=db_path,
        frame=frame,
        output_dir=output_dir,
        floor_judgement=floor_judgement,
        axis_outputs=axis_outputs,
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return axis_outputs, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rakuen event-day vs non-event tail/hanaban comparison")
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

    axis_outputs, report = build_outputs(db_path, Path(args.output_dir), min_n=int(args.min_n))
    for axis_name, axis_result in axis_outputs.items():
        print(f"[OK] {axis_name}: summary_rows={len(axis_result.summary)}, kw_rows={len(axis_result.kw_by_eventtype)}")
    print(f"[OK] report saved: {Path(args.output_dir) / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
