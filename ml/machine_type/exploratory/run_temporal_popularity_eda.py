from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .. import machine_type_common as common

DEFAULT_OUTPUT_DIR = Path("ml/machine_type/exploratory/output")
DEFAULT_DB_ROOT = Path("db")
MIN_DB_SIZE_BYTES = 100_000

LAG_FEATURES = (
    "lag1_efficiency",
    "lag2_efficiency",
    "lag1_total_diff_coins",
    "lag2_total_diff_coins",
    "lag1_is_top_3",
    "lag2_is_top_3",
)

MONTHLY_FEATURES = (
    "prev_month_total_games",
    "prev_month_avg_efficiency",
    "prev2_month_total_games",
    "prev2_month_avg_efficiency",
    "prev_month_machine_count_mean",
    "prev2_month_machine_count_mean",
)

TARGET_COLUMNS = ("is_top_3", "efficiency")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Temporal popularity EDA for machine_type")
    parser.add_argument("--db-root", default=str(DEFAULT_DB_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-db-size-bytes", type=int, default=MIN_DB_SIZE_BYTES)
    return parser.parse_args()


def _ensure_entity_key(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "hall_id" not in out.columns:
        raise ValueError("hall_id column is required")
    if "machine_name" not in out.columns:
        raise ValueError("machine_name column is required")
    out["entity_key"] = out["hall_id"].astype(str) + "::" + out["machine_name"].astype(str)
    return out


def load_pooled_machine_type_frame(
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
            raw = common.load_daily_machine_type_summary(db_path)
            base = common.prepare_machine_type_base_frame(raw)
            ranked = common.add_shrunk_rank_targets(base, alpha=5.0)
        except Exception as exc:  # pragma: no cover - defensive runtime logging
            print(f"skip {hall_id}: {exc}")
            continue
        ranked = ranked.copy()
        ranked["hall_id"] = hall_id
        frames.append(ranked)

    if not frames:
        raise ValueError(f"No usable DBs found under {db_root}")

    pooled = pd.concat(frames, ignore_index=True, sort=False)
    pooled["date"] = pd.to_datetime(pooled["date"], errors="coerce")
    pooled = pooled.dropna(subset=["date", "machine_name", "hall_id"]).copy()
    pooled = _ensure_entity_key(pooled)
    pooled = pooled.sort_values(["hall_id", "machine_name", "date"]).reset_index(drop=True)
    return pooled


def _calendar_shifted_values(group: pd.DataFrame, value_col: str, lag_days: int) -> pd.Series:
    shifted = group[value_col].shift(lag_days)
    expected_delta = pd.Timedelta(days=lag_days)
    actual_delta = group["date"] - group["date"].shift(lag_days)
    return shifted.where(actual_delta == expected_delta)


def add_temporal_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_entity_key(df)
    work = work.sort_values(["entity_key", "date"]).reset_index(drop=True)

    groups: list[pd.DataFrame] = []
    for _, group in work.groupby("entity_key", sort=False):
        g = group.sort_values("date").copy()
        g["lag1_efficiency"] = _calendar_shifted_values(g, "efficiency", 1)
        g["lag2_efficiency"] = _calendar_shifted_values(g, "efficiency", 2)
        g["lag1_total_diff_coins"] = _calendar_shifted_values(g, "total_diff_coins", 1)
        g["lag2_total_diff_coins"] = _calendar_shifted_values(g, "total_diff_coins", 2)
        g["lag1_is_top_3"] = _calendar_shifted_values(g, "is_top_3", 1)
        g["lag2_is_top_3"] = _calendar_shifted_values(g, "is_top_3", 2)
        groups.append(g)

    out = pd.concat(groups, ignore_index=True, sort=False)
    out = out.sort_values(["hall_id", "machine_name", "date"]).reset_index(drop=True)
    return out


def add_monthly_popularity_features(df: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_entity_key(df)
    work = work.copy()
    work["year_month"] = work["date"].dt.to_period("M")

    monthly = (
        work.groupby(["hall_id", "machine_name", "year_month"], sort=True)
        .agg(
            monthly_total_games=("total_games", "sum"),
            monthly_avg_efficiency=("efficiency", "mean"),
            monthly_machine_count_mean=("machine_count", "mean"),
        )
        .reset_index()
        .sort_values(["hall_id", "machine_name", "year_month"])
        .reset_index(drop=True)
    )

    monthly_groups: list[pd.DataFrame] = []
    for (hall_id, machine_name), group in monthly.groupby(["hall_id", "machine_name"], sort=False):
        g = group.sort_values("year_month").copy()
        if g.empty:
            continue

        full_periods = pd.period_range(g["year_month"].min(), g["year_month"].max(), freq="M")
        g = (
            g.set_index("year_month")
            .reindex(full_periods)
            .rename_axis("year_month")
            .reset_index()
        )
        g["hall_id"] = hall_id
        g["machine_name"] = machine_name
        g["entity_key"] = str(hall_id) + "::" + str(machine_name)

        for lag, prefix in ((1, "prev_month"), (2, "prev2_month")):
            shifted = g[["monthly_total_games", "monthly_avg_efficiency", "monthly_machine_count_mean"]].shift(lag)
            valid = g["year_month"].shift(lag).eq(g["year_month"] - lag)
            g[f"{prefix}_total_games"] = shifted["monthly_total_games"].where(valid)
            g[f"{prefix}_avg_efficiency"] = shifted["monthly_avg_efficiency"].where(valid)
            g[f"{prefix}_machine_count_mean"] = shifted["monthly_machine_count_mean"].where(valid)

        monthly_groups.append(g)

    monthly_feature_frame = pd.concat(monthly_groups, ignore_index=True, sort=False)
    merged = work.merge(
        monthly_feature_frame[
            [
                "hall_id",
                "machine_name",
                "year_month",
                "monthly_total_games",
                "monthly_avg_efficiency",
                "monthly_machine_count_mean",
                "prev_month_total_games",
                "prev_month_avg_efficiency",
                "prev_month_machine_count_mean",
                "prev2_month_total_games",
                "prev2_month_avg_efficiency",
                "prev2_month_machine_count_mean",
            ]
        ],
        on=["hall_id", "machine_name", "year_month"],
        how="left",
    )
    merged = merged.sort_values(["hall_id", "machine_name", "date"]).reset_index(drop=True)
    return merged


def build_analysis_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = add_temporal_lag_features(df)
    out = add_monthly_popularity_features(out)
    return out


def _safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    work = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(work) < 2:
        return (float("nan"), int(len(work)))
    if work["x"].nunique(dropna=True) < 2 or work["y"].nunique(dropna=True) < 2:
        return (float("nan"), int(len(work)))
    rho = spearmanr(work["x"].to_numpy(dtype=float), work["y"].to_numpy(dtype=float)).correlation
    return (float(rho), int(len(work)))


def build_correlation_table(df: pd.DataFrame, feature_cols: Iterable[str], target_col: str) -> pd.DataFrame:
    rows = []
    for feature in feature_cols:
        rho, n = _safe_spearman(df[feature], df[target_col])
        rows.append(
            {
                "feature": feature,
                "target": target_col,
                "n_pairs": n,
                "spearman_rho": rho,
            }
        )
    return pd.DataFrame(rows)


def build_transition_table(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.loc[df["lag1_is_top_3"].notna() & df["is_top_3"].notna(), ["lag1_is_top_3", "is_top_3"]].copy()
    work["lag1_is_top_3"] = work["lag1_is_top_3"].astype(int)
    work["is_top_3"] = work["is_top_3"].astype(int)
    counts = pd.crosstab(work["lag1_is_top_3"], work["is_top_3"]).reindex(index=[0, 1], columns=[0, 1], fill_value=0)
    counts.index.name = "prev_is_top_3"
    counts.columns.name = "current_is_top_3"

    rows = []
    for prev_state in (0, 1):
        total = int(counts.loc[prev_state].sum())
        top_rate = float(counts.loc[prev_state, 1] / total) if total else float("nan")
        rows.append(
            {
                "prev_is_top_3": prev_state,
                "n_pairs": total,
                "next_top_3_rate": top_rate,
            }
        )
    rates = pd.DataFrame(rows)
    return counts.reset_index(), rates


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


def build_quartile_hit_rate_table(df: pd.DataFrame, value_col: str, *, group_col: str | None = None) -> pd.DataFrame:
    work = df.copy()
    if group_col is None:
        work["quartile"] = _quartile_labels(work[value_col])
        grouped = work.groupby("quartile", sort=True)
        rows = []
        for quartile, group in grouped:
            if pd.isna(quartile):
                continue
            rows.append(
                {
                    "quartile": quartile,
                    "n_rows": int(len(group)),
                    "is_top_3_rate": float(group["is_top_3"].mean()) if len(group) else float("nan"),
                    "mean_efficiency": float(group["efficiency"].mean()) if len(group) else float("nan"),
                }
            )
        return pd.DataFrame(rows)

    rows = []
    for group_value, group in work.groupby(group_col, sort=True):
        group = group.copy()
        group["quartile"] = _quartile_labels(group[value_col])
        for quartile, slice_df in group.groupby("quartile", sort=True):
            if pd.isna(quartile):
                continue
            rows.append(
                {
                    group_col: group_value,
                    "quartile": quartile,
                    "n_rows": int(len(slice_df)),
                    "is_top_3_rate": float(slice_df["is_top_3"].mean()) if len(slice_df) else float("nan"),
                    "mean_efficiency": float(slice_df["efficiency"].mean()) if len(slice_df) else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def build_machine_name_correlation_summary(
    df: pd.DataFrame,
    feature_cols: Iterable[str],
    target_col: str,
) -> pd.DataFrame:
    rows = []
    for feature in feature_cols:
        per_machine = []
        for machine_name, group in df.groupby("machine_name", sort=True):
            rho, n = _safe_spearman(group[feature], group[target_col])
            if np.isfinite(rho) and n >= 3:
                per_machine.append(rho)
        if per_machine:
            series = pd.Series(per_machine, dtype=float)
            rows.append(
                {
                    "feature": feature,
                    "target": target_col,
                    "n_machines": int(series.size),
                    "mean_rho": float(series.mean()),
                    "median_rho": float(series.median()),
                    "std_rho": float(series.std(ddof=0)) if series.size > 1 else 0.0,
                    "min_rho": float(series.min()),
                    "max_rho": float(series.max()),
                }
            )
        else:
            rows.append(
                {
                    "feature": feature,
                    "target": target_col,
                    "n_machines": 0,
                    "mean_rho": float("nan"),
                    "median_rho": float("nan"),
                    "std_rho": float("nan"),
                    "min_rho": float("nan"),
                    "max_rho": float("nan"),
                }
            )
    return pd.DataFrame(rows)


def _format_markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_no rows_\n"
    work = df.copy()
    for column in work.columns:
        if pd.api.types.is_float_dtype(work[column]):
            work[column] = work[column].map(lambda v: "" if pd.isna(v) else f"{v:.6f}")
        elif pd.api.types.is_integer_dtype(work[column]):
            work[column] = work[column].astype(str)
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


def build_report_payload(df: pd.DataFrame) -> dict[str, object]:
    lag_corr_is_top_3 = build_correlation_table(df, [c for c in LAG_FEATURES], "is_top_3")
    lag_corr_efficiency = build_correlation_table(df, [c for c in LAG_FEATURES], "efficiency")
    monthly_corr_is_top_3 = build_correlation_table(df, [c for c in MONTHLY_FEATURES], "is_top_3")
    monthly_corr_efficiency = build_correlation_table(df, [c for c in MONTHLY_FEATURES], "efficiency")
    transition_counts, transition_rates = build_transition_table(df)
    quartile_overall = build_quartile_hit_rate_table(df.dropna(subset=["prev_month_total_games"]), "prev_month_total_games")
    quartile_by_hall = build_quartile_hit_rate_table(df.dropna(subset=["prev_month_total_games"]), "prev_month_total_games", group_col="hall_id")
    machine_summary_lag_is_top_3 = build_machine_name_correlation_summary(df, [c for c in LAG_FEATURES], "is_top_3")
    machine_summary_lag_efficiency = build_machine_name_correlation_summary(df, [c for c in LAG_FEATURES], "efficiency")
    machine_summary_monthly_is_top_3 = build_machine_name_correlation_summary(df, [c for c in MONTHLY_FEATURES], "is_top_3")
    machine_summary_monthly_efficiency = build_machine_name_correlation_summary(df, [c for c in MONTHLY_FEATURES], "efficiency")

    return {
        "dataset": {
            "rows": int(len(df)),
            "halls": int(df["hall_id"].nunique()),
            "machines": int(df["machine_name"].nunique()),
            "date_min": str(df["date"].min().date()) if not df.empty else None,
            "date_max": str(df["date"].max().date()) if not df.empty else None,
        },
        "lag_corr_is_top_3": lag_corr_is_top_3,
        "lag_corr_efficiency": lag_corr_efficiency,
        "monthly_corr_is_top_3": monthly_corr_is_top_3,
        "monthly_corr_efficiency": monthly_corr_efficiency,
        "transition_counts": transition_counts,
        "transition_rates": transition_rates,
        "quartile_overall": quartile_overall,
        "quartile_by_hall": quartile_by_hall,
        "machine_summary_lag_is_top_3": machine_summary_lag_is_top_3,
        "machine_summary_lag_efficiency": machine_summary_lag_efficiency,
        "machine_summary_monthly_is_top_3": machine_summary_monthly_is_top_3,
        "machine_summary_monthly_efficiency": machine_summary_monthly_efficiency,
    }


def render_report(payload: dict[str, object]) -> str:
    lines = ["# Temporal Popularity EDA", ""]

    dataset = payload["dataset"]
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- rows: {dataset['rows']}")
    lines.append(f"- halls: {dataset['halls']}")
    lines.append(f"- machines: {dataset['machines']}")
    lines.append(f"- date_min: {dataset['date_min']}")
    lines.append(f"- date_max: {dataset['date_max']}")
    lines.append("")

    sections = [
        ("Lag correlations vs is_top_3", payload["lag_corr_is_top_3"]),
        ("Lag correlations vs efficiency", payload["lag_corr_efficiency"]),
        ("Monthly correlations vs is_top_3", payload["monthly_corr_is_top_3"]),
        ("Monthly correlations vs efficiency", payload["monthly_corr_efficiency"]),
        ("Transition counts", payload["transition_counts"]),
        ("Transition rates", payload["transition_rates"]),
        ("Monthly popularity quartiles", payload["quartile_overall"]),
        ("Monthly popularity quartiles by hall", payload["quartile_by_hall"]),
        ("Within-machine lag correlation summary vs is_top_3", payload["machine_summary_lag_is_top_3"]),
        ("Within-machine lag correlation summary vs efficiency", payload["machine_summary_lag_efficiency"]),
        ("Within-machine monthly correlation summary vs is_top_3", payload["machine_summary_monthly_is_top_3"]),
        ("Within-machine monthly correlation summary vs efficiency", payload["machine_summary_monthly_efficiency"]),
    ]
    for title, table in sections:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(_format_markdown_table(table))

    return "\n".join(lines)


def save_report(payload: dict[str, object], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "temporal_popularity_eda_report.md"
    json_path = output_dir / "temporal_popularity_eda_report.json"
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
    analyzed = build_analysis_frame(pooled)
    payload = build_report_payload(analyzed)
    md_path, json_path = save_report(payload, output_dir)
    print(f"wrote: {md_path}")
    print(f"wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
