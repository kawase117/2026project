from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binom, skew

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from ml.experiments.jug_rb_setting_prediction.config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_DBS, HALL_SLUGS  # noqa: E402
    from ml.experiments.jug_rb_setting_prediction.stage1_machine_catalog import classify_machine_name  # noqa: E402
else:  # pragma: no cover - exercised via package imports in tests
    from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_DBS, HALL_SLUGS  # noqa: E402
    from .stage1_machine_catalog import classify_machine_name  # noqa: E402

STAGE5_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "family_key",
    "section",
    "G",
    "rb",
    "midp_family",
    "pct_family",
    "n_family",
    "midp_section",
    "pct_section",
    "n_section",
]

STAGE2_STAGE5_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "G",
    "rb",
    "bb",
    "p_high",
    "e_setting",
    "e_payout",
]

MIN_FAMILY_GROUP_SIZE = 5
MIN_SECTION_GROUP_SIZE = 4
DEFAULT_SUMMARY_PATH = "stage5_rank_daily_summary.md"


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_db_path(hall: str, db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    try:
        return HALL_DBS[hall]
    except KeyError as exc:  # pragma: no cover - argparse validates hall
        raise KeyError(f"unknown hall: {hall}") from exc


def _resolve_stage2_csv(hall: str, stage2_csv: Path | None = None) -> Path:
    if stage2_csv is not None:
        return Path(stage2_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage2_daily_posterior.csv"


def _load_stage2_frame(stage2_csv: Path) -> pd.DataFrame:
    if not stage2_csv.exists():
        raise FileNotFoundError(stage2_csv)
    frame = pd.read_csv(stage2_csv, encoding="utf-8-sig")
    missing = [column for column in STAGE2_STAGE5_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"stage2 frame is missing required columns: {missing}")
    return frame


def _load_machine_layout(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        layout = pd.read_sql_query(
            """
            SELECT
                machine_number,
                x,
                section,
                section_min,
                section_max,
                rank_from_min,
                rank_from_max
            FROM machine_layout
            """,
            conn,
        )
    required = ["machine_number", "x", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"]
    missing = [column for column in required if column not in layout.columns]
    if missing:
        raise ValueError(f"machine_layout is missing required columns: {missing}")
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
    layout["x"] = pd.to_numeric(layout["x"], errors="coerce")
    layout["section_min"] = pd.to_numeric(layout["section_min"], errors="coerce")
    layout["section_max"] = pd.to_numeric(layout["section_max"], errors="coerce")
    layout["rank_from_min"] = pd.to_numeric(layout["rank_from_min"], errors="coerce")
    layout["rank_from_max"] = pd.to_numeric(layout["rank_from_max"], errors="coerce")
    layout = layout.dropna(
        subset=["machine_number", "x", "section_min", "section_max", "rank_from_min", "rank_from_max"]
    ).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["section"] = layout["section"].fillna("unknown").astype(str)
    layout["kakuban_rank_min"] = layout["rank_from_min"].astype(int)
    layout["kakuban_rank_max"] = layout["rank_from_max"].astype(int)
    layout["section_size"] = (layout["section_max"] - layout["section_min"] + 1).astype(int)
    layout["is_corner1"] = layout[["rank_from_min", "rank_from_max"]].eq(1).any(axis=1).astype(int)
    section_medians = layout.groupby("section", dropna=False)["x"].transform("median")
    layout["side_lr"] = np.where(layout["x"].lt(section_medians), "L", "R")
    layout = layout.drop_duplicates(subset=["machine_number"], keep="first").copy()
    return layout.loc[
        :,
        ["machine_number", "section", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"],
    ]


def _prepare_stage2_frame(frame: pd.DataFrame, *, hall: str) -> tuple[pd.DataFrame, dict[str, int]]:
    work = frame.copy()
    counts = {
        "raw_rows": int(len(work)),
        "non_juggler_rows": 0,
        "unknown_family_rows": 0,
        "unmatched_layout_rows": 0,
    }

    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["machine_name"] = work["machine_name"].astype(str)
    work["G"] = pd.to_numeric(work["G"], errors="coerce")
    work["rb"] = pd.to_numeric(work["rb"], errors="coerce")
    work["bb"] = pd.to_numeric(work["bb"], errors="coerce")
    work["p_high"] = pd.to_numeric(work["p_high"], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "G", "rb", "bb", "p_high"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    before = len(work)
    work = work[work["machine_name"].str.contains("ジャグラー", na=False, regex=False)].copy()
    counts["non_juggler_rows"] = before - int(len(work))

    family_info = work["machine_name"].map(classify_machine_name)
    work["family_key"] = [item[1] for item in family_info]
    work["resolved_family_key"] = work["family_key"]
    work["is_unknown_family"] = [item[2] for item in family_info]
    counts["unknown_family_rows"] = int(work["is_unknown_family"].sum())
    work = work[~work["is_unknown_family"]].copy()
    for column in ("section", "x", "section_min", "section_max", "rank_from_min", "rank_from_max"):
        if column in work.columns:
            work = work.drop(columns=[column])

    work["date"] = work["date"].astype(str)
    work["hall"] = hall
    return work.reset_index(drop=True), counts


def _midp_values(g: pd.Series, rb: pd.Series, pooled_rate: float) -> pd.Series:
    if pd.isna(pooled_rate):
        return pd.Series(np.nan, index=g.index, dtype=float)
    p = float(np.clip(pooled_rate, 1e-12, 1 - 1e-12))
    g_numeric = pd.to_numeric(g, errors="coerce")
    rb_numeric = pd.to_numeric(rb, errors="coerce")
    valid = g_numeric.notna() & rb_numeric.notna()
    out = pd.Series(np.nan, index=g.index, dtype=float)
    if valid.any():
        g_values = g_numeric.loc[valid].astype(int)
        rb_values = rb_numeric.loc[valid].astype(int)
        out.loc[valid] = binom.cdf(rb_values - 1, g_values, p) + 0.5 * binom.pmf(rb_values, g_values, p)
    return out


def _apply_group_scores(frame: pd.DataFrame, *, group_cols: list[str], label: str, min_size: int) -> pd.DataFrame:
    work = frame.copy()
    midp_col = f"midp_{label}"
    pct_col = f"pct_{label}"
    n_col = f"n_{label}"
    work[midp_col] = np.nan
    work[pct_col] = np.nan
    work[n_col] = pd.NA

    for _, group in work.groupby(group_cols, sort=False, dropna=False):
        n = int(len(group))
        work.loc[group.index, n_col] = n
        pooled_games = pd.to_numeric(group["G"], errors="coerce").sum()
        pooled_rb = pd.to_numeric(group["rb"], errors="coerce").sum()
        if n < min_size or pd.isna(pooled_games) or pooled_games <= 0:
            continue
        pooled_rate = float(pooled_rb / pooled_games) if pooled_games else float("nan")
        work.loc[group.index, midp_col] = _midp_values(group["G"], group["rb"], pooled_rate)
        ranks = work.loc[group.index, midp_col].rank(method="average", ascending=True)
        work.loc[group.index, pct_col] = (ranks - 0.5) / n

    work[n_col] = pd.to_numeric(work[n_col], errors="coerce").astype("Int64")
    return work


def build_stage5_rank_daily(
    frame: pd.DataFrame, *, hall: str, layout_frame: pd.DataFrame | None = None
) -> pd.DataFrame:
    work, _ = _prepare_stage2_frame(frame, hall=hall)
    if work.empty:
        return pd.DataFrame(columns=STAGE5_COLUMNS)

    layout = layout_frame.copy() if layout_frame is not None else _load_machine_layout(_resolve_db_path(hall))
    missing_layout = [
        column
        for column in [
            "machine_number",
            "section",
            "kakuban_rank_min",
            "kakuban_rank_max",
            "section_size",
            "is_corner1",
            "side_lr",
        ]
        if column not in layout.columns
    ]
    if missing_layout:
        raise ValueError(f"layout frame is missing required columns: {missing_layout}")

    layout = layout.loc[
        :,
        ["machine_number", "section", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"],
    ].copy()
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
    layout["section"] = layout["section"].astype(str)
    layout["kakuban_rank_min"] = pd.to_numeric(layout["kakuban_rank_min"], errors="coerce")
    layout["kakuban_rank_max"] = pd.to_numeric(layout["kakuban_rank_max"], errors="coerce")
    layout["section_size"] = pd.to_numeric(layout["section_size"], errors="coerce")
    layout["is_corner1"] = pd.to_numeric(layout["is_corner1"], errors="coerce")
    layout["side_lr"] = layout["side_lr"].astype(str)
    layout = layout.dropna(subset=["machine_number", "section", "section_size"]).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["kakuban_rank_min"] = layout["kakuban_rank_min"].astype(int)
    layout["kakuban_rank_max"] = layout["kakuban_rank_max"].astype(int)
    layout["section_size"] = layout["section_size"].astype(int)
    layout["is_corner1"] = layout["is_corner1"].astype(int)

    layout_machine_numbers = set(layout["machine_number"].astype(int).tolist())
    has_layout = bool(layout_machine_numbers) and work["machine_number"].isin(layout_machine_numbers).any()

    if has_layout:
        merged = work.merge(layout, on="machine_number", how="inner", validate="many_to_one")
        if merged.empty:
            raise ValueError("No rows remained after merging stage2 rows with machine_layout")
        merged = merged.sort_values(
            ["date_dt", "family_key", "section", "machine_number"], kind="mergesort"
        ).reset_index(drop=True)
        merged = _apply_group_scores(
            merged, group_cols=["date", "family_key"], label="family", min_size=MIN_FAMILY_GROUP_SIZE
        )
        merged = _apply_group_scores(
            merged, group_cols=["date", "family_key", "section"], label="section", min_size=MIN_SECTION_GROUP_SIZE
        )
    else:
        merged = work.copy()
        for column in ["section", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"]:
            merged[column] = np.nan
        merged = merged.sort_values(["date_dt", "family_key", "machine_number"], kind="mergesort").reset_index(
            drop=True
        )
        merged = _apply_group_scores(
            merged, group_cols=["date", "family_key"], label="family", min_size=MIN_FAMILY_GROUP_SIZE
        )
        for column in ("midp_section", "pct_section", "n_section"):
            merged[column] = np.nan
    merged["date"] = merged["date"].astype(str)

    out = merged.loc[:, STAGE5_COLUMNS].copy()
    out = out.sort_values(["date", "family_key", "section", "machine_number"], kind="mergesort").reset_index(drop=True)
    return out


def _uniformity_summary(frame: pd.DataFrame) -> str:
    pct = pd.to_numeric(frame.get("pct_family"), errors="coerce").dropna().astype(float)
    if pct.empty:
        return "pct_family: no valid rows"
    return (
        f"pct_family: n={len(pct)}, mean={pct.mean():.6f}, std={pct.std(ddof=0):.6f}, "
        f"skew={skew(pct, bias=False):.6f}, min={pct.min():.6f}, max={pct.max():.6f}"
    )


def _build_report(
    *,
    hall: str,
    output_csv: Path,
    source_stage2: Path,
    db_path: Path,
    frame: pd.DataFrame,
    counts: dict[str, int],
) -> str:
    lines = [
        "# Stage 5 Rank Daily",
        "",
        f"- hall: `{hall}`",
        f"- db: `{db_path}`",
        f"- stage2: `{source_stage2}`",
        f"- output: `{output_csv}`",
        f"- raw rows: {counts['raw_rows']}",
        f"- non-juggler rows removed: {counts['non_juggler_rows']}",
        f"- unknown family rows removed: {counts['unknown_family_rows']}",
        "",
        "## Sanity",
        "",
        _uniformity_summary(frame),
        f"family group valid rows: {int(pd.to_numeric(frame['n_family'], errors='coerce').ge(MIN_FAMILY_GROUP_SIZE).sum())}",
        f"section group valid rows: {int(pd.to_numeric(frame['n_section'], errors='coerce').ge(MIN_SECTION_GROUP_SIZE).sum())}",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_stage5_outputs(
    *,
    hall: str,
    db_path: Path | None = None,
    stage2_csv: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, pd.DataFrame | str | Path]:
    resolved_db_path = _resolve_db_path(hall, db_path)
    resolved_stage2_csv = _resolve_stage2_csv(hall, stage2_csv)
    resolved_output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(hall)
    stage2_frame = _load_stage2_frame(resolved_stage2_csv)
    layout_frame = _load_machine_layout(resolved_db_path)
    prepared, counts = _prepare_stage2_frame(stage2_frame, hall=hall)
    rank_daily = build_stage5_rank_daily(prepared, hall=hall, layout_frame=layout_frame)
    report = _build_report(
        hall=hall,
        output_csv=resolved_output_dir / "stage5_rank_daily.csv",
        source_stage2=resolved_stage2_csv,
        db_path=resolved_db_path,
        frame=rank_daily,
        counts=counts,
    )
    return {
        "rank_daily": rank_daily,
        "report": report,
        "db_path": resolved_db_path,
        "stage2_csv": resolved_stage2_csv,
    }


def save_stage5_outputs(outputs: dict[str, pd.DataFrame | str | Path], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rank_daily = outputs["rank_daily"]
    report = outputs["report"]
    assert isinstance(rank_daily, pd.DataFrame)
    assert isinstance(report, str)
    rank_daily.to_csv(output_dir / "stage5_rank_daily.csv", index=False, encoding="utf-8-sig")
    (output_dir / DEFAULT_SUMMARY_PATH).write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="蒲田ジャグラー Stage 5 daily rank export")
    parser.add_argument("--hall", default=DEFAULT_HALL)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--stage2-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall))
    outputs = build_stage5_outputs(
        hall=args.hall, db_path=args.db_path, stage2_csv=args.stage2_csv, output_dir=output_dir
    )
    save_stage5_outputs(outputs, output_dir)
    rank_daily = outputs["rank_daily"]
    assert isinstance(rank_daily, pd.DataFrame)
    print(f"[OK] wrote {output_dir / 'stage5_rank_daily.csv'}")
    print(_uniformity_summary(rank_daily))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
