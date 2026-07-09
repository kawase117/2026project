from __future__ import annotations

import argparse
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


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase9c_juggler_split"
X_DDS = {4, 7, 14, 17, 24, 27}
ZOROME_DAYS = {11, 22}
EVENT_CATEGORY_ORDER = ["xdds_day", "zorome_day", "strong_zorome", "month_end", "non_event"]
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
LAST_DIGIT_ORDER = [str(i) for i in range(10)]
JUG_ORDER = ["jug", "non_jug"]
DD_SCOPE_ORDER = ["dd", "dd_mod10"]
DATE_SCOPE_ORDER = ["zorome_day", "strong_zorome"]
ZOROME_DIGITS = [f"{i}{i}" for i in range(10)]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = phase9._prepare_frame(df)
    work = work.copy()

    if "machine_number" in work.columns:
        machine_number = pd.to_numeric(work["machine_number"], errors="coerce")
        work = work.loc[machine_number.ne(745) | machine_number.isna()].copy()

    if "games" in work.columns:
        work["games"] = pd.to_numeric(work["games"], errors="coerce")
    else:
        work["games"] = np.nan
    work = work.loc[work["games"].ge(1000)].copy()

    if "machine_name" in work.columns:
        machine_name = work["machine_name"].fillna("").astype(str)
    else:
        machine_name = pd.Series([""] * len(work), index=work.index)
    work["jug_flag"] = np.where(machine_name.str.contains("ジャグラー", na=False), "jug", "non_jug")

    work["date_dt"] = pd.to_datetime(work.get("date_dt"), errors="coerce")
    if "dd" not in work.columns:
        work["dd"] = work["date_dt"].dt.day
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")
    work["dd_mod10"] = (work["dd"] % 10).astype("Int64")
    work["last_digit"] = work["last_digit"].astype("string").str.strip()
    work["last_digit"] = work["last_digit"].where(work["last_digit"].isin(LAST_DIGIT_ORDER))
    work["last_digit_num"] = pd.to_numeric(work["last_digit"], errors="coerce").astype("Int64")
    work["is_dd_digit_match"] = (work["last_digit_num"] == work["dd_mod10"]).fillna(False).astype(int)

    if "is_zorome" in work.columns:
        work["is_zorome_machine"] = pd.to_numeric(work["is_zorome"], errors="coerce").fillna(0).astype(int)
    else:
        machine_str = work.get("machine_number", pd.Series([pd.NA] * len(work), index=work.index)).astype("string")
        last2 = machine_str.str[-2:]
        work["is_zorome_machine"] = last2.str.len().eq(2) & last2.str[0].eq(last2.str[1])
        work["is_zorome_machine"] = work["is_zorome_machine"].fillna(False).astype(int)

    work["is_xdds_day"] = work["dd"].isin(X_DDS).astype(int)
    work["is_zorome_day"] = work["dd"].isin(ZOROME_DAYS).astype(int)
    work["is_strong_zorome_day"] = (work["date_dt"].dt.day.eq(work["date_dt"].dt.month)).fillna(False).astype(int)
    work["is_month_end"] = work["date_dt"].dt.is_month_end.fillna(False).astype(int)
    work["is_anniversary"] = (work["date_dt"].dt.month.eq(7) & work["date_dt"].dt.day.eq(10)).fillna(False).astype(int)
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

    if "corner_bucket" in work.columns:
        work["corner_bucket"] = work["corner_bucket"].fillna("unknown").astype(str)
    else:
        work["corner_bucket"] = work.get("rank_from_aisle", pd.Series([pd.NA] * len(work), index=work.index))
        work["corner_bucket"] = work["corner_bucket"].apply(_corner_bucket_from_rank).astype(str)
    return work


