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
PERSISTENCE_THRESHOLD = 0.15

PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("lag1_total_diff_coins", "efficiency", "lag1_total_diff_vs_efficiency"),
    ("lag1_efficiency", "efficiency", "lag1_efficiency_vs_efficiency"),
    ("lag1_total_diff_coins", "is_top_3", "lag1_total_diff_vs_is_top_3"),
    ("lag1_is_top_3", "is_top_3", "lag1_is_top_3_vs_is_top_3"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lag persistence clustering for machine_type")
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


def add_temporal_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    return temporal.add_temporal_lag_features(df)


def _safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    return temporal._safe_spearman(x, y)


def build_lag_persistence_table(
    df: pd.DataFrame,
    feature_col: str,
    target_col: str,
    group_cols: list[str],
) -> pd.DataFrame:
    if not group_cols:
        raise ValueError("group_cols must not be empty")
    missing = [col for col in [*group_cols, feature_col, target_col] if col not in df.columns]
    if missing:
        raise KeyError(f"missing columns: {missing}")

    rows: list[dict[str, object]] = []
    for keys, group in df.groupby(group_cols, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n_rows = int(len(group))
        rho, n = _safe_spearman(group[feature_col], group[target_col])
        if n < 10 or not np.isfinite(rho):
            continue
        row = {col: value for col, value in zip(group_cols, keys)}
        row.update(
            {
                "feature_col": feature_col,
                "target_col": target_col,
                "rho": float(rho),
                "n": int(n),
                "n_rows": n_rows,
            }
        )
        rows.append(row)

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["rho", *group_cols], ascending=[False, *([True] * len(group_cols))]).reset_index(drop=True)


def classify_lag_persistence(rho: float) -> str:
    if not np.isfinite(rho):
        return "excluded"
    if rho >= PERSISTENCE_THRESHOLD:
        return "persistence"
    if rho <= -PERSISTENCE_THRESHOLD:
        return "reversal"
    return "neutral"


def annotate_persistence_type(table: pd.DataFrame) -> pd.DataFrame:
    out = table.copy()
    if out.empty:
        out["persistence_type"] = pd.Series(dtype="object")
        return out
    out["persistence_type"] = out["rho"].map(classify_lag_persistence)
    return out


def summarize_persistence_types(table: pd.DataFrame) -> pd.DataFrame:
    if table.empty:
        return pd.DataFrame(
            [
                {"persistence_type": "persistence", "n_groups": 0},
                {"persistence_type": "reversal", "n_groups": 0},
                {"persistence_type": "neutral", "n_groups": 0},
            ]
        )
    counts = (
        table.loc[table["persistence_type"].isin(["persistence", "reversal", "neutral"])]
        .groupby("persistence_type", sort=True)
        .size()
        .reindex(["persistence", "reversal", "neutral"], fill_value=0)
        .reset_index(name="n_groups")
    )
    return counts


def split_persistence_tables(table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    annotated = annotate_persistence_type(table)
    for label in ("persistence", "reversal", "neutral"):
        subset = annotated.loc[annotated["persistence_type"] == label].copy()
        if subset.empty:
            out[label] = subset
            continue
        if label == "persistence":
            ascending = [False]
        elif label == "reversal":
            ascending = [True]
        else:
            subset["abs_rho"] = subset["rho"].abs()
            ascending = [True]
        sort_cols = ["rho"] if label != "neutral" else ["abs_rho"]
        if "hall_id" in subset.columns and "machine_name" in subset.columns:
            sort_cols.extend(["hall_id", "machine_name"])
            ascending = ascending + [True, True]
        elif "machine_name" in subset.columns:
            sort_cols.append("machine_name")
            ascending = ascending + [True]
        out[label] = subset.sort_values(sort_cols, ascending=ascending).drop(columns=["abs_rho"], errors="ignore").reset_index(drop=True)
    return out


def build_hall_conflict_table(hall_machine_table: pd.DataFrame) -> pd.DataFrame:
    if hall_machine_table.empty:
        return pd.DataFrame(columns=["machine_name", "hall_id", "rho", "n", "n_rows", "persistence_type", "rho_sign"])
    work = hall_machine_table.copy()
    work = work.loc[work["rho"].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=["machine_name", "hall_id", "rho", "n", "n_rows", "persistence_type", "rho_sign"])
    work["rho_sign"] = np.sign(work["rho"]).astype(int)
    conflicting_machine_names: list[str] = []
    for machine_name, group in work.groupby("machine_name", sort=True):
        signs = set(group["rho_sign"].tolist())
        if -1 in signs and 1 in signs:
            conflicting_machine_names.append(str(machine_name))
    conflict = work.loc[work["machine_name"].isin(conflicting_machine_names)].copy()
    if conflict.empty:
        return pd.DataFrame(columns=["machine_name", "hall_id", "rho", "n", "n_rows", "persistence_type", "rho_sign"])
    conflict["persistence_type"] = conflict["rho"].map(classify_lag_persistence)
    return conflict.sort_values(["machine_name", "rho", "hall_id"], ascending=[True, False, True]).reset_index(drop=True)


def build_hall_conflict_summary(hall_machine_table: pd.DataFrame) -> pd.DataFrame:
    conflict = build_hall_conflict_table(hall_machine_table)
    if conflict.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "hall_count",
                "positive_halls",
                "negative_halls",
                "neutral_halls",
                "rho_min",
                "rho_max",
            ]
        )
    rows = []
    for machine_name, group in conflict.groupby("machine_name", sort=True):
        rows.append(
            {
                "machine_name": machine_name,
                "hall_count": int(group["hall_id"].nunique()),
                "positive_halls": int((group["rho_sign"] > 0).sum()),
                "negative_halls": int((group["rho_sign"] < 0).sum()),
                "neutral_halls": int((group["rho_sign"] == 0).sum()),
                "rho_min": float(group["rho"].min()),
                "rho_max": float(group["rho"].max()),
            }
        )
    return pd.DataFrame(rows).sort_values(["hall_count", "machine_name"], ascending=[False, True]).reset_index(drop=True)


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
    sections: list[dict[str, object]] = []
    for feature_col, target_col, slug in PATTERNS:
        for group_name, group_cols in (
            ("machine_name", ["machine_name"]),
            ("hall_machine", ["hall_id", "machine_name"]),
        ):
            raw_table = build_lag_persistence_table(df, feature_col, target_col, list(group_cols))
            annotated = annotate_persistence_type(raw_table)
            split_tables = split_persistence_tables(raw_table)
            summary = summarize_persistence_types(annotated)
            section: dict[str, object] = {
                "slug": slug,
                "feature_col": feature_col,
                "target_col": target_col,
                "group_name": group_name,
                "group_cols": list(group_cols),
                "summary": summary,
                "tables": split_tables,
            }
            if group_name == "hall_machine":
                conflict_table = build_hall_conflict_table(raw_table)
                conflict_summary = build_hall_conflict_summary(raw_table)
                section["conflict_table"] = conflict_table
                section["conflict_summary"] = conflict_summary
            sections.append(section)

    return {
        "dataset": {
            "rows": int(len(df)),
            "halls": int(df["hall_id"].nunique()) if "hall_id" in df.columns else None,
            "machines": int(df["machine_name"].nunique()) if "machine_name" in df.columns else None,
            "date_min": str(df["date"].min().date()) if "date" in df.columns and not df.empty else None,
            "date_max": str(df["date"].max().date()) if "date" in df.columns and not df.empty else None,
        },
        "sections": sections,
    }


