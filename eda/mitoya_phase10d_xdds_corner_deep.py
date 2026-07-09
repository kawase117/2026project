from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda import mitoya_phase10_segment_validation as phase10  # noqa: E402
from eda.mitoya_prompt_common import (  # noqa: E402
    X_DDS,
    add_event_category,
    ensure_results_dir,
    load_mitoya_frame,
    render_markdown_table,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "tmp" / "mitoya_phase10d_xdds_corner_deep"
SEGMENT_ORDER = ["h_jug", "h_nonjug", "v_jug", "v_nonjug", "mixed_805"]
FINE_RANK_ORDER = [str(i) for i in range(1, 6)]
DD_ORDER = ["4", "7", "14", "17", "24", "27"]


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = phase10._prepare_frame(df)  # noqa: SLF001
    work = work.copy()
    work = add_event_category(work)

    work["section"] = work.get("section", pd.Series(["unknown"] * len(work), index=work.index)).astype(str)
    work["rank_from_aisle"] = pd.to_numeric(work.get("rank_from_aisle"), errors="coerce").astype("Int64")
    work["rank_from_aisle_str"] = work["rank_from_aisle"].astype("string")
    work["dd"] = pd.to_numeric(work.get("dd"), errors="coerce").astype("Int64")
    work["corner_bucket"] = work.get("corner_bucket", pd.Series([pd.NA] * len(work), index=work.index))
    work["corner_bucket"] = work["corner_bucket"].fillna("unknown").astype(str)
    return work


def _segment_frame(work: pd.DataFrame, segment: str) -> pd.DataFrame:
    frame = phase10._segment_frame(work, segment)  # noqa: SLF001
    if segment != "mixed_805" and "section" in frame.columns:
        frame = frame.loc[frame["section"].astype(str).ne("805-815")].copy()
    return frame


def _xdds_frame(work: pd.DataFrame) -> pd.DataFrame:
    return work.loc[work["event_category"].astype(str).eq("X_DDS")].copy()


def _group_stats(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> pd.DataFrame:
    return phase10._group_stats(frame, group_col, order=order)  # noqa: SLF001


def _kruskal_summary(frame: pd.DataFrame, group_col: str, *, order: list[str] | None = None) -> dict[str, object]:
    return phase10._kruskal_summary(frame, group_col, order=order)  # noqa: SLF001


def _ordered_group_stats(frame: pd.DataFrame, group_col: str, order: list[str]) -> pd.DataFrame:
    stats = _group_stats(frame, group_col, order=order)
    lattice = pd.DataFrame({group_col: order})
    if stats.empty:
        lattice["n"] = 0
        lattice["avg_diff"] = np.nan
        lattice["plus_rate"] = np.nan
        return lattice
    out = lattice.merge(stats, on=group_col, how="left")
    out["n"] = out["n"].fillna(0).astype(int)
    return out


def _dd_stats(frame: pd.DataFrame, dd_value: int) -> dict[str, object]:
    scoped = frame.loc[pd.to_numeric(frame["dd"], errors="coerce").eq(dd_value)].copy()
    corner1 = scoped.loc[scoped["rank_from_aisle"].eq(1)].copy()
    rest = scoped.loc[scoped["rank_from_aisle"].gt(1)].copy()

    corner1_values = pd.to_numeric(corner1["diff"], errors="coerce").dropna()
    rest_values = pd.to_numeric(rest["diff"], errors="coerce").dropna()
    return {
        "corner1_n": int(len(corner1_values)),
        "corner1_avg_diff": float(corner1_values.mean()) if len(corner1_values) else float("nan"),
        "corner1_plus_rate": float((corner1_values > 0).mean() * 100) if len(corner1_values) else float("nan"),
        "rest_n": int(len(rest_values)),
        "rest_avg_diff": float(rest_values.mean()) if len(rest_values) else float("nan"),
        "rest_plus_rate": float((rest_values > 0).mean() * 100) if len(rest_values) else float("nan"),
        "delta_diff": float(corner1_values.mean() - rest_values.mean())
        if len(corner1_values) and len(rest_values)
        else float("nan"),
    }


def _mwu_summary(frame: pd.DataFrame, dd_value: int) -> dict[str, object]:
    scoped = frame.loc[pd.to_numeric(frame["dd"], errors="coerce").eq(dd_value)].copy()
    corner1_values = pd.to_numeric(scoped.loc[scoped["rank_from_aisle"].eq(1), "diff"], errors="coerce").dropna()
    rest_values = pd.to_numeric(scoped.loc[scoped["rank_from_aisle"].gt(1), "diff"], errors="coerce").dropna()
    if len(corner1_values) == 0 or len(rest_values) == 0:
        return {"u_stat": float("nan"), "p_value": float("nan"), "n": int(len(corner1_values) + len(rest_values))}
    try:
        u_stat, p_value = mannwhitneyu(corner1_values, rest_values, alternative="two-sided")
    except ValueError:
        u_stat, p_value = float("nan"), float("nan")
    return {"u_stat": float(u_stat), "p_value": float(p_value), "n": int(len(corner1_values) + len(rest_values))}


def build_xdds_fine_rank(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _xdds_frame(_segment_frame(work, segment))
        stats = _ordered_group_stats(frame, "rank_from_aisle_str", FINE_RANK_ORDER)
        for _, row in stats.iterrows():
            rows.append(
                {
                    "segment": segment,
                    "rank_from_aisle": int(row["rank_from_aisle_str"]),
                    "n": int(row["n"]),
                    "avg_diff": float(row["avg_diff"]),
                    "plus_rate": float(row["plus_rate"]),
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "rank_from_aisle", "n", "avg_diff", "plus_rate"])
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table = table.sort_values(["segment", "rank_from_aisle"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    return table


def build_xdds_fine_rank_kw(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _xdds_frame(_segment_frame(work, segment))
        kw = _kruskal_summary(frame, "rank_from_aisle_str", order=FINE_RANK_ORDER)
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
    table["segment"] = table["segment"].astype(str)
    return table


def build_dd_corner1_delta(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        for dd_value in [4, 7, 14, 17, 24, 27]:
            stats = _dd_stats(frame, dd_value)
            rows.append(
                {
                    "segment": segment,
                    "dd": dd_value,
                    **stats,
                }
            )
    table = pd.DataFrame(
        rows,
        columns=[
            "segment",
            "dd",
            "corner1_n",
            "corner1_avg_diff",
            "corner1_plus_rate",
            "rest_n",
            "rest_avg_diff",
            "rest_plus_rate",
            "delta_diff",
        ],
    )
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["dd"] = pd.Categorical(table["dd"].astype(str), categories=DD_ORDER, ordered=True)
    table = table.sort_values(["segment", "dd"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["dd"] = table["dd"].astype(str)
    return table


def build_dd_corner1_mwu(work: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for segment in SEGMENT_ORDER:
        frame = _segment_frame(work, segment)
        for dd_value in [4, 7, 14, 17, 24, 27]:
            dd_stats = _dd_stats(frame, dd_value)
            mwu = _mwu_summary(frame, dd_value)
            rows.append(
                {
                    "segment": segment,
                    "dd": dd_value,
                    "corner1_n": int(dd_stats["corner1_n"]),
                    "rest_n": int(dd_stats["rest_n"]),
                    "u_stat": mwu["u_stat"],
                    "p_value": mwu["p_value"],
                    "n": mwu["n"],
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "dd", "corner1_n", "rest_n", "u_stat", "p_value", "n"])
    table["segment"] = pd.Categorical(table["segment"], categories=SEGMENT_ORDER, ordered=True)
    table["dd"] = pd.Categorical(table["dd"].astype(str), categories=DD_ORDER, ordered=True)
    table = table.sort_values(["segment", "dd"], kind="mergesort").reset_index(drop=True)
    table["segment"] = table["segment"].astype(str)
    table["dd"] = table["dd"].astype(str)
    return table


def _latest_source_date(work: pd.DataFrame) -> str:
    source_dates = (
        pd.to_datetime(work.get("date_dt"), errors="coerce")
        if "date_dt" in work.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    latest_date = source_dates.max() if not source_dates.empty else pd.NaT
    return latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else "unknown"


def build_report(artifacts: dict[str, pd.DataFrame | str], *, source_latest_date: str) -> str:
    lines = [
        "# Mitoya Phase 10d: X_DDS rank and corner deep dive",
        "",
        f"- source_latest_date: {source_latest_date}",
        "- min_games_filter: games >= 1000",
        "- xdds_days: 4, 7, 14, 17, 24, 27",
        "- dd_scope: 4, 7, 14, 17, 24, 27 only; DD=30 excluded",
        "- corner1_definition: rank_from_aisle == 1 (raw value, not bucket)",
        "- segment_partition: mixed_805 is 805-815 only; the other four segments exclude section 805-815",
        "",
        "## A. X_DDS fine rank analysis",
        "",
        render_markdown_table(artifacts["xdds_fine_rank"]) if not artifacts["xdds_fine_rank"].empty else "_no rows_",
        "",
        "## B. DD corner1 delta analysis",
        "",
        render_markdown_table(artifacts["dd_corner1_delta"])
        if not artifacts["dd_corner1_delta"].empty
        else "_no rows_",
        "",
        "## C-1. X_DDS fine rank KW test",
        "",
        render_markdown_table(artifacts["xdds_fine_rank_kw"])
        if not artifacts["xdds_fine_rank_kw"].empty
        else "_no rows_",
        "",
        "## C-2. DD corner1 MWU test",
        "",
        render_markdown_table(artifacts["dd_corner1_mwu"]) if not artifacts["dd_corner1_mwu"].empty else "_no rows_",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_all_artifacts(df: pd.DataFrame) -> dict[str, pd.DataFrame | str]:
    work = _prepare_frame(df)
    artifacts: dict[str, pd.DataFrame | str] = {
        "xdds_fine_rank": build_xdds_fine_rank(work),
        "dd_corner1_delta": build_dd_corner1_delta(work),
        "xdds_fine_rank_kw": build_xdds_fine_rank_kw(work),
        "dd_corner1_mwu": build_dd_corner1_mwu(work),
    }
    artifacts["report"] = build_report(artifacts, source_latest_date=_latest_source_date(work))
    return artifacts


def save_outputs(artifacts: dict[str, pd.DataFrame | str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts["xdds_fine_rank"].to_csv(output_dir / "xdds_fine_rank.csv", index=False, encoding="utf-8-sig")
    artifacts["dd_corner1_delta"].to_csv(output_dir / "dd_corner1_delta.csv", index=False, encoding="utf-8-sig")
    artifacts["xdds_fine_rank_kw"].to_csv(output_dir / "xdds_fine_rank_kw.csv", index=False, encoding="utf-8-sig")
    artifacts["dd_corner1_mwu"].to_csv(output_dir / "dd_corner1_mwu.csv", index=False, encoding="utf-8-sig")
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