def _corner_bucket_from_rank(rank: object) -> str:
    value = pd.to_numeric(pd.Series([rank]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    int_value = int(value)
    if int_value <= 1:
        return "corner1"
    if int_value <= 4:
        return "corner2-4"
    if int_value <= 9:
        return "corner5-9"
    return "corner10+"


def _subset(frame: pd.DataFrame, sections: list[str] | None) -> pd.DataFrame:
    if sections is None:
        return frame.copy()
    allowed = {str(section) for section in sections}
    return frame.loc[frame["section"].astype(str).isin(allowed)].copy()


def _value_stats(frame: pd.DataFrame, *, value_col: str = "diff") -> dict[str, object]:
    values = pd.to_numeric(frame[value_col], errors="coerce").dropna()
    if values.empty:
        return {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan"), "machine_days": 0}
    return {
        "n": int(len(values)),
        "avg_diff": float(values.mean()),
        "plus_rate": float((values > 0).mean() * 100),
        "machine_days": int(len(values)),
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
        for col in ["section", "jug_flag", "corner_bucket", "dd", "dd_mod10", "last_digit", "event_category"]
        if col in out.columns
    ]
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=True, kind="mergesort")
    out["section"] = out["section"].astype(str)
    return out.reset_index(drop=True)


def _lattice_fill(table: pd.DataFrame, lattice: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    if table.empty:
        out = lattice.copy()
        out["n"] = 0
        out["machine_days"] = 0
        out["avg_diff"] = np.nan
        out["plus_rate"] = np.nan
        return out
    merged = lattice.merge(table, on=key_cols, how="left")
    for col in ("n", "machine_days"):
        if col in merged.columns:
            merged[col] = merged[col].fillna(0).astype(int)
    return merged


def build_jug_distribution(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["section", "machine_number"]).copy()
    rows: list[dict[str, object]] = []
    for (section, jug_flag), grp in work.groupby(["section", "jug_flag"], dropna=False, sort=False):
        stats = _value_stats(grp)
        rows.append(
            {
                "section": str(section),
                "jug_flag": str(jug_flag),
                "n": int(stats["n"]),
                "machine_days": int(stats["machine_days"]),
                "machine_count": int(pd.to_numeric(grp["machine_number"], errors="coerce").dropna().nunique()),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    return _sort_by_section(table)


def build_jug_digit_effect(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["corner_bucket", "last_digit", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for (corner_bucket, jug_flag, last_digit), grp in work.groupby(
        ["corner_bucket", "jug_flag", "last_digit"], dropna=False, sort=False
    ):
        stats = _value_stats(grp)
        rows.append(
            {
                "corner_bucket": str(corner_bucket),
                "jug_flag": str(jug_flag),
                "last_digit": str(last_digit),
                "n": int(stats["n"]),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )
    table = pd.DataFrame(rows)
    lattice = pd.MultiIndex.from_product(
        [CORNER_BUCKET_ORDER, JUG_ORDER, LAST_DIGIT_ORDER],
        names=["corner_bucket", "jug_flag", "last_digit"],
    ).to_frame(index=False)
    table = _lattice_fill(table, lattice, ["corner_bucket", "jug_flag", "last_digit"])
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["jug_flag"] = pd.Categorical(table["jug_flag"], categories=JUG_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(["corner_bucket", "jug_flag", "last_digit"], kind="mergesort").reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["jug_flag"] = table["jug_flag"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_jug_dd_effect(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["dd", "dd_mod10", "diff"]).copy()

    dd_rows: list[dict[str, object]] = []
    for (dd, jug_flag), grp in work.groupby(["dd", "jug_flag"], dropna=False, sort=False):
        stats = _value_stats(grp)
        dd_rows.append(
            {
                "metric_type": "dd",
                "dd": int(dd),
                "dd_mod10": pd.NA,
                "jug_flag": str(jug_flag),
                "n": int(stats["n"]),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )

    mod_rows: list[dict[str, object]] = []
    for (dd_mod10, jug_flag), grp in work.groupby(["dd_mod10", "jug_flag"], dropna=False, sort=False):
        stats = _value_stats(grp)
        mod_rows.append(
            {
                "metric_type": "dd_mod10",
                "dd": pd.NA,
                "dd_mod10": int(dd_mod10),
                "jug_flag": str(jug_flag),
                "n": int(stats["n"]),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )

    table = pd.DataFrame(dd_rows + mod_rows)
    if table.empty:
        return table
    table["metric_type"] = pd.Categorical(table["metric_type"], categories=DD_SCOPE_ORDER, ordered=True)
    table["jug_flag"] = pd.Categorical(table["jug_flag"], categories=JUG_ORDER, ordered=True)
    table = table.sort_values(["metric_type", "jug_flag", "dd", "dd_mod10"], kind="mergesort").reset_index(drop=True)
    table["metric_type"] = table["metric_type"].astype(str)
    table["jug_flag"] = table["jug_flag"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_jug_corner_effect(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["corner_bucket", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for (corner_bucket, jug_flag), grp in work.groupby(["corner_bucket", "jug_flag"], dropna=False, sort=False):
        stats = _value_stats(grp)
        rows.append(
            {
                "corner_bucket": str(corner_bucket),
                "jug_flag": str(jug_flag),
                "n": int(stats["n"]),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["jug_flag"] = pd.Categorical(table["jug_flag"], categories=JUG_ORDER, ordered=True)
    table = table.sort_values(["corner_bucket", "jug_flag"], kind="mergesort").reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["jug_flag"] = table["jug_flag"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_jug_event_digit(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["event_category", "last_digit", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for (event_category, jug_flag, last_digit), grp in work.groupby(
        ["event_category", "jug_flag", "last_digit"], dropna=False, sort=False
    ):
        stats = _value_stats(grp)
        rows.append(
            {
                "event_category": str(event_category),
                "jug_flag": str(jug_flag),
                "last_digit": str(last_digit),
                "n": int(stats["n"]),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )
    table = pd.DataFrame(rows)
    lattice = pd.MultiIndex.from_product(
        [EVENT_CATEGORY_ORDER, JUG_ORDER, LAST_DIGIT_ORDER],
        names=["event_category", "jug_flag", "last_digit"],
    ).to_frame(index=False)
    table = _lattice_fill(table, lattice, ["event_category", "jug_flag", "last_digit"])
    table["event_category"] = pd.Categorical(table["event_category"], categories=EVENT_CATEGORY_ORDER, ordered=True)
    table["jug_flag"] = pd.Categorical(table["jug_flag"], categories=JUG_ORDER, ordered=True)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(["event_category", "jug_flag", "last_digit"], kind="mergesort").reset_index(drop=True)
    table["event_category"] = table["event_category"].astype(str)
    table["jug_flag"] = table["jug_flag"].astype(str)
    table["last_digit"] = table["last_digit"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_jug_zorome(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["corner_bucket", "diff"]).copy()
    rows: list[dict[str, object]] = []

    for (corner_bucket, jug_flag, is_machine), grp in work.groupby(
        ["corner_bucket", "jug_flag", "is_zorome_machine"], dropna=False, sort=False
    ):
        stats = _value_stats(grp)
        rows.append(
            {
                "record_type": "overall_machine_split",
                "date_scope": "all_dates",
                "corner_bucket": str(corner_bucket),
                "jug_flag": str(jug_flag),
                "is_zorome_date": pd.NA,
                "is_zorome_machine": int(is_machine),
                "n": int(stats["n"]),
                "avg_diff": float(stats["avg_diff"]),
                "plus_rate": float(stats["plus_rate"]),
            }
        )

    for scope_name in DATE_SCOPE_ORDER:
        if scope_name == "zorome_day":
            scoped = work.loc[work["is_zorome_day"].eq(1)].copy()
        else:
            scoped = work.loc[work["is_strong_zorome_day"].eq(1)].copy()
        if scoped.empty:
            continue
        for (corner_bucket, jug_flag, is_date, is_machine), grp in scoped.assign(is_zorome_date=1).groupby(
            ["corner_bucket", "jug_flag", "is_zorome_date", "is_zorome_machine"], dropna=False, sort=False
        ):
            stats = _value_stats(grp)
            rows.append(
                {
                    "record_type": "interaction_2x2",
                    "date_scope": scope_name,
                    "corner_bucket": str(corner_bucket),
                    "jug_flag": str(jug_flag),
                    "is_zorome_date": int(is_date),
                    "is_zorome_machine": int(is_machine),
                    "n": int(stats["n"]),
                    "avg_diff": float(stats["avg_diff"]),
                    "plus_rate": float(stats["plus_rate"]),
                }
            )

    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["record_type"] = pd.Categorical(
        table["record_type"], categories=["overall_machine_split", "interaction_2x2"], ordered=True
    )
    table["date_scope"] = pd.Categorical(table["date_scope"], categories=["all_dates", *DATE_SCOPE_ORDER], ordered=True)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table["jug_flag"] = pd.Categorical(table["jug_flag"], categories=JUG_ORDER, ordered=True)
    table = table.sort_values(
        ["record_type", "date_scope", "corner_bucket", "jug_flag", "is_zorome_date", "is_zorome_machine"],
        kind="mergesort",
    ).reset_index(drop=True)
    table["record_type"] = table["record_type"].astype(str)
    table["date_scope"] = table["date_scope"].astype(str)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["jug_flag"] = table["jug_flag"].astype(str)
    table["avg_diff"] = table["avg_diff"].round(0)
    table["plus_rate"] = table["plus_rate"].round(1)
    return table


def build_report(
    artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str, excluded_745_rows: int, anniversary_rows: int
) -> str:
    lines = [
        "# Mitoya Phase 9c: juggler split",
        "",
        f"- source_latest_date: {source_latest_date}",
        f"- excluded_machine_number_745_rows: {excluded_745_rows}",
        f"- anniversary_rows_tracked: {anniversary_rows}",
        f"- sections: {', '.join(MITOYA_ALL_SECTIONS)}",
        f"- main_sections: {', '.join(MITOYA_MAIN_SECTIONS)}",
        "",
        "## jug_distribution",
        "",
        render_markdown_table(artifacts["jug_distribution"])
        if not artifacts["jug_distribution"].empty
        else "_no rows_",
        "",
        "## jug_digit_effect",
        "",
        render_markdown_table(artifacts["jug_digit_effect"].head(40))
        if not artifacts["jug_digit_effect"].empty
        else "_no rows_",
        "",
        "## jug_dd_effect",
        "",
        render_markdown_table(artifacts["jug_dd_effect"].head(40))
        if not artifacts["jug_dd_effect"].empty
        else "_no rows_",
        "",
        "## jug_corner_effect",
        "",
        render_markdown_table(artifacts["jug_corner_effect"])
        if not artifacts["jug_corner_effect"].empty
        else "_no rows_",
        "",
        "## jug_event_digit",
        "",
        render_markdown_table(artifacts["jug_event_digit"].head(40))
        if not artifacts["jug_event_digit"].empty
        else "_no rows_",
        "",
        "## jug_zorome",
        "",
        render_markdown_table(artifacts["jug_zorome"].head(40)) if not artifacts["jug_zorome"].empty else "_no rows_",
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
        "jug_distribution": build_jug_distribution(work, sections=section_scope),
        "jug_digit_effect": build_jug_digit_effect(work, sections=section_scope),
        "jug_dd_effect": build_jug_dd_effect(work, sections=section_scope),
        "jug_corner_effect": build_jug_corner_effect(work, sections=section_scope),
        "jug_event_digit": build_jug_event_digit(work, sections=section_scope),
        "jug_zorome": build_jug_zorome(work, sections=section_scope),
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
    artifacts["jug_distribution"].to_csv(output_dir / "jug_distribution.csv", index=False, encoding="utf-8-sig")
    artifacts["jug_digit_effect"].to_csv(output_dir / "jug_digit_effect.csv", index=False, encoding="utf-8-sig")
    artifacts["jug_dd_effect"].to_csv(output_dir / "jug_dd_effect.csv", index=False, encoding="utf-8-sig")
    artifacts["jug_corner_effect"].to_csv(output_dir / "jug_corner_effect.csv", index=False, encoding="utf-8-sig")
    artifacts["jug_event_digit"].to_csv(output_dir / "jug_event_digit.csv", index=False, encoding="utf-8-sig")
    artifacts["jug_zorome"].to_csv(output_dir / "jug_zorome.csv", index=False, encoding="utf-8-sig")
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
