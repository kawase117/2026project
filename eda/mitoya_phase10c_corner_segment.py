from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda import mitoya_phase10_segment_validation as phase10  # noqa: E402
from eda.mitoya_prompt_common import (  # noqa: E402
    add_event_category,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10c_corner_segment"
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
FINE_RANK_ORDER = [str(i) for i in range(1, 23)]
EVENT_CATEGORY_ORDER = ["X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = phase10._prepare_frame(df)  # noqa: SLF001
    work = work.copy()
    work = add_event_category(work)

    work["rank_from_aisle"] = pd.to_numeric(work.get("rank_from_aisle"), errors="coerce")
    work["rank_from_aisle_str"] = work["rank_from_aisle"].dropna().astype(int).astype(str).reindex(work.index)

    work["corner_bucket"] = work["corner_bucket"].fillna("unknown").astype(str)
    return work


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    frame = phase10._segment_frame(work, segment)  # noqa: SLF001
    if segment != "mixed_805" and "section" in frame.columns:
        frame = frame.loc[frame["section"].astype(str).ne("805-815")].copy()
    return frame


def _non_event_frame(work: pd.DataFrame) -> pd.DataFrame:
    return work.loc[work["event_category"].astype(str).eq("非イベント日")].copy()


def _group_stats(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> pd.DataFrame:
    return phase10._group_stats(frame, group_col, order=order)  # noqa: SLF001


def _kruskal_summary(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> dict[str, object]:
    return phase10._kruskal_summary(frame, group_col, order=order)  # noqa: SLF001


def build_corner_kw_allday(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        kw = _kruskal_summary(frame, "corner_bucket", order=CORNER_BUCKET_ORDER)
        rows.append(
            {
                "segment": segment,
                "scope": "all_day",
                "kw_stat": kw["kw_stat"],
                "p_value": kw["p_value"],
                "epsilon_sq": kw["epsilon_sq"],
                "n_groups": kw["n_groups"],
                "n": kw["total_n"],
            }
        )
    return pd.DataFrame(rows)


def build_corner_kw_nonevent(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _non_event_frame(_segment_frame(work, segment))
        kw = _kruskal_summary(frame, "corner_bucket", order=CORNER_BUCKET_ORDER)
        rows.append(
            {
                "segment": segment,
                "scope": "nonevent",
                "kw_stat": kw["kw_stat"],
                "p_value": kw["p_value"],
                "epsilon_sq": kw["epsilon_sq"],
                "n_groups": kw["n_groups"],
                "n": kw["total_n"],
            }
        )
    return pd.DataFrame(rows)


def build_corner_ranking(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for segment in SEGMENT_ORDER:
        for scope, frame_fn in [("all_day", lambda w: w), ("nonevent", _non_event_frame)]:
            frame = frame_fn(_segment_frame(work, segment))
            stats = _group_stats(frame, "corner_bucket", order=CORNER_BUCKET_ORDER)
            if not stats.empty:
                stats["segment"] = segment
                stats["scope"] = scope
                rows.append(stats)
    if not rows:
        return pd.DataFrame(columns=["segment", "scope", "corner_bucket", "n", "avg_diff", "plus_rate"])
    table = pd.concat(rows, ignore_index=True)
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values(["segment", "scope", "corner_bucket"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table[["segment", "scope", "corner_bucket", "n", "avg_diff", "plus_rate"]]


def build_event_corner_cross(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        for event_cat in EVENT_CATEGORY_ORDER:
            scoped = frame.loc[frame["event_category"].astype(str).eq(event_cat)].copy()
            kw = _kruskal_summary(scoped, "corner_bucket", order=CORNER_BUCKET_ORDER)
            stats = _group_stats(scoped, "corner_bucket", order=CORNER_BUCKET_ORDER)
            for _, row in stats.iterrows():
                rows.append(
                    {
                        "segment": segment,
                        "event_category": event_cat,
                        "corner_bucket": row["corner_bucket"],
                        "n": int(row["n"]),
                        "avg_diff": float(row["avg_diff"]),
                        "plus_rate": float(row["plus_rate"]),
                        "kw_p": kw["p_value"],
                    }
                )
    table = pd.DataFrame(rows)
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["event_category"] = pd.Categorical(table["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(["segment", "event_category", "corner_bucket"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["event_category"] = table["event_category"].astype(str)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    return table


def build_fine_rank_analysis(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        for scope, frame_fn in [("all_day", lambda w: w), ("nonevent", _non_event_frame)]:
            frame = frame_fn(_segment_frame(work, segment))
            if frame.empty or frame["rank_from_aisle_str"].isna().all():
                continue
            valid = frame.dropna(subset=["rank_from_aisle_str"]).copy()
            for rank_val, grp in valid.groupby("rank_from_aisle_str", dropna=False, sort=False):
                values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
                if len(values) == 0:
                    continue
                rows.append(
                    {
                        "segment": segment,
                        "scope": scope,
                        "rank_from_aisle": int(rank_val),
                        "n": int(len(values)),
                        "avg_diff": float(values.mean()),
                        "plus_rate": float((values > 0).mean() * 100),
                    }
                )
    table = pd.DataFrame(rows)
    if table.empty:
        return pd.DataFrame(columns=["segment", "scope", "rank_from_aisle", "n", "avg_diff", "plus_rate"])
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values(["segment", "scope", "rank_from_aisle"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_fine_rank_kw(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        for scope, frame_fn in [("all_day", lambda w: w), ("nonevent", _non_event_frame)]:
            frame = frame_fn(_segment_frame(work, segment))
            kw = _kruskal_summary(frame, "rank_from_aisle_str", order=FINE_RANK_ORDER)
            rows.append(
                {
                    "segment": segment,
                    "scope": scope,
                    "kw_stat": kw["kw_stat"],
                    "p_value": kw["p_value"],
                    "epsilon_sq": kw["epsilon_sq"],
                    "n_groups": kw["n_groups"],
                    "n": kw["total_n"],
                }
            )
    return pd.DataFrame(rows)


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    lines = [
        "# Mitoya Phase 10c: corner position effect by segment",
        "",
        f"- source_latest_date: {source_latest_date}",
        "- min_games_filter: games >= 1000",
        "- corner_bucket: rank_from_aisle 1→corner1, 2-4→corner2-4, 5-9→corner5-9, 10+→corner10+",
        "- segments: h_jug, h_nonjug, v_jug, v_nonjug, mixed_805 (mutually exclusive)",
        "",
        "## A. corner_bucket KW test (all days)",
        "",
        render_markdown_table(artifacts["corner_kw_allday"]),
        "",
        "## B. corner_bucket KW test (non-event only)",
        "",
        render_markdown_table(artifacts["corner_kw_nonevent"]),
        "",
        "## C. corner_bucket ranking by segment",
        "",
        render_markdown_table(artifacts["corner_ranking"]),
        "",
        "## D. event_category × corner_bucket cross",
        "",
        render_markdown_table(artifacts["event_corner_cross"].head(100)),
        "",
        "## E. fine rank_from_aisle KW test",
        "",
        render_markdown_table(artifacts["fine_rank_kw"]),
        "",
        "## F. fine rank_from_aisle ranking (top 80 rows)",
        "",
        render_markdown_table(artifacts["fine_rank_analysis"].head(80)),
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    date_series = (
        pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")
        if "date" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = date_series.max() if not date_series.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"

    artifacts: dict[str, pd.DataFrame | str] = {
        "corner_kw_allday": build_corner_kw_allday(work),
        "corner_kw_nonevent": build_corner_kw_nonevent(work),
        "corner_ranking": build_corner_ranking(work),
        "event_corner_cross": build_event_corner_cross(work),
        "fine_rank_kw": build_fine_rank_kw(work),
        "fine_rank_analysis": build_fine_rank_analysis(work),
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=source_latest_date)
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, value in artifacts.items():
        if key == "report":
            (output_dir / "report.md").write_text(str(value), encoding="utf-8")
        elif isinstance(value, pd.DataFrame):
            value.to_csv(output_dir / f"{key}.csv", index=False, encoding="utf-8-sig")


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
