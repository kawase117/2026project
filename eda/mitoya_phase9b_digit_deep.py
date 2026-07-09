from __future__ import annotations

import argparse
import calendar
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda import mitoya_phase9_gap_analysis as phase9  # noqa: E402
from eda.mitoya_prompt_common import (  # noqa: E402
    MITOYA_ALL_SECTIONS,
    MITOYA_MAIN_SECTIONS,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase9b_digit_deep"
X_DDS = {4, 7, 14, 17, 24, 27}
ZOROME_DAYS = {11, 22}
EVENT_CATEGORY_ORDER = ["xdds_day", "zorome_day", "strong_zorome", "month_end", "non_event"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
LAST_DIGIT_ORDER = [str(i) for i in range(10)]
ZOROME_DIGITS = [f"{i}{i}" for i in range(10)]
DATE_SCOPES = ("zorome_day", "strong_zorome")


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = phase9._prepare_frame(df)
    if "machine_number" in work.columns:
        machine_number = pd.to_numeric(work["machine_number"], errors="coerce")
        work = work.loc[machine_number.ne(745) | machine_number.isna()].copy()
    else:
        work = work.copy()

    work["date_dt"] = pd.to_datetime(
        work.get("date_dt", pd.to_datetime(work.get("date"), format="%Y%m%d", errors="coerce")), errors="coerce"
    )
    if "dd" not in work.columns:
        work["dd"] = work["date_dt"].dt.day
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")
    work["dd_mod10"] = (work["dd"] % 10).astype("Int64")
    work["last_digit"] = work["last_digit"].astype("string").str.strip()
    work["last_digit"] = work["last_digit"].where(work["last_digit"].isin(LAST_DIGIT_ORDER))
    work["is_dd_digit_match"] = (
        (pd.to_numeric(work["last_digit"], errors="coerce").astype("Int64") == work["dd_mod10"])
        .fillna(False)
        .astype(int)
    )

    work["is_xdds_day"] = work["dd"].isin(X_DDS).astype(int)
    work["is_zorome_day"] = work["dd"].isin(ZOROME_DAYS).astype(int)
    work["is_strong_zorome_day"] = (
        pd.to_datetime(work["date_dt"], errors="coerce")
        .dt.day.eq(pd.to_datetime(work["date_dt"], errors="coerce").dt.month)
        .fillna(False)
        .astype(int)
    )
    work["is_month_end"] = pd.to_datetime(work["date_dt"], errors="coerce").dt.is_month_end.fillna(False).astype(int)
    work["is_anniversary"] = (
        (
            pd.to_datetime(work["date_dt"], errors="coerce").dt.month.eq(7)
            & pd.to_datetime(work["date_dt"], errors="coerce").dt.day.eq(10)
        )
        .fillna(False)
        .astype(int)
    )

    work["event_category"] = np.select(
        [
            work["is_xdds_day"].eq(1),
            work["is_zorome_day"].eq(1),
            work["is_strong_zorome_day"].eq(1),
            work["is_month_end"].eq(1),
        ],
        ["xdds_day", "zorome_day", "strong_zorome", "month_end"],
        default="non_event",
    )
    work["event_category"] = pd.Categorical(work["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    work["corner_bucket"] = work["corner_bucket"].fillna("unknown").astype(str)
    return work


def _subset(frame: pd.DataFrame, sections: list[str] | None) -> pd.DataFrame:
    if sections is None:
        return frame.copy()
    allowed = {str(section) for section in sections}
    return frame.loc[frame["section"].astype(str).isin(allowed)].copy()


def _value_stats(frame: pd.DataFrame, *, value_col: str = "diff") -> dict[str, object]:
    values = pd.to_numeric(frame[value_col], errors="coerce").dropna()
    if values.empty:
        return {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan")}
    return {
        "n": int(len(values)),
        "avg_diff": float(values.mean()),
        "plus_rate": float((values > 0).mean() * 100),
    }


def _sort_by_section(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "section" not in df.columns:
        return df
    out = df.copy()
    out["section"] = pd.Categorical(
        out["section"],
        categories=sorted(out["section"].dropna().astype(str).unique(), key=section_sort_key),
        ordered=True,
    )
    sort_cols = [
        col
        for col in ["section", "corner_bucket", "dd", "dd_mod10", "last_digit", "event_category"]
        if col in out.columns
    ]
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=True, kind="mergesort")
    out["section"] = out["section"].astype(str)
    return out.reset_index(drop=True)


def build_digit_by_corner_bucket(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["corner_bucket", "last_digit", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for (corner_bucket, last_digit), grp in work.groupby(["corner_bucket", "last_digit"], dropna=False, sort=False):
        stats = _value_stats(grp)
        rows.append({"corner_bucket": str(corner_bucket), "last_digit": str(last_digit), **stats})
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(["corner_bucket", "last_digit"], kind="mergesort").reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_dd_digit_cross(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["dd", "last_digit", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for (corner_bucket, dd, last_digit), grp in work.groupby(
        ["corner_bucket", "dd", "last_digit"], dropna=False, sort=False
    ):
        stats = _value_stats(grp)
        rows.append(
            {
                "corner_bucket": str(corner_bucket),
                "dd": int(dd),
                "last_digit": str(last_digit),
                **stats,
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(["corner_bucket", "dd", "last_digit"], kind="mergesort").reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_dd_mod10_digit_match(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["dd_mod10", "last_digit", "diff"]).copy()
    work["last_digit_num"] = pd.to_numeric(work["last_digit"], errors="coerce").astype("Int64")
    work = work.dropna(subset=["last_digit_num"]).copy()
    rows: list[dict[str, object]] = []
    for (corner_bucket, dd_mod10), grp in work.groupby(["corner_bucket", "dd_mod10"], dropna=False, sort=False):
        grp = grp.copy()
        grp["is_dd_digit_match"] = grp["last_digit_num"].eq(grp["dd_mod10"]).astype(int)
        match_stats = _value_stats(grp.loc[grp["is_dd_digit_match"].eq(1)])
        non_stats = _value_stats(grp.loc[grp["is_dd_digit_match"].eq(0)])
        lift = (
            float(match_stats["avg_diff"] - non_stats["avg_diff"])
            if pd.notna(match_stats["avg_diff"]) and pd.notna(non_stats["avg_diff"])
            else float("nan")
        )
        for match_flag, stats in ((0, non_stats), (1, match_stats)):
            rows.append(
                {
                    "corner_bucket": str(corner_bucket),
                    "dd_mod10": int(dd_mod10),
                    "is_dd_digit_match": int(match_flag),
                    "n": int(stats["n"]),
                    "avg_diff": float(stats["avg_diff"]),
                    "plus_rate": float(stats["plus_rate"]),
                    "match_lift": lift,
                }
            )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(["corner_bucket", "dd_mod10", "is_dd_digit_match"], kind="mergesort").reset_index(
        drop=True
    )
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    table["match_lift"] = table["match_lift"].round(0)
    return table


def build_zorome_date_machine_interaction(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["diff", "corner_bucket", "last_digit"]).copy()
    rows: list[dict[str, object]] = []
    for scope in DATE_SCOPES:
        if scope == "zorome_day":
            scope_flag = work["is_zorome_day"].eq(1)
        else:
            scope_flag = work["is_strong_zorome_day"].eq(1)
        scoped = work.copy()
        scoped["is_zorome_date"] = scope_flag.astype(int)

        for (corner_bucket, is_date, is_machine), grp in scoped.groupby(
            ["corner_bucket", "is_zorome_date", "is_zorome"], dropna=False, sort=False
        ):
            stats = _value_stats(grp)
            rows.append(
                {
                    "record_type": "interaction_2x2",
                    "date_scope": scope,
                    "corner_bucket": str(corner_bucket),
                    "is_zorome_date": int(is_date),
                    "is_zorome_machine": int(is_machine),
                    "n": int(stats["n"]),
                    "avg_diff": float(stats["avg_diff"]),
                    "plus_rate": float(stats["plus_rate"]),
                }
            )

        digit_scope = scoped.loc[scoped["is_zorome"].eq(1)].copy()
        digit_scope["zorome_digit"] = pd.to_numeric(digit_scope["last_digit"], errors="coerce")
        digit_scope = digit_scope.dropna(subset=["zorome_digit"]).copy()
        digit_scope["zorome_digit"] = digit_scope["zorome_digit"].astype(int).map(lambda x: f"{x}{x}")
        for (corner_bucket, zorome_digit), grp in digit_scope.groupby(
            ["corner_bucket", "zorome_digit"], dropna=False, sort=False
        ):
            stats = _value_stats(grp)
            rows.append(
                {
                    "record_type": "digit_detail",
                    "date_scope": scope,
                    "corner_bucket": str(corner_bucket),
                    "zorome_digit": str(zorome_digit),
                    "n": int(stats["n"]),
                    "avg_diff": float(stats["avg_diff"]),
                    "plus_rate": float(stats["plus_rate"]),
                }
            )

    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(
        ["date_scope", "record_type", "corner_bucket", "is_zorome_date", "is_zorome_machine", "zorome_digit"],
        kind="mergesort",
    ).reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_event_category_digit(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["corner_bucket", "last_digit", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for (corner_bucket, event_category, last_digit), grp in work.groupby(
        ["corner_bucket", "event_category", "last_digit"], dropna=False, sort=False
    ):
        stats = _value_stats(grp)
        rows.append(
            {
                "corner_bucket": str(corner_bucket),
                "event_category": str(event_category),
                "last_digit": str(last_digit),
                **stats,
            }
        )
    table = pd.DataFrame(rows)
    lattice = pd.MultiIndex.from_product(
        [CORNER_BUCKET_ORDER, EVENT_CATEGORY_ORDER, LAST_DIGIT_ORDER],
        names=["corner_bucket", "event_category", "last_digit"],
    ).to_frame(index=False)
    if table.empty:
        table = lattice.copy()
        table["n"] = 0
        table["avg_diff"] = np.nan
        table["plus_rate"] = np.nan
    else:
        table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
        table["event_category"] = pd.Categorical(table["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
        table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
        table = lattice.merge(table, on=["corner_bucket", "event_category", "last_digit"], how="left")
        table["n"] = table["n"].fillna(0).astype(int)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["event_category"] = pd.Categorical(table["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(["event_category", "corner_bucket", "last_digit"], kind="mergesort").reset_index(
        drop=True
    )
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["event_category"] = table["event_category"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_report(
    artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str, excluded_745_rows: int, anniversary_rows: int
) -> str:
    lines = [
        "# Mitoya Phase 9b: digit deep dive",
        "",
        f"- source_latest_date: {source_latest_date}",
        f"- excluded_machine_number_745_rows: {excluded_745_rows}",
        f"- anniversary_rows_tracked: {anniversary_rows}",
        f"- sections: {', '.join(MITOYA_ALL_SECTIONS)}",
        f"- main_sections: {', '.join(MITOYA_MAIN_SECTIONS)}",
        "",
        "## digit_by_corner_bucket",
        "",
        render_markdown_table(artifacts["digit_by_corner_bucket"].head(40))
        if not artifacts["digit_by_corner_bucket"].empty
        else "_no rows_",
        "",
        "## dd_digit_cross",
        "",
        render_markdown_table(artifacts["dd_digit_cross"].head(40))
        if not artifacts["dd_digit_cross"].empty
        else "_no rows_",
        "",
        "## dd_mod10_digit_match",
        "",
        render_markdown_table(artifacts["dd_mod10_digit_match"].head(40))
        if not artifacts["dd_mod10_digit_match"].empty
        else "_no rows_",
        "",
        "## zorome_date_machine_interaction",
        "",
        render_markdown_table(artifacts["zorome_date_machine_interaction"].head(40))
        if not artifacts["zorome_date_machine_interaction"].empty
        else "_no rows_",
        "",
        "## event_category_digit",
        "",
        render_markdown_table(artifacts["event_category_digit"].head(40))
        if not artifacts["event_category_digit"].empty
        else "_no rows_",
        "",
        "_Note: 7/10 is tracked in the frame as `is_anniversary`, but the requested event grouping is the five-category split below._",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(
    df: pd.DataFrame,
    *,
    sections: list[str] | None = None,
    main_sections: list[str] | None = None,
) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    source_dates = (
        pd.to_datetime(work.get("date_dt"), errors="coerce")
        if "date_dt" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = source_dates.max() if not source_dates.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"
    excluded_745_rows = (
        int(pd.to_numeric(df.get("machine_number"), errors="coerce").eq(745).sum())
        if "machine_number" in df.columns
        else 0
    )
    anniversary_rows = int(work["is_anniversary"].sum()) if "is_anniversary" in work.columns else 0
    section_scope = [str(section) for section in (sections or MITOYA_ALL_SECTIONS)]
    _ = [str(section) for section in (main_sections or MITOYA_MAIN_SECTIONS)]

    artifacts: dict[str, pd.DataFrame | str] = {
        "digit_by_corner_bucket": build_digit_by_corner_bucket(work, sections=section_scope),
        "dd_digit_cross": build_dd_digit_cross(work, sections=section_scope),
        "dd_mod10_digit_match": build_dd_mod10_digit_match(work, sections=section_scope),
        "zorome_date_machine_interaction": build_zorome_date_machine_interaction(work, sections=section_scope),
        "event_category_digit": build_event_category_digit(work, sections=section_scope),
    }
    artifacts["report"] = build_report(
        artifacts,
        source_latest_date=source_latest_date,
        excluded_745_rows=excluded_745_rows,
        anniversary_rows=anniversary_rows,
    )
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["digit_by_corner_bucket"].to_csv(
        output_dir / "digit_by_corner_bucket.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["dd_digit_cross"].to_csv(output_dir / "dd_digit_cross.csv", index=False, encoding="utf-8-sig")
    artifacts["dd_mod10_digit_match"].to_csv(output_dir / "dd_mod10_digit_match.csv", index=False, encoding="utf-8-sig")
    artifacts["zorome_date_machine_interaction"].to_csv(
        output_dir / "zorome_date_machine_interaction.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["event_category_digit"].to_csv(output_dir / "event_category_digit.csv", index=False, encoding="utf-8-sig")
    (output_dir / "report.md").write_text(str(artifacts["report"]), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--sections", nargs="*", default=None)
    parser.add_argument("--main-sections", nargs="*", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_results_dir()
    args = parse_args(argv)
    df = load_mitoya_frame(join_layout=True)
    artifacts = build_all_artifacts(df, sections=args.sections, main_sections=args.main_sections)
    save_outputs(artifacts, args.output_dir)
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