def render_report(payload: dict[str, object]) -> str:
    lines = ["# Lag Persistence Clustering", ""]
    dataset = payload["dataset"]
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- rows: {dataset['rows']}")
    lines.append(f"- halls: {dataset['halls']}")
    lines.append(f"- machines: {dataset['machines']}")
    lines.append(f"- date_min: {dataset['date_min']}")
    lines.append(f"- date_max: {dataset['date_max']}")
    lines.append("")

    for section in payload["sections"]:
        lines.append(
            f"## {section['slug']} | {section['group_name']} | {section['feature_col']} -> {section['target_col']}"
        )
        lines.append("")
        lines.append(_format_markdown_table(section["summary"]))
        lines.append("")
        lines.append("### persistence")
        lines.append("")
        lines.append(_format_markdown_table(section["tables"]["persistence"]))
        lines.append("")
        lines.append("### reversal")
        lines.append("")
        lines.append(_format_markdown_table(section["tables"]["reversal"]))
        lines.append("")
        lines.append("### neutral")
        lines.append("")
        lines.append(_format_markdown_table(section["tables"]["neutral"]))
        lines.append("")
        if section["group_name"] == "hall_machine":
            lines.append("### hall conflicts")
            lines.append("")
            lines.append(_format_markdown_table(section["conflict_summary"]))
            lines.append("")
            lines.append(_format_markdown_table(section["conflict_table"]))
            lines.append("")
    return "\n".join(lines)


def save_report(payload: dict[str, object], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "lag_persistence_clustering_report.md"
    json_path = output_dir / "lag_persistence_clustering_report.json"
    md_path.write_text(render_report(payload), encoding="utf-8")
    common.write_json_report(
        json_path,
        {
            "dataset": payload["dataset"],
            "sections": [
                {
                    **{k: v for k, v in section.items() if k not in {"summary", "tables", "conflict_table", "conflict_summary"}},
                    "summary": section["summary"].to_dict(orient="records"),
                    "tables": {name: table.to_dict(orient="records") for name, table in section["tables"].items()},
                    "conflict_table": section.get("conflict_table", pd.DataFrame()).to_dict(orient="records"),
                    "conflict_summary": section.get("conflict_summary", pd.DataFrame()).to_dict(orient="records"),
                }
                for section in payload["sections"]
            ],
        },
    )
    return md_path, json_path


def main() -> int:
    args = parse_args()
    db_root = Path(args.db_root)
    output_dir = Path(args.output_dir)
    pooled = load_pooled_machine_type_frame(db_root, min_db_size_bytes=args.min_db_size_bytes)
    analyzed = add_temporal_lag_features(pooled)
    payload = build_report_payload(analyzed)
    md_path, json_path = save_report(payload, output_dir)
    print(f"wrote: {md_path}")
    print(f"wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
