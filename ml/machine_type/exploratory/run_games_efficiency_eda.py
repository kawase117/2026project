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
WINDOW_DAYS = 30
TARGET_COLUMNS = ("is_top_3", "efficiency")
FEATURE_COLUMNS = ("games_zscore", "lag1_games_zscore")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Games efficiency EDA for machine_type")
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


def _calendar_shifted_values(group: pd.DataFrame, value_col: str, lag_days: int) -> pd.Series:
    shifted = group[value_col].shift(lag_days)
    expected_delta = pd.Timedelta(days=lag_days)
    actual_delta = group["date"] - group["date"].shift(lag_days)
    return shifted.where(actual_delta == expected_delta)


def _prior_window_stats(group: pd.DataFrame, value_col: str, window_days: int = WINDOW_DAYS) -> tuple[pd.Series, pd.Series]:
    means = pd.Series(np.nan, index=group.index, dtype=float)
    stds = pd.Series(np.nan, index=group.index, dtype=float)
    for idx, current_date in zip(group.index, group["date"], strict=True):
        start = pd.Timestamp(current_date) - pd.Timedelta(days=window_days)
        end = pd.Timestamp(current_date) - pd.Timedelta(days=1)
        window = group.loc[(group["date"] >= start) & (group["date"] <= end), value_col]
        if window.empty:
            continue
        means.loc[idx] = float(window.mean())
        stds.loc[idx] = float(window.std(ddof=1))
    return means, stds


def add_games_efficiency_features(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    numeric_cols = ["avg_games", "efficiency", "is_top_3"]
    for column in numeric_cols:
        if column not in work.columns:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["date", "hall_id", "machine_name"]).copy()
    work = work.sort_values(["hall_id", "machine_name", "date"]).reset_index(drop=True)

    groups: list[pd.DataFrame] = []
    for _, group in work.groupby(["hall_id", "machine_name"], sort=False):
        g = group.sort_values("date").copy()
        prior_mean, prior_std = _prior_window_stats(g, "avg_games", window_days=WINDOW_DAYS)
        g["games_zscore"] = (g["avg_games"] - prior_mean) / prior_std
        g["lag1_games_zscore"] = _calendar_shifted_values(g, "games_zscore", 1)
        groups.append(g)

    out = pd.concat(groups, ignore_index=True, sort=False)
    out = out.sort_values(["hall_id", "machine_name", "date"]).reset_index(drop=True)
    return out


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
                "mean_games_zscore": float(group["games_zscore"].mean()) if len(group) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def build_report_payload(df: pd.DataFrame) -> dict[str, object]:
    correlation_table = build_correlation_table(df, FEATURE_COLUMNS, "is_top_3")
    efficiency_correlation = build_correlation_table(df, FEATURE_COLUMNS, "efficiency")
    quartile_table = build_quartile_table(df.dropna(subset=["games_zscore"]), "games_zscore")
    machine_summary_is_top_3 = common.build_machine_name_correlation_summary(
        df,
        FEATURE_COLUMNS,
        "is_top_3",
        min_n=10,
    )
    machine_summary_efficiency = common.build_machine_name_correlation_summary(
        df,
        FEATURE_COLUMNS,
        "efficiency",
        min_n=10,
    )
    same_day_vs_lag1 = correlation_table.loc[correlation_table["feature"].isin(["games_zscore", "lag1_games_zscore"])].copy()

    return {
        "dataset": {
            "rows": int(len(df)),
            "halls": int(df["hall_id"].nunique()),
            "machines": int(df["machine_name"].nunique()),
            "date_min": str(df["date"].min().date()) if not df.empty else None,
            "date_max": str(df["date"].max().date()) if not df.empty else None,
        },
        "correlation_table": correlation_table,
        "efficiency_correlation": efficiency_correlation,
        "quartile_table": quartile_table,
        "machine_summary_is_top_3": machine_summary_is_top_3,
        "machine_summary_efficiency": machine_summary_efficiency,
        "same_day_vs_lag1": same_day_vs_lag1,
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
    lines = ["# Games Efficiency EDA", ""]
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
        ("Same-day vs lag1 correlation", payload["same_day_vs_lag1"]),
        ("Correlation vs is_top_3", payload["correlation_table"]),
        ("Correlation vs efficiency", payload["efficiency_correlation"]),
        ("Games z-score quartiles", payload["quartile_table"]),
        ("Within-machine correlation summary vs is_top_3", payload["machine_summary_is_top_3"]),
        ("Within-machine correlation summary vs efficiency", payload["machine_summary_efficiency"]),
    ):
        lines.append(f"## {title}")
        lines.append("")
        lines.append(_format_markdown_table(table))
    return "\n".join(lines)


def save_report(payload: dict[str, object], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "run_games_efficiency_eda_report.md"
    json_path = output_dir / "run_games_efficiency_eda_report.json"
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
    pooled = load_pooled_machine_type_frame(db_root, min_db_size_bytes=args.min_db_size_bytes)
    analyzed = add_games_efficiency_features(pooled)
    payload = build_report_payload(analyzed)
    md_path, json_path = save_report(payload, output_dir)
    print(f"wrote: {md_path}")
    print(f"wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
