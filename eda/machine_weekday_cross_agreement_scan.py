from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from statsmodels.stats.multitest import multipletests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import DB_DIR, HALL_DBS, load_hall_df
from eda.machine_axis_pattern_scan import MIN_CELL_N, WEEKDAY_ORDER, _axis_breakdown
from eda.machine_dd_cross_agreement_scan import (
    CATEGORY_FLAG_PRIORITY,
    DEFAULT_CATEGORY,
    DEFAULT_FDR_ALPHA,
    DEFAULT_HALLS,
    DEFAULT_KNOWN_EVENT_THRESHOLD,
    DEFAULT_MIN_MACHINES_FOR_TEST,
    DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE,
    UNKNOWN_CATEGORY,
    load_machine_categories,
)
from eda.machine_name_significance_scan import DEFAULT_SHINDAI_EXCLUDE_DAYS, _prepare_frame
from eda.machine_volatility_event_gap_scan import _parse_halls

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "machine_weekday_cross_agreement"

RESIDUAL_COLUMNS = [
    "hall",
    "machine_name",
    "weekday",
    "n",
    "hit104_rate",
    "baseline_hit104_rate",
    "residual",
]

RESIDUAL_WITH_CATEGORY_COLUMNS = RESIDUAL_COLUMNS + ["category"]

AGREEMENT_COLUMNS = [
    "hall",
    "weekday",
    "n_machines",
    "n_positive",
    "n_negative",
    "agreement_rate",
    "mean_residual",
    "median_residual",
    "p_value",
    "cohens_h",
    "note",
]

AGREEMENT_WITH_FDR_COLUMNS = AGREEMENT_COLUMNS + ["q_value", "is_significant"]

POOLED_COLUMNS = [
    "hall",
    "weekday",
    "pooled_n",
    "pooled_hit104_rate",
    "pooled_diff",
    "hall_overall_hit104_rate",
    "hall_overall_diff",
    "pooled_hit104_rate_vs_hall",
    "pooled_diff_vs_hall",
]

AGREEMENT_FULL_COLUMNS = (
    AGREEMENT_WITH_FDR_COLUMNS
    + ["weekday_event_coverage_rate", "is_known_weekend_day"]
    + [c for c in POOLED_COLUMNS if c not in ("hall", "weekday")]
)

CATEGORY_BREAKDOWN_COLUMNS = [
    "hall",
    "weekday",
    "category",
    "n_machines",
    "n_positive",
    "n_negative",
    "agreement_rate",
    "mean_residual",
    "median_residual",
]

ROBUSTNESS_COLUMNS = [
    "hall",
    "weekday",
    "dominant_category",
    "dominant_category_share_of_majority",
    "n_machines_excl_dominant",
    "n_positive_excl_dominant",
    "agreement_rate_excl_dominant",
    "p_value_excl_dominant",
    "signal_survives_without_dominant_category",
    "note",
]

SUMMARY_COLUMNS = [
    "hall",
    "weekday",
    "n_machines",
    "n_positive",
    "agreement_rate",
    "mean_residual",
    "q_value",
    "cohens_h",
    "is_known_weekend_day",
    "is_novel",
    "pooled_hit104_rate_vs_hall",
    "pooled_diff_vs_hall",
    "dominant_category",
    "dominant_category_share_of_majority",
    "agreement_rate_excl_dominant",
    "p_value_excl_dominant",
    "signal_survives_without_dominant_category",
    "top_positive_machines",
]


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _format_residual_machine(name: object, residual: float) -> str:
    return f"{name}({residual:+.1f})"


def _weekday_sort_key(value: object) -> tuple[int, str]:
    text = str(value)
    try:
        return (WEEKDAY_ORDER.index(text), text)
    except ValueError:
        return (99, text)


