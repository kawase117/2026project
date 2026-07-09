from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import adjusted_rand_score, silhouette_score
from statsmodels.formula.api import ols

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import load_hall_df
from eda.machine_name_significance_scan import DEFAULT_SHINDAI_EXCLUDE_DAYS, _prepare_frame
from eda.section_kakuban_axis_pattern_scan import _load_hall_layout_frame
from ml.analysis.kamata_kakuban_section_residual_eda import (
    DEFAULT_COORDS_1,
    DEFAULT_COORDS_7_2F,
    DEFAULT_COORDS_7_3F,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_HALLS = ["蒲田7", "蒲田1", "みとや"]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ml" / "experiments" / "latent_grouping" / "results"
DEFAULT_K_RANGE = (2, 10)
MIN_COMMON_DAYS_DEFAULT = 90

OUTPUT_COLUMNS = [
    "machine_number",
    "machine_name",
    "section",
    "kakuban",
    "machine_digit",
    "row_group",
    "cluster_id",
]

KNOWN_GROUP_COLUMNS = ["section", "kakuban", "row_group", "machine_digit"]
RESIDUAL_COL = "residual_payout_rate"
SEQUENTIAL_RESIDUAL_COL = "sequential_residual_payout_rate"
FIXED_EFFECT_FORMULA = "payout_rate ~ C(machine_name) + C(section) + C(kakuban) + C(machine_digit) + C(row_group)"


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _parse_k_range(value: str) -> tuple[int, int]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("k-range must be start,end")
    try:
        start, end = (int(parts[0]), int(parts[1]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("k-range must contain integers") from exc
    if start < 2 or end < start:
        raise argparse.ArgumentTypeError("k-range must satisfy 2 <= start <= end")
    return start, end


def _ensure_output_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _payout_rate(frame: pd.DataFrame) -> pd.Series:
    games = pd.to_numeric(frame["games"], errors="coerce")
    diff = pd.to_numeric(frame["diff"], errors="coerce")
    denom = games * 3.0
    return np.where(denom.gt(0), ((denom + diff) / denom) * 100.0, np.nan)


def _prepare_input_frame(raw: pd.DataFrame, *, shindai_exclude_days: int) -> pd.DataFrame:
    frame = _prepare_frame(raw, shindai_exclude_days=shindai_exclude_days).copy()
    frame["date"] = frame["date"].astype(str)
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["games"] = pd.to_numeric(frame["games"], errors="coerce")
    frame["diff"] = pd.to_numeric(frame["diff"], errors="coerce")
    frame = frame.dropna(subset=["date", "machine_number", "machine_name", "games", "diff", "payout_rate"]).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["machine_digit"] = frame["machine_number"] % 10
    return frame.reset_index(drop=True)


def _resolve_layout_frame(
    hall: str,
    *,
    coords1: Path,
    coords7_2f: Path,
    coords7_3f: Path,
    mitoya_db_path: Path | None,
    mitoya_db_dir: Path,
) -> pd.DataFrame:
    layout = _load_hall_layout_frame(
        hall,
        coords1=coords1,
        coords7_2f=coords7_2f,
        coords7_3f=coords7_3f,
        mitoya_db_path=mitoya_db_path,
        mitoya_db_dir=mitoya_db_dir,
    )
    layout = layout.copy()
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
    layout["rank_from_min"] = pd.to_numeric(layout["rank_from_min"], errors="coerce")
    layout["section"] = layout["section"].astype("string")
    layout = layout.dropna(subset=["machine_number", "rank_from_min", "section"]).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["rank_from_min"] = layout["rank_from_min"].astype(int)
    layout["section"] = layout["section"].astype(str)
    return layout.loc[:, ["machine_number", "rank_from_min", "section"]].drop_duplicates(subset=["machine_number"])


def _build_hall_frame(
    hall: str,
    *,
    shindai_exclude_days: int,
    coords1: Path,
    coords7_2f: Path,
    coords7_3f: Path,
    mitoya_db_path: Path | None,
    mitoya_db_dir: Path,
) -> pd.DataFrame:
    raw = load_hall_df(hall)
    frame = _prepare_input_frame(raw, shindai_exclude_days=shindai_exclude_days)
    layout = _resolve_layout_frame(
        hall,
        coords1=coords1,
        coords7_2f=coords7_2f,
        coords7_3f=coords7_3f,
        mitoya_db_path=mitoya_db_path,
        mitoya_db_dir=mitoya_db_dir,
    )

    merged = frame.merge(layout, on="machine_number", how="inner", validate="many_to_one")
    merged["kakuban"] = merged["rank_from_min"].astype(int)
    merged["row_group"] = (merged["machine_number"] // 10) * 10
    merged["date"] = merged["date"].astype(str)
    merged = merged.drop(columns=["rank_from_min"])
    return merged.reset_index(drop=True)


def compute_fixed_effect_residuals(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"machine_name", "section", "kakuban", "machine_digit", "row_group"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing required columns for residualization: {missing}")

    work = frame.copy()
    if "payout_rate" not in work.columns:
        if {"games", "diff"}.issubset(work.columns):
            work["payout_rate"] = _payout_rate(work)
        else:
            raise ValueError("missing payout_rate and cannot derive it from games/diff")
    for column in ["machine_name", "section", "kakuban", "machine_digit", "row_group"]:
        work[column] = work[column].astype("string") if column in {"machine_name", "section"} else work[column]

    fit_frame = work.dropna(
        subset=["payout_rate", "machine_name", "section", "kakuban", "machine_digit", "row_group"]
    ).copy()
    if fit_frame.empty:
        fit_frame[RESIDUAL_COL] = pd.Series(dtype=float)
        return fit_frame

    fit = ols(FIXED_EFFECT_FORMULA, data=fit_frame).fit()
    fit_frame[RESIDUAL_COL] = fit.resid
    fit_frame["residual_fitted_payout_rate"] = fit.fittedvalues
    return fit_frame.reset_index(drop=True)


def compute_sequential_demeaned_residuals(frame: pd.DataFrame) -> pd.DataFrame:
    required = {*KNOWN_GROUP_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing required columns for demeaning: {missing}")

    work = frame.copy()
    if "payout_rate" not in work.columns:
        if {"games", "diff"}.issubset(work.columns):
            work["payout_rate"] = _payout_rate(work)
        else:
            raise ValueError("missing payout_rate and cannot derive it from games/diff")
    work[SEQUENTIAL_RESIDUAL_COL] = pd.to_numeric(work["payout_rate"], errors="coerce")
    for column in ["machine_name", "section", "kakuban", "machine_digit", "row_group"]:
        group_mean = work.groupby(column, dropna=False)[SEQUENTIAL_RESIDUAL_COL].transform("mean")
        work[SEQUENTIAL_RESIDUAL_COL] = work[SEQUENTIAL_RESIDUAL_COL] - group_mean
    return work.dropna(subset=[SEQUENTIAL_RESIDUAL_COL]).reset_index(drop=True)


def compute_pairwise_correlations(
    pivot: pd.DataFrame,
    *,
    min_common_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix = pivot.copy()
    matrix.columns = pd.Index(pd.to_numeric(matrix.columns, errors="coerce").astype(int))
    matrix = matrix.loc[:, ~matrix.columns.duplicated()].copy()
    machine_ids = list(matrix.columns)
    corr = pd.DataFrame(np.nan, index=machine_ids, columns=machine_ids, dtype=float)
    common_days = pd.DataFrame(0, index=machine_ids, columns=machine_ids, dtype=int)

    for i, left in enumerate(machine_ids):
        left_series = pd.to_numeric(matrix[left], errors="coerce")
        for j in range(i, len(machine_ids)):
            right = machine_ids[j]
            right_series = pd.to_numeric(matrix[right], errors="coerce")
            valid = left_series.notna() & right_series.notna()
            count = int(valid.sum())
            common_days.loc[left, right] = count
            common_days.loc[right, left] = count
            if left == right:
                corr.loc[left, right] = 1.0
                continue
            if count < min_common_days:
                continue
            value = left_series.loc[valid].corr(right_series.loc[valid])
            corr.loc[left, right] = value
            corr.loc[right, left] = value
    return corr, common_days


def _distance_matrix_from_corr(corr: pd.DataFrame) -> pd.DataFrame:
    distance = 1.0 - corr.astype(float)
    distance = distance.clip(lower=0.0, upper=2.0)
    array = distance.to_numpy(copy=True)
    np.fill_diagonal(array, 0.0)
    return pd.DataFrame(array, index=distance.index, columns=distance.columns).fillna(2.0)


def _select_cluster_count(distance: pd.DataFrame, *, k_range: tuple[int, int]) -> tuple[int, list[dict[str, object]]]:
    n_items = distance.shape[0]
    if n_items < 2:
        return 1, []

    condensed = squareform(distance.to_numpy(), checks=False)
    linkage_matrix = linkage(condensed, method="ward")
    best_k = 2
    best_score = float("-inf")
    scores: list[dict[str, object]] = []
    lower, upper = k_range
    for k in range(lower, min(upper, n_items) + 1):
        labels = fcluster(linkage_matrix, t=k, criterion="maxclust")
        unique = np.unique(labels)
        score = float("nan")
        if len(unique) >= 2 and len(unique) < n_items:
            try:
                score = float(silhouette_score(distance.to_numpy(), labels, metric="precomputed"))
            except ValueError:
                score = float("nan")
        scores.append({"k": k, "silhouette": score, "n_clusters": int(len(unique))})
        if not np.isnan(score) and score > best_score:
            best_score = score
            best_k = k

    if not scores:
        return min(max(2, lower), max(2, n_items)), scores

    if best_score == float("-inf"):
        best_k = scores[0]["k"] if scores else 2
    return int(best_k), scores


def assign_clusters(corr: pd.DataFrame, *, k_range: tuple[int, int]) -> tuple[pd.Series, pd.DataFrame]:
    if corr.empty:
        return pd.Series(dtype=int, name="cluster_id"), pd.DataFrame(columns=["k", "silhouette", "n_clusters"])
    if corr.shape[0] == 1:
        return pd.Series([1], index=corr.index, name="cluster_id"), pd.DataFrame(
            columns=["k", "silhouette", "n_clusters"]
        )

    distance = _distance_matrix_from_corr(corr)
    chosen_k, scores = _select_cluster_count(distance, k_range=k_range)
    condensed = squareform(distance.to_numpy(), checks=False)
    linkage_matrix = linkage(condensed, method="ward")
    labels = fcluster(linkage_matrix, t=chosen_k, criterion="maxclust")
    cluster_ids = pd.Series(labels, index=corr.index, name="cluster_id").astype(int)
    return cluster_ids, pd.DataFrame(scores)


def _build_machine_axis_frame(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "machine_number",
        "machine_name",
        "section",
        "kakuban",
        "machine_digit",
        "row_group",
        "date",
        "payout_rate",
    ]
    work = frame.loc[:, [col for col in cols if col in frame.columns]].copy()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")
    work["machine_digit"] = pd.to_numeric(work["machine_digit"], errors="coerce")
    work["row_group"] = pd.to_numeric(work["row_group"], errors="coerce")
    work = work.dropna(
        subset=[
            "machine_number",
            "machine_name",
            "section",
            "kakuban",
            "machine_digit",
            "row_group",
            "date",
            "payout_rate",
        ]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["kakuban"] = work["kakuban"].astype(int)
    work["machine_digit"] = work["machine_digit"].astype(int)
    work["row_group"] = work["row_group"].astype(int)
    work["date"] = work["date"].astype(str)
    return work.reset_index(drop=True)


def _build_pivot(frame: pd.DataFrame, value_col: str) -> pd.DataFrame:
    pivot = frame.pivot_table(index="date", columns="machine_number", values=value_col, aggfunc="mean")
    pivot = pivot.sort_index(axis=0).sort_index(axis=1)
    return pivot


def _summarize_ari(frame: pd.DataFrame, cluster_ids: pd.Series) -> pd.DataFrame:
    aligned = frame.set_index("machine_number").loc[cluster_ids.index].copy()
    aligned["cluster_id"] = cluster_ids
    rows = []
    for axis in KNOWN_GROUP_COLUMNS:
        labels = aligned[axis].astype("string")
        score = adjusted_rand_score(labels, aligned["cluster_id"])
        rows.append({"axis": axis, "ari": float(score)})
    return pd.DataFrame(rows)


def _cluster_breakdown(frame: pd.DataFrame, cluster_ids: pd.Series) -> dict[int, pd.DataFrame]:
    aligned = frame.set_index("machine_number").loc[cluster_ids.index].copy()
    aligned["cluster_id"] = cluster_ids
    breakdowns: dict[int, pd.DataFrame] = {}
    for cluster_id, group in aligned.groupby("cluster_id", sort=True):
        rows = []
        for axis in KNOWN_GROUP_COLUMNS:
            counts = group[axis].astype("string").value_counts(dropna=False).sort_index()
            for label, count in counts.items():
                rows.append(
                    {
                        "cluster_id": int(cluster_id),
                        "axis": axis,
                        "axis_level": str(label),
                        "count": int(count),
                    }
                )
        breakdowns[int(cluster_id)] = pd.DataFrame(rows)
    return breakdowns


def build_report(
    *,
    hall: str,
    frame: pd.DataFrame,
    regression_frame: pd.DataFrame,
    sequential_frame: pd.DataFrame,
    common_days: pd.DataFrame,
    pairwise_corr: pd.DataFrame,
    silhouette_scores: pd.DataFrame,
    ari_frame: pd.DataFrame,
    cluster_ids: pd.Series,
    min_common_days: int,
) -> str:
    n_pairs = int((pairwise_corr.shape[0] * (pairwise_corr.shape[0] - 1)) / 2)
    observed_pairs = int(
        (common_days.where(np.triu(np.ones(common_days.shape), k=1).astype(bool)) >= min_common_days).sum().sum()
    )
    total_cells = int((common_days.where(np.triu(np.ones(common_days.shape), k=1).astype(bool)).notna()).sum().sum())
    common_ratio = float(observed_pairs / n_pairs) if n_pairs > 0 else float("nan")

    lines: list[str] = []
    lines.append(f"# Residual clustering report: {hall}")
    lines.append("")
    lines.append(f"- machines analyzed: {frame['machine_number'].nunique()}")
    lines.append(f"- machine-day rows used: {len(frame)}")
    lines.append(f"- min_common_days: {min_common_days}")
    lines.append(f"- pairwise pairs with enough overlap: {observed_pairs}/{n_pairs} ({common_ratio:.3f})")
    lines.append(f"- regression residual rows: {len(regression_frame)}")
    lines.append(f"- sequential demeaning rows: {len(sequential_frame)}")
    if not regression_frame.empty and not sequential_frame.empty:
        merged = regression_frame[["machine_number", "date", RESIDUAL_COL]].merge(
            sequential_frame[["machine_number", "date", SEQUENTIAL_RESIDUAL_COL]],
            on=["machine_number", "date"],
            how="inner",
        )
        corr = merged[RESIDUAL_COL].corr(merged[SEQUENTIAL_RESIDUAL_COL])
        lines.append(f"- residual correlation: {corr:.4f}")
    lines.append("")
    lines.append("## Silhouette sweep")
    if silhouette_scores.empty:
        lines.append("No silhouette sweep was possible.")
    else:
        lines.append(_markdown_table(silhouette_scores))

    lines.append("")
    lines.append("## Adjusted Rand Index vs known groups")
    lines.append(_markdown_table(ari_frame))

    lines.append("")
    lines.append("## Cluster composition")
    aligned = frame.set_index("machine_number").loc[cluster_ids.index].copy()
    aligned["cluster_id"] = cluster_ids
    for cluster_id, group in aligned.groupby("cluster_id", sort=True):
        lines.append(f"### Cluster {int(cluster_id)}")
        lines.append(f"- size: {len(group)}")
        for axis in KNOWN_GROUP_COLUMNS:
            counts = group[axis].astype("string").value_counts(dropna=False).sort_values(ascending=False)
            top = counts.head(5).reset_index()
            top.columns = [axis, "count"]
            lines.append(f"#### {axis}")
            lines.append(_markdown_table(top))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(empty)"
    work = df.copy()
    work = work.replace({np.nan: ""})
    columns = list(work.columns)
    header = "| " + " | ".join(str(col) for col in columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows = ["| " + " | ".join(str(work.iloc[i][col]) for col in columns) + " |" for i in range(len(work))]
    return "\n".join([header, separator, *rows])


def run_hall(
    hall: str,
    *,
    shindai_exclude_days: int,
    min_common_days: int,
    k_range: tuple[int, int],
    coords1: Path,
    coords7_2f: Path,
    coords7_3f: Path,
    mitoya_db_path: Path | None,
    mitoya_db_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    frame = _build_hall_frame(
        hall,
        shindai_exclude_days=shindai_exclude_days,
        coords1=coords1,
        coords7_2f=coords7_2f,
        coords7_3f=coords7_3f,
        mitoya_db_path=mitoya_db_path,
        mitoya_db_dir=mitoya_db_dir,
    )
    if frame.empty:
        raise ValueError(f"no rows remained after joining layout for {hall}")

    regression_frame = compute_fixed_effect_residuals(frame)
    sequential_frame = compute_sequential_demeaned_residuals(frame)

    residuals = regression_frame.loc[:, ["machine_number", "date", RESIDUAL_COL]].copy()
    pivot = _build_pivot(regression_frame, RESIDUAL_COL)
    pairwise_corr, common_days = compute_pairwise_correlations(pivot, min_common_days=min_common_days)

    eligible_corr = pairwise_corr.dropna(axis=0, how="all").dropna(axis=1, how="all")
    cluster_ids, silhouette_scores = assign_clusters(eligible_corr, k_range=k_range)
    ari_frame = _summarize_ari(regression_frame, cluster_ids)
    report_text = build_report(
        hall=hall,
        frame=frame,
        regression_frame=regression_frame,
        sequential_frame=sequential_frame,
        common_days=common_days,
        pairwise_corr=pairwise_corr,
        silhouette_scores=silhouette_scores,
        ari_frame=ari_frame,
        cluster_ids=cluster_ids,
        min_common_days=min_common_days,
    )

    output_frame = regression_frame.set_index("machine_number").loc[cluster_ids.index].copy()
    output_frame["cluster_id"] = cluster_ids.astype(int)
    output_frame = output_frame.reset_index()
    if "machine_number" not in output_frame.columns and "index" in output_frame.columns:
        output_frame = output_frame.rename(columns={"index": "machine_number"})
    output_frame = (
        output_frame.loc[:, OUTPUT_COLUMNS].sort_values(["cluster_id", "machine_number"]).reset_index(drop=True)
    )

    csv_path = output_dir / f"{hall}_residual_corr_clusters.csv"
    report_path = output_dir / f"{hall}_cluster_ari_report.md"
    _write_csv(output_frame, csv_path)
    _write_text(report_path, report_text)
    return {"csv": csv_path, "report": report_path}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="residual correlation clustering")
    parser.add_argument("--halls", type=_parse_halls, default=DEFAULT_HALLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-common-days", type=int, default=MIN_COMMON_DAYS_DEFAULT)
    parser.add_argument("--shindai-exclude-days", type=int, default=DEFAULT_SHINDAI_EXCLUDE_DAYS)
    parser.add_argument("--k-range", type=_parse_k_range, default=DEFAULT_K_RANGE)
    parser.add_argument("--coords1", type=Path, default=DEFAULT_COORDS_1)
    parser.add_argument("--coords7-2f", dest="coords7_2f", type=Path, default=DEFAULT_COORDS_7_2F)
    parser.add_argument("--coords7-3f", dest="coords7_3f", type=Path, default=DEFAULT_COORDS_7_3F)
    parser.add_argument("--mitoya-db-path", type=Path, default=None)
    parser.add_argument("--mitoya-db-dir", type=Path, default=Path("db"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = _ensure_output_dir(args.output_dir)

    mitoya_db_path = args.mitoya_db_path

    for hall in args.halls:
        paths = run_hall(
            hall,
            shindai_exclude_days=args.shindai_exclude_days,
            min_common_days=args.min_common_days,
            k_range=args.k_range,
            coords1=args.coords1,
            coords7_2f=args.coords7_2f,
            coords7_3f=args.coords7_3f,
            mitoya_db_path=mitoya_db_path if hall == "みとや" else None,
            mitoya_db_dir=args.mitoya_db_dir,
            output_dir=output_dir,
        )
        print(f"[OK] {hall}: {paths['csv'].name}, {paths['report'].name}")

    print(f"written: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
