from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .. import machine_type_common as common
from . import run_temporal_popularity_eda as temporal

DEFAULT_OUTPUT_DIR = Path("ml/machine_type/exploratory/output")
DEFAULT_DB_ROOT = Path("db")
MIN_DB_SIZE_BYTES = 100_000
TARGET_COLUMNS = ("is_top_3",)
FEATURE_COLUMNS = ("hall_win_rate", "efficiency", "efficiency_minus_hall_avg")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hall-relative performance EDA for machine_type")
    parser.add_argument("--db-root", default=str(DEFAULT_DB_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-db-size-bytes", type=int, default=MIN_DB_SIZE_BYTES)
    return parser.parse_args()


def load_pooled_machine_type_frame(
    db_root: Path = DEFAULT_DB_ROOT,
    *,
    min_db_size_bytes: int = MIN_DB_SIZE_BYTES,
) -> pd.DataFrame:
    return temporal.load_pooled_machine_type_frame(db_root, min_db_size_bytes=min_db_size_bytes)


def load_pooled_daily_hall_summary_frame(
    db_root: Path = DEFAULT_DB_ROOT,
    *,
    min_db_size_bytes: int = MIN_DB_SIZE_BYTES,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for db_path in sorted(db_root.glob("*.db")):
        if db_path.stat().st_size < int(min_db_size_bytes):
            continue
        hall_id = db_path.stem
        try:
            raw = common.load_daily_hall_summary_slim(db_path)
        except Exception as exc:  # pragma: no cover - defensive runtime logging
            print(f"skip {hall_id}: {exc}")
            continue
        raw = raw.copy()
        raw["hall_id"] = hall_id
        frames.append(raw)
    if not frames:
        raise ValueError(f"No usable DBs found under {db_root}")
    pooled = pd.concat(frames, ignore_index=True, sort=False)
    pooled["date"] = pd.to_datetime(pooled["date"], errors="coerce")
    pooled = pooled.dropna(subset=["date", "hall_id"]).copy()
    pooled = pooled.sort_values(["hall_id", "date"]).reset_index(drop=True)
    return pooled


def _quartile_labels(values: pd.Series) -> pd.Series:
    labels = pd.Series(pd.NA, index=values.index, dtype="object")
    non_null = values.dropna()
    if non_null.empty:
        return labels
    if non_null.nunique() < 4:
        labels.loc[non_null.index] = "Q1"
        return labels
    ranked = non_null.rank(method="first")
    bins = pd.qcut(ranked, 4, labels=["Q1", "Q2", "Q3", "Q4"])
    labels.loc[non_null.index] = bins.astype(str)
    return labels


def add_hall_relative_features(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    if "hall_win_rate" not in work.columns and "win_rate_hall" in work.columns:
        work["hall_win_rate"] = work["win_rate_hall"]
    if "hall_avg_diff_per_machine" not in work.columns and "avg_diff_per_machine_hall" in work.columns:
        work["hall_avg_diff_per_machine"] = work["avg_diff_per_machine_hall"]
    if "hall_win_rate" not in work.columns and "win_rate" in work.columns:
        work["hall_win_rate"] = work["win_rate"]
    if "hall_avg_diff_per_machine" not in work.columns:
        work["hall_avg_diff_per_machine"] = np.nan

    for column in ("hall_win_rate", "efficiency", "is_top_3"):
        if column not in work.columns:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if "hall_id" not in work.columns:
        raise KeyError("hall_id column is required")
    work = work.dropna(subset=["date", "hall_id", "machine_name"]).copy()
    work = work.sort_values(["hall_id", "date", "machine_name"]).reset_index(drop=True)
    work["hall_avg_efficiency"] = work.groupby(["hall_id", "date"], sort=False)["efficiency"].transform("mean")
    hall_day = work[["hall_id", "date", "hall_win_rate"]].drop_duplicates().copy()
    hall_day["hall_win_rate_quartile"] = _quartile_labels(hall_day["hall_win_rate"])
    merged = work.merge(hall_day[["hall_id", "date", "hall_win_rate_quartile"]], on=["hall_id", "date"], how="left")
    merged["efficiency_minus_hall_avg"] = merged["efficiency"] - merged["hall_avg_efficiency"]
    return merged


def build_correlation_table(df: pd.DataFrame, feature_cols: Iterable[str], target_col: str) -> pd.DataFrame:
    rows = []
    for feature in feature_cols:
        rho, n = common._safe_spearman(df[feature], df[target_col])
        rows.append({"feature": feature, "target": target_col, "n_pairs": int(n), "spearman_rho": float(rho)})
    return pd.DataFrame(rows)


def build_quartile_table(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    work = df.copy()
    work["quartile"] = _quartile_labels(work[value_col])
    rows = []
    for quartile, group in work.groupby("quartile", sort=True):
        if pd.isna(quartile):
            continue
        rows.append(
            {
                "quartile": quartile,
                "n_rows": int(len(group)),
                "is_top_3_rate": float(group["is_top_3"].mean()) if len(group) else float("nan"),
                "mean_efficiency": float(group["efficiency"].mean()) if len(group) else float("nan"),
                "mean_efficiency_minus_hall_avg": float(group["efficiency_minus_hall_avg"].mean()) if len(group) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def build_hall_summary_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for hall_id, group in df.groupby("hall_id", sort=True):
        row = {
            "hall_id": hall_id,
            "n_rows": int(len(group)),
            "avg_win_rate": float(group["hall_win_rate"].mean()),
            "avg_diff_per_machine": float(group["hall_avg_diff_per_machine"].mean()) if "hall_avg_diff_per_machine" in group.columns else float("nan"),
        }
        for feature in FEATURE_COLUMNS:
            rho, n = common._safe_spearman(group[feature], group["is_top_3"])
            row[f"rho_{feature}"] = float(rho)
            row[f"n_{feature}"] = int(n)
        rows.append(row)
    return pd.DataFrame(rows)


def build_report_payload(df: pd.DataFrame) -> dict[str, object]:
    correlation_table = build_correlation_table(df, FEATURE_COLUMNS, "is_top_3")
    quartile_table = build_quartile_table(df.dropna(subset=["hall_win_rate"]), "hall_win_rate")
    hall_summary_table = build_hall_summary_table(df)
    correlation_by_hall = common.build_machine_name_correlation_summary(
        df,
        ("hall_win_rate", "efficiency", "efficiency_minus_hall_avg"),
        "is_top_3",
        group_col="hall_id",
        min_n=10,
    )
    hall_context_table = (
        df.groupby("hall_id", sort=True)
        .agg(
            n_rows=("date", "size"),
            hall_win_rate_mean=("hall_win_rate", "mean"),
            hall_avg_diff_per_machine_mean=("hall_avg_diff_per_machine", "mean"),
        )
        .reset_index()
    )

    return {
        "dataset": {
            "rows": int(len(df)),
            "halls": int(df["hall_id"].nunique()),
            "machines": int(df["machine_name"].nunique()),
            "date_min": str(df["date"].min().date()) if not df.empty else None,
            "date_max": str(df["date"].max().date()) if not df.empty else None,
        },
        "correlation_table": correlation_table,
        "quartile_table": quartile_table,
        "hall_summary_table": hall_summary_table,
        "correlation_by_hall": correlation_by_hall,
        "hall_context_table": hall_context_table,
    }


def _format_markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_no rows_\n"
    work = df.copy()
    for column in work.columns:
        if pd.api.types.is_float_dtype(work[column]):
            work[column] = work[column].map(lambda v: "" if pd.isna(v) else f"{v:.6f}")
        else:
            work[column] = work[column].astype(str).replace({"<NA>": ""})
    headers = list(work.columns)
    widths = [max(len(str(header)), *(len(str(v)) for v in work[col].tolist())) for header, col in zip(headers, work.columns)]
    lines = [
        "| " + " | ".join(f"{header:<{widths[i]}}" for i, header in enumerate(headers)) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    for _, row in work.iterrows():
        lines.append("| " + " | ".join(f"{str(row[col]):<{widths[i]}}" for i, col in enumerate(work.columns)) + " |")
    return "\n".join(lines) + "\n"


def render_report(payload: dict[str, object]) -> str:
    lines = ["# Hall Relative Performance EDA", ""]
    dataset = payload["dataset"]
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- rows: {dataset['rows']}")
    lines.append(f"- halls: {dataset['halls']}")
    lines.append(f"- machines: {dataset['machines']}")
    lines.append(f"- date_min: {dataset['date_min']}")
    lines.append(f"- date_max: {dataset['date_max']}")
    lines.append("")
    for title, table in (
        ("Correlation vs is_top_3", payload["correlation_table"]),
        ("Hall win-rate quartiles", payload["quartile_table"]),
        ("Hall summary", payload["hall_summary_table"]),
        ("Hall correlation summary", payload["correlation_by_hall"]),
        ("Hall context summary", payload["hall_context_table"]),
    ):
        lines.append(f"## {title}")
        lines.append("")
        lines.append(_format_markdown_table(table))
    return "\n".join(lines)


def save_report(payload: dict[str, object], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "run_hall_relative_performance_eda_report.md"
    json_path = output_dir / "run_hall_relative_performance_eda_report.json"
    md_path.write_text(render_report(payload), encoding="utf-8")
    common.write_json_report(
        json_path,
        {
            key: value.to_dict(orient="records") if isinstance(value, pd.DataFrame) else value
            for key, value in payload.items()
        },
    )
    return md_path, json_path


def main() -> int:
    args = parse_args()
    db_root = Path(args.db_root)
    output_dir = Path(args.output_dir)
    machine_frame = load_pooled_machine_type_frame(db_root, min_db_size_bytes=args.min_db_size_bytes)
    hall_frame = load_pooled_daily_hall_summary_frame(db_root, min_db_size_bytes=args.min_db_size_bytes)
    hall_frame = hall_frame.rename(
        columns={
            "win_rate": "hall_win_rate",
            "avg_diff_per_machine": "hall_avg_diff_per_machine",
        }
    )
    analyzed = add_hall_relative_features(machine_frame.merge(hall_frame, on=["hall_id", "date"], how="left"))
    payload = build_report_payload(analyzed)
    md_path, json_path = save_report(payload, output_dir)
    print(f"wrote: {md_path}")
    print(f"wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
