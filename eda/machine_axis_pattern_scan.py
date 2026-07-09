from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, kruskal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, _epsilon_squared, load_hall_df
from eda.machine_name_significance_scan import (
    DEFAULT_SHINDAI_EXCLUDE_DAYS as DEFAULT_SHINDAI_EXCLUDE_DAYS_FROM_NAME_SCAN,
    _cramers_v_bias_corrected,
    _prepare_frame,
)
from eda.machine_volatility_event_gap_scan import (
    DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS as DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS_FROM_VOL_SCAN,
    _apply_currently_installed_filter,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_HALLS = ["蒲田1", "蒲田7", "みとや"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "machine_axis_pattern_scan"
DEFAULT_SHINDAI_EXCLUDE_DAYS = DEFAULT_SHINDAI_EXCLUDE_DAYS_FROM_NAME_SCAN
DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS_FROM_VOL_SCAN
DEFAULT_MIN_MACHINE_DAYS_TOTAL = 200
DEFAULT_MIN_OBS_FOR_RANKING = 100
DEFAULT_TOP_N = 30
MIN_CELL_N = 5
EFFECT_SIZE_THRESHOLD = 0.1
WEEKDAY_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
# DD(1-31)を週単位相当の5区分にまとめた軸。個別DDセルの小サンプル(n=5-15程度)を
# 束ねて検出力を上げる目的。既存のkamata7_theory.mdの「DDビン」(DD1-6,DD7-12,...)
# とは境界が異なる点に注意(こちらは7日区切り、あちらは6日区切り)。
DD_BIN_EDGES = [(1, 7, "1-7"), (8, 14, "8-14"), (15, 21, "15-21"), (22, 28, "22-28"), (29, 31, "29-31")]
DD_BIN_ORDER = [label for _, _, label in DD_BIN_EDGES]

PATTERN_SUMMARY_COLUMNS = [
    "hall",
    "machine_name",
    "n_machine_days",
    "axis",
    "outcome",
    "test",
    "statistic",
    "p_value",
    "effect_size",
    "n_obs",
    "n_levels",
    "n_sparse_levels",
    "note",
]

TOP_SIGNALS_COLUMNS = [
    "hall",
    "machine_name",
    "n_machine_days",
    "axis",
    "outcome",
    "test",
    "statistic",
    "p_value",
    "effect_size",
    "n_obs",
    "n_levels",
    "n_sparse_levels",
    "note",
]

BREAKDOWN_COLUMNS = [
    "hall",
    "machine_name",
    "axis",
    "outcome",
    "axis_level",
    "axis_level_order",
    "n",
    "avg_diff",
    "plus_rate",
    "hit104_rate",
]

SUMMARY_REPORT_COLUMNS = [
    "hall",
    "axis",
    "outcome",
    "n_patterns",
    "n_valid_patterns",
    "n_effect_ge_0_1",
    "pct_effect_ge_0_1",
]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _axis_order(axis: str) -> list[object]:
    if axis == "dd":
        return []
    if axis == "day_of_week":
        return WEEKDAY_ORDER
    if axis == "is_x_day":
        return [0, 1]
    if axis == "dd_bin":
        return DD_BIN_ORDER
    return []


def _compute_dd_bin(dd_series: pd.Series) -> pd.Series:
    """DD(1-31)を DD_BIN_EDGES に従って '1-7'/'8-14'/... のラベルに変換する。"""
    numeric = pd.to_numeric(dd_series, errors="coerce")

    def _label(dd: float) -> object:
        if pd.isna(dd):
            return np.nan
        dd_int = int(dd)
        for lo, hi, label in DD_BIN_EDGES:
            if lo <= dd_int <= hi:
                return label
        return np.nan

    return numeric.map(_label)


def _sorted_axis_values(values: pd.Series, axis: str) -> list[object]:
    observed = pd.Series(values.dropna().tolist())
    if axis == "dd":
        numeric = pd.to_numeric(observed, errors="coerce").dropna().astype(int)
        return sorted(numeric.unique().tolist())
    if axis == "day_of_week":
        order = {name: idx for idx, name in enumerate(WEEKDAY_ORDER)}

        def _sort_key(value: object) -> tuple[int, str]:
            text = str(value)
            return (order.get(text, 99), text)

        return sorted(observed.unique().tolist(), key=_sort_key)
    if axis == "is_x_day":
        numeric = pd.to_numeric(observed, errors="coerce").dropna().astype(int)
        return sorted(numeric.unique().tolist())
    if axis == "dd_bin":
        order = {name: idx for idx, name in enumerate(DD_BIN_ORDER)}

        def _bin_sort_key(value: object) -> tuple[int, str]:
            text = str(value)
            return (order.get(text, 99), text)

        return sorted(observed.unique().tolist(), key=_bin_sort_key)
    return sorted(observed.unique().tolist(), key=lambda value: str(value))


def _format_axis_level(level: object) -> object:
    if isinstance(level, (np.integer,)):
        return int(level)
    if isinstance(level, (np.floating,)) and float(level).is_integer():
        return int(level)
    return level


def _axis_level_order(level: object, axis: str) -> int:
    if axis == "dd":
        return int(pd.to_numeric(pd.Series([level]), errors="coerce").iloc[0])
    if axis == "day_of_week":
        order = {name: idx for idx, name in enumerate(WEEKDAY_ORDER)}
        return int(order.get(str(level), 99))
    if axis == "is_x_day":
        try:
            return int(level)
        except Exception:
            return 99
    if axis == "dd_bin":
        order = {name: idx for idx, name in enumerate(DD_BIN_ORDER)}
        return int(order.get(str(level), 99))
    return 0


def _mean_percent(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return float("nan")
    return float(numeric.mean() * 100.0)


def _scan_diff_outcome(
    machine_frame: pd.DataFrame,
    *,
    axis: str,
    min_cell_n: int,
) -> dict[str, object]:
    axis_values = _sorted_axis_values(machine_frame[axis], axis)
    groups: list[np.ndarray] = []
    n_sparse_levels = 0
    sparse_notes: list[str] = []

    for level in axis_values:
        level_frame = machine_frame.loc[machine_frame[axis].eq(level)]
        level_values = pd.to_numeric(level_frame["diff"], errors="coerce").dropna().to_numpy()
        if len(level_values) < min_cell_n:
            n_sparse_levels += 1
            sparse_notes.append(f"{_format_axis_level(level)}:{len(level_values)}")
            continue
        groups.append(level_values)

    if len(groups) < 2:
        reason = "fewer than two groups with n>=MIN_CELL_N"
        if sparse_notes:
            reason = f"{reason}; sparse={','.join(sparse_notes[:4])}"
        return {
            "test": "kruskal",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_obs": int(sum(len(group) for group in groups)),
            "n_levels": int(len(axis_values)),
            "n_sparse_levels": int(n_sparse_levels),
            "note": reason,
        }

    statistic, p_value = kruskal(*groups)
    n_obs = int(sum(len(group) for group in groups))
    note = ""
    if sparse_notes:
        note = f"dropped sparse levels (<{min_cell_n}): {', '.join(sparse_notes[:4])}"
    return {
        "test": "kruskal",
        "statistic": float(statistic),
        "p_value": float(p_value),
        "effect_size": float(_epsilon_squared(float(statistic), len(groups), n_obs)),
        "n_obs": n_obs,
        "n_levels": int(len(axis_values)),
        "n_sparse_levels": int(n_sparse_levels),
        "note": note,
    }


def _scan_binary_outcome(
    machine_frame: pd.DataFrame,
    *,
    axis: str,
    outcome_col: str,
) -> dict[str, object]:
    axis_values = _sorted_axis_values(machine_frame[axis], axis)
    contingency = pd.crosstab(machine_frame[axis], machine_frame[outcome_col]).reindex(
        index=axis_values, columns=[0, 1], fill_value=0
    )
    n_obs = int(contingency.to_numpy().sum())
    if contingency.empty or contingency.shape[0] < 2 or contingency.shape[1] < 2 or n_obs == 0:
        return {
            "test": "chi2",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_obs": n_obs,
            "n_levels": int(contingency.shape[0]),
            "n_sparse_levels": np.nan,
            "note": "insufficient contingency table",
        }

    if (contingency.sum(axis=0) == 0).any() or (contingency.sum(axis=1) == 0).any():
        return {
            "test": "chi2",
            "statistic": np.nan,
            "p_value": np.nan,
            "effect_size": np.nan,
            "n_obs": n_obs,
            "n_levels": int(contingency.shape[0]),
            "n_sparse_levels": np.nan,
            "note": "insufficient contingency table",
        }

    chi2, p_value, _, expected = chi2_contingency(contingency, correction=False)
    sparse_ratio = float((expected < 5).mean())
    note = ""
    if sparse_ratio > 0.2:
        note = f"warning: {sparse_ratio:.1%} of expected cells are below 5"
        warnings.warn(note, RuntimeWarning)

    return {
        "test": "chi2",
        "statistic": float(chi2),
        "p_value": float(p_value),
        # Bias-corrected Cramer's V to reduce axis-cardinality inflation on binary outcomes.
        "effect_size": float(_cramers_v_bias_corrected(float(chi2), n_obs, contingency.shape[0], contingency.shape[1])),
        "n_obs": n_obs,
        "n_levels": int(contingency.shape[0]),
        "n_sparse_levels": np.nan,
        "note": note,
    }


def _machine_axis_outcome_rows(
    hall: str,
    machine_name: str,
    machine_frame: pd.DataFrame,
    *,
    min_cell_n: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    n_machine_days = int(len(machine_frame))

    for axis in ["dd", "day_of_week", "is_x_day", "dd_bin"]:
        diff_stats = _scan_diff_outcome(machine_frame, axis=axis, min_cell_n=min_cell_n)
        rows.append(
            {
                "hall": hall,
                "machine_name": machine_name,
                "n_machine_days": n_machine_days,
                "axis": axis,
                "outcome": "diff",
                **diff_stats,
            }
        )

        for outcome_col in ["plus", "hit104"]:
            binary_stats = _scan_binary_outcome(machine_frame, axis=axis, outcome_col=outcome_col)
            rows.append(
                {
                    "hall": hall,
                    "machine_name": machine_name,
                    "n_machine_days": n_machine_days,
                    "axis": axis,
                    "outcome": outcome_col,
                    **binary_stats,
                }
            )

    return rows


def _axis_breakdown(
    hall: str,
    machine_name: str,
    machine_frame: pd.DataFrame,
    *,
    axis: str,
    outcome: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    axis_values = _sorted_axis_values(machine_frame[axis], axis)
    for idx, level in enumerate(axis_values, start=1):
        level_frame = machine_frame.loc[machine_frame[axis].eq(level)]
        rows.append(
            {
                "hall": hall,
                "machine_name": machine_name,
                "axis": axis,
                "outcome": outcome,
                "axis_level": _format_axis_level(level),
                "axis_level_order": idx if axis == "dd" else _axis_level_order(level, axis),
                "n": int(len(level_frame)),
                "avg_diff": float(pd.to_numeric(level_frame["diff"], errors="coerce").mean()),
                "plus_rate": _mean_percent(level_frame["plus"]),
                "hit104_rate": _mean_percent(level_frame["hit104"]),
            }
        )
    return pd.DataFrame(rows, columns=BREAKDOWN_COLUMNS)


def _summarize_pattern_summary(pattern_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if pattern_summary.empty:
        return pd.DataFrame(columns=SUMMARY_REPORT_COLUMNS)

    for (hall, axis, outcome), group in pattern_summary.groupby(["hall", "axis", "outcome"], sort=True):
        tested = group.loc[group["effect_size"].notna()].copy()
        n_patterns = int(len(group))
        n_valid_patterns = int(len(tested))
        n_effect_ge_0_1 = int((tested["effect_size"] >= EFFECT_SIZE_THRESHOLD).sum())
        pct_effect_ge_0_1 = float((n_effect_ge_0_1 / n_valid_patterns) * 100.0) if n_valid_patterns else float("nan")
        rows.append(
            {
                "hall": hall,
                "axis": axis,
                "outcome": outcome,
                "n_patterns": n_patterns,
                "n_valid_patterns": n_valid_patterns,
                "n_effect_ge_0_1": n_effect_ge_0_1,
                "pct_effect_ge_0_1": pct_effect_ge_0_1,
            }
        )
    return pd.DataFrame(rows, columns=SUMMARY_REPORT_COLUMNS)


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    shindai_exclude_days: int = DEFAULT_SHINDAI_EXCLUDE_DAYS,
    currently_installed_grace_days: int = DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
    min_machine_days_total: int = DEFAULT_MIN_MACHINE_DAYS_TOTAL,
    min_obs_for_ranking: int = DEFAULT_MIN_OBS_FOR_RANKING,
    top_n: int = DEFAULT_TOP_N,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = _prepare_frame(raw, shindai_exclude_days=shindai_exclude_days).copy()
    if "hall" not in frame.columns:
        frame["hall"] = hall
    frame["dd_bin"] = _compute_dd_bin(frame["dd"])
    frame = _apply_currently_installed_filter(frame, grace_days=currently_installed_grace_days).copy()
    if frame.empty:
        empty_pattern = pd.DataFrame(columns=PATTERN_SUMMARY_COLUMNS)
        empty_top = pd.DataFrame(columns=TOP_SIGNALS_COLUMNS)
        empty_breakdown = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
        empty_summary = pd.DataFrame(columns=SUMMARY_REPORT_COLUMNS)
        return empty_pattern, empty_top, empty_breakdown, empty_summary

    machine_days = frame.groupby("machine_name", sort=True).size().rename("n_machine_days")
    eligible_names = machine_days.loc[machine_days >= min_machine_days_total].index.astype(str).tolist()
    working = frame.loc[frame["machine_name"].astype(str).isin(eligible_names)].copy()
    if working.empty:
        empty_pattern = pd.DataFrame(columns=PATTERN_SUMMARY_COLUMNS)
        empty_top = pd.DataFrame(columns=TOP_SIGNALS_COLUMNS)
        empty_breakdown = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
        empty_summary = pd.DataFrame(columns=SUMMARY_REPORT_COLUMNS)
        return empty_pattern, empty_top, empty_breakdown, empty_summary

    rows: list[dict[str, object]] = []
    for machine_name, machine_frame in working.groupby("machine_name", sort=True):
        rows.extend(_machine_axis_outcome_rows(hall, str(machine_name), machine_frame, min_cell_n=MIN_CELL_N))

    pattern_summary = pd.DataFrame(rows, columns=PATTERN_SUMMARY_COLUMNS)
    if pattern_summary.empty:
        empty_top = pd.DataFrame(columns=TOP_SIGNALS_COLUMNS)
        empty_breakdown = pd.DataFrame(columns=BREAKDOWN_COLUMNS)
        summary = _summarize_pattern_summary(pattern_summary)
        return pattern_summary, empty_top, empty_breakdown, summary

    pattern_summary = pattern_summary.sort_values(
        ["machine_name", "axis", "outcome"],
        ascending=[True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    top_signals = (
        pattern_summary.loc[pattern_summary["effect_size"].notna() & (pattern_summary["n_obs"] >= min_obs_for_ranking)]
        .sort_values(
            ["effect_size", "n_obs", "machine_name", "axis", "outcome"],
            ascending=[False, False, True, True, True],
            kind="mergesort",
        )
        .head(top_n)
        .reset_index(drop=True)
    )

    breakdown_frames: list[pd.DataFrame] = []
    if not top_signals.empty:
        unique_pairs = (
            top_signals.sort_values(
                ["effect_size", "n_obs", "machine_name", "axis", "outcome"],
                ascending=[False, False, True, True, True],
                kind="mergesort",
            )
            .drop_duplicates(subset=["machine_name", "axis"], keep="first")
            .reset_index(drop=True)
        )
        for _, row in unique_pairs.iterrows():
            machine_frame = working.loc[working["machine_name"].astype(str).eq(str(row["machine_name"]))].copy()
            breakdown_frames.append(
                _axis_breakdown(
                    hall,
                    str(row["machine_name"]),
                    machine_frame,
                    axis=str(row["axis"]),
                    outcome=str(row["outcome"]),
                )
            )
    top_signal_breakdown = (
        pd.concat(breakdown_frames, ignore_index=True) if breakdown_frames else pd.DataFrame(columns=BREAKDOWN_COLUMNS)
    )
    top_signal_breakdown = top_signal_breakdown.sort_values(
        ["machine_name", "axis", "axis_level_order", "outcome"],
        ascending=[True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    summary = _summarize_pattern_summary(pattern_summary)
    return pattern_summary, top_signals, top_signal_breakdown, summary


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _print_hall_report(
    hall: str, pattern_summary: pd.DataFrame, top_signals: pd.DataFrame, summary: pd.DataFrame
) -> None:
    print(f"\n=== {hall} ===")
    if summary.empty:
        print("no eligible machines")
        return

    print(summary.to_string(index=False))
    if top_signals.empty:
        print("top signals: none")
        return

    columns = ["machine_name", "axis", "outcome", "effect_size", "n_obs", "note"]
    print("top signals:")
    print(top_signals.loc[:, columns].head(10).to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="機種名×DD／機種名×イベント日／機種名×曜日 の法則性スキャン")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--currently-installed-grace-days", type=int, default=DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS)
    parser.add_argument("--min-machine-days-total", type=int, default=DEFAULT_MIN_MACHINE_DAYS_TOTAL)
    parser.add_argument("--min-obs-for-ranking", type=int, default=DEFAULT_MIN_OBS_FOR_RANKING)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args(argv)

    output_dir = _ensure_output_dir(args.output_dir)
    all_summary_frames: list[pd.DataFrame] = []

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        raw = load_hall_df(hall)
        pattern_summary, top_signals, top_signal_breakdown, summary = build_hall_outputs(
            hall,
            raw,
            shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS,
            currently_installed_grace_days=args.currently_installed_grace_days,
            min_machine_days_total=args.min_machine_days_total,
            min_obs_for_ranking=args.min_obs_for_ranking,
            top_n=args.top_n,
        )

        _write_csv(pattern_summary, output_dir / f"{hall}_pattern_summary.csv")
        _write_csv(top_signals, output_dir / f"{hall}_top_signals.csv")
        _write_csv(top_signal_breakdown, output_dir / f"{hall}_top_signal_breakdown.csv")
        _print_hall_report(hall, pattern_summary, top_signals, summary)
        all_summary_frames.append(summary)

    summary_report = (
        pd.concat(all_summary_frames, ignore_index=True)
        if all_summary_frames
        else pd.DataFrame(columns=SUMMARY_REPORT_COLUMNS)
    )
    _write_csv(summary_report, output_dir / "summary_report.csv")
    print(f"\nwritten: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
