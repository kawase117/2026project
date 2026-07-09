from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import stage4_real_money as stage4
from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_SLUGS

BIAS_CHECK_FILENAME = "stage5_shrinkage_bias_check.csv"
BIAS_CHECK_COLUMNS = ["machine_number", "mean_G", "raw_pct_family_180d", "b_rank_180d"]


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


def _add_raw_pct_family_180d(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.sort_values(["machine_number", "date_dt", "machine_name"], kind="mergesort").copy()

    def _rolling_raw(group: pd.DataFrame) -> pd.Series:
        indexed = group.set_index("date_dt")["pct_family"]
        rolling = indexed.rolling("180D", closed="left").mean()
        return pd.Series(rolling.to_numpy(dtype=float), index=group.index, dtype=float)

    work["raw_pct_family_180d"] = work.groupby("machine_number", group_keys=False, sort=False).apply(_rolling_raw)
    return work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)


def build_stage5_shrinkage_bias_check_outputs(
    *,
    hall: str,
    db_path: Path | None = None,
    stage3_csv: Path | None = None,
    stage5_csv: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, pd.DataFrame | float | Path]:
    resolved_db_path = stage4._resolve_db_path(hall, db_path)
    resolved_stage3 = _resolve_stage3_csv(hall, stage3_csv)
    resolved_stage5 = _resolve_stage5_csv(hall, stage5_csv)
    resolved_output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(hall)

    stage3_frame = stage4._prepare_stage3(_load_csv(resolved_stage3), hall=hall)
    stage5_frame = stage4._prepare_stage5(_load_csv(resolved_stage5), hall=hall)
    db_frame = stage4._prepare_db_frame(stage4._load_db_frame(resolved_db_path), hall=hall)
    merged = stage4._merge_frames(stage3_frame, stage5_frame, db_frame)
    merged = stage4._add_b_rank_features(merged)
    merged = merged.loc[merged["date_dt"].ge(stage4.EVAL_START_DATE)].copy()
    merged = _add_raw_pct_family_180d(merged)

    machine_summary = (
        merged.groupby("machine_number", sort=True, dropna=False)
        .agg(
            mean_G=("games_normalized", "mean"),
            raw_pct_family_180d=("raw_pct_family_180d", "mean"),
            b_rank_180d=("b_rank_180d", "mean"),
        )
        .reset_index()
        .sort_values("machine_number", kind="mergesort")
        .reset_index(drop=True)
    )
    machine_summary = machine_summary.loc[:, BIAS_CHECK_COLUMNS].copy()
    correlation = (
        float(machine_summary["mean_G"].corr(machine_summary["b_rank_180d"]))
        if not machine_summary.empty
        else float("nan")
    )

    return {
        "machine_summary": machine_summary,
        "correlation_mean_G_b_rank_180d": correlation,
        "stage3_csv": resolved_stage3,
        "stage5_csv": resolved_stage5,
        "db_path": resolved_db_path,
        "output_dir": resolved_output_dir,
    }


def save_stage5_shrinkage_bias_check_outputs(outputs: dict[str, pd.DataFrame | float | Path], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    machine_summary = outputs["machine_summary"]
    assert isinstance(machine_summary, pd.DataFrame)
    machine_summary.to_csv(output_dir / BIAS_CHECK_FILENAME, index=False, encoding="utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Stage 5 shrinkage bias check")
    parser.add_argument("--hall", default=DEFAULT_HALL)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--stage3-csv", type=Path, default=None)
    parser.add_argument("--stage5-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall))
    outputs = build_stage5_shrinkage_bias_check_outputs(
        hall=args.hall,
        db_path=args.db_path,
        stage3_csv=args.stage3_csv,
        stage5_csv=args.stage5_csv,
        output_dir=output_dir,
    )
    save_stage5_shrinkage_bias_check_outputs(outputs, output_dir)
    correlation = outputs["correlation_mean_G_b_rank_180d"]
    assert isinstance(correlation, float)
    print(f"[OK] wrote {output_dir / BIAS_CHECK_FILENAME}")
    print(f"[INFO] mean_G vs b_rank_180d correlation: {correlation:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