def compute_machine_weekday_residuals(
    hall: str,
    frame: pd.DataFrame,
    *,
    min_machine_days_total: int,
    min_cell_n: int,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    machine_name_series = frame["machine_name"].astype(str)
    for machine_name, machine_frame in frame.loc[machine_name_series.notna()].groupby("machine_name", sort=True):
        machine_frame = machine_frame.copy()
        if len(machine_frame) < min_machine_days_total:
            continue

        baseline_hit104_rate = float(pd.to_numeric(machine_frame["hit104"], errors="coerce").mean() * 100.0)
        breakdown = _axis_breakdown(hall, str(machine_name), machine_frame, axis="day_of_week", outcome="hit104")
        if breakdown.empty:
            continue

        working = breakdown.loc[breakdown["n"] >= min_cell_n].copy()
        if working.empty:
            continue

        working["hall"] = hall
        working["machine_name"] = str(machine_name)
        working["weekday"] = working["axis_level"].astype(str)
        working["hit104_rate"] = pd.to_numeric(working["hit104_rate"], errors="coerce")
        working["baseline_hit104_rate"] = baseline_hit104_rate
        working["residual"] = working["hit104_rate"] - baseline_hit104_rate
        rows.append(
            working.loc[:, ["hall", "machine_name", "weekday", "n", "hit104_rate", "baseline_hit104_rate", "residual"]]
        )

    if not rows:
        return pd.DataFrame(columns=RESIDUAL_COLUMNS)

    residuals = pd.concat(rows, ignore_index=True)
    residuals["n"] = residuals["n"].astype(int)
    return residuals.loc[:, RESIDUAL_COLUMNS]


def attach_machine_category(residuals: pd.DataFrame, hall: str) -> pd.DataFrame:
    if residuals.empty:
        result = residuals.copy()
        result["category"] = pd.Series(dtype=str)
        return result.loc[:, RESIDUAL_WITH_CATEGORY_COLUMNS]

    categories = load_machine_categories(hall)
    result = residuals.merge(categories, on="machine_name", how="left")
    result["category"] = result["category"].fillna(UNKNOWN_CATEGORY)
    return result.loc[:, RESIDUAL_WITH_CATEGORY_COLUMNS]


def aggregate_weekday_agreement(residuals: pd.DataFrame, *, min_machines_for_test: int) -> pd.DataFrame:
    if residuals.empty:
        return pd.DataFrame(columns=AGREEMENT_COLUMNS)

    rows: list[dict[str, object]] = []
    for (hall, weekday), group in residuals.groupby(["hall", "weekday"], sort=True):
        numeric = pd.to_numeric(group["residual"], errors="coerce").dropna()
        n_machines = int(len(numeric))
        if n_machines == 0:
            continue

        # Residual == 0 is intentionally treated as a non-positive outcome.
        n_positive = int((numeric > 0).sum())
        n_negative = int(n_machines - n_positive)
        agreement_rate = float(n_positive / n_machines)
        mean_residual = float(numeric.mean())
        median_residual = float(numeric.median())

        if n_machines >= min_machines_for_test:
            p_value = float(binomtest(n_positive, n_machines, p=0.5, alternative="two-sided").pvalue)
            cohens_h = float(2 * np.arcsin(np.sqrt(agreement_rate)) - 2 * np.arcsin(np.sqrt(0.5)))
            note = ""
        else:
            p_value = float("nan")
            cohens_h = float("nan")
            note = f"insufficient machines (<{min_machines_for_test})"

        rows.append(
            {
                "hall": hall,
                "weekday": weekday,
                "n_machines": n_machines,
                "n_positive": n_positive,
                "n_negative": n_negative,
                "agreement_rate": agreement_rate,
                "mean_residual": mean_residual,
                "median_residual": median_residual,
                "p_value": p_value,
                "cohens_h": cohens_h,
                "note": note,
            }
        )

    return pd.DataFrame(rows, columns=AGREEMENT_COLUMNS)


def apply_fdr_per_hall(agreement: pd.DataFrame, *, fdr_alpha: float) -> pd.DataFrame:
    if agreement.empty:
        result = agreement.copy()
        result["q_value"] = pd.Series(dtype=float)
        result["is_significant"] = pd.Series(dtype=bool)
        return result.reindex(columns=AGREEMENT_WITH_FDR_COLUMNS)

    result = agreement.copy()
    result["q_value"] = np.nan
    result["is_significant"] = False

    for hall, hall_index in result.groupby("hall", sort=False).groups.items():
        valid_mask = result.loc[hall_index, "p_value"].notna()
        valid_index = result.loc[hall_index].index[valid_mask]
        if valid_index.empty:
            continue

        _, q_values, _, _ = multipletests(result.loc[valid_index, "p_value"].astype(float).to_numpy(), method="fdr_bh")
        result.loc[valid_index, "q_value"] = q_values

    result["is_significant"] = result["q_value"].lt(fdr_alpha).fillna(False)
    return result.loc[:, AGREEMENT_WITH_FDR_COLUMNS]


def attach_weekday_coverage(
    agreement: pd.DataFrame,
    hall_frames: dict[str, pd.DataFrame],
    *,
    known_event_threshold: float,
) -> pd.DataFrame:
    if agreement.empty:
        result = agreement.copy()
        result["weekday_event_coverage_rate"] = pd.Series(dtype=float)
        result["is_known_weekend_day"] = pd.Series(dtype=bool)
        return result

    coverage_frames: list[pd.DataFrame] = []
    for hall, frame in hall_frames.items():
        if frame.empty or "day_of_week" not in frame.columns or "is_weekend" not in frame.columns:
            continue
        coverage = (
            frame.assign(
                weekday=frame["day_of_week"].astype(str),
                is_weekend=pd.to_numeric(frame["is_weekend"], errors="coerce"),
            )
            .dropna(subset=["weekday"])
            .groupby("weekday", sort=True)["is_weekend"]
            .mean()
            .reset_index()
        )
        coverage["hall"] = hall
        coverage["weekday_event_coverage_rate"] = pd.to_numeric(coverage["is_weekend"], errors="coerce")
        coverage_frames.append(coverage.loc[:, ["hall", "weekday", "weekday_event_coverage_rate"]])

    coverage_df = (
        pd.concat(coverage_frames, ignore_index=True)
        if coverage_frames
        else pd.DataFrame(columns=["hall", "weekday", "weekday_event_coverage_rate"])
    )
    result = agreement.merge(coverage_df, on=["hall", "weekday"], how="left")
    result["is_known_weekend_day"] = result["weekday_event_coverage_rate"].ge(known_event_threshold).fillna(False)
    return result


def compute_pooled_weekday_stats(hall: str, frame: pd.DataFrame) -> pd.DataFrame:
    """機種ごとのbaseline補正をしない、ホール全体でプールした曜日別の絶対水準。"""

    if frame.empty or "day_of_week" not in frame.columns:
        return pd.DataFrame(columns=POOLED_COLUMNS)

    hit104 = pd.to_numeric(frame["hit104"], errors="coerce")
    diff = pd.to_numeric(frame["diff"], errors="coerce")
    overall_hit104_rate = float(hit104.mean() * 100.0)
    overall_diff = float(diff.mean())

    working = frame.assign(_hit104=hit104, _diff=diff)
    working = working.loc[working["day_of_week"].notna()].copy()
    working["weekday"] = working["day_of_week"].astype(str)

    rows: list[dict[str, object]] = []
    for weekday, group in working.groupby("weekday", sort=True):
        pooled_n = int(len(group))
        pooled_hit104_rate = float(group["_hit104"].mean() * 100.0)
        pooled_diff = float(group["_diff"].mean())
        rows.append(
            {
                "hall": hall,
                "weekday": weekday,
                "pooled_n": pooled_n,
                "pooled_hit104_rate": pooled_hit104_rate,
                "pooled_diff": pooled_diff,
                "hall_overall_hit104_rate": overall_hit104_rate,
                "hall_overall_diff": overall_diff,
                "pooled_hit104_rate_vs_hall": pooled_hit104_rate - overall_hit104_rate,
                "pooled_diff_vs_hall": pooled_diff - overall_diff,
            }
        )
    return pd.DataFrame(rows, columns=POOLED_COLUMNS)


def attach_pooled_stats(agreement: pd.DataFrame, hall_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if agreement.empty:
        result = agreement.copy()
        for col in POOLED_COLUMNS:
            if col not in ("hall", "weekday"):
                result[col] = pd.Series(dtype=float)
        return result

    pooled_frames = [compute_pooled_weekday_stats(hall, frame) for hall, frame in hall_frames.items()]
    pooled_frames = [f for f in pooled_frames if not f.empty]
    pooled_df = pd.concat(pooled_frames, ignore_index=True) if pooled_frames else pd.DataFrame(columns=POOLED_COLUMNS)
    return agreement.merge(pooled_df, on=["hall", "weekday"], how="left")


def build_category_breakdown(residuals_with_category: pd.DataFrame, agreement: pd.DataFrame) -> pd.DataFrame:
    if residuals_with_category.empty or agreement.empty:
        return pd.DataFrame(columns=CATEGORY_BREAKDOWN_COLUMNS)

    valid_pairs = set(zip(agreement["hall"].astype(str), agreement["weekday"].astype(str)))
    rows: list[dict[str, object]] = []
    grouped = residuals_with_category.groupby(["hall", "weekday", "category"], sort=True)
    for (hall, weekday, category), group in grouped:
        if (str(hall), str(weekday)) not in valid_pairs:
            continue
        numeric = pd.to_numeric(group["residual"], errors="coerce").dropna()
        n_machines = int(len(numeric))
        if n_machines == 0:
            continue
        n_positive = int((numeric > 0).sum())
        n_negative = int(n_machines - n_positive)
        rows.append(
            {
                "hall": hall,
                "weekday": str(weekday),
                "category": category,
                "n_machines": n_machines,
                "n_positive": n_positive,
                "n_negative": n_negative,
                "agreement_rate": float(n_positive / n_machines),
                "mean_residual": float(numeric.mean()),
                "median_residual": float(numeric.median()),
            }
        )
    return pd.DataFrame(rows, columns=CATEGORY_BREAKDOWN_COLUMNS)


def compute_dominant_category_robustness(
    residuals_with_category: pd.DataFrame,
    agreement: pd.DataFrame,
    *,
    min_machines_for_test: int,
    fdr_alpha: float,
) -> pd.DataFrame:
    if residuals_with_category.empty or agreement.empty:
        return pd.DataFrame(columns=ROBUSTNESS_COLUMNS)

    significant = agreement.loc[agreement["is_significant"].fillna(False)]
    if significant.empty:
        return pd.DataFrame(columns=ROBUSTNESS_COLUMNS)

    rows: list[dict[str, object]] = []
    for _, row in significant.iterrows():
        hall = str(row["hall"])
        weekday = str(row["weekday"])
        agreement_rate = float(row["agreement_rate"])
        majority_positive = agreement_rate >= 0.5

        group = residuals_with_category.loc[
            (residuals_with_category["hall"].astype(str) == hall)
            & (residuals_with_category["weekday"].astype(str) == weekday)
        ].copy()
        group["_residual"] = pd.to_numeric(group["residual"], errors="coerce")
        majority_mask = group["_residual"] > 0 if majority_positive else group["_residual"] < 0
        majority_group = group.loc[majority_mask]

        if majority_group.empty:
            rows.append(
                {
                    "hall": hall,
                    "weekday": weekday,
                    "dominant_category": "",
                    "dominant_category_share_of_majority": float("nan"),
                    "n_machines_excl_dominant": 0,
                    "n_positive_excl_dominant": 0,
                    "agreement_rate_excl_dominant": float("nan"),
                    "p_value_excl_dominant": float("nan"),
                    "signal_survives_without_dominant_category": False,
                    "note": "no majority-direction machines found",
                }
            )
            continue

        category_counts = majority_group["category"].value_counts()
        dominant_category = str(category_counts.index[0])
        dominant_share = float(category_counts.iloc[0] / len(majority_group))

        remainder = group.loc[group["category"] != dominant_category]
        n_excl = int(len(remainder))

        if n_excl == 0:
            rows.append(
                {
                    "hall": hall,
                    "weekday": weekday,
                    "dominant_category": dominant_category,
                    "dominant_category_share_of_majority": dominant_share,
                    "n_machines_excl_dominant": 0,
                    "n_positive_excl_dominant": 0,
                    "agreement_rate_excl_dominant": float("nan"),
                    "p_value_excl_dominant": float("nan"),
                    "signal_survives_without_dominant_category": False,
                    "note": "no machines remain after excluding dominant category",
                }
            )
            continue

        n_positive_excl = int((remainder["_residual"] > 0).sum())
        agreement_rate_excl = float(n_positive_excl / n_excl)

        if n_excl >= min_machines_for_test:
            p_value_excl = float(binomtest(n_positive_excl, n_excl, p=0.5, alternative="two-sided").pvalue)
            survives = bool(p_value_excl < fdr_alpha)
            note = ""
        else:
            p_value_excl = float("nan")
            survives = False
            note = f"insufficient machines after exclusion (<{min_machines_for_test})"

        rows.append(
            {
                "hall": hall,
                "weekday": weekday,
                "dominant_category": dominant_category,
                "dominant_category_share_of_majority": dominant_share,
                "n_machines_excl_dominant": n_excl,
                "n_positive_excl_dominant": n_positive_excl,
                "agreement_rate_excl_dominant": agreement_rate_excl,
                "p_value_excl_dominant": p_value_excl,
                "signal_survives_without_dominant_category": survives,
                "note": note,
            }
        )

    return pd.DataFrame(rows, columns=ROBUSTNESS_COLUMNS)


def _build_top_positive_machines(group: pd.DataFrame) -> str:
    positives = group.loc[pd.to_numeric(group["residual"], errors="coerce") > 0].copy()
    if positives.empty:
        return ""

    positives = positives.sort_values(["residual", "machine_name"], ascending=[False, True], kind="mergesort")
    total = int(len(positives))
    items = [
        _format_residual_machine(row["machine_name"], float(row["residual"])) for _, row in positives.head(5).iterrows()
    ]
    if total > 5:
        items.append(f"...(他{total - 5}件)")
    return ";".join(items)


def build_summary_report(agreement: pd.DataFrame, residuals: pd.DataFrame) -> pd.DataFrame:
    if agreement.empty or residuals.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    rows: list[dict[str, object]] = []
    significant = agreement.loc[agreement["is_significant"].fillna(False)].copy()
    if significant.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    for _, row in significant.iterrows():
        hall = str(row["hall"])
        weekday = str(row["weekday"])
        residual_group = residuals.loc[
            (residuals["hall"].astype(str) == hall) & (residuals["weekday"].astype(str) == weekday)
        ].copy()
        rows.append(
            {
                "hall": hall,
                "weekday": weekday,
                "n_machines": int(row["n_machines"]),
                "n_positive": int(row["n_positive"]),
                "agreement_rate": float(row["agreement_rate"]),
                "mean_residual": float(row["mean_residual"]),
                "q_value": float(row["q_value"]),
                "cohens_h": float(row["cohens_h"]),
                "is_known_weekend_day": bool(row["is_known_weekend_day"]),
                "is_novel": not bool(row["is_known_weekend_day"]),
                "pooled_hit104_rate_vs_hall": float(row["pooled_hit104_rate_vs_hall"])
                if "pooled_hit104_rate_vs_hall" in row and pd.notna(row["pooled_hit104_rate_vs_hall"])
                else float("nan"),
                "pooled_diff_vs_hall": float(row["pooled_diff_vs_hall"])
                if "pooled_diff_vs_hall" in row and pd.notna(row["pooled_diff_vs_hall"])
                else float("nan"),
                "dominant_category": "",
                "dominant_category_share_of_majority": float("nan"),
                "agreement_rate_excl_dominant": float("nan"),
                "p_value_excl_dominant": float("nan"),
                "signal_survives_without_dominant_category": False,
                "top_positive_machines": _build_top_positive_machines(residual_group),
            }
        )

    summary = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    if summary.empty:
        return summary

    summary = summary.sort_values(
        ["is_novel", "cohens_h", "hall", "weekday"],
        ascending=[False, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    summary["weekday"] = pd.Categorical(summary["weekday"], categories=WEEKDAY_ORDER, ordered=True)
    summary = summary.sort_values(
        ["is_novel", "cohens_h", "hall", "weekday"],
        ascending=[False, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    summary["weekday"] = summary["weekday"].astype(str)
    return summary.loc[:, SUMMARY_COLUMNS]


def merge_robustness_into_summary(summary: pd.DataFrame, robustness: pd.DataFrame) -> pd.DataFrame:
    if summary.empty or robustness.empty:
        return summary

    robust_cols = [
        "hall",
        "weekday",
        "dominant_category",
        "dominant_category_share_of_majority",
        "agreement_rate_excl_dominant",
        "p_value_excl_dominant",
        "signal_survives_without_dominant_category",
    ]
    merged = summary.drop(columns=[c for c in robust_cols if c not in ("hall", "weekday")]).merge(
        robustness.loc[:, robust_cols],
        on=["hall", "weekday"],
        how="left",
    )
    return merged.loc[:, SUMMARY_COLUMNS]


def _print_hall_report(hall: str, agreement: pd.DataFrame, summary: pd.DataFrame) -> None:
    hall_agreement = agreement.loc[agreement["hall"].astype(str) == hall].copy()
    hall_summary = summary.loc[summary["hall"].astype(str) == hall].copy()
    significant = hall_agreement.loc[hall_agreement["is_significant"].fillna(False)].copy()
    novel = hall_summary.loc[hall_summary["is_novel"].fillna(False)].copy()
    known = hall_summary.loc[~hall_summary["is_novel"].fillna(False)].copy()

    display_cols = [
        "weekday",
        "agreement_rate",
        "cohens_h",
        "pooled_hit104_rate_vs_hall",
        "pooled_diff_vs_hall",
        "dominant_category",
        "dominant_category_share_of_majority",
        "signal_survives_without_dominant_category",
        "top_positive_machines",
    ]

    print(f"\n=== {hall} ===")
    print(f"significant weekdays: {int(len(significant))}")

    print("novel weekdays:")
    if novel.empty:
        print("none")
    else:
        print(
            novel.loc[:, display_cols]
            .assign(_weekday_sort=novel["weekday"].map(_weekday_sort_key))
            .sort_values(["cohens_h", "_weekday_sort"], ascending=[False, True], kind="mergesort")
            .drop(columns=["_weekday_sort"])
            .to_string(index=False)
        )

    print("known-weekend weekdays:")
    if known.empty:
        print("none")
    else:
        print(
            known.loc[:, display_cols]
            .assign(_weekday_sort=known["weekday"].map(_weekday_sort_key))
            .sort_values(["cohens_h", "_weekday_sort"], ascending=[False, True], kind="mergesort")
            .drop(columns=["_weekday_sort"])
            .to_string(index=False)
        )


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _prepare_hall_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = _prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)
    if "hall" not in frame.columns:
        frame = frame.copy()
    return frame


def build_weekday_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    min_machine_days_total: int,
    min_cell_n: int,
    min_machines_for_test: int,
    fdr_alpha: float,
    known_event_threshold: float,
) -> dict[str, pd.DataFrame]:
    frame = _prepare_hall_frame(raw)
    if frame.empty:
        return {
            "residuals": pd.DataFrame(columns=RESIDUAL_WITH_CATEGORY_COLUMNS),
            "agreement": pd.DataFrame(columns=AGREEMENT_FULL_COLUMNS),
            "category_breakdown": pd.DataFrame(columns=CATEGORY_BREAKDOWN_COLUMNS),
            "robustness": pd.DataFrame(columns=ROBUSTNESS_COLUMNS),
            "summary": pd.DataFrame(columns=SUMMARY_COLUMNS),
        }

    if "hall" not in frame.columns:
        frame = frame.copy()
        frame["hall"] = hall

    residuals = compute_machine_weekday_residuals(
        hall,
        frame,
        min_machine_days_total=min_machine_days_total,
        min_cell_n=min_cell_n,
    )
    residuals = attach_machine_category(residuals, hall)

    agreement = aggregate_weekday_agreement(residuals, min_machines_for_test=min_machines_for_test)
    agreement = apply_fdr_per_hall(agreement, fdr_alpha=fdr_alpha)
    agreement = attach_weekday_coverage(agreement, {hall: frame}, known_event_threshold=known_event_threshold)
    agreement = attach_pooled_stats(agreement, {hall: frame})

    category_breakdown = build_category_breakdown(residuals, agreement)
    robustness = compute_dominant_category_robustness(
        residuals, agreement, min_machines_for_test=min_machines_for_test, fdr_alpha=fdr_alpha
    )

    summary = build_summary_report(agreement, residuals)
    summary = merge_robustness_into_summary(summary, robustness)

    return {
        "residuals": residuals,
        "agreement": agreement,
        "category_breakdown": category_breakdown,
        "robustness": robustness,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="機種横断曜日一致度スキャン")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--all-halls", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-machine-days-total", type=int, default=DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE)
    parser.add_argument("--min-cell-n", type=int, default=MIN_CELL_N)
    parser.add_argument("--min-machines-for-test", type=int, default=DEFAULT_MIN_MACHINES_FOR_TEST)
    parser.add_argument("--fdr-alpha", type=float, default=DEFAULT_FDR_ALPHA)
    parser.add_argument("--known-event-threshold", type=float, default=DEFAULT_KNOWN_EVENT_THRESHOLD)
    args = parser.parse_args(argv)

    output_dir = _ensure_output_dir(args.output_dir)
    halls = list(HALL_DBS) if args.all_halls else list(args.halls)

    residual_frames: list[pd.DataFrame] = []
    agreement_frames: list[pd.DataFrame] = []

    for hall in halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")

        raw = load_hall_df(hall)
        outputs = build_weekday_hall_outputs(
            hall,
            raw,
            min_machine_days_total=args.min_machine_days_total,
            min_cell_n=args.min_cell_n,
            min_machines_for_test=args.min_machines_for_test,
            fdr_alpha=args.fdr_alpha,
            known_event_threshold=args.known_event_threshold,
        )

        _write_csv(outputs["residuals"], output_dir / f"{hall}_machine_weekday_residuals.csv")
        _write_csv(outputs["agreement"], output_dir / f"{hall}_weekday_agreement.csv")
        _write_csv(outputs["category_breakdown"], output_dir / f"{hall}_category_breakdown.csv")
        _write_csv(outputs["robustness"], output_dir / f"{hall}_category_robustness.csv")

        residual_frames.append(outputs["residuals"])
        agreement_frames.append(outputs["agreement"])
        _print_hall_report(hall, outputs["agreement"], outputs["summary"])

    summary = (
        pd.concat(agreement_frames, ignore_index=True)
        if agreement_frames
        else pd.DataFrame(columns=AGREEMENT_FULL_COLUMNS)
    )
    _write_csv(summary, output_dir / "summary_report.csv")

    print(f"\nwritten summary: {output_dir / 'summary_report.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
