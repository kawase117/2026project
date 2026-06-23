from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

from ml.experiments.gate_analysis.config import (
    ANNIVERSARY_MMDD,
    COORDS_2F_PATH,
    COORDS_3F_PATH,
    DEFAULT_DB_FALLBACK,
    EVENT_DDS,
    GAMES_MIN,
    GATE_QUANTILES,
    GATE_WINDOW_DAYS,
    PRIMARY_GATE_QUANTILE,
    PROJECT_ROOT,
    RESULTS_DIR,
    SEGMENT_ORDER,
)
from ml.experiments.walkforward_scoring.scoring_model import classify_seg as _walkforward_classify_seg


def resolve_default_db_path() -> Path:
    db_dir = PROJECT_ROOT / "db"
    candidates = [path for path in db_dir.glob("*蒲田7*.db") if path.is_file() and path.stat().st_size > 0]
    if candidates:
        return sorted(candidates, key=lambda path: path.stat().st_size, reverse=True)[0]
    return DEFAULT_DB_FALLBACK


DEFAULT_DB_PATH = resolve_default_db_path()


def classify_seg(machine_name: object) -> str:
    return _walkforward_classify_seg(machine_name)


def is_event_day(date_str: str) -> bool:
    date_text = str(date_str)
    if len(date_text) < 8:
        return False
    dt = pd.to_datetime(date_text, format="%Y%m%d", errors="coerce")
    if pd.isna(dt):
        return False
    dd = int(dt.day)
    mmdd = date_text[4:8]
    is_month_end = bool(dt.is_month_end)
    return dd in EVENT_DDS or is_month_end or mmdd == ANNIVERSARY_MMDD


