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

from eda.core import HALL_DBS, load_hall_df
from eda.machine_axis_pattern_scan import MIN_CELL_N
from eda.machine_dd_cross_agreement_scan import (
    DEFAULT_FDR_ALPHA,
    DEFAULT_HALLS,
    DEFAULT_KNOWN_EVENT_THRESHOLD,
    DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE,
    DEFAULT_MIN_MACHINES_FOR_TEST,
    build_hall_outputs,
)
from eda.machine_name_significance_scan import DEFAULT_SHINDAI_EXCLUDE_DAYS, _prepare_frame
from eda.machine_volatility_event_gap_scan import _parse_halls

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eda" / "results" / "machine_dd_cross_agreement_deepdive"

FULL_RANKING_COLUMNS = [
    "hall",
    "dd",
    "is_novel",
    "machine_name",
    "category",
    "n",
    "hit104_rate",
    "baseline_hit104_rate",
    "residual",
    "rank_desc",
    "rank_asc",
    "p_value",
    "q_value",
    "is_machine_significant",
]

SELF_SIGNIFICANCE_COLUMNS = [
    "hall",
    "dd",
    "machine_name",
    "n_at_dd",
    "hits_at_dd",
    "hit104_rate_at_dd",
    "n_rest",
    "rest_hit104_rate",
    "p_value",
]

SELF_SIGNIFICANCE_WITH_FDR_COLUMNS = SELF_SIGNIFICANCE_COLUMNS + ["q_value", "is_machine_significant"]

REPEAT_COLUMNS = [
    "hall",
    "machine_name",
    "category",
    "n_appearances",
    "dds_appeared",
    "residuals_at_each_dd",
    "n_machine_significant_appearances",
]

CROSS_HALL_COLUMNS = [
    "machine_name",
    "category",
    "n_halls",
    "halls",
    "dds",
    "dd_matches_across_halls",
]


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _format_residual(value: float) -> str:
    return f"{value:+.1f}"


