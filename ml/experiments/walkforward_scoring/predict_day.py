from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import (
    DEFAULT_DB_PATH,
    RESULTS_DIR,
    SEGMENT_HIST_RATIO_V7,
    COMPONENT_LIFT_V7,
    build_variant_configs,
    compute_v7_segment_weights,
)
from .scoring_model import build_score_context, classify_seg, score_day
from .walk_forward_engine import load_machine_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Predict a single day with walk-forward scoring v7")
    parser.add_argument("--date", required=True, help="Target date in YYYYMMDD format")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    return parser


def _prepare_source(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = out["date"].astype(str)
    out["date_dt"] = pd.to_datetime(out["date"], format="%Y%m%d", errors="coerce")
    out["machine_number"] = pd.to_numeric(out["machine_number"], errors="coerce")
    out["games_normalized"] = pd.to_numeric(out["games_normalized"], errors="coerce")
    out["diff_coins_normalized"] = pd.to_numeric(out["diff_coins_normalized"], errors="coerce")
    if "is_zorome" in out.columns:
        out["is_zorome"] = pd.to_numeric(out["is_zorome"], errors="coerce").fillna(0).astype(int)
    else:
        out["is_zorome"] = 0
    out = out[out["date"].str[4:8] != "0707"].copy()
    out = out[out["machine_number"].ne(2026)].copy()
    return out.dropna(subset=["date_dt", "machine_number"]).reset_index(drop=True)


def _format_markdown_table(rows: pd.DataFrame) -> str:
    header = "| 順位 | 台番 | 機種名 | Seg | 角番 | 末尾 | ゾロ目 | スコア | C1 | C2 | C3 | C4 | C5 | C6 | hist |"
    divider = "|:---:|:---:|:---|:---|:---:|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines = [header, divider]
    for row in rows.itertuples(index=False):
        lines.append(
            "| {rank} | {machine_number} | {machine_name} | {segment} | {kakuban} | {last_digit} | {is_zorome} | "
            "{composite:.2f} | {c1:.2f} | {c2:.2f} | {c3:.2f} | {c4:.2f} | {c5:.2f} | {c6:.2f} | {hist_metric:.2f} |".format(
                rank=int(row.rank),
                machine_number=int(row.machine_number),
                machine_name=str(row.machine_name),
                segment=str(row.segment),
                kakuban=int(row.kakuban),
                last_digit=str(row.last_digit),
                is_zorome=int(row.is_zorome),
                composite=float(row.composite),
                c1=float(row.c1),
                c2=float(row.c2),
                c3=float(row.c3),
                c4=float(row.c4),
                c5=float(row.c5),
                c6=float(row.c6),
                hist_metric=float(row.hist_metric),
            )
        )
    return "\n".join(lines)


def _run_smoke_checks(scored: pd.DataFrame, source: pd.DataFrame) -> None:
    counts = source["machine_name"].dropna().map(classify_seg).value_counts()
    assert counts.get("A", 0) > 0, "classify_seg returned no A rows"

    for segment in COMPONENT_LIFT_V7:
        hist_ratio = SEGMENT_HIST_RATIO_V7[segment]
        struct_ratio = 1.0 - hist_ratio
        weights = compute_v7_segment_weights(segment, struct_ratio)
        total = sum(weights) + hist_ratio
        assert abs(total - 1.0) < 0.01, f"{segment}: weights sum={total}"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    target_date = pd.Timestamp(args.date).normalize()

    data = _prepare_source(load_machine_data(args.db_path))
    train = data[data["date_dt"] < target_date].copy()
    actual = data[data["date_dt"] == target_date].copy()
    if actual.empty:
        raise SystemExit(f"no rows found for {target_date.strftime('%Y-%m-%d')}")

    variant_map = build_variant_configs()
    variant = variant_map["v7_lift_weights"]
    context = build_score_context()
    scored = score_day(train, actual, variant, test_date=target_date, context=context)
    if scored.empty:
        raise SystemExit("no rows scored for target date")

    scored = scored.sort_values(["composite", "diff_coins_normalized", "machine_number"], ascending=[False, False, True]).reset_index(drop=True)
    scored["rank"] = range(1, len(scored) + 1)

    _run_smoke_checks(scored, data)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"predict_{target_date.strftime('%Y%m%d')}.csv"
    scored.to_csv(csv_path, index=False, encoding="utf-8-sig")

    top50 = scored.head(50).copy()
    print(_format_markdown_table(top50))
    print(csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
