from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

from eda import mitoya_phase10_segment_validation as phase10
from eda.mitoya_prompt_common import (
    EVENT_CATEGORY_ORDER,
    X_DDS,
    add_event_category,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_104pct_analysis"
DD_ORDER = list(range(1, 32))
NON_XDDS_DD_ORDER = [1, 2, 3, 5, 6, 8, 9, 10, 12, 13, 15, 16, 18, 19, 20, 21, 23, 25, 26, 28, 29, 31]
EVENT_SCOPE_ORDER = ["X_DDS", "非イベント日"]
SEGMENT_ORDER = list(phase10.SEGMENT_ORDER)
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]

STEP1_COLUMNS = ["grain", "segment", "event_scope", "dd", "n", "rate_104", "avg_payout", "avg_diff"]
STEP2_COLUMNS = ["category", "dd", "n", "rate_104", "avg_payout", "avg_diff", "is_xdds"]
STEP3_SUMMARY_COLUMNS = ["grain", "segment", "event_scope", "spearman_rho", "p_value", "n_dd"]
STEP3_GAP_COLUMNS = [
    "grain",
    "segment",
    "event_scope",
    "dd",
    "diff_rank",
    "rate104_rank",
    "gap",
    "avg_diff",
    "rate_104",
]
STEP4_COLUMNS = ["segment", "corner_bucket", "n", "rate_104", "avg_payout", "avg_diff", "diff_rank", "rate104_rank"]
STEP5_COLUMNS = ["grain", "segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
STEP6_COLUMNS = ["finding", "value", "note"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = add_event_category(df)
    work = phase10._prepare_frame(work)  # noqa: SLF001

    diff = pd.to_numeric(work.get("diff"), errors="coerce")
    games = pd.to_numeric(work.get("games"), errors="coerce")
    if "payout_rate" in work.columns:
        work["payout_rate"] = pd.to_numeric(work["payout_rate"], errors="coerce")
    else:
        denom = games * 3.0
        work["payout_rate"] = np.where(denom.gt(0), 100.0 + (diff / denom) * 100.0, np.nan)

    work["dd"] = pd.to_numeric(work.get("dd"), errors="coerce").astype("Int64")
    work["event_category"] = work["event_category"].astype("string")
    work["corner_bucket"] = work["corner_bucket"].astype("string") if "corner_bucket" in work.columns else "unknown"
    work["segment"] = work["section"].astype("string") if "section" in work.columns else ""
    return work


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    return phase10._segment_frame(work, segment)  # noqa: SLF001


def _event_scope_frame(frame: pd.DataFrame, event_scope: str) -> pd.DataFrame:
    if event_scope == "X_DDS":
        return frame.loc[frame["event_category"].astype(str).eq("X_DDS")].copy()
    if event_scope == "非イベント日":
        return frame.loc[frame["event_category"].astype(str).eq("非イベント日")].copy()
    raise KeyError(event_scope)


def _row_stats(frame: pd.DataFrame) -> dict[str, object]:
    diff = pd.to_numeric(frame.get("diff"), errors="coerce").dropna()
    payout = pd.to_numeric(frame.get("payout_rate"), errors="coerce").dropna()
    if diff.empty or payout.empty:
        return {
            "n": int(len(frame)),
            "rate_104": float("nan"),
            "avg_payout": float("nan"),
            "avg_diff": float("nan"),
        }
    return {
        "n": int(len(payout)),
        "rate_104": float((payout >= 104).mean() * 100),
        "avg_payout": float(payout.mean()),
        "avg_diff": float(diff.mean()) if not diff.empty else float("nan"),
    }


def _dd_spectrum_rows(frame: pd.DataFrame, *, grain: str, segment: str, event_scope: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dd in DD_ORDER:
        dd_frame = frame.loc[frame["dd"].eq(dd)].copy()
        stats = _row_stats(dd_frame)
        rows.append(
            {
                "grain": grain,
                "segment": segment,
                "event_scope": event_scope,
                "dd": dd,
                "n": stats["n"],
                "rate_104": stats["rate_104"],
                "avg_payout": stats["avg_payout"],
                "avg_diff": stats["avg_diff"],
            }
        )
    return pd.DataFrame(rows, columns=STEP1_COLUMNS)


def build_step1_dd_104rate(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []

    rows.append(_dd_spectrum_rows(work, grain="hall", segment="", event_scope=""))
    for segment in SEGMENT_ORDER:
        segment_frame = _segment_frame(work, segment)
        rows.append(_dd_spectrum_rows(segment_frame, grain="segment", segment=segment, event_scope=""))
    for segment in SEGMENT_ORDER:
        segment_frame = _segment_frame(work, segment)
        for event_scope in EVENT_SCOPE_ORDER:
            scoped = _event_scope_frame(segment_frame, event_scope)
            rows.append(_dd_spectrum_rows(scoped, grain="composite", segment=segment, event_scope=event_scope))

    table = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=STEP1_COLUMNS)
    table["grain"] = pd.Categorical(table["grain"], categories=["hall", "segment", "composite"], ordered=True)
    table["segment"] = pd.Categorical(table["segment"], categories=[""] + SEGMENT_ORDER, ordered=True)
    table["event_scope"] = pd.Categorical(table["event_scope"], categories=[""] + EVENT_SCOPE_ORDER, ordered=True)
    table = table.sort_values(["grain", "segment", "event_scope", "dd"], kind="mergesort").reset_index(drop=True)
    table["grain"] = table["grain"].astype(str)
    table["segment"] = table["segment"].astype(str)
    table["event_scope"] = table["event_scope"].astype(str)
    return table


def build_step2_peak_trough(step1: pd.DataFrame) -> pd.DataFrame:
    hall = step1.loc[step1["grain"].astype(str).eq("hall") & step1["n"].gt(0)].copy()
    if hall.empty:
        return pd.DataFrame(columns=STEP2_COLUMNS)

    hall["is_xdds"] = hall["dd"].isin(X_DDS)
    ordered = hall.sort_values(["rate_104", "avg_payout", "dd"], ascending=[False, False, True], kind="mergesort")
    peaks = ordered.head(5).copy()
    peaks["category"] = "peak"
    troughs = (
        hall.sort_values(["rate_104", "avg_payout", "dd"], ascending=[True, True, True], kind="mergesort")
        .head(5)
        .copy()
    )
    troughs["category"] = "trough"

    table = pd.concat([peaks, troughs], ignore_index=True)
    table = table.loc[:, ["category", "dd", "n", "rate_104", "avg_payout", "avg_diff", "is_xdds"]]
    table["category"] = pd.Categorical(table["category"], categories=["peak", "trough"], ordered=True)
    table = table.sort_values(
        ["category", "rate_104", "dd"], ascending=[True, False, True], kind="mergesort"
    ).reset_index(drop=True)
    table["category"] = table["category"].astype(str)
    return table


def _rank_comparison_frame(frame: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame]:
    work = frame.loc[frame["n"].gt(0)].copy()
    if len(work) < 2:
        summary = {"spearman_rho": float("nan"), "p_value": float("nan"), "n_dd": int(len(work))}
        return summary, pd.DataFrame(columns=STEP3_GAP_COLUMNS)

    work["diff_rank"] = pd.to_numeric(work["avg_diff"], errors="coerce").rank(ascending=False, method="average")
    work["rate104_rank"] = pd.to_numeric(work["rate_104"], errors="coerce").rank(ascending=False, method="average")
    rho, p_value = spearmanr(work["avg_diff"], work["rate_104"], nan_policy="omit")
    work["gap"] = (work["diff_rank"] - work["rate104_rank"]).abs()
    gap = work.sort_values(["gap", "dd"], ascending=[False, True], kind="mergesort").head(10)
    summary = {
        "spearman_rho": float(rho) if pd.notna(rho) else float("nan"),
        "p_value": float(p_value) if pd.notna(p_value) else float("nan"),
        "n_dd": int(len(work)),
    }
    gap = gap.loc[:, ["dd", "diff_rank", "rate104_rank", "gap", "avg_diff", "rate_104"]].copy()
    return summary, gap


def build_step3_diff_vs_104(step1: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _step1_groups(step1):
        summary, _ = _rank_comparison_frame(frame)
        rows.append(
            {
                "grain": grain,
                "segment": segment,
                "event_scope": event_scope,
                "spearman_rho": summary["spearman_rho"],
                "p_value": summary["p_value"],
                "n_dd": summary["n_dd"],
            }
        )
    table = pd.DataFrame(rows, columns=STEP3_SUMMARY_COLUMNS)
    table["grain"] = pd.Categorical(table["grain"], categories=["hall", "segment", "composite"], ordered=True)
    table["segment"] = pd.Categorical(table["segment"], categories=[""] + SEGMENT_ORDER, ordered=True)
    table["event_scope"] = pd.Categorical(table["event_scope"], categories=[""] + EVENT_SCOPE_ORDER, ordered=True)
    table = table.sort_values(["grain", "segment", "event_scope"], kind="mergesort").reset_index(drop=True)
    table["grain"] = table["grain"].astype(str)
    table["segment"] = table["segment"].astype(str)
    table["event_scope"] = table["event_scope"].astype(str)
    return table


def build_step3_divergent_dd(step1: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for grain, segment, event_scope, frame in _step1_groups(step1):
        _, gap = _rank_comparison_frame(frame)
        if gap.empty:
            continue
        for _, row in gap.iterrows():
            rows.append(
                {
                    "grain": grain,
                    "segment": segment,
                    "event_scope": event_scope,
                    "dd": int(row["dd"]),
                    "diff_rank": float(row["diff_rank"]),
                    "rate104_rank": float(row["rate104_rank"]),
                    "gap": float(row["gap"]),
                    "avg_diff": float(row["avg_diff"]),
                    "rate_104": float(row["rate_104"]),
                }
            )
    table = pd.DataFrame(rows, columns=STEP3_GAP_COLUMNS)
    if table.empty:
        return table
    table["grain"] = pd.Categorical(table["grain"], categories=["hall", "segment", "composite"], ordered=True)
    table["segment"] = pd.Categorical(table["segment"], categories=[""] + SEGMENT_ORDER, ordered=True)
    table["event_scope"] = pd.Categorical(table["event_scope"], categories=[""] + EVENT_SCOPE_ORDER, ordered=True)
    table = table.sort_values(
        ["grain", "segment", "event_scope", "gap", "dd"], ascending=[True, True, True, False, True], kind="mergesort"
    ).reset_index(drop=True)
    table["grain"] = table["grain"].astype(str)
    table["segment"] = table["segment"].astype(str)
    table["event_scope"] = table["event_scope"].astype(str)
    return table


def _step1_groups(step1: pd.DataFrame) -> list[tuple[str, str, str, pd.DataFrame]]:
    groups: list[tuple[str, str, str, pd.DataFrame]] = []
    for grain in ["hall", "segment", "composite"]:
        grain_frame = step1.loc[step1["grain"].astype(str).eq(grain)].copy()
        if grain == "hall":
            groups.append((grain, "", "", grain_frame))
            continue
        for segment in SEGMENT_ORDER:
            segment_frame = grain_frame.loc[grain_frame["segment"].astype(str).eq(segment)].copy()
            if grain == "segment":
                groups.append((grain, segment, "", segment_frame))
            else:
                for event_scope in EVENT_SCOPE_ORDER:
                    scope_frame = segment_frame.loc[segment_frame["event_scope"].astype(str).eq(event_scope)].copy()
                    groups.append((grain, segment, event_scope, scope_frame))
    return groups


def build_step4_corner_104rate(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        if frame.empty:
            rows.append(
                pd.DataFrame(
                    [
                        {
                            "segment": segment,
                            "corner_bucket": corner_bucket,
                            "n": 0,
                            "rate_104": float("nan"),
                            "avg_payout": float("nan"),
                            "avg_diff": float("nan"),
                            "diff_rank": float("nan"),
                            "rate104_rank": float("nan"),
                        }
                        for corner_bucket in CORNER_BUCKET_ORDER
                    ]
                )
            )
            continue

        bucket_rows: list[dict[str, object]] = []
        for corner_bucket in CORNER_BUCKET_ORDER:
            bucket = frame.loc[frame["corner_bucket"].astype(str).eq(corner_bucket)].copy()
            stats = _row_stats(bucket)
            bucket_rows.append(
                {
                    "segment": segment,
                    "corner_bucket": corner_bucket,
                    "n": stats["n"],
                    "rate_104": stats["rate_104"],
                    "avg_payout": stats["avg_payout"],
                    "avg_diff": stats["avg_diff"],
                }
            )

        bucket_df = pd.DataFrame(bucket_rows)
        observed = bucket_df.loc[bucket_df["n"].gt(0)].copy()
        if len(observed) >= 2:
            bucket_df["diff_rank"] = bucket_df["avg_diff"].rank(ascending=False, method="average")
            bucket_df["rate104_rank"] = bucket_df["rate_104"].rank(ascending=False, method="average")
        else:
            bucket_df["diff_rank"] = np.nan
            bucket_df["rate104_rank"] = np.nan
        rows.append(bucket_df)

    table = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=STEP4_COLUMNS)
    table = table.loc[:, STEP4_COLUMNS]
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(["segment", "corner_bucket"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    return table


def build_step5_nonxdds_104(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grains = [("hall", ""), *[("segment", segment) for segment in SEGMENT_ORDER]]
    for grain, segment in grains:
        frame = work.copy() if grain == "hall" else _segment_frame(work, segment)
        frame = frame.loc[frame["dd"].isin(NON_XDDS_DD_ORDER)].copy()
        if frame.empty:
            rows.append(
                {
                    "grain": grain,
                    "segment": segment,
                    "kw_stat": float("nan"),
                    "p_value": float("nan"),
                    "epsilon_sq": float("nan"),
                    "n_groups": 0,
                    "n": 0,
                }
            )
            continue
        frame["dd"] = frame["dd"].astype("Int64").astype(str)
        summary = _kruskal_summary(frame, "dd", value_col="payout_rate", order=[str(dd) for dd in NON_XDDS_DD_ORDER])
        rows.append(
            {
                "grain": grain,
                "segment": segment,
                "kw_stat": summary["kw_stat"],
                "p_value": summary["p_value"],
                "epsilon_sq": summary["epsilon_sq"],
                "n_groups": summary["n_groups"],
                "n": summary["n"],
            }
        )
    table = pd.DataFrame(rows, columns=STEP5_COLUMNS)
    table["grain"] = pd.Categorical(table["grain"], categories=["hall", "segment"], ordered=True)
    table["segment"] = pd.Categorical(table["segment"], categories=[""] + SEGMENT_ORDER, ordered=True)
    table = table.sort_values(["grain", "segment"], kind="mergesort").reset_index(drop=True)
    table["grain"] = table["grain"].astype(str)
    table["segment"] = table["segment"].astype(str)
    return table


def _kruskal_summary(
    frame: pd.DataFrame, group_col: str, *, value_col: str, order: list[str] | list[int]
) -> dict[str, object]:
    if frame.empty or group_col not in frame.columns or value_col not in frame.columns:
        return {"kw_stat": float("nan"), "p_value": float("nan"), "epsilon_sq": float("nan"), "n_groups": 0, "n": 0}

    work = frame.dropna(subset=[group_col, value_col]).copy()
    work[group_col] = work[group_col].astype(str)
    order_labels = [str(level) for level in order]
    groups: list[np.ndarray] = []
    total_n = 0
    for level in order_labels:
        grp = work.loc[work[group_col].eq(level)]
        values = pd.to_numeric(grp[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values):
            groups.append(values)
            total_n += len(values)
    if len(groups) < 2:
        return {
            "kw_stat": float("nan"),
            "p_value": float("nan"),
            "epsilon_sq": float("nan"),
            "n_groups": len(groups),
            "n": total_n,
        }
    try:
        kw_stat, p_value = kruskal(*groups)
    except ValueError:
        kw_stat, p_value = float("nan"), float("nan")
    return {
        "kw_stat": float(kw_stat) if pd.notna(kw_stat) else float("nan"),
        "p_value": float(p_value) if pd.notna(p_value) else float("nan"),
        "epsilon_sq": kw_epsilon_squared(float(kw_stat), len(groups), total_n),
        "n_groups": len(groups),
        "n": total_n,
    }


def build_step6_summary(
    step2: pd.DataFrame, step3: pd.DataFrame, step4: pd.DataFrame, step5: pd.DataFrame, work: pd.DataFrame
) -> pd.DataFrame:
    hall_peak = step2.loc[step2["category"].astype(str).eq("peak")].sort_values("rate_104", ascending=False).head(1)
    hall_trough = step2.loc[step2["category"].astype(str).eq("trough")].sort_values("rate_104", ascending=True).head(1)
    hall_step3 = step3.loc[
        step3["grain"].astype(str).eq("hall")
        & step3["segment"].astype(str).eq("")
        & step3["event_scope"].astype(str).eq("")
    ]
    hall_step5 = step5.loc[step5["grain"].astype(str).eq("hall") & step5["segment"].astype(str).eq("")]
    h_jug_corner1 = step4.loc[
        step4["segment"].astype(str).eq("h_jug") & step4["corner_bucket"].astype(str).eq("corner1")
    ]
    h_nonjug = _segment_frame(work, "h_nonjug")
    h_nonjug_event = _event_scope_frame(h_nonjug, "X_DDS")
    h_nonjug_corner1_event = h_nonjug_event.loc[h_nonjug_event["corner_bucket"].astype(str).eq("corner1")].copy()
    h_nonjug_corner1_event_stats = _row_stats(h_nonjug_corner1_event)

    rows = [
        {
            "finding": "hall_peak_trough_gap_pp",
            "value": float(hall_peak["rate_104"].iloc[0] - hall_trough["rate_104"].iloc[0])
            if not hall_peak.empty and not hall_trough.empty
            else float("nan"),
            "note": "hall peak minus trough in rate_104",
        },
        {
            "finding": "hall_diff_vs_104_rho",
            "value": float(hall_step3["spearman_rho"].iloc[0]) if not hall_step3.empty else float("nan"),
            "note": "hall grain Spearman rho between avg_diff and rate_104",
        },
        {
            "finding": "nonxdds_dd_kw_p_hall",
            "value": float(hall_step5["p_value"].iloc[0]) if not hall_step5.empty else float("nan"),
            "note": "hall KW p-value for non-X_DDS DD on payout_rate",
        },
        {
            "finding": "h_jug_corner1_104rate",
            "value": float(h_jug_corner1["rate_104"].iloc[0]) if not h_jug_corner1.empty else float("nan"),
            "note": "segment=h_jug corner1 rate_104",
        },
        {
            "finding": "h_nonjug_corner1_event_104rate",
            "value": float(h_nonjug_corner1_event_stats["rate_104"]),
            "note": "segment=h_nonjug, event_scope=X_DDS, corner1 rate_104",
        },
    ]
    return pd.DataFrame(rows, columns=STEP6_COLUMNS)


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    lines = [
        "# みとや 104%率分析",
        "",
        f"- source_latest_date: {source_latest_date}",
        "- grain_rules: hall/segment use all rows, composite uses X_DDS or 非イベント日 only",
        "- step5_scope: non-X_DDS DD only, including 11/22 and month-end, excluding X_DDS DD",
        "",
        "## Step 1",
        "",
        render_markdown_table(artifacts["step1_dd_104rate"].head(60))
        if not artifacts["step1_dd_104rate"].empty
        else "_no rows_",
        "",
        "## Step 2",
        "",
        render_markdown_table(artifacts["step2_peak_trough"])
        if not artifacts["step2_peak_trough"].empty
        else "_no rows_",
        "",
        "## Step 3",
        "",
        render_markdown_table(artifacts["step3_diff_vs_104"])
        if not artifacts["step3_diff_vs_104"].empty
        else "_no rows_",
        "",
        "## Step 3b",
        "",
        render_markdown_table(artifacts["step3_divergent_dd"])
        if not artifacts["step3_divergent_dd"].empty
        else "_no rows_",
        "",
        "## Step 4",
        "",
        render_markdown_table(artifacts["step4_corner_104rate"])
        if not artifacts["step4_corner_104rate"].empty
        else "_no rows_",
        "",
        "## Step 5",
        "",
        render_markdown_table(artifacts["step5_nonxdds_kw"])
        if not artifacts["step5_nonxdds_kw"].empty
        else "_no rows_",
        "",
        "## Step 6",
        "",
        render_markdown_table(artifacts["step6_summary"]) if not artifacts["step6_summary"].empty else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    date_series = (
        pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        if "date" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = date_series.max() if not date_series.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"

    step1 = build_step1_dd_104rate(work)
    step2 = build_step2_peak_trough(step1)
    step3 = build_step3_diff_vs_104(step1)
    step3_gap = build_step3_divergent_dd(step1)
    step4 = build_step4_corner_104rate(work)
    step5 = build_step5_nonxdds_104(work)
    step6 = build_step6_summary(step2, step3, step4, step5, work)

    artifacts: dict[str, pd.DataFrame | str] = {
        "step1_dd_104rate": step1,
        "step2_peak_trough": step2,
        "step3_diff_vs_104": step3,
        "step3_divergent_dd": step3_gap,
        "step4_corner_104rate": step4,
        "step5_nonxdds_kw": step5,
        "step6_summary": step6,
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=source_latest_date)
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["step1_dd_104rate"].to_csv(output_dir / "step1_dd_104rate.csv", index=False, encoding="utf-8-sig")
    artifacts["step2_peak_trough"].to_csv(output_dir / "step2_peak_trough.csv", index=False, encoding="utf-8-sig")
    artifacts["step3_diff_vs_104"].to_csv(output_dir / "step3_diff_vs_104.csv", index=False, encoding="utf-8-sig")
    artifacts["step3_divergent_dd"].to_csv(output_dir / "step3_divergent_dd.csv", index=False, encoding="utf-8-sig")
    artifacts["step4_corner_104rate"].to_csv(output_dir / "step4_corner_104rate.csv", index=False, encoding="utf-8-sig")
    artifacts["step5_nonxdds_kw"].to_csv(output_dir / "step5_nonxdds_kw.csv", index=False, encoding="utf-8-sig")
    artifacts["step6_summary"].to_csv(output_dir / "step6_summary.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    args = parse_args(argv)
    df = load_mitoya_frame(join_layout=True)
    artifacts = build_all_artifacts(df)
    save_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
