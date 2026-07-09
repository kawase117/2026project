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


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10b_digit_nonevent"
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
LAST_DIGIT_ORDER = [str(i) for i in range(10)]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
EVENT_CATEGORY_ORDER = ["X_DDS", "ゾロ目日", "強ゾロ目", "月末", "非イベント日"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = phase10._prepare_frame(df)  # noqa: SLF001
    work = work.copy()
    work = add_event_category(work)
    work["last_digit"] = work["last_digit"].astype("string").str.strip()
    work["last_digit"] = work["last_digit"].where(work["last_digit"].isin(LAST_DIGIT_ORDER))
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


def _fill_lattice(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    order_map: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouped = frame.groupby(group_cols, dropna=False, sort=False)
    for keys, grp in grouped:
        key_values = keys if isinstance(keys, tuple) else (keys,)
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
        row = {"n": int(len(values))}
        row["avg_diff"] = float(values.mean()) if row["n"] else float("nan")
        row["plus_rate"] = float((values > 0).mean() * 100) if row["n"] else float("nan")
        for col, value in zip(group_cols, key_values):
            row[col] = str(value)
        rows.append(row)

    table = pd.DataFrame(rows)
    lattice = pd.MultiIndex.from_product([order_map[col] for col in group_cols], names=group_cols).to_frame(index=False)
    if table.empty:
        table = lattice.copy()
        table["n"] = 0
        table["avg_diff"] = np.nan
        table["plus_rate"] = np.nan
    else:
        for col in group_cols:
            table[col] = table[col].astype(str)
        table = lattice.merge(table, on=group_cols, how="left")
        table["n"] = table["n"].fillna(0).astype(int)
    for col in group_cols:
        table[col] = pd.Categorical(table[col], categories=order_map[col], ordered=True)
    table = table.sort_values(group_cols, kind="mergesort").reset_index(drop=True)
    for col in group_cols:
        table[col] = table[col].astype(str)
    return table


def build_nonevent_digit_kw(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _non_event_frame(_segment_frame(work, segment))
        kw = _kruskal_summary(frame, "last_digit", order=LAST_DIGIT_ORDER)
        rows.append(
            {
                "segment": segment,
                "kw_stat": kw["kw_stat"],
                "p_value": kw["p_value"],
                "epsilon_sq": kw["epsilon_sq"],
                "n_groups": kw["n_groups"],
                "n": kw["total_n"],
            }
        )
    table = pd.DataFrame(rows, columns=["segment", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"])
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values("segment", kind="mergesort").reset_index(drop=True)
    return table


def build_nonevent_digit_ranking(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _non_event_frame(_segment_frame(work, segment))
        stats = _group_stats(frame, "last_digit", order=LAST_DIGIT_ORDER)
        if stats.empty:
            continue
        stats["segment"] = segment
        rows.append(stats)
    if not rows:
        return pd.DataFrame(columns=["segment", "last_digit", "n", "avg_diff", "plus_rate"])
    table = pd.concat(rows, ignore_index=True)
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    lattice = pd.MultiIndex.from_product([SEGMENT_ORDER, LAST_DIGIT_ORDER], names=["segment", "last_digit"]).to_frame(
        index=False
    )
    table = lattice.merge(table, on=["segment", "last_digit"], how="left")
    table["n"] = table["n"].fillna(0).astype(int)
    table = table.sort_values(["segment", "last_digit"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    return table


def build_event_category_digit_kw(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        for event_category in EVENT_CATEGORY_ORDER:
            scoped = frame.loc[frame["event_category"].astype(str).eq(event_category)].copy()
            kw = _kruskal_summary(scoped, "last_digit", order=LAST_DIGIT_ORDER)
            rows.append(
                {
                    "segment": segment,
                    "event_category": event_category,
                    "kw_stat": kw["kw_stat"],
                    "p_value": kw["p_value"],
                    "epsilon_sq": kw["epsilon_sq"],
                    "n_groups": kw["n_groups"],
                    "n": kw["total_n"],
                }
            )
    table = pd.DataFrame(
        rows, columns=["segment", "event_category", "kw_stat", "p_value", "epsilon_sq", "n_groups", "n"]
    )
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["event_category"] = pd.Categorical(table["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    table = table.sort_values(["segment", "event_category"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["event_category"] = table["event_category"].astype(str)
    return table


def build_nonevent_corner_digit(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    order_map = {"corner_bucket": CORNER_BUCKET_ORDER, "last_digit": LAST_DIGIT_ORDER}
    for segment in ["h_jug", "h_nonjug"]:
        frame = _non_event_frame(_segment_frame(work, segment)).copy()
        if frame.empty:
            continue
        rows.append(
            _fill_lattice(frame, group_cols=["corner_bucket", "last_digit"], order_map=order_map).assign(
                segment=segment
            )
        )
    if not rows:
        return pd.DataFrame(columns=["segment", "corner_bucket", "last_digit", "n", "avg_diff", "plus_rate"])
    table = pd.concat(rows, ignore_index=True)
    table["segment"] = pd.Categorical(table["segment"], categories=["h_jug", "h_nonjug"], ordered=True)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(["segment", "corner_bucket", "last_digit"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    lines = [
        "# Mitoya Phase 10b: nonevent digit revalidation",
        "",
        f"- source_latest_date: {source_latest_date}",
        "- min_games_filter: games >= 1000",
        "- event_category_priority: X_DDS > ゾロ目日 > 強ゾロ目 > 月末 > 非イベント日",
        "- segment_partition: mixed_805 is excluded from the four orientation/jug segments",
        "",
        "## nonevent_digit_kw",
        "",
        render_markdown_table(artifacts["nonevent_digit_kw"])
        if not artifacts["nonevent_digit_kw"].empty
        else "_no rows_",
        "",
        "## nonevent_digit_ranking",
        "",
        render_markdown_table(artifacts["nonevent_digit_ranking"].head(60))
        if not artifacts["nonevent_digit_ranking"].empty
        else "_no rows_",
        "",
        "## event_category_digit_kw",
        "",
        render_markdown_table(artifacts["event_category_digit_kw"])
        if not artifacts["event_category_digit_kw"].empty
        else "_no rows_",
        "",
        "## nonevent_corner_digit",
        "",
        render_markdown_table(artifacts["nonevent_corner_digit"].head(80))
        if not artifacts["nonevent_corner_digit"].empty
        else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    source_dates = (
        pd.to_datetime(work.get("date_dt"), errors="coerce")
        if "date_dt" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = source_dates.max() if not source_dates.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"

    artifacts: dict[str, pd.DataFrame | str] = {
        "nonevent_digit_kw": build_nonevent_digit_kw(work),
        "nonevent_digit_ranking": build_nonevent_digit_ranking(work),
        "event_category_digit_kw": build_event_category_digit_kw(work),
        "nonevent_corner_digit": build_nonevent_corner_digit(work),
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=source_latest_date)
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["nonevent_digit_kw"].to_csv(output_dir / "nonevent_digit_kw.csv", index=False, encoding="utf-8-sig")
    artifacts["nonevent_digit_ranking"].to_csv(
        output_dir / "nonevent_digit_ranking.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["event_category_digit_kw"].to_csv(
        output_dir / "event_category_digit_kw.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["nonevent_corner_digit"].to_csv(
        output_dir / "nonevent_corner_digit.csv", index=False, encoding="utf-8-sig"
    )
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
