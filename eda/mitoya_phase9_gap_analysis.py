from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.mitoya_prompt_common import (  # noqa: E402
    MITOYA_ALL_SECTIONS,
    MITOYA_MAIN_SECTIONS,
    RESULTS_DIR,
    add_debut_phase,
    ensure_results_dir,
    kw_epsilon_squared,
    load_mitoya_frame,
    render_markdown_table,
    section_sort_key,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase9_gap_analysis"
X_DDS = {4, 7, 14, 17, 24, 27}
CORNER_BUCKET_ORDER = ["corner1", "corner2-4", "corner5-9", "corner10+"]
DEBUT_PHASE_ORDER = ["pre_existing", "debut", "growth", "mature"]
LAST_DIGIT_ORDER = [str(i) for i in range(10)]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "section" in work.columns:
        work["section"] = work["section"].fillna("unknown").astype(str)
    else:
        work["section"] = "unknown"

    if "machine_digit" in work.columns and "last_digit" not in work.columns:
        work["last_digit"] = work["machine_digit"]
    if "machine_zorome" in work.columns and "is_zorome" not in work.columns:
        work["is_zorome"] = work["machine_zorome"]

    if "last_digit" in work.columns:
        work["last_digit"] = pd.Series(work["last_digit"], dtype="string").astype("string")
    else:
        work["last_digit"] = pd.Series([pd.NA] * len(work), dtype="string")

    if "is_zorome" in work.columns:
        work["is_zorome"] = pd.to_numeric(work["is_zorome"], errors="coerce").fillna(0).astype(int)
    else:
        work["is_zorome"] = 0

    if "is_reversed_section" in work.columns:
        work["is_reversed_section"] = pd.to_numeric(work["is_reversed_section"], errors="coerce").fillna(0).astype(int)
    else:
        work["is_reversed_section"] = 0

    if "diff" in work.columns:
        work["diff"] = pd.to_numeric(work["diff"], errors="coerce")
    else:
        work["diff"] = np.nan
    if "games" in work.columns:
        work["games"] = pd.to_numeric(work["games"], errors="coerce")
    else:
        work["games"] = np.nan

    if "date_dt" not in work.columns:
        if "date" in work.columns:
            work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        else:
            work["date_dt"] = pd.NaT
    if "dd" not in work.columns:
        work["dd"] = work["date_dt"].dt.day
    work["dd"] = pd.to_numeric(work["dd"], errors="coerce").astype("Int64")
    work["is_xdds"] = work["dd"].isin(X_DDS).astype(int)

    if "corner_bucket" in work.columns:
        work["corner_bucket"] = work["corner_bucket"].fillna("unknown").astype(str)
    else:
        work["corner_bucket"] = work.get("rank_from_aisle", pd.Series([pd.NA] * len(work)))
        work["corner_bucket"] = work["corner_bucket"].apply(_corner_bucket_from_rank).astype(str)

    if "debut_phase" not in work.columns:
        if {"date", "machine_number", "machine_name"} <= set(work.columns):
            work = add_debut_phase(work)
        else:
            work["debut_phase"] = "unknown"
    work["debut_phase"] = work["debut_phase"].fillna("unknown").astype(str)

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


def _safe_group_stats(frame: pd.DataFrame, *, label_col: str, value_col: str = "diff") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[label_col, "n", "avg_diff", "plus_rate"])
    rows: list[dict[str, object]] = []
    for label, grp in frame.groupby(label_col, dropna=False, sort=False):
        values = pd.to_numeric(grp[value_col], errors="coerce").dropna()
        rows.append(
            {
                label_col: label,
                "n": int(len(values)),
                "avg_diff": float(values.mean()) if len(values) else float("nan"),
                "plus_rate": float((values > 0).mean() * 100) if len(values) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def _kruskal_summary(frame: pd.DataFrame, *, group_col: str, value_col: str = "diff") -> dict[str, object]:
    groups: list[np.ndarray] = []
    for _, grp in frame.groupby(group_col, dropna=False, sort=False):
        values = pd.to_numeric(grp[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        if len(values):
            groups.append(values)
    if len(groups) < 2:
        return {
            "kw_stat": float("nan"),
            "p_value": float("nan"),
            "epsilon_sq": float("nan"),
            "n_groups": len(groups),
            "total_n": int(sum(len(group) for group in groups)),
        }
    try:
        kw_stat, p_value = kruskal(*groups)
    except ValueError:
        kw_stat, p_value = float("nan"), float("nan")
    total_n = int(sum(len(group) for group in groups))
    return {
        "kw_stat": float(kw_stat) if pd.notna(kw_stat) else float("nan"),
        "p_value": float(p_value) if pd.notna(p_value) else float("nan"),
        "epsilon_sq": kw_epsilon_squared(float(kw_stat), len(groups), total_n),
        "n_groups": len(groups),
        "total_n": total_n,
    }


def _finalize_section_order(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "section" not in df.columns:
        return df
    ordered = df.copy()
    ordered["section"] = pd.Categorical(
        ordered["section"], categories=sorted(ordered["section"].dropna().unique(), key=section_sort_key), ordered=True
    )
    ordered = ordered.sort_values(
        [col for col in ["section", "is_reversed_section"] if col in ordered.columns],
        ascending=True,
        kind="mergesort",
    )
    ordered["section"] = ordered["section"].astype(str)
    return ordered.reset_index(drop=True)


def build_last_digit_by_section(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["section", "last_digit", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "is_reversed_section",
                "last_digit",
                "n",
                "avg_diff",
                "plus_rate",
                "kw_stat",
                "p_value",
                "epsilon_sq",
                "n_groups",
                "total_n",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, reversed_flag), grp in work.groupby(["section", "is_reversed_section"], dropna=False, sort=False):
        stats = _kruskal_summary(grp, group_col="last_digit")
        digit_table = _safe_group_stats(grp, label_col="last_digit")
        if not digit_table.empty:
            digit_table["last_digit"] = pd.Categorical(
                digit_table["last_digit"].astype(str),
                categories=LAST_DIGIT_ORDER,
                ordered=True,
            )
            digit_table = digit_table.sort_values("last_digit", kind="mergesort")
        for _, row in digit_table.iterrows():
            rows.append(
                {
                    "section": str(section),
                    "is_reversed_section": int(reversed_flag),
                    "last_digit": str(row["last_digit"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                    **stats,
                }
            )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table["avg_diff"] = table["avg_diff"].round(0).astype(float)
    table["plus_rate"] = table["plus_rate"].round(1)
    table["kw_stat"] = table["kw_stat"].round(4)
    table["epsilon_sq"] = table["epsilon_sq"].round(6)
    table["last_digit"] = pd.Categorical(table["last_digit"], categories=LAST_DIGIT_ORDER, ordered=True)
    table = table.sort_values(
        ["section", "is_reversed_section", "last_digit"],
        ascending=[True, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    )
    table["last_digit"] = table["last_digit"].astype(str)
    return table.reset_index(drop=True)


def build_zorome_by_section(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["section", "is_zorome", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "is_reversed_section",
                "n_zorome",
                "n_non_zorome",
                "avg_diff_zorome",
                "avg_diff_non_zorome",
                "plus_rate_zorome",
                "plus_rate_non_zorome",
                "zorome_lift",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, reversed_flag), grp in work.groupby(["section", "is_reversed_section"], dropna=False, sort=False):
        zorome = grp.loc[grp["is_zorome"].eq(1)].copy()
        non = grp.loc[grp["is_zorome"].eq(0)].copy()

        def _metrics(frame: pd.DataFrame) -> dict[str, object]:
            values = pd.to_numeric(frame["diff"], errors="coerce").dropna()
            if values.empty:
                return {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan")}
            return {
                "n": int(len(values)),
                "avg_diff": float(values.mean()),
                "plus_rate": float((values > 0).mean() * 100),
            }

        zorome_stats = _metrics(zorome)
        non_stats = _metrics(non)
        rows.append(
            {
                "section": str(section),
                "is_reversed_section": int(reversed_flag),
                "n_zorome": zorome_stats["n"],
                "n_non_zorome": non_stats["n"],
                "avg_diff_zorome": zorome_stats["avg_diff"],
                "avg_diff_non_zorome": non_stats["avg_diff"],
                "plus_rate_zorome": zorome_stats["plus_rate"],
                "plus_rate_non_zorome": non_stats["plus_rate"],
                "zorome_lift": (
                    float(zorome_stats["avg_diff"] - non_stats["avg_diff"])
                    if pd.notna(zorome_stats["avg_diff"]) and pd.notna(non_stats["avg_diff"])
                    else float("nan")
                ),
            }
        )

    table = pd.DataFrame(rows)
    table["avg_diff_zorome"] = table["avg_diff_zorome"].round(0)
    table["avg_diff_non_zorome"] = table["avg_diff_non_zorome"].round(0)
    table["plus_rate_zorome"] = table["plus_rate_zorome"].round(1)
    table["plus_rate_non_zorome"] = table["plus_rate_non_zorome"].round(1)
    table["zorome_lift"] = table["zorome_lift"].round(0)
    return _finalize_section_order(table)


def _interaction_table(
    work: pd.DataFrame,
    *,
    factor_col: str,
    factor_order: list[str],
    prefix: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (section, reversed_flag, bucket), grp in work.groupby(
        ["section", "is_reversed_section", factor_col], dropna=False, sort=False
    ):
        values = pd.to_numeric(grp["diff"], errors="coerce").dropna()
        rows.append(
            {
                "section": str(section),
                "is_reversed_section": int(reversed_flag),
                factor_col: str(bucket),
                f"n_{prefix}": int(len(values)),
                f"avg_diff_{prefix}": float(values.mean()) if len(values) else float("nan"),
                f"plus_rate_{prefix}": float((values > 0).mean() * 100) if len(values) else float("nan"),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    table[f"{factor_col}"] = pd.Categorical(table[factor_col], categories=factor_order, ordered=True)
    table = table.sort_values(
        ["section", "is_reversed_section", factor_col],
        ascending=[True, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)
    table[factor_col] = table[factor_col].astype(str)
    return table


def build_xdds_corner_interaction(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["section", "corner_bucket", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "is_reversed_section",
                "corner_bucket",
                "n_non_xdds",
                "avg_diff_non_xdds",
                "plus_rate_non_xdds",
                "n_xdds",
                "avg_diff_xdds",
                "plus_rate_xdds",
                "xdds_premium",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, reversed_flag, corner_bucket), grp in work.groupby(
        ["section", "is_reversed_section", "corner_bucket"], dropna=False, sort=False
    ):
        non = grp.loc[grp["is_xdds"].eq(0)].copy()
        xdds = grp.loc[grp["is_xdds"].eq(1)].copy()

        def _metrics(frame: pd.DataFrame) -> dict[str, object]:
            values = pd.to_numeric(frame["diff"], errors="coerce").dropna()
            if values.empty:
                return {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan")}
            return {
                "n": int(len(values)),
                "avg_diff": float(values.mean()),
                "plus_rate": float((values > 0).mean() * 100),
            }

        non_stats = _metrics(non)
        xdds_stats = _metrics(xdds)
        rows.append(
            {
                "section": str(section),
                "is_reversed_section": int(reversed_flag),
                "corner_bucket": str(corner_bucket),
                "n_non_xdds": non_stats["n"],
                "avg_diff_non_xdds": non_stats["avg_diff"],
                "plus_rate_non_xdds": non_stats["plus_rate"],
                "n_xdds": xdds_stats["n"],
                "avg_diff_xdds": xdds_stats["avg_diff"],
                "plus_rate_xdds": xdds_stats["plus_rate"],
                "xdds_premium": (
                    float(xdds_stats["avg_diff"] - non_stats["avg_diff"])
                    if pd.notna(xdds_stats["avg_diff"]) and pd.notna(non_stats["avg_diff"])
                    else float("nan")
                ),
            }
        )

    table = pd.DataFrame(rows)
    table["corner_bucket"] = pd.Categorical(table["corner_bucket"], categories=CORNER_BUCKET_ORDER, ordered=True)
    table = table.sort_values(
        ["section", "is_reversed_section", "corner_bucket"],
        ascending=[True, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)
    table["corner_bucket"] = table["corner_bucket"].astype(str)
    table["avg_diff_non_xdds"] = table["avg_diff_non_xdds"].round(0)
    table["avg_diff_xdds"] = table["avg_diff_xdds"].round(0)
    table["plus_rate_non_xdds"] = table["plus_rate_non_xdds"].round(1)
    table["plus_rate_xdds"] = table["plus_rate_xdds"].round(1)
    table["xdds_premium"] = table["xdds_premium"].round(0)
    return table


def build_debut_event_premium(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.loc[work["debut_phase"].isin(DEBUT_PHASE_ORDER)].copy()
    work = work.dropna(subset=["section", "debut_phase", "diff"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "section",
                "is_reversed_section",
                "debut_phase",
                "n_non_xdds",
                "avg_diff_non_xdds",
                "plus_rate_non_xdds",
                "n_xdds",
                "avg_diff_xdds",
                "plus_rate_xdds",
                "event_premium",
            ]
        )

    rows: list[dict[str, object]] = []
    for (section, reversed_flag, debut_phase), grp in work.groupby(
        ["section", "is_reversed_section", "debut_phase"], dropna=False, sort=False
    ):
        non = grp.loc[grp["is_xdds"].eq(0)].copy()
        xdds = grp.loc[grp["is_xdds"].eq(1)].copy()

        def _metrics(frame: pd.DataFrame) -> dict[str, object]:
            values = pd.to_numeric(frame["diff"], errors="coerce").dropna()
            if values.empty:
                return {"n": 0, "avg_diff": float("nan"), "plus_rate": float("nan")}
            return {
                "n": int(len(values)),
                "avg_diff": float(values.mean()),
                "plus_rate": float((values > 0).mean() * 100),
            }

        non_stats = _metrics(non)
        xdds_stats = _metrics(xdds)
        rows.append(
            {
                "section": str(section),
                "is_reversed_section": int(reversed_flag),
                "debut_phase": str(debut_phase),
                "n_non_xdds": non_stats["n"],
                "avg_diff_non_xdds": non_stats["avg_diff"],
                "plus_rate_non_xdds": non_stats["plus_rate"],
                "n_xdds": xdds_stats["n"],
                "avg_diff_xdds": xdds_stats["avg_diff"],
                "plus_rate_xdds": xdds_stats["plus_rate"],
                "event_premium": (
                    float(xdds_stats["avg_diff"] - non_stats["avg_diff"])
                    if pd.notna(xdds_stats["avg_diff"]) and pd.notna(non_stats["avg_diff"])
                    else float("nan")
                ),
            }
        )

    table = pd.DataFrame(rows)
    table["debut_phase"] = pd.Categorical(table["debut_phase"], categories=DEBUT_PHASE_ORDER, ordered=True)
    table = table.sort_values(
        ["section", "is_reversed_section", "debut_phase"],
        ascending=[True, True, True],
        key=lambda col: col.map(section_sort_key) if col.name == "section" else col,
        kind="mergesort",
    ).reset_index(drop=True)
    table["debut_phase"] = table["debut_phase"].astype(str)
    table["avg_diff_non_xdds"] = table["avg_diff_non_xdds"].round(0)
    table["avg_diff_xdds"] = table["avg_diff_xdds"].round(0)
    table["plus_rate_non_xdds"] = table["plus_rate_non_xdds"].round(1)
    table["plus_rate_xdds"] = table["plus_rate_xdds"].round(1)
    table["event_premium"] = table["event_premium"].round(0)
    return table


def _payout_rate_pct(frame: pd.DataFrame) -> float:
    values = frame.copy()
    values["diff"] = pd.to_numeric(values["diff"], errors="coerce")
    values["games"] = pd.to_numeric(values["games"], errors="coerce")
    values = values.dropna(subset=["diff", "games"]).copy()
    if values.empty:
        return float("nan")
    denom = values["games"] * 3.0
    denom = denom.replace(0, np.nan)
    payout_rate = ((denom + values["diff"]) / denom) * 100
    hit = payout_rate.ge(104.0)
    return float(hit.mean() * 100)


def build_dd_fullspectrum(df: pd.DataFrame, *, sections: list[str] | None = None) -> pd.DataFrame:
    work = _subset(_prepare_frame(df), sections)
    work = work.dropna(subset=["dd", "diff"]).copy()
    rows: list[dict[str, object]] = []
    for dd in range(1, 32):
        dd_frame = work.loc[work["dd"].eq(dd)].copy()
        reversed0 = dd_frame.loc[dd_frame["is_reversed_section"].eq(0)].copy()
        reversed0_corner = reversed0.loc[reversed0["corner_bucket"].isin(["corner1", "corner2-4"])].copy()

        def _metrics(frame: pd.DataFrame) -> dict[str, object]:
            values = pd.to_numeric(frame["diff"], errors="coerce").dropna()
            if values.empty:
                return {"n": 0, "avg_diff": float("nan"), "hit104_rate_pct": float("nan")}
            return {
                "n": int(len(values)),
                "avg_diff": float(values.mean()),
                "hit104_rate_pct": _payout_rate_pct(frame),
            }

        overall = _metrics(dd_frame)
        reversed0_stats = _metrics(reversed0)
        reversed0_corner_stats = _metrics(reversed0_corner)
        rows.append(
            {
                "dd": dd,
                "overall_n": overall["n"],
                "overall_avg_diff": overall["avg_diff"],
                "overall_hit104_rate_pct": overall["hit104_rate_pct"],
                "reversed0_n": reversed0_stats["n"],
                "reversed0_avg_diff": reversed0_stats["avg_diff"],
                "reversed0_corner1_4_n": reversed0_corner_stats["n"],
                "reversed0_corner1_4_avg_diff": reversed0_corner_stats["avg_diff"],
            }
        )
    table = pd.DataFrame(rows)
    table["overall_avg_diff"] = table["overall_avg_diff"].round(0)
    table["overall_hit104_rate_pct"] = table["overall_hit104_rate_pct"].round(1)
    table["reversed0_avg_diff"] = table["reversed0_avg_diff"].round(0)
    table["reversed0_corner1_4_avg_diff"] = table["reversed0_corner1_4_avg_diff"].round(0)
    return table


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    lines = [
        "# Mitoya Phase 9: gap analysis",
        "",
        f"- source_latest_date: {source_latest_date}",
        f"- sections: {', '.join(MITOYA_ALL_SECTIONS)}",
        f"- main_sections: {', '.join(MITOYA_MAIN_SECTIONS)}",
        "",
        "## last_digit_by_section",
        "",
        render_markdown_table(artifacts["last_digit_by_section"].head(40))
        if not artifacts["last_digit_by_section"].empty
        else "_no rows_",
        "",
        "## zorome_by_section",
        "",
        render_markdown_table(artifacts["zorome_by_section"])
        if not artifacts["zorome_by_section"].empty
        else "_no rows_",
        "",
        "## xdds_corner_interaction",
        "",
        render_markdown_table(artifacts["xdds_corner_interaction"].head(40))
        if not artifacts["xdds_corner_interaction"].empty
        else "_no rows_",
        "",
        "## debut_event_premium",
        "",
        render_markdown_table(artifacts["debut_event_premium"].head(40))
        if not artifacts["debut_event_premium"].empty
        else "_no rows_",
        "",
        "## dd_fullspectrum",
        "",
        render_markdown_table(artifacts["dd_fullspectrum"]) if not artifacts["dd_fullspectrum"].empty else "_no rows_",
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
    date_series = work["date_dt"] if "date_dt" in work.columns else pd.Series(dtype="datetime64[ns]")
    latest_date = pd.to_datetime(date_series, errors="coerce").max() if not date_series.empty else pd.NaT
    source_latest_date = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"
    section_scope = [str(section) for section in (sections or MITOYA_ALL_SECTIONS)]
    main_scope = [str(section) for section in (main_sections or MITOYA_MAIN_SECTIONS)]

    artifacts: dict[str, pd.DataFrame | str] = {
        "last_digit_by_section": build_last_digit_by_section(work, sections=section_scope),
        "zorome_by_section": build_zorome_by_section(work, sections=section_scope),
        "xdds_corner_interaction": build_xdds_corner_interaction(work, sections=section_scope),
        "debut_event_premium": build_debut_event_premium(work, sections=main_scope),
        "dd_fullspectrum": build_dd_fullspectrum(work, sections=section_scope),
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=source_latest_date)
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["last_digit_by_section"].to_csv(
        output_dir / "last_digit_by_section.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["zorome_by_section"].to_csv(output_dir / "zorome_by_section.csv", index=False, encoding="utf-8-sig")
    artifacts["xdds_corner_interaction"].to_csv(
        output_dir / "xdds_corner_interaction.csv", index=False, encoding="utf-8-sig"
    )
    artifacts["debut_event_premium"].to_csv(output_dir / "debut_event_premium.csv", index=False, encoding="utf-8-sig")
    artifacts["dd_fullspectrum"].to_csv(output_dir / "dd_fullspectrum.csv", index=False, encoding="utf-8-sig")
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
