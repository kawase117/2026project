from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.mixture import GaussianMixture

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.machine_name_significance_scan import COINS_PER_GAME, _payout_rate, _prepare_frame

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DEFAULT_HALLS = ["蒲田7", "蒲田1", "みとや"]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "results"
DEFAULT_SHINDAI_EXCLUDE_DAYS = 30
DEFAULT_MIN_GAMES_FOR_GMM_FIT = 2000
DEFAULT_MIN_MACHINE_DAYS_FOR_GMM = 100

SOFT_LABEL_COLUMNS = [
    "date",
    "machine_name",
    "machine_number",
    "games",
    "diff",
    "payout_rate",
    "hit104",
    "p_high_setting",
    "gmm_fit_used",
    "note",
]

CELL_VARIANCE_COLUMNS = [
    "hall",
    "dd",
    "machine_digit",
    "n_days",
    "var_hit104",
    "var_p_high_setting",
    "variance_reduced",
]


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _ensure_payout_rate(frame: pd.DataFrame) -> pd.DataFrame:
    if "payout_rate" in frame.columns:
        return frame.copy()

    work = frame.copy()
    if {"games", "diff"}.issubset(work.columns):
        work["payout_rate"] = _payout_rate(work)
    else:
        work["payout_rate"] = np.nan
    return work


def _machine_fit_subset(frame: pd.DataFrame, *, min_games_for_gmm_fit: int) -> pd.DataFrame:
    work = _ensure_payout_rate(frame)
    games = pd.to_numeric(work["games"], errors="coerce")
    return work.loc[games.ge(min_games_for_gmm_fit) & work["payout_rate"].notna()].copy()


def _fit_machine_gmm(fit_frame: pd.DataFrame) -> tuple[GaussianMixture, int]:
    model = GaussianMixture(n_components=2, random_state=42, n_init=10)
    values = pd.to_numeric(fit_frame["payout_rate"], errors="coerce").to_numpy(dtype=float).reshape(-1, 1)
    model.fit(values)
    high_component = int(np.argmax(model.means_.reshape(-1)))
    return model, high_component


def _safe_corr(x: pd.Series, y: pd.Series) -> dict[str, float | None]:
    valid = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(valid) < 2 or valid["x"].nunique() < 2 or valid["y"].nunique() < 2:
        return {"pearson_r": None, "pearson_p": None, "spearman_r": None, "spearman_p": None}

    pearson_r, pearson_p = pearsonr(valid["x"], valid["y"])
    spearman_r, spearman_p = spearmanr(valid["x"], valid["y"])
    return {
        "pearson_r": float(pearson_r),
        "pearson_p": float(pearson_p),
        "spearman_r": float(spearman_r),
        "spearman_p": float(spearman_p),
    }


def _score_machine_group(
    group: pd.DataFrame,
    *,
    min_games_for_gmm_fit: int,
    min_machine_days_for_gmm: int,
) -> pd.DataFrame:
    work = _ensure_payout_rate(group)
    work = work.sort_values(["date", "machine_number"], kind="mergesort").copy()

    fit_frame = _machine_fit_subset(work, min_games_for_gmm_fit=min_games_for_gmm_fit)
    if len(fit_frame) < min_machine_days_for_gmm:
        work["p_high_setting"] = np.nan
        work["gmm_fit_used"] = False
        work["note"] = f"skipped: fit rows {len(fit_frame)} < {min_machine_days_for_gmm}"
        return work

    if fit_frame["payout_rate"].nunique(dropna=True) < 2:
        work["p_high_setting"] = np.nan
        work["gmm_fit_used"] = False
        work["note"] = "skipped: insufficient payout variance"
        return work

    try:
        model, high_component = _fit_machine_gmm(fit_frame)
        values = pd.to_numeric(work["payout_rate"], errors="coerce").to_numpy(dtype=float).reshape(-1, 1)
        probs = model.predict_proba(values)[:, high_component]
        work["p_high_setting"] = probs
        work["gmm_fit_used"] = True
        work["note"] = (
            f"fit_rows={len(fit_frame)}; scored_all_rows={len(work)}; min_games_for_fit={min_games_for_gmm_fit}"
        )
    except Exception as exc:  # pragma: no cover - defensive path
        work["p_high_setting"] = np.nan
        work["gmm_fit_used"] = False
        work["note"] = f"fit_failed: {type(exc).__name__}: {exc}"

    return work


