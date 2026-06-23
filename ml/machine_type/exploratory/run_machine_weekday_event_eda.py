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
MIN_INTERACTION_N = 20
WEEKDAY_LABELS = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thu",
    4: "Fri",
    5: "Sat",
    6: "Sun",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Machine weekday/event interaction EDA for machine_type")
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


def add_machine_weekday_event_features(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    for column in ("efficiency", "is_top_3"):
        if column not in work.columns:
            work[column] = np.nan
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["date", "hall_id", "machine_name"]).copy()
    work = work.sort_values(["hall_id", "machine_name", "date"]).reset_index(drop=True)
    # daily_hall_summary.day_of_week is sparse/null in this repo, so derive weekdays directly from the date.
    work["day_of_week"] = work["date"].dt.dayofweek.astype(int)
    work["day_of_week_label"] = work["day_of_week"].map(WEEKDAY_LABELS).astype("object")
    work["event_group"] = work["date"].dt.day.map(common._event_group_for_day).astype(int)
    work["is_zorome_day"] = work["date"].dt.day.isin({11, 22}).astype(int)
    return work


def build_period_effect_table(df: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = []
    for value, group in df.groupby(column, sort=True):
        rows.append(
            {
                column: value,
                "n_rows": int(len(group)),
                "is_top_3_rate": float(group["is_top_3"].mean()) if len(group) else float("nan"),
                "mean_efficiency": float(group["efficiency"].mean()) if len(group) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def build_interaction_extremes(
    df: pd.DataFrame,
    *,
    group_cols: list[str],
    min_n: int = MIN_INTERACTION_N,
    top_n: int = 20,
) -> pd.DataFrame:
    if "machine_name" not in group_cols:
        raise ValueError("group_cols must include machine_name")
    missing = [col for col in [*group_cols, "machine_name", "efficiency"] if col not in df.columns]
    if missing:
        raise KeyError(f"missing columns: {missing}")
    machine_means = df.groupby("machine_name", sort=True)["efficiency"].mean()
    rows: list[dict[str, object]] = []
    for keys, group in df.groupby(group_cols, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n = int(len(group))
        if n < int(min_n):
            continue
        machine_name = str(group["machine_name"].iloc[0])
        baseline = float(machine_means.loc[machine_name])
        mean_efficiency = float(group["efficiency"].mean())
        row = {col: value for col, value in zip(group_cols, keys)}
        row.update(
            {
                "n": n,
                "group_mean_efficiency": mean_efficiency,
                "machine_mean_efficiency": baseline,
                "interaction_delta": mean_efficiency - baseline,
            }
        )
        rows.append(row)
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    top = table.sort_values(["interaction_delta", *group_cols], ascending=[False, *([True] * len(group_cols))]).head(top_n).copy()
    top["interaction_type"] = "top"
    bottom = table.sort_values(["interaction_delta", *group_cols], ascending=[True, *([True] * len(group_cols))]).head(top_n).copy()
    bottom["interaction_type"] = "bottom"
    return pd.concat([top, bottom], ignore_index=True, sort=False)


def build_report_payload(df: pd.DataFrame) -> dict[str, object]:
    weekday_table = build_period_effect_table(df, "day_of_week")
    event_group_table = build_period_effect_table(df, "event_group")
    zorome_table = build_period_effect_table(df, "is_zorome_day")
    weekday_interactions = build_interaction_extremes(df, group_cols=["machine_name", "day_of_week"], min_n=MIN_INTERACTION_N)
    event_interactions = build_interaction_extremes(df, group_cols=["machine_name", "event_group"], min_n=MIN_INTERACTION_N)
    zorome_interactions = build_interaction_extremes(df, group_cols=["machine_name", "is_zorome_day"], min_n=MIN_INTERACTION_N)
    machine_day_summary = common.build_machine_name_correlation_summary(
        df,
        ("day_of_week", "event_group", "is_zorome_day"),
        "efficiency",
        min_n=MIN_INTERACTION_N,
    )

    return {
        "dataset": {
            "rows": int(len(df)),
            "halls": int(df["hall_id"].nunique()),
            "machines": int(df["machine_name"].nunique()),
            "date_min": str(df["date"].min().date()) if not df.empty else None,
            "date_max": str(df["date"].max().date()) if not df.empty else None,
        },
        "weekday_table": weekday_table,
        "event_group_table": event_group_table,
        "zorome_table": zorome_table,
        "weekday_interactions": weekday_interactions,
        "event_interactions": event_interactions,
        "zorome_interactions": zorome_interactions,
        "machine_day_summary": machine_day_summary,
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
    lines = ["# Machine Weekday Event EDA", ""]
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
        ("Weekday effect", payload["weekday_table"]),
        ("Event group effect", payload["event_group_table"]),
        ("Zorome day effect", payload["zorome_table"]),
        ("Weekday interactions", payload["weekday_interactions"]),
        ("Event group interactions", payload["event_interactions"]),
        ("Zorome day interactions", payload["zorome_interactions"]),
        ("Machine-day summary", payload["machine_day_summary"]),
    ):
        lines.append(f"## {title}")
        lines.append("")
        lines.append(_format_markdown_table(table))
    return "\n".join(lines)


def save_report(payload: dict[str, object], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "run_machine_weekday_event_eda_report.md"
    json_path = output_dir / "run_machine_weekday_event_eda_report.json"
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
    analyzed = add_machine_weekday_event_features(pooled)
    payload = build_report_payload(analyzed)
    md_path, json_path = save_report(payload, output_dir)
    print(f"wrote: {md_path}")
    print(f"wrote: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
