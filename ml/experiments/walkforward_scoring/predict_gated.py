"""Gated prediction: apply gate (active-segment filter) on top of v6a / v9b / v9c."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .config import DEFAULT_DB_PATH, GATE_QUALITY_TIERS, RESULTS_DIR, build_variant_configs
from .scoring_model import build_score_context, score_day
from .walk_forward_engine import load_machine_data

from ml.experiments.gate_analysis.run_gate_analysis import (
    build_segment_daily_counts,
    is_event_day,
)

GATED_VARIANTS = ("v12b_debut_multiplier_half",)
RERANK_POOL_N = 80

SEGMENT_RANKING_STRATEGY: dict[str, str] = {
    "3F_L_A": "composite",
}
SEGMENT_RANKING_DEFAULT = "hist_metric"
SEGMENT_ORDER = ["2F_L_N", "2F_R_N", "3F_L_A", "3F_L_N", "3F_R_A", "3F_R_N"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gated prediction with seg_percentile reranking")
    parser.add_argument("--date", required=True, help="Target date YYYYMMDD")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Enable seg_percentile reranking (disabled by default; experimental, not validated)",
    )
    parser.add_argument(
        "--pool-n",
        type=int,
        default=RERANK_POOL_N,
        help="Pool size for reranking (default: 80)",
    )
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
    parser.add_argument(
        "--segment-ranking",
        action="store_true",
        help="Rank within each segment independently (hist_metric for N-type, composite for 3F_L_A)",
    )
    parser.add_argument(
        "--top-n-per-seg",
        type=int,
        default=10,
        help="Number of top machines per segment in segment-ranking mode (default: 10)",
    )
    parser.add_argument(
        "--gate-mode",
        choices=["count", "good_only", "good_ok", "exclude_bad"],
        default="good_ok",
        help=(
            "Gate strategy: "
            "'count' = original MIN_ACTIVE>=2, "
            "'good_only' = only good-tier segments (3F_L_A, 3F_R_A, 2F_L_N), "
            "'good_ok' = good + ok-tier (+ 3F_R_N), "
            "'exclude_bad' = all active except bad-tier (2F_R_N, 3F_L_N). "
            "Default: good_ok"
        ),
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


def _apply_gate_mode(
    active_segments: list[str],
    gate_mode: str,
) -> tuple[list[str], bool, str | None]:
    """Filter active segments by quality tier and return (segments, is_gated, fallback_reason)."""
    good = GATE_QUALITY_TIERS["good"]
    ok = GATE_QUALITY_TIERS["ok"]
    bad = GATE_QUALITY_TIERS["bad"]

    if gate_mode == "count":
        if len(active_segments) < 2:
            return (
                active_segments,
                False,
                f"Only {len(active_segments)} active segment(s) "
                f"({', '.join(active_segments)}), minimum is 2",
            )
        return active_segments, True, None

    if gate_mode == "good_only":
        filtered = [s for s in active_segments if s in good]
    elif gate_mode == "good_ok":
        filtered = [s for s in active_segments if s in good | ok]
    elif gate_mode == "exclude_bad":
        filtered = [s for s in active_segments if s not in bad]
    else:
        filtered = active_segments

    if not filtered:
        active_labels = ", ".join(active_segments)
        return (
            active_segments,
            False,
            f"No qualifying segments in gate_mode='{gate_mode}' "
            f"(active: {active_labels})",
        )
    return filtered, True, None


def _build_variant_pool(
    scored: pd.DataFrame,
    *,
    active_segments: list[str] | None,
    is_gated: bool,
) -> pd.DataFrame:
    if is_gated and active_segments:
        pool = scored[scored["segment"].isin(active_segments)].copy()
    else:
        pool = scored.copy()

    return pool.sort_values(
        ["composite", "diff_coins_normalized", "machine_number"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def _rerank_segment_percentile(
    scored: pd.DataFrame,
    pool: pd.DataFrame,
    top_n: int,
) -> pd.DataFrame:
    """Rerank a pool by segment-internal percentile times segment strength weight."""
    seg_composite_mean = scored.groupby("segment", dropna=False)["composite"].mean()
    seg_min = seg_composite_mean.min()
    seg_max = seg_composite_mean.max()
    if pd.isna(seg_min) or pd.isna(seg_max) or seg_max <= seg_min:
        seg_weight_map = {segment: 1.0 for segment in seg_composite_mean.index}
    else:
        normalized = 0.5 + 0.5 * (seg_composite_mean - seg_min) / (seg_max - seg_min)
        seg_weight_map = normalized.to_dict()

    scored_copy = scored.copy()
    scored_copy["seg_percentile"] = scored_copy.groupby("segment", dropna=False)["composite"].rank(pct=True)
    scored_copy["strength_weight"] = scored_copy["segment"].map(seg_weight_map).fillna(0.75)
    scored_copy["rerank_score"] = scored_copy["seg_percentile"] * scored_copy["strength_weight"]

    pool_rerank = pool.merge(
        scored_copy[["machine_number", "rerank_score"]].drop_duplicates("machine_number"),
        on="machine_number",
        how="left",
        suffixes=("", "_rr"),
    )
    col = "rerank_score_rr" if "rerank_score_rr" in pool_rerank.columns else "rerank_score"
    return pool_rerank.sort_values(col, ascending=False).head(top_n)


def _format_variant_table(
    rows: pd.DataFrame,
    *,
    variant_id: str,
    active_segments: list[str] | None,
    is_gated: bool,
) -> str:
    gate_label = "GATED" if is_gated else "NOGATE"
    lines = [
        f"## {variant_id} ({gate_label}) 窶・Top {len(rows)}",
        f"Active segments: {', '.join(active_segments or ['ALL'])} ({len(rows)} machines)",
        "",
        "| 鬆・ｽ・| 蜿ｰ逡ｪ | 讖溽ｨｮ蜷・| Seg | 隗堤分 | 譛ｫ蟆ｾ | 繧ｹ繧ｳ繧｢ | C1 | C2 | C3 | C4 | C5 | C6 | hist |",
        "|:---:|:---:|:---|:---|:---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows.itertuples(index=False):
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
    variant_rows: dict[str, pd.DataFrame],
    top_n: int,
) -> str:
    """Borda-count consensus across variants: average rank -> final ranking."""
    rank_frames: list[pd.DataFrame] = []
    for vid, rows in variant_rows.items():
        rank_col = f"rank_{vid}"
        rank_frames.append(rows[["machine_number", "rank"]].rename(columns={"rank": rank_col}).copy())

    if not rank_frames:
        return "## Consensus 窶・no variants"

    merged = rank_frames[0]
    for rf in rank_frames[1:]:
        merged = merged.merge(rf, on="machine_number", how="outer")

    rank_cols = [c for c in merged.columns if c.startswith("rank_")]
    merged["avg_rank"] = merged[rank_cols].mean(axis=1)
    merged["n_in_top"] = merged[rank_cols].notna().sum(axis=1)
    merged = merged.sort_values(["avg_rank"]).reset_index(drop=True)
    merged["consensus_rank"] = range(1, len(merged) + 1)

    first_variant_rows = next(iter(variant_rows.values()))
    info_cols = ["machine_number", "machine_name", "segment"]
    if "kakuban" in first_variant_rows.columns:
        info_cols.append("kakuban")
    if "last_digit" in first_variant_rows.columns:
        info_cols.append("last_digit")
    info = first_variant_rows[info_cols].drop_duplicates(subset=["machine_number"], keep="first")
    merged = merged.merge(info, on="machine_number", how="left")

    top = merged.head(top_n)
    lines = [
        f"## CONSENSUS 窶・Top {top_n} (Borda average rank)",
        "",
    ]
    rank_header = " | ".join(f"rank_{vid}" for vid in variant_rows)
    lines.append(f"| 鬆・ｽ・| 蜿ｰ逡ｪ | 讖溽ｨｮ蜷・| Seg | {rank_header} | 蟷ｳ蝮・・ｽ・| 蜃ｺ迴ｾ謨ｰ |")
    lines.append("|:---:|:---:|:---|:---|" + "|---:" * len(variant_rows) + "|---:|:---:|")

    for row in top.itertuples(index=False):
        rank_vals = " | ".join(
            str(int(getattr(row, f"rank_{vid}"))) if pd.notna(getattr(row, f"rank_{vid}", None)) else "-"
            for vid in variant_rows
        )
        lines.append(
            f"| {int(row.consensus_rank)} | {int(row.machine_number)} | "
            f"{row.machine_name} | {row.segment} | "
            f"{rank_vals} | {row.avg_rank:.1f} | {int(row.n_in_top)}/{len(variant_rows)} |"
        )
    return "\n".join(lines)


def _build_segment_ranking(
    scored: pd.DataFrame,
    top_n_per_seg: int,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for seg in SEGMENT_ORDER:
        seg_df = scored[scored["segment"] == seg].copy()
        if seg_df.empty:
            continue
        sort_col = SEGMENT_RANKING_STRATEGY.get(seg, SEGMENT_RANKING_DEFAULT)
        if sort_col not in seg_df.columns:
            sort_col = "composite"
        seg_df = seg_df.sort_values(
            [sort_col, "diff_coins_normalized", "machine_number"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        top = seg_df.head(top_n_per_seg).copy()
        top["rank"] = range(1, len(top) + 1)
        top["sort_col"] = sort_col
        result[seg] = top
    return result


def _format_segment_tables(
    segment_rows: dict[str, pd.DataFrame],
    *,
    target_date: pd.Timestamp,
    is_event: bool,
) -> str:
    parts: list[str] = [
        f"# Segment Ranking: {target_date.strftime('%Y-%m-%d')} "
        f"(DD{target_date.day}, {target_date.day_name()[:3]}, "
        f"{'EVENT' if is_event else 'non-event'})",
        "",
    ]
    for seg, rows in segment_rows.items():
        sort_col = rows["sort_col"].iloc[0] if not rows.empty else "?"
        strategy_label = "composite" if sort_col == "composite" else "hist_metric"
        parts.append(f"## {seg} (sort={strategy_label}, top {len(rows)})")
        parts.append("")
        parts.append(
            "| 順位 | 台番 | 機種名 | 角番 | 末尾 | スコア | hist |"
        )
        parts.append("|:---:|:---:|:---|:---:|:---:|---:|---:|")
        for row in rows.itertuples(index=False):
            kb = int(row.kakuban) if hasattr(row, "kakuban") and pd.notna(row.kakuban) else "-"
            ld = str(row.last_digit) if hasattr(row, "last_digit") else "-"
            score_val = float(row.composite) if sort_col == "composite" else float(row.hist_metric) if hasattr(row, "hist_metric") and pd.notna(row.hist_metric) else 0.0
            hist_val = float(row.hist_metric) if hasattr(row, "hist_metric") and pd.notna(row.hist_metric) else 0.0
            parts.append(
                f"| {int(row.rank)} | {int(row.machine_number)} | "
                f"{row.machine_name} | {kb} | {ld} | "
                f"{score_val:.1f} | {hist_val:.3f} |"
            )
        parts.append("")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    target_date = pd.Timestamp(args.date).normalize()
    db_path = args.db_path
    window_days = args.window_days
    top_n = args.top_n
    is_gated = not args.no_gate
    rerank_enabled = args.rerank
    pool_n = max(args.pool_n, top_n)

    data = _prepare_source(load_machine_data(db_path))
    train = data[
        (data["date_dt"] < target_date)
        & (data["date_dt"] >= target_date - pd.Timedelta(days=window_days))
    ].copy()
    actual = data[data["date_dt"] == target_date].copy()
    if actual.empty:
        print(f"No data for {target_date.strftime('%Y-%m-%d')}", file=sys.stderr)
        return 1

    gate_mode = args.gate_mode
    MIN_ACTIVE_SEGMENTS = 2

    active_segments: list[str] | None = None
    gate_fallback_reason: str | None = None
    if is_gated:
        seg_counts = build_segment_daily_counts(db_path)
        active_segments = _get_active_segments(seg_counts, target_date)
        if not active_segments:
            gate_fallback_reason = "No active segments"
            is_gated = False
        else:
            active_segments, is_gated, gate_fallback_reason = _apply_gate_mode(
                active_segments, gate_mode,
            )

    if gate_fallback_reason:
        print(
            f"WARNING: {gate_fallback_reason} for {target_date.strftime('%Y-%m-%d')}. "
            "Falling back to NOGATE (all segments).",
            file=sys.stderr,
        )

    variant_map = build_variant_configs()
    context = build_score_context()
    is_event = is_event_day(target_date.strftime("%Y%m%d"))

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

    if not variant_results:
        print("ERROR: no variants produced results", file=sys.stderr)
        return 1

    variant_rows: dict[str, pd.DataFrame] = {}
    for vid, scored in variant_results.items():
        pool = _build_variant_pool(scored, active_segments=active_segments, is_gated=is_gated)
        if rerank_enabled:
            rows = _rerank_segment_percentile(scored, pool.head(pool_n).copy(), top_n)
        else:
            rows = pool.head(top_n).copy()
        rows = rows.reset_index(drop=True)
        rows["rank"] = range(1, len(rows) + 1)
        variant_rows[vid] = rows

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = target_date.strftime("%Y%m%d")

    def _build_output(
        *,
        use_gate: bool,
        segments: list[str] | None,
        label: str,
        fallback_reason: str | None = None,
    ) -> str:
        parts: list[str] = [
            f"# {label} Prediction: {target_date.strftime('%Y-%m-%d')} "
            f"(DD{target_date.day}, {target_date.day_name()[:3]}, "
            f"{'EVENT' if is_event else 'non-event'})",
            "",
        ]
        if rerank_enabled:
            parts.append(f"**Reranking**: seg_percentile (pool={pool_n})")
        else:
            parts.append("**Reranking**: disabled")
        parts.append("")
        if use_gate and segments:
            parts.append(f"**Active segments**: {', '.join(segments)}")
            parts.append("")
        if fallback_reason:
            parts.append(f"**Fallback**: {fallback_reason}")
            parts.append("")

        for vid, rows in variant_rows.items():
            parts.append(
                _format_variant_table(
                    rows,
                    variant_id=vid,
                    active_segments=segments if use_gate else None,
                    is_gated=use_gate,
                )
            )
            parts.append("")

        if len(variant_rows) >= 2:
            parts.append(_build_consensus_table(variant_rows, top_n))
            parts.append("")
        return "\n".join(parts)

    def _save_csvs(*, use_gate: bool, segments: list[str] | None, label: str) -> None:
        for vid, rows in variant_rows.items():
            csv_path = output_dir / f"predict_{label}_{vid}_{date_str}.csv"
            rows.to_csv(csv_path, index=False, encoding="utf-8-sig")

    if is_gated:
        gated_report = _build_output(use_gate=True, segments=active_segments, label="GATED")
        print(gated_report)
        (output_dir / f"predict_gated_{date_str}.md").write_text(gated_report, encoding="utf-8")
        _save_csvs(use_gate=True, segments=active_segments, label="gated")

    nogate_report = _build_output(
        use_gate=False,
        segments=None,
        label="NOGATE" if is_gated else "NOGATE (fallback)",
        fallback_reason=gate_fallback_reason,
    )
    if not is_gated:
        print(nogate_report)
    (output_dir / f"predict_nogate_{date_str}.md").write_text(nogate_report, encoding="utf-8")
    _save_csvs(use_gate=False, segments=None, label="nogate")

    if args.segment_ranking:
        first_scored = next(iter(variant_results.values()))
        seg_rows = _build_segment_ranking(first_scored, args.top_n_per_seg)
        seg_report = _format_segment_tables(
            seg_rows, target_date=target_date, is_event=is_event,
        )
        print(seg_report)
        (output_dir / f"predict_segment_{date_str}.md").write_text(
            seg_report, encoding="utf-8",
        )
        for seg, rows in seg_rows.items():
            csv_path = output_dir / f"predict_segment_{seg}_{date_str}.csv"
            rows.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\nSegment ranking saved to {output_dir}", file=sys.stderr)

    if is_gated:
        print(f"\nGATED + NOGATE both saved to {output_dir}", file=sys.stderr)
    else:
        print(f"\nNOGATE (fallback) saved to {output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