def build_full_machine_ranking(residuals: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    if residuals.empty or summary.empty:
        return pd.DataFrame(columns=FULL_RANKING_COLUMNS)

    valid_pairs = summary.loc[:, ["hall", "dd", "is_novel"]].copy()
    valid_pairs["hall"] = valid_pairs["hall"].astype(str)
    valid_pairs["dd"] = pd.to_numeric(valid_pairs["dd"], errors="coerce").astype("Int64")

    working = residuals.copy()
    working["hall"] = working["hall"].astype(str)
    working["dd"] = pd.to_numeric(working["dd"], errors="coerce").astype("Int64")
    working = working.merge(valid_pairs, on=["hall", "dd"], how="inner")
    if working.empty:
        return pd.DataFrame(columns=FULL_RANKING_COLUMNS)

    working["residual"] = pd.to_numeric(working["residual"], errors="coerce")
    working = working.dropna(subset=["residual"]).copy()
    if working.empty:
        return pd.DataFrame(columns=FULL_RANKING_COLUMNS)

    desc = working.sort_values(
        ["hall", "dd", "residual", "machine_name"],
        ascending=[True, True, False, True],
        kind="mergesort",
    ).copy()
    desc["rank_desc"] = desc.groupby(["hall", "dd"], sort=False).cumcount() + 1

    asc = working.sort_values(
        ["hall", "dd", "residual", "machine_name"],
        ascending=[True, True, True, True],
        kind="mergesort",
    ).copy()
    asc["rank_asc"] = asc.groupby(["hall", "dd"], sort=False).cumcount() + 1

    ranked = desc.merge(
        asc.loc[:, ["hall", "dd", "machine_name", "rank_asc"]],
        on=["hall", "dd", "machine_name"],
        how="left",
    )

    ranked["dd"] = ranked["dd"].astype(int)
    ranked["rank_desc"] = ranked["rank_desc"].astype(int)
    ranked["rank_asc"] = ranked["rank_asc"].astype(int)
    ranked["n"] = pd.to_numeric(ranked["n"], errors="coerce").astype(int)
    ranked["hit104_rate"] = pd.to_numeric(ranked["hit104_rate"], errors="coerce")
    ranked["baseline_hit104_rate"] = pd.to_numeric(ranked["baseline_hit104_rate"], errors="coerce")
    ranked["residual"] = pd.to_numeric(ranked["residual"], errors="coerce")
    ranked["is_novel"] = ranked["is_novel"].fillna(False).astype(bool)

    ordered = ranked.sort_values(
        ["hall", "dd", "rank_desc", "machine_name"],
        ascending=[True, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return ordered.loc[:, [c for c in FULL_RANKING_COLUMNS if c in ordered.columns]]


def compute_machine_dd_self_significance(
    hall: str,
    frame: pd.DataFrame,
    target_dds: set[int],
    *,
    min_machine_days_total: int,
    min_cell_n: int,
) -> pd.DataFrame:
    if frame.empty or not target_dds:
        return pd.DataFrame(columns=SELF_SIGNIFICANCE_COLUMNS)

    rows: list[dict[str, object]] = []
    working = frame.copy()
    if "hall" not in working.columns:
        working["hall"] = hall
    working["hall"] = working["hall"].astype(str)
    working["dd"] = pd.to_numeric(working["dd"], errors="coerce").astype("Int64")
    working["hit104"] = pd.to_numeric(working["hit104"], errors="coerce")

    for machine_name, machine_frame in working.groupby("machine_name", sort=True):
        machine_frame = machine_frame.copy()
        if len(machine_frame) < min_machine_days_total:
            continue

        for dd in sorted(int(dd) for dd in target_dds):
            at_dd = machine_frame.loc[machine_frame["dd"].eq(dd)]
            n_at_dd = int(len(at_dd))
            if n_at_dd < min_cell_n:
                continue

            rest = machine_frame.loc[~machine_frame["dd"].eq(dd)]
            n_rest = int(len(rest))
            if n_rest == 0:
                continue

            hits_at_dd = int(pd.to_numeric(at_dd["hit104"], errors="coerce").fillna(0).sum())
            hits_rest = int(pd.to_numeric(rest["hit104"], errors="coerce").fillna(0).sum())
            rest_rate = float(hits_rest / n_rest)
            p_value = float(binomtest(hits_at_dd, n_at_dd, p=rest_rate, alternative="two-sided").pvalue)

            rows.append(
                {
                    "hall": hall,
                    "dd": int(dd),
                    "machine_name": str(machine_name),
                    "n_at_dd": n_at_dd,
                    "hits_at_dd": hits_at_dd,
                    "hit104_rate_at_dd": float(hits_at_dd / n_at_dd),
                    "n_rest": n_rest,
                    "rest_hit104_rate": rest_rate,
                    "p_value": p_value,
                }
            )

    return pd.DataFrame(rows, columns=SELF_SIGNIFICANCE_COLUMNS)


def apply_fdr_per_hall_dd(self_significance: pd.DataFrame, *, fdr_alpha: float) -> pd.DataFrame:
    if self_significance.empty:
        result = self_significance.copy()
        result["q_value"] = pd.Series(dtype=float)
        result["is_machine_significant"] = pd.Series(dtype=bool)
        return result.reindex(columns=SELF_SIGNIFICANCE_WITH_FDR_COLUMNS)

    result = self_significance.copy()
    result["q_value"] = np.nan
    result["is_machine_significant"] = False

    for _, indexer in result.groupby(["hall", "dd"], sort=False).groups.items():
        group_index = result.loc[indexer].index
        valid_mask = result.loc[group_index, "p_value"].notna().to_numpy()
        if not valid_mask.any():
            continue

        selected_index = group_index[valid_mask]
        selected = result.loc[selected_index, "p_value"].astype(float).to_numpy()
        _, q_values, _, _ = multipletests(selected, method="fdr_bh")
        result.loc[selected_index, "q_value"] = q_values

    result["is_machine_significant"] = result["q_value"].lt(fdr_alpha).fillna(False)
    return result.loc[:, SELF_SIGNIFICANCE_WITH_FDR_COLUMNS]


def merge_ranking_with_significance(ranking: pd.DataFrame, self_significance: pd.DataFrame) -> pd.DataFrame:
    if ranking.empty:
        return ranking.copy()

    if self_significance.empty:
        merged = ranking.copy()
        merged["p_value"] = np.nan
        merged["q_value"] = np.nan
        merged["is_machine_significant"] = False
        return merged

    merged = ranking.merge(
        self_significance.loc[:, ["hall", "dd", "machine_name", "p_value", "q_value", "is_machine_significant"]],
        on=["hall", "dd", "machine_name"],
        how="left",
    )
    merged["is_machine_significant"] = merged["is_machine_significant"].fillna(False).astype(bool)
    return merged


def find_repeat_contributors(ranking_with_significance: pd.DataFrame, *, top_n: int = 10) -> pd.DataFrame:
    if ranking_with_significance.empty:
        return pd.DataFrame(columns=REPEAT_COLUMNS)

    working = ranking_with_significance.copy()
    working["hall"] = working["hall"].astype(str)
    working["dd"] = pd.to_numeric(working["dd"], errors="coerce").astype("Int64")
    working["rank_desc"] = pd.to_numeric(working["rank_desc"], errors="coerce")
    working["rank_asc"] = pd.to_numeric(working["rank_asc"], errors="coerce")
    working["residual"] = pd.to_numeric(working["residual"], errors="coerce")

    major = working.loc[(working["rank_desc"] <= top_n) | (working["rank_asc"] <= top_n)].copy()
    if major.empty:
        return pd.DataFrame(columns=REPEAT_COLUMNS)

    rows: list[dict[str, object]] = []
    for (hall, machine_name), group in major.groupby(["hall", "machine_name"], sort=False):
        dds_seen: list[int] = []
        residual_parts: list[str] = []
        sig_count = 0
        category_values = [value for value in group["category"].astype(str).tolist() if value]
        category = category_values[0] if category_values else ""

        for _, row in group.iterrows():
            dd = int(row["dd"])
            if dd not in dds_seen:
                dds_seen.append(dd)
            residual_parts.append(_format_residual(float(row["residual"])))
            if bool(row.get("is_machine_significant", False)):
                sig_count += 1

        if len(dds_seen) < 2:
            continue

        rows.append(
            {
                "hall": hall,
                "machine_name": machine_name,
                "category": category,
                "n_appearances": len(dds_seen),
                "dds_appeared": ";".join(str(dd) for dd in dds_seen),
                "residuals_at_each_dd": ";".join(residual_parts),
                "n_machine_significant_appearances": sig_count,
            }
        )

    result = pd.DataFrame(rows, columns=REPEAT_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(
        ["n_appearances", "n_machine_significant_appearances", "hall", "machine_name"],
        ascending=[False, False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def find_cross_hall_consistency(ranking_with_significance: pd.DataFrame) -> pd.DataFrame:
    if ranking_with_significance.empty:
        return pd.DataFrame(columns=CROSS_HALL_COLUMNS)

    working = ranking_with_significance.copy()
    working["hall"] = working["hall"].astype(str)
    working["dd"] = pd.to_numeric(working["dd"], errors="coerce").astype("Int64")
    working["rank_desc"] = pd.to_numeric(working["rank_desc"], errors="coerce")
    working["rank_asc"] = pd.to_numeric(working["rank_asc"], errors="coerce")
    major = working.loc[(working["rank_desc"] <= 10) | (working["rank_asc"] <= 10)].copy()
    if major.empty:
        return pd.DataFrame(columns=CROSS_HALL_COLUMNS)

    rows: list[dict[str, object]] = []
    for machine_name, group in major.groupby("machine_name", sort=False):
        hall_order: list[str] = []
        dds_order: list[int] = []
        dd_counts: dict[int, int] = {}
        category_values = [value for value in group["category"].astype(str).tolist() if value]
        category = category_values[0] if category_values else ""

        for _, row in group.iterrows():
            hall = str(row["hall"])
            dd = int(row["dd"])
            if hall not in hall_order:
                hall_order.append(hall)
            dds_order.append(dd)
            dd_counts[dd] = dd_counts.get(dd, 0) + 1

        if len(hall_order) < 2:
            continue

        matches = [str(dd) for dd, count in dd_counts.items() if count > 1]
        rows.append(
            {
                "machine_name": machine_name,
                "category": category,
                "n_halls": len(hall_order),
                "halls": ";".join(hall_order),
                "dds": ";".join(str(dd) for dd in dds_order),
                "dd_matches_across_halls": ";".join(matches),
            }
        )

    result = pd.DataFrame(rows, columns=CROSS_HALL_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["n_halls", "machine_name"], ascending=[False, True], kind="mergesort").reset_index(
        drop=True
    )


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _print_hall_report(hall: str, ranking: pd.DataFrame) -> None:
    hall_rows = ranking.loc[
        (ranking["hall"].astype(str) == hall)
        & ranking["is_machine_significant"].fillna(False)
        & ((ranking["rank_desc"] <= 5) | (ranking["rank_asc"] <= 5))
    ].copy()
    hall_rows = hall_rows.sort_values(["residual", "machine_name"], ascending=[False, True], kind="mergesort")

    print(f"\n=== {hall} ===")
    if hall_rows.empty:
        print("none")
        return
    print(hall_rows.loc[:, ["dd", "machine_name", "residual", "q_value"]].to_string(index=False))


def _prepare_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    min_machine_days_total: int,
    min_cell_n: int,
    min_machines_for_test: int,
    fdr_alpha: float,
    known_event_threshold: float,
) -> dict[str, pd.DataFrame]:
    prepared = _prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)
    if "hall" not in prepared.columns:
        prepared = prepared.copy()
        prepared["hall"] = hall

    outputs = build_hall_outputs(
        hall,
        raw,
        min_machine_days_total=min_machine_days_total,
        min_cell_n=min_cell_n,
        min_machines_for_test=min_machines_for_test,
        fdr_alpha=fdr_alpha,
        known_event_threshold=known_event_threshold,
    )

    residuals = outputs["residuals"].copy()
    summary = outputs["summary"].copy()
    ranking = build_full_machine_ranking(residuals, summary)
    target_dds = set(pd.to_numeric(summary["dd"], errors="coerce").dropna().astype(int).tolist())
    self_significance = compute_machine_dd_self_significance(
        hall,
        prepared,
        target_dds,
        min_machine_days_total=min_machine_days_total,
        min_cell_n=min_cell_n,
    )
    self_significance = apply_fdr_per_hall_dd(self_significance, fdr_alpha=fdr_alpha)
    merged = merge_ranking_with_significance(ranking, self_significance)
    return {
        "ranking": merged,
        "repeat": find_repeat_contributors(merged),
        "cross": find_cross_hall_consistency(merged),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="機種横断DD一致度の機種名レベル深堀り")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--all-halls", action="store_true")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-machine-days-total", type=int, default=DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE)
    parser.add_argument("--min-cell-n", type=int, default=MIN_CELL_N)
    parser.add_argument("--min-machines-for-test", type=int, default=DEFAULT_MIN_MACHINES_FOR_TEST)
    parser.add_argument("--fdr-alpha", type=float, default=DEFAULT_FDR_ALPHA)
    parser.add_argument("--known-event-threshold", type=float, default=DEFAULT_KNOWN_EVENT_THRESHOLD)
    args = parser.parse_args(argv)

    output_dir = _ensure_output_dir(args.output_dir)
    halls = list(HALL_DBS) if args.all_halls else list(args.halls)

    all_rankings: list[pd.DataFrame] = []
    for hall in halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")

        raw = load_hall_df(hall)
        outputs = _prepare_hall_outputs(
            hall,
            raw,
            min_machine_days_total=args.min_machine_days_total,
            min_cell_n=args.min_cell_n,
            min_machines_for_test=args.min_machines_for_test,
            fdr_alpha=args.fdr_alpha,
            known_event_threshold=args.known_event_threshold,
        )

        ranking = outputs["ranking"]
        _write_csv(ranking, output_dir / f"{hall}_full_ranking.csv")
        _print_hall_report(hall, ranking)
        all_rankings.append(ranking)

    combined = (
        pd.concat(all_rankings, ignore_index=True) if all_rankings else pd.DataFrame(columns=FULL_RANKING_COLUMNS)
    )
    repeat = find_repeat_contributors(combined, top_n=args.top_n)
    cross = find_cross_hall_consistency(combined)

    _write_csv(repeat, output_dir / "repeat_contributors.csv")
    _write_csv(cross, output_dir / "cross_hall_consistency.csv")

    print(f"\nrepeat_contributors: {len(repeat)}")
    print(f"cross_hall_consistency: {len(cross)}")
    print(f"written: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
