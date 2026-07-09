from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from ml.experiments.jug_rb_setting_prediction.config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_SLUGS  # noqa: E402
else:  # pragma: no cover - exercised via package imports in tests
    from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_SLUGS  # noqa: E402

STAGE3_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "weekday",
    "day_of_month",
    "is_event_day",
]

STAGE5_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "family_key",
    "section",
    "pct_family",
    "pct_section",
]

ALLOC_FILENAMES = {
    "machine_weekday": "stage5_alloc_machine_weekday.csv",
    "machine_dd": "stage5_alloc_machine_dd.csv",
    "section_event_day": "stage5_alloc_section_event_day.csv",
    "kakuban_rank_min_section_size": "stage5_alloc_kakuban_rank_min_section_size.csv",
    "family_gap": "stage5_alloc_family_gap.csv",
}

SUMMARY_PATH = "stage5_alloc_summary.md"


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_stage3_csv(hall: str, stage3_csv: Path | None = None) -> Path:
    if stage3_csv is not None:
        return Path(stage3_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage3_features.csv"


def _resolve_stage5_csv(hall: str, stage5_csv: Path | None = None) -> Path:
    if stage5_csv is not None:
        return Path(stage5_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage5_rank_daily.csv"


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, encoding="utf-8-sig")


def _prepare_stage3(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    missing = [column for column in STAGE3_REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        raise ValueError(f"stage3 frame is missing required columns: {missing}")

    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    for column in ("weekday", "day_of_month", "is_event_day", "kakuban_rank_min", "section_size"):
        if column not in work.columns:
            work[column] = pd.NA
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(
        subset=["date_dt", "machine_number", "machine_name", "weekday", "day_of_month", "is_event_day"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["weekday"] = work["weekday"].astype(int)
    work["day_of_month"] = work["day_of_month"].astype(int)
    work["is_event_day"] = work["is_event_day"].astype(int)
    work["kakuban_rank_min"] = work["kakuban_rank_min"].astype("Int64")
    work["section_size"] = work["section_size"].astype("Int64")
    work["machine_name"] = work["machine_name"].astype(str)
    work["hall"] = hall
    return work


def _prepare_stage5(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    missing = [column for column in STAGE5_REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        raise ValueError(f"stage5 frame is missing required columns: {missing}")

    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["pct_family"] = pd.to_numeric(work["pct_family"], errors="coerce")
    if "pct_section" in work.columns:
        work["pct_section"] = pd.to_numeric(work["pct_section"], errors="coerce")
    else:
        work["pct_section"] = pd.NA
    work["machine_name"] = work["machine_name"].astype(str)
    work["family_key"] = work["family_key"].astype(str)
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "pct_family"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    for column in ("kakuban_rank_min", "section_size"):
        if column not in work.columns:
            work[column] = pd.NA
        work[column] = pd.to_numeric(work[column], errors="coerce").astype("Int64")
    work["hall"] = hall
    return work


def _merge_frames(stage3_frame: pd.DataFrame, stage5_frame: pd.DataFrame) -> pd.DataFrame:
    merged = stage5_frame.merge(
        stage3_frame,
        on=["date", "machine_number", "machine_name", "date_dt", "hall"],
        how="inner",
        validate="one_to_one",
        suffixes=("", "_stage3"),
    )
    if merged.empty:
        raise ValueError("No rows remained after merging stage3 and stage5 frames")

    for column in ("kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"):
        stage3_column = f"{column}_stage3"
        if stage3_column in merged.columns:
            merged[column] = merged[column].where(merged[column].notna(), merged[stage3_column])
            merged = merged.drop(columns=[stage3_column])

    merged["pct_gap"] = merged["pct_family"] - merged["pct_section"]
    merged["weekday_name"] = merged["weekday"].map(
        {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    )
    return merged.sort_values(["date_dt", "machine_number"], kind="mergesort").reset_index(drop=True)


def _aggregate_frame(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    value_col: str,
    label: str,
    extra_value_cols: list[str] | None = None,
) -> pd.DataFrame:
    work = frame.copy()
    valid_cols = [value_col]
    if extra_value_cols:
        valid_cols.extend(extra_value_cols)
    work = work.dropna(subset=valid_cols).copy()
    if work.empty:
        return pd.DataFrame(columns=[*group_cols, "n_rows", f"mean_{label}"])

    rows: list[dict[str, object]] = []
    for keys, group in work.groupby(group_cols, sort=True, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row: dict[str, object] = dict(zip(group_cols, keys, strict=False))
        row["n_rows"] = int(len(group))
        row[f"mean_{label}"] = float(pd.to_numeric(group[value_col], errors="coerce").mean())
        if extra_value_cols:
            for extra_col in extra_value_cols:
                row[f"mean_{extra_col}"] = float(pd.to_numeric(group[extra_col], errors="coerce").mean())
        rows.append(row)
    return (
        pd.DataFrame(rows)
        .sort_values(["n_rows", f"mean_{label}"], ascending=[False, False], kind="mergesort")
        .reset_index(drop=True)
    )


def _format_top_bottom(table: pd.DataFrame, *, value_col: str, n: int = 5) -> list[str]:
    if table.empty:
        return ["No rows."]
    ordered = table.copy()
    ordered["_abs"] = (
        (pd.to_numeric(ordered[value_col], errors="coerce") - 0.5).abs()
        if value_col.startswith("mean_pct")
        else pd.to_numeric(ordered[value_col], errors="coerce").abs()
    )
    top = (
        ordered.sort_values(["_abs", "n_rows"], ascending=[False, False], kind="mergesort")
        .head(n)
        .drop(columns=["_abs"])
    )
    bottom = (
        ordered.sort_values(["_abs", "n_rows"], ascending=[True, False], kind="mergesort")
        .head(n)
        .drop(columns=["_abs"])
    )
    return [
        top.to_string(index=False),
        "",
        bottom.to_string(index=False),
    ]


def _build_summary(hall: str, *, output_dir: Path, tables: dict[str, pd.DataFrame]) -> str:
    lines = [
        "# Stage 5 Allocation EDA",
        "",
        f"- hall: `{hall}`",
        f"- output_dir: `{output_dir}`",
        "",
        "This report is descriptive only.",
        "",
    ]
    for key, filename in ALLOC_FILENAMES.items():
        table = tables[key]
        lines.extend(
            [
                f"## {filename}",
                "",
                f"- rows: {len(table)}",
                f"- columns: {', '.join(table.columns)}",
                "",
            ]
        )
        if table.empty:
            lines.append("No rows.")
            lines.append("")
            continue
        value_col = next(
            (column for column in table.columns if column.startswith("mean_") and column != "mean_pct_section"),
            "mean_pct_family",
        )
        lines.append("Top/Bottom by deviation:")
        lines.extend(_format_top_bottom(table, value_col=value_col, n=5))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_stage5_alloc_outputs(
    *,
    hall: str,
    stage3_csv: Path | None = None,
    stage5_csv: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, pd.DataFrame | str | Path]:
    resolved_stage3 = _resolve_stage3_csv(hall, stage3_csv)
    resolved_stage5 = _resolve_stage5_csv(hall, stage5_csv)
    resolved_output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(hall)

    stage3_frame = _prepare_stage3(_load_csv(resolved_stage3), hall=hall)
    stage5_frame = _prepare_stage5(_load_csv(resolved_stage5), hall=hall)
    merged = _merge_frames(stage3_frame, stage5_frame)

    machine_weekday = _aggregate_frame(
        merged, group_cols=["machine_number", "weekday", "weekday_name"], value_col="pct_family", label="pct_family"
    )
    machine_dd = _aggregate_frame(
        merged, group_cols=["machine_number", "day_of_month"], value_col="pct_family", label="pct_family"
    )
    layoutless = merged["section"].isna().all()
    if layoutless:
        section_event_day = pd.DataFrame(columns=["section", "is_event_day", "n_rows", "mean_pct_family"])
        kakuban_section = pd.DataFrame(columns=["kakuban_rank_min", "section_size", "n_rows", "mean_pct_family"])
        family_gap = pd.DataFrame(
            columns=["family_key", "section", "n_rows", "mean_pct_gap", "mean_pct_family", "mean_pct_section"]
        )
    else:
        section_event_day = _aggregate_frame(
            merged, group_cols=["section", "is_event_day"], value_col="pct_family", label="pct_family"
        )
        kakuban_section = _aggregate_frame(
            merged, group_cols=["kakuban_rank_min", "section_size"], value_col="pct_family", label="pct_family"
        )
        family_gap = _aggregate_frame(
            merged,
            group_cols=["family_key", "section"],
            value_col="pct_gap",
            label="pct_gap",
            extra_value_cols=["pct_family", "pct_section"],
        )

    tables = {
        "machine_weekday": machine_weekday,
        "machine_dd": machine_dd,
        "section_event_day": section_event_day,
        "kakuban_rank_min_section_size": kakuban_section,
        "family_gap": family_gap,
    }
    summary = _build_summary(hall, output_dir=resolved_output_dir, tables=tables)
    return {
        **tables,
        "summary": summary,
        "stage3_csv": resolved_stage3,
        "stage5_csv": resolved_stage5,
        "output_dir": resolved_output_dir,
    }


def save_stage5_alloc_outputs(outputs: dict[str, pd.DataFrame | str | Path], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in ALLOC_FILENAMES.items():
        table = outputs[key]
        assert isinstance(table, pd.DataFrame)
        table.to_csv(output_dir / filename, index=False, encoding="utf-8-sig")
    summary = outputs["summary"]
    assert isinstance(summary, str)
    (output_dir / SUMMARY_PATH).write_text(summary, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Stage 5 allocation EDA")
    parser.add_argument("--hall", default=DEFAULT_HALL)
    parser.add_argument("--stage3-csv", type=Path, default=None)
    parser.add_argument("--stage5-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall))
    outputs = build_stage5_alloc_outputs(
        hall=args.hall,
        stage3_csv=args.stage3_csv,
        stage5_csv=args.stage5_csv,
        output_dir=output_dir,
    )
    save_stage5_alloc_outputs(outputs, output_dir)
    print(f"[OK] wrote {output_dir / SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
