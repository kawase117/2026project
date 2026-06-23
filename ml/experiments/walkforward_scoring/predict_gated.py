"""Gated prediction: apply gate (active-segment filter) on top of v6a / v9b / v9c."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import DEFAULT_DB_PATH, RESULTS_DIR, build_variant_configs
from .scoring_model import build_score_context, score_day
from .walk_forward_engine import load_machine_data

from ml.experiments.gate_analysis.run_gate_analysis import (
    build_segment_daily_counts,
    is_event_day,
)

GATED_VARIANTS = ("v6a_hit_an", "v9b_blend_05", "v9c_percentile")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gated prediction for v6a/v9b/v9c")
    parser.add_argument("--date", required=True, help="Target date YYYYMMDD")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument(
        "--variants",
        nargs="*",
        default=list(GATED_VARIANTS),
        help="Variant IDs to run (default: v6a_hit_an v9b_blend_05 v9c_percentile)",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Skip gate filtering (run all segments, for comparison)",
    )
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


def _get_active_segments(
    segment_daily_counts: pd.DataFrame,
    target_date: pd.Timestamp,
) -> list[str]:
    date_str = target_date.strftime("%Y%m%d")
    gate_rows = segment_daily_counts[
        segment_daily_counts["date"].astype(str).eq(date_str)
    ]
    active = gate_rows[
        gate_rows["eligible_for_gate"] & gate_rows["gate_positive"]
    ]["segment"].astype(str).tolist()
    return list(dict.fromkeys(active))


def _format_variant_table(
    scored: pd.DataFrame,
    *,
    top_n: int,
    variant_id: str,
    active_segments: list[str] | None,
    is_gated: bool,
) -> str:
    if is_gated and active_segments:
        pool = scored[scored["segment"].isin(active_segments)].copy()
    else:
        pool = scored.copy()

    pool = pool.sort_values(
        ["composite", "diff_coins_normalized", "machine_number"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    pool["rank"] = range(1, len(pool) + 1)
    top = pool.head(top_n)

    gate_label = "GATED" if is_gated else "NOGATE"
    lines = [
        f"## {variant_id} ({gate_label}) — Top {top_n}",
        f"Active segments: {', '.join(active_segments or ['ALL'])} ({len(pool)} machines)",
        "",
        "| 順位 | 台番 | 機種名 | Seg | 角番 | 末尾 | スコア | C1 | C2 | C3 | C4 | C5 | C6 | hist |",
        "|:---:|:---:|:---|:---|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in top.itertuples(index=False):
        lines.append(
            "| {rank} | {mn} | {name} | {seg} | {kb} | {ld} | "
            "{comp:.1f} | {c1:.1f} | {c2:.1f} | {c3:.1f} | {c4:.1f} | {c5:.1f} | {c6:.1f} | {hm:.3f} |".format(
                rank=int(row.rank),
                mn=int(row.machine_number),
                name=str(row.machine_name),
                seg=str(row.segment),
                kb=int(row.kakuban) if hasattr(row, "kakuban") and pd.notna(row.kakuban) else "-",
                ld=str(row.last_digit) if hasattr(row, "last_digit") else "-",
                comp=float(row.composite),
                c1=float(row.c1),
                c2=float(row.c2),
                c3=float(row.c3),
                c4=float(row.c4),
                c5=float(row.c5),
                c6=float(row.c6),
                hm=float(row.hist_metric) if hasattr(row, "hist_metric") and pd.notna(row.hist_metric) else 0.0,
            )
        )
    return "\n".join(lines)


def _build_consensus_table(
    variant_results: dict[str, pd.DataFrame],
    active_segments: list[str] | None,
    is_gated: bool,
    top_n: int,
) -> str:
    """Borda-count consensus across variants: average rank -> final ranking."""
    rank_frames: list[pd.DataFrame] = []
    for vid, scored in variant_results.items():
        if is_gated and active_segments:
            pool = scored[scored["segment"].isin(active_segments)].copy()
        else:
            pool = scored.copy()
        pool = pool.sort_values(
            ["composite", "diff_coins_normalized", "machine_number"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        pool[f"rank_{vid}"] = range(1, len(pool) + 1)
        rank_frames.append(pool[["machine_number", f"rank_{vid}"]].copy())

    if not rank_frames:
        return "## Consensus — no variants"

    merged = rank_frames[0]
    for rf in rank_frames[1:]:
        merged = merged.merge(rf, on="machine_number", how="outer")

    rank_cols = [c for c in merged.columns if c.startswith("rank_")]
    merged["avg_rank"] = merged[rank_cols].mean(axis=1)
    merged["n_in_top50"] = (merged[rank_cols] <= top_n).sum(axis=1)
    merged = merged.sort_values(["avg_rank"]).reset_index(drop=True)
    merged["consensus_rank"] = range(1, len(merged) + 1)

    first_variant_scored = next(iter(variant_results.values()))
    info_cols = ["machine_number", "machine_name", "segment"]
    if "kakuban" in first_variant_scored.columns:
        info_cols.append("kakuban")
    if "last_digit" in first_variant_scored.columns:
        info_cols.append("last_digit")
    info = first_variant_scored[info_cols].drop_duplicates(subset=["machine_number"], keep="first")
    merged = merged.merge(info, on="machine_number", how="left")

    top = merged.head(top_n)
    gate_label = "GATED" if is_gated else "NOGATE"
    lines = [
        f"## CONSENSUS ({gate_label}) — Top {top_n} (Borda average rank)",
        "",
    ]
    rank_header = " | ".join(f"rank_{vid}" for vid in variant_results)
    lines.append(f"| 順位 | 台番 | 機種名 | Seg | {rank_header} | 平均順位 | 出現数 |")
    lines.append("|:---:|:---:|:---|:---|" + "|---:" * len(variant_results) + "|---:|:---:|")

    for row in top.itertuples(index=False):
        rank_vals = " | ".join(
            str(int(getattr(row, f"rank_{vid}"))) if pd.notna(getattr(row, f"rank_{vid}", None)) else "-"
            for vid in variant_results
        )
        lines.append(
            f"| {int(row.consensus_rank)} | {int(row.machine_number)} | "
            f"{row.machine_name} | {row.segment} | "
            f"{rank_vals} | {row.avg_rank:.1f} | {int(row.n_in_top50)}/3 |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    target_date = pd.Timestamp(args.date).normalize()
    db_path = args.db_path
    window_days = args.window_days
    top_n = args.top_n
    is_gated = not args.no_gate

    data = _prepare_source(load_machine_data(db_path))
    train = data[
        (data["date_dt"] < target_date)
        & (data["date_dt"] >= target_date - pd.Timedelta(days=window_days))
    ].copy()
    actual = data[data["date_dt"] == target_date].copy()
    if actual.empty:
        print(f"No data for {target_date.strftime('%Y-%m-%d')}", file=sys.stderr)
        return 1

    active_segments: list[str] | None = None
    if is_gated:
        seg_counts = build_segment_daily_counts(db_path)
        active_segments = _get_active_segments(seg_counts, target_date)
        if not active_segments:
            print(
                f"WARNING: No active segments for {target_date.strftime('%Y-%m-%d')}. "
                "Falling back to all segments.",
                file=sys.stderr,
            )
            is_gated = False

    variant_map = build_variant_configs()
    context = build_score_context()
    is_event = is_event_day(target_date.strftime("%Y%m%d"))

    output_parts: list[str] = [
        f"# Gated Prediction: {target_date.strftime('%Y-%m-%d')} "
        f"(DD{target_date.day}, {target_date.day_name()[:3]}, "
        f"{'EVENT' if is_event else 'non-event'})",
        "",
    ]
    if is_gated:
        output_parts.append(f"**Active segments**: {', '.join(active_segments or [])}")
        output_parts.append("")

    variant_results: dict[str, pd.DataFrame] = {}
    for vid in args.variants:
        if vid not in variant_map:
            print(f"WARNING: unknown variant '{vid}', skipping", file=sys.stderr)
            continue
        variant_cfg = variant_map[vid]
        scored = score_day(train, actual, variant_cfg, test_date=target_date, context=context)
        if scored.empty:
            print(f"WARNING: no scored rows for variant {vid}", file=sys.stderr)
            continue
        variant_results[vid] = scored
        output_parts.append(
            _format_variant_table(
                scored,
                top_n=top_n,
                variant_id=vid,
                active_segments=active_segments,
                is_gated=is_gated,
            )
        )
        output_parts.append("")

    if len(variant_results) >= 2:
        output_parts.append(
            _build_consensus_table(variant_results, active_segments, is_gated, top_n)
        )
        output_parts.append("")

    report = "\n".join(output_parts)
    print(report)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    gate_label = "gated" if is_gated else "nogate"
    report_path = output_dir / f"predict_{gate_label}_{target_date.strftime('%Y%m%d')}.md"
    report_path.write_text(report, encoding="utf-8")

    for vid, scored in variant_results.items():
        if is_gated and active_segments:
            pool = scored[scored["segment"].isin(active_segments)].copy()
        else:
            pool = scored.copy()
        pool = pool.sort_values(
            ["composite", "diff_coins_normalized", "machine_number"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        pool["rank"] = range(1, len(pool) + 1)
        csv_path = output_dir / f"predict_{gate_label}_{vid}_{target_date.strftime('%Y%m%d')}.csv"
        pool.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"\nSaved to {output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