def _build_cell_variance_comparison(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    if "dd" not in work.columns:
        work["dd"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce").dt.day
    work["machine_digit"] = pd.to_numeric(work["machine_number"], errors="coerce").mod(10)
    work["machine_digit"] = work["machine_digit"].round().astype("Int64")

    rows: list[dict[str, object]] = []
    for (dd, machine_digit), group in work.groupby(["dd", "machine_digit"], dropna=False):
        hit_var = pd.to_numeric(group["hit104"], errors="coerce").var(ddof=0)
        p_high = pd.to_numeric(group["p_high_setting"], errors="coerce").dropna()
        p_var = p_high.var(ddof=0) if len(p_high) >= 2 else np.nan
        reduced = bool(pd.notna(hit_var) and pd.notna(p_var) and float(p_var) < float(hit_var))
        rows.append(
            {
                "hall": hall,
                "dd": int(dd) if pd.notna(dd) else pd.NA,
                "machine_digit": int(machine_digit) if pd.notna(machine_digit) else pd.NA,
                "n_days": int(len(group)),
                "var_hit104": float(hit_var) if pd.notna(hit_var) else np.nan,
                "var_p_high_setting": float(p_var) if pd.notna(p_var) else np.nan,
                "variance_reduced": reduced,
            }
        )

    return pd.DataFrame(rows, columns=CELL_VARIANCE_COLUMNS)


def build_hall_outputs(
    hall: str,
    raw: pd.DataFrame,
    *,
    shindai_exclude_days: int,
    min_games_for_gmm_fit: int,
    min_machine_days_for_gmm: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    prepared = _prepare_frame(raw, shindai_exclude_days=shindai_exclude_days)
    if "payout_rate" not in prepared.columns:
        prepared = _ensure_payout_rate(prepared)
        prepared["hit104"] = (pd.to_numeric(prepared["payout_rate"], errors="coerce") >= 104.0).astype(int)

    scored_groups = [
        _score_machine_group(
            group,
            min_games_for_gmm_fit=min_games_for_gmm_fit,
            min_machine_days_for_gmm=min_machine_days_for_gmm,
        )
        for _, group in prepared.groupby("machine_name", sort=False)
    ]

    scored_frame = pd.concat(scored_groups, ignore_index=True) if scored_groups else prepared.copy()
    scored_frame = scored_frame.sort_values(["date", "machine_number", "machine_name"], kind="mergesort").reset_index(
        drop=True
    )

    cell_frame = _build_cell_variance_comparison(scored_frame, hall=hall)
    soft_frame = scored_frame.loc[:, [col for col in SOFT_LABEL_COLUMNS if col in scored_frame.columns]].copy()
    corr = _safe_corr(soft_frame["hit104"], soft_frame["p_high_setting"])

    summary = {
        "hall": hall,
        "n_rows": int(len(soft_frame)),
        "n_scored_rows": int(soft_frame["p_high_setting"].notna().sum()),
        "n_scored_machines": int(soft_frame.loc[soft_frame["gmm_fit_used"].fillna(False), "machine_name"].nunique()),
        "variance_reduced_cells": int(cell_frame["variance_reduced"].sum()),
        **corr,
    }
    return soft_frame, cell_frame, summary


def _write_hall_outputs(output_dir: Path, hall: str, soft_frame: pd.DataFrame, cell_frame: pd.DataFrame) -> None:
    soft_path = output_dir / f"{hall}_soft_label_comparison.csv"
    cell_path = output_dir / f"{hall}_cell_variance_comparison.csv"
    soft_frame.to_csv(soft_path, index=False, encoding="utf-8-sig")
    cell_frame.to_csv(cell_path, index=False, encoding="utf-8-sig")


def _format_corr(value: float | None) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.4f}"


def run_analysis(
    halls: Iterable[str],
    *,
    output_dir: Path,
    shindai_exclude_days: int,
    min_games_for_gmm_fit: int,
    min_machine_days_for_gmm: int,
) -> list[dict[str, object]]:
    output_dir = _ensure_output_dir(output_dir)
    summaries: list[dict[str, object]] = []

    for hall in halls:
        raw = load_hall_df(hall)
        soft_frame, cell_frame, summary = build_hall_outputs(
            hall,
            raw,
            shindai_exclude_days=shindai_exclude_days,
            min_games_for_gmm_fit=min_games_for_gmm_fit,
            min_machine_days_for_gmm=min_machine_days_for_gmm,
        )
        _write_hall_outputs(output_dir, hall, soft_frame, cell_frame)
        summaries.append(summary)

        date_min = pd.to_datetime(soft_frame["date"], format="%Y%m%d", errors="coerce").min()
        date_max = pd.to_datetime(soft_frame["date"], format="%Y%m%d", errors="coerce").max()
        if pd.notna(date_min) and pd.notna(date_max):
            date_range = f"{date_min:%Y-%m-%d}..{date_max:%Y-%m-%d}"
        else:
            date_range = "n/a"
        print(f"[{hall}] rows={summary['n_rows']} scored={summary['n_scored_rows']} date_range={date_range}")
        print(
            f"  pearson_r={_format_corr(summary['pearson_r'])} "
            f"spearman_r={_format_corr(summary['spearman_r'])} "
            f"variance_reduced_cells={summary['variance_reduced_cells']}/{len(cell_frame)}"
        )

    return summaries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate GMM-based soft labels and variance comparison CSVs.")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--shindai-exclude-days", type=int, default=DEFAULT_SHINDAI_EXCLUDE_DAYS)
    parser.add_argument("--min-games-for-gmm-fit", type=int, default=DEFAULT_MIN_GAMES_FOR_GMM_FIT)
    parser.add_argument("--min-machine-days-for-gmm", type=int, default=DEFAULT_MIN_MACHINE_DAYS_FOR_GMM)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    unknown_halls = [hall for hall in args.halls if hall not in HALL_DBS]
    if unknown_halls:
        parser.error(f"unknown halls: {unknown_halls}")

    run_analysis(
        args.halls,
        output_dir=args.output_dir,
        shindai_exclude_days=args.shindai_exclude_days,
        min_games_for_gmm_fit=args.min_games_for_gmm_fit,
        min_machine_days_for_gmm=args.min_machine_days_for_gmm,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