def _read_machine_detailed_results(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    if frame.empty:
        raise ValueError(f"machine_detailed_results returned no rows in {db_path}")
    return frame


def _read_coordinates(coords_2f_path: Path = COORDS_2F_PATH, coords_3f_path: Path = COORDS_3F_PATH) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in (coords_2f_path, coords_3f_path):
        coords = pd.read_csv(path, encoding="utf-8-sig")
        required = {
            "machine_number",
            "floor",
            "section",
            "section_min",
            "section_max",
            "rank_from_min",
            "rank_from_max",
        }
        missing = sorted(required - set(coords.columns))
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        coords = coords.copy()
        coords["machine_number"] = pd.to_numeric(coords["machine_number"], errors="coerce")
        coords["section_min"] = pd.to_numeric(coords["section_min"], errors="coerce")
        coords["section_max"] = pd.to_numeric(coords["section_max"], errors="coerce")
        coords["rank_from_min"] = pd.to_numeric(coords["rank_from_min"], errors="coerce")
        coords["rank_from_max"] = pd.to_numeric(coords["rank_from_max"], errors="coerce")
        coords = coords.dropna(subset=["machine_number", "floor", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"]).copy()
        coords["machine_number"] = coords["machine_number"].astype(int)
        coords["floor"] = coords["floor"].astype(str)
        coords["section"] = coords["section"].astype(str)
        frames.append(coords)
    if not frames:
        return pd.DataFrame(columns=["machine_number", "floor", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"])
    coords = pd.concat(frames, ignore_index=True)
    coords["section_median"] = coords.groupby("section")["machine_number"].transform("median")
    coords["lr"] = coords["machine_number"].le(coords["section_median"]).map({True: "L", False: "R"})
    return coords.drop_duplicates(subset=["machine_number"]).reset_index(drop=True)


def _prepare_frame(
    db_path: Path,
    coords_2f_path: Path = COORDS_2F_PATH,
    coords_3f_path: Path = COORDS_3F_PATH,
) -> pd.DataFrame:
    raw = _read_machine_detailed_results(db_path)
    coords = _read_coordinates(coords_2f_path, coords_3f_path)

    raw = raw.copy()
    raw["date"] = raw["date"].astype(str)
    raw["date_dt"] = pd.to_datetime(raw["date"], format="%Y%m%d", errors="coerce")
    raw["machine_number"] = pd.to_numeric(raw["machine_number"], errors="coerce")
    raw["games_normalized"] = pd.to_numeric(raw["games_normalized"], errors="coerce")
    raw["diff_coins_normalized"] = pd.to_numeric(raw["diff_coins_normalized"], errors="coerce")
    raw = raw.dropna(subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]).copy()
    raw["machine_number"] = raw["machine_number"].astype(int)
    raw = raw[raw["machine_number"] != 2026].copy()
    raw["date"] = raw["date_dt"].dt.strftime("%Y%m%d")
    raw["dd"] = raw["date_dt"].dt.day.astype(int)
    raw["dow"] = raw["date_dt"].dt.day_name().str[:3]
    raw["is_event"] = raw["date"].map(is_event_day).astype(bool)
    raw["payout_rate"] = ((raw["games_normalized"] * 3 + raw["diff_coins_normalized"]) / (raw["games_normalized"] * 3)) * 100
    raw["seg"] = raw["machine_name"].map(classify_seg)

    merged = raw.merge(
        coords[["machine_number", "floor", "section", "section_min", "section_max", "rank_from_min", "rank_from_max", "lr"]],
        on="machine_number",
        how="inner",
        validate="m:1",
    )
    if merged.empty:
        raise ValueError("No rows remained after joining machine_detailed_results and coordinate CSVs")
    merged["segment"] = merged["floor"].astype(str) + "_" + merged["lr"].astype(str) + "_" + merged["seg"].astype(str)
    return merged


def _quantile_label(quantile: float) -> str:
    return f"q{int(round(float(quantile) * 100)):02d}"


def _rolling_quantile_col(quantile: float) -> str:
    return f"rolling_{_quantile_label(quantile)}"


def _gate_positive_col(quantile: float) -> str:
    return f"gate_positive_{_quantile_label(quantile)}"


def _attach_rolling_quantile_gates(
    segment_daily_counts: pd.DataFrame,
    *,
    quantiles: Iterable[float] = GATE_QUANTILES,
    window_days: int = GATE_WINDOW_DAYS,
) -> pd.DataFrame:
    work = segment_daily_counts.sort_values(["segment", "date"]).copy()
    work["history_days"] = work.groupby("segment").cumcount()
    work["eligible_for_gate"] = work["history_days"] >= window_days

    for quantile in quantiles:
        rolling_col = _rolling_quantile_col(quantile)
        gate_col = _gate_positive_col(quantile)
        work[rolling_col] = pd.NA
        work[gate_col] = False

        for _, idx in work.groupby("segment", sort=False).groups.items():
            segment_series = work.loc[idx, "segment_avg_payout"].astype(float)
            history = segment_series.shift(1)
            rolling_quantile = history.rolling(window=window_days, min_periods=window_days).quantile(quantile)
            work.loc[idx, rolling_col] = rolling_quantile.to_numpy()
            gate_positive = work.loc[idx, "eligible_for_gate"] & work.loc[idx, "segment_avg_payout"].ge(rolling_quantile)
            work.loc[idx, gate_col] = gate_positive.fillna(False).to_numpy()

        work[rolling_col] = pd.to_numeric(work[rolling_col], errors="coerce")
        work[gate_col] = work[gate_col].fillna(False).astype(bool)

    work[_gate_positive_col(PRIMARY_GATE_QUANTILE)] = work[_gate_positive_col(PRIMARY_GATE_QUANTILE)].astype(bool)
    work["gate_positive"] = work[_gate_positive_col(PRIMARY_GATE_QUANTILE)]
    return work


def _format_markdown_table(frame: pd.DataFrame, *, float_digits: int = 3) -> str:
    if frame.empty:
        return "No rows."
    work = frame.copy()
    columns = [str(col) for col in work.columns]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    rows: list[str] = []
    for _, row in work.iterrows():
        values: list[str] = []
        for col in work.columns:
            value = row[col]
            if pd.isna(value):
                values.append("")
            elif isinstance(value, float):
                values.append(f"{value:.{float_digits}f}")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def build_segment_daily_counts(
    db_path: Path,
    coords_2f_path: Path = COORDS_2F_PATH,
    coords_3f_path: Path = COORDS_3F_PATH,
) -> pd.DataFrame:
    frame = _prepare_frame(db_path, coords_2f_path, coords_3f_path)
    eligible = frame[frame["games_normalized"] >= GAMES_MIN].copy()

    date_index = pd.Index(sorted(frame["date"].unique()), name="date")
    segment_index = pd.Index(SEGMENT_ORDER, name="segment")
    scaffold = pd.MultiIndex.from_product([date_index, segment_index], names=["date", "segment"]).to_frame(index=False)

    agg = (
        eligible.groupby(["date", "segment"], as_index=False)
        .agg(
            n_machines=("machine_number", "size"),
            segment_avg_payout=("payout_rate", "mean"),
        )
        .copy()
    )
    merged = scaffold.merge(agg, on=["date", "segment"], how="left")
    merged["n_machines"] = merged["n_machines"].fillna(0).astype(int)
    merged["segment_avg_payout"] = merged["segment_avg_payout"].fillna(0.0).astype(float)
    merged["is_event"] = merged["date"].map(is_event_day).astype(bool)
    merged["dd"] = pd.to_datetime(merged["date"], format="%Y%m%d", errors="coerce").dt.day.astype("Int64").fillna(0).astype(int)
    merged["dow"] = pd.to_datetime(merged["date"], format="%Y%m%d", errors="coerce").dt.day_name().str[:3]
    merged = _attach_rolling_quantile_gates(merged, quantiles=GATE_QUANTILES, window_days=GATE_WINDOW_DAYS)
    merged["primary_gate_quantile"] = PRIMARY_GATE_QUANTILE
    merged = merged[
        [
            "date",
            "segment",
            "n_machines",
            "segment_avg_payout",
            "history_days",
            "eligible_for_gate",
            _rolling_quantile_col(0.60),
            _gate_positive_col(0.60),
            _rolling_quantile_col(0.70),
            _gate_positive_col(0.70),
            _rolling_quantile_col(0.80),
            _gate_positive_col(0.80),
            "gate_positive",
            "primary_gate_quantile",
            "is_event",
            "dow",
            "dd",
        ]
    ]
    return merged.sort_values(["date", "segment"]).reset_index(drop=True)


def build_gate_sensitivity(segment_daily_counts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        seg = segment_daily_counts[segment_daily_counts["segment"] == segment].copy()
        for quantile in GATE_QUANTILES:
            rolling_col = _rolling_quantile_col(quantile)
            gate_col = _gate_positive_col(quantile)
            analyzable = seg[seg["eligible_for_gate"] & seg[rolling_col].notna()].copy()
            active = analyzable[gate_col].astype(bool)
            active_days = int(active.sum())
            total_days = int(len(analyzable))
            active_avg = float(analyzable.loc[active, "segment_avg_payout"].mean()) if active_days else 0.0
            inactive_avg = float(analyzable.loc[~active, "segment_avg_payout"].mean()) if active_days < total_days else 0.0
            if pd.isna(active_avg):
                active_avg = 0.0
            if pd.isna(inactive_avg):
                inactive_avg = 0.0
            rows.append(
                {
                    "segment": segment,
                    "gate_quantile": float(quantile),
                    "gate_label": _quantile_label(quantile),
                    "window_days": int(GATE_WINDOW_DAYS),
                    "n_active_days": active_days,
                    "n_total_days": total_days,
                    "active_rate": (active_days / total_days * 100.0) if total_days else 0.0,
                    "active_avg_payout": active_avg,
                    "inactive_avg_payout": inactive_avg,
                    "payout_gap": active_avg - inactive_avg,
                }
            )
    return pd.DataFrame(rows).sort_values(["segment", "gate_quantile"]).reset_index(drop=True)


def _primary_gate_view(segment_daily_counts: pd.DataFrame) -> pd.DataFrame:
    primary_gate_col = _gate_positive_col(PRIMARY_GATE_QUANTILE)
    rolling_col = _rolling_quantile_col(PRIMARY_GATE_QUANTILE)
    return segment_daily_counts[segment_daily_counts["eligible_for_gate"] & segment_daily_counts[rolling_col].notna() & segment_daily_counts[primary_gate_col].notna()].copy()


def _event_comparison(segment_daily_counts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seg = _primary_gate_view(segment_daily_counts)
    primary_gate_col = _gate_positive_col(PRIMARY_GATE_QUANTILE)
    for segment in SEGMENT_ORDER:
        part = seg[seg["segment"] == segment]
        for is_event in (True, False):
            subset = part[part["is_event"].eq(is_event)]
            active = subset[primary_gate_col].astype(bool)
            active_days = int(active.sum())
            total_days = int(len(subset))
            active_avg = float(subset.loc[active, "segment_avg_payout"].mean()) if active_days else 0.0
            inactive_avg = float(subset.loc[~active, "segment_avg_payout"].mean()) if active_days < total_days else 0.0
            if pd.isna(active_avg):
                active_avg = 0.0
            if pd.isna(inactive_avg):
                inactive_avg = 0.0
            rows.append(
                {
                    "segment": segment,
                    "is_event": is_event,
                    "gate_quantile": PRIMARY_GATE_QUANTILE,
                    "gate_label": _quantile_label(PRIMARY_GATE_QUANTILE),
                    "n_days": total_days,
                    "active_rate": (active_days / total_days * 100.0) if total_days else 0.0,
                    "active_avg_payout": active_avg,
                    "inactive_avg_payout": inactive_avg,
                    "payout_gap": active_avg - inactive_avg,
                }
            )
    return pd.DataFrame(rows)


def _weekday_cross(segment_daily_counts: pd.DataFrame) -> pd.DataFrame:
    seg = _primary_gate_view(segment_daily_counts)
    primary_gate_col = _gate_positive_col(PRIMARY_GATE_QUANTILE)
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        part = seg[seg["segment"] == segment]
        for dow in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            subset = part[part["dow"] == dow]
            rows.append(
                {
                    "segment": segment,
                    "dow": dow,
                    "gate_quantile": PRIMARY_GATE_QUANTILE,
                    "gate_label": _quantile_label(PRIMARY_GATE_QUANTILE),
                    "n_days": int(len(subset)),
                    "active_rate": (float(subset[primary_gate_col].mean()) * 100.0) if len(subset) else 0.0,
                    "avg_payout": float(subset["segment_avg_payout"].mean()) if len(subset) else 0.0,
                }
            )
    return pd.DataFrame(rows)


def _dd_cross(segment_daily_counts: pd.DataFrame) -> pd.DataFrame:
    seg = _primary_gate_view(segment_daily_counts)
    primary_gate_col = _gate_positive_col(PRIMARY_GATE_QUANTILE)
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        part = seg[seg["segment"] == segment]
        for dd in range(1, 32):
            subset = part[part["dd"] == dd]
            rows.append(
                {
                    "segment": segment,
                    "dd": dd,
                    "gate_quantile": PRIMARY_GATE_QUANTILE,
                    "gate_label": _quantile_label(PRIMARY_GATE_QUANTILE),
                    "n_days": int(len(subset)),
                    "active_rate": (float(subset[primary_gate_col].mean()) * 100.0) if len(subset) else 0.0,
                    "avg_payout": float(subset["segment_avg_payout"].mean()) if len(subset) else 0.0,
                }
            )
    return pd.DataFrame(rows)


def build_report(segment_daily_counts: pd.DataFrame, gate_sensitivity: pd.DataFrame, *, output_dir: Path) -> str:
    event_comparison = _event_comparison(segment_daily_counts)
    weekday_cross = _weekday_cross(segment_daily_counts)
    dd_cross = _dd_cross(segment_daily_counts)

    primary_gate_col = _gate_positive_col(PRIMARY_GATE_QUANTILE)
    primary_rolling_col = _rolling_quantile_col(PRIMARY_GATE_QUANTILE)

    daily_hist_rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        seg = _primary_gate_view(segment_daily_counts)
        seg = seg[seg["segment"] == segment]
        if seg.empty:
            continue
        active = seg[primary_gate_col].astype(bool)
        daily_hist_rows.append(
            {
                "segment": segment,
                "n_days": int(len(segment_daily_counts[segment_daily_counts["segment"] == segment])),
                "warmup_days": int((~segment_daily_counts[segment_daily_counts["segment"] == segment]["eligible_for_gate"]).sum()),
                "eligible_days": int(len(seg)),
                "avg_segment_avg_payout": float(seg["segment_avg_payout"].mean()),
                "median_segment_avg_payout": float(seg["segment_avg_payout"].median()),
                "avg_rolling_q70": float(seg[primary_rolling_col].mean()),
                "gate_positive_days": int(active.sum()),
                "gate_negative_days": int((~active).sum()),
                "gate_positive_rate_%": float(active.mean() * 100.0) if len(seg) else 0.0,
                "active_avg_payout": float(seg.loc[active, "segment_avg_payout"].mean()) if int(active.sum()) else 0.0,
                "inactive_avg_payout": float(seg.loc[~active, "segment_avg_payout"].mean()) if int(active.sum()) < len(seg) else 0.0,
            }
        )
    daily_hist = pd.DataFrame(daily_hist_rows)

    recommendation = (
        gate_sensitivity.groupby(["gate_quantile", "gate_label"], as_index=False)
        .agg(
            avg_gap=("payout_gap", "mean"),
            avg_active_rate=("active_rate", "mean"),
            avg_active_payout=("active_avg_payout", "mean"),
        )
        .sort_values(["avg_gap", "avg_active_rate"], ascending=[False, False])
    )
    best_row = recommendation.iloc[0] if not recommendation.empty else None
    primary_label = _quantile_label(PRIMARY_GATE_QUANTILE)

    lines = [
        "# Gate Condition Analysis Report",
        "",
        f"Output: `{output_dir.as_posix()}`",
        f"Rows: {len(segment_daily_counts):,}",
        "",
        "## 1. Segment Daily Distribution",
        "",
        _format_markdown_table(daily_hist),
        "",
        f"- Primary gate: `segment_avg_payout >= rolling_{primary_label}` using the previous {GATE_WINDOW_DAYS} days.",
        f"- Warmup rows (`history_days < {GATE_WINDOW_DAYS}`) are excluded from gate sensitivity and cross tables.",
        "",
        "## 2. Rolling Quantile Gate Sensitivity",
        "",
        _format_markdown_table(gate_sensitivity.sort_values(["segment", "gate_quantile"])),
        "",
        "## 3. Event vs Non-Event",
        "",
        _format_markdown_table(event_comparison.sort_values(["segment", "is_event"])),
        "",
        "## 4. Weekday × Gate Cross Table",
        "",
        _format_markdown_table(weekday_cross.sort_values(["segment", "dow"])),
        "",
        "## 5. DD × Gate Cross Table",
        "",
        _format_markdown_table(dd_cross.sort_values(["segment", "dd"])),
        "",
        "## 6. Recommendation",
        "",
        f"Primary gate quantile: **{primary_label}** (`Top{int(round((1.0 - PRIMARY_GATE_QUANTILE) * 100))}%`)",
        f"Best sweep quantile by average gap: **{best_row['gate_label']}**" if best_row is not None else "Best sweep quantile by average gap: n/a",
        "",
        _format_markdown_table(recommendation),
        "",
        "- `DD=21` is included in the event-day definition.",
        "- `7/7` is treated as a special day and retained in the analysis.",
        "- Segment rows are retained even when `n_machines=0` or during warmup.",
        "",
        "## Raw Tables",
        "",
        "### segment_daily_counts.csv preview",
        "",
        _format_markdown_table(segment_daily_counts.head(24)),
        "",
        "### gate_sensitivity.csv preview",
        "",
        _format_markdown_table(gate_sensitivity),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def run_gate_analysis(
    db_path: Path | None = None,
    *,
    output_dir: Path = RESULTS_DIR,
    coords_2f_path: Path = COORDS_2F_PATH,
    coords_3f_path: Path = COORDS_3F_PATH,
) -> dict[str, pd.DataFrame]:
    db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    segment_daily_counts = build_segment_daily_counts(db_path, coords_2f_path, coords_3f_path)
    gate_sensitivity = build_gate_sensitivity(segment_daily_counts)
    report = build_report(segment_daily_counts, gate_sensitivity, output_dir=output_dir)

    segment_daily_counts.to_csv(output_dir / "segment_daily_counts.csv", index=False, encoding="utf-8-sig")
    gate_sensitivity.to_csv(output_dir / "gate_sensitivity.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(report, encoding="utf-8")

    return {
        "segment_daily_counts": segment_daily_counts,
        "gate_sensitivity": gate_sensitivity,
        "report": pd.DataFrame({"report": [report]}),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 gate condition analysis")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--coords-2f", type=Path, default=COORDS_2F_PATH)
    parser.add_argument("--coords-3f", type=Path, default=COORDS_3F_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    run_gate_analysis(
        db_path=args.db_path,
        output_dir=args.output_dir,
        coords_2f_path=args.coords_2f,
        coords_3f_path=args.coords_3f,
    )
    print(args.output_dir)
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
