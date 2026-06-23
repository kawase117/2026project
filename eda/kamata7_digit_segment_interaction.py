"""
蒲田7 台番号末尾 × セグメント交互作用分析

分析対象:
  - dd_mod10(0-9)
  - 曜日(月-日)
  - segment(A/N)
  - machine_digit(0-9)

出力:
  - eda/reports/kamata7_digit_segment_interaction_report.md
  - eda/reports/kamata7_digit_segment_full_reference.csv
  - eda/reports/kamata7_digit_segment_quickref.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent.parent))
from eda.kamata7_dd_internal_structure import _agg_metrics, _prepare_frame, _table_to_markdown

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


HALL = "蒲田7"
SEGMENT_ORDER = ["A", "N"]
DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]
DD_MOD10_ORDER = list(range(10))
DIGIT_ORDER = [str(i) for i in range(10)]
FOCUS_DOWS = ["水", "土"]

REPORT_PATH = Path(__file__).parent / "reports" / "kamata7_digit_segment_interaction_report.md"
FULL_REFERENCE_CSV = Path(__file__).parent / "reports" / "kamata7_digit_segment_full_reference.csv"
QUICKREF_CSV = Path(__file__).parent / "reports" / "kamata7_digit_segment_quickref.csv"

MIN_SECTION2_N = 50
MIN_SECTION3_N = 30
MIN_SECTION4_N = 20


def _ensure_orders(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["segment"] = pd.Categorical(work["segment"], categories=SEGMENT_ORDER, ordered=True)
    work["day_of_week"] = pd.Categorical(work["day_of_week"], categories=DOW_ORDER, ordered=True)
    work["dd_mod10"] = pd.to_numeric(work["dd_mod10"], errors="coerce").astype("Int64")
    work["dd_mod10"] = pd.Categorical(work["dd_mod10"], categories=DD_MOD10_ORDER, ordered=True)
    work["machine_digit"] = work["machine_digit"].astype(str)
    work["machine_digit"] = pd.Categorical(work["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    return work


def _fmt_dd_mod10(value: object) -> str:
    if pd.isna(value):
        return "NaN"
    return str(int(value))


def _format_tail_row(row: pd.Series) -> str:
    return f"d{int(row['machine_digit'])}({row['avg_diff']:+.0f})"


def _summarize_tail_list(
    stats: pd.DataFrame,
    *,
    group_cols: list[str],
    top_n: int = 3,
    bottom_n: int = 2,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if stats.empty:
        return pd.DataFrame(columns=group_cols + ["top3", "avoid2"])

    for keys, group in stats.groupby(group_cols, observed=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        ranked = group.dropna(subset=["avg_diff"]).sort_values(["avg_diff", "machine_digit"], ascending=[False, True])
        top = ranked.head(top_n)
        bottom = ranked.tail(bottom_n).sort_values(["avg_diff", "machine_digit"], ascending=[True, True])
        row: dict[str, object] = {col: key for col, key in zip(group_cols, keys)}
        row["top3"] = ",".join(top.apply(_format_tail_row, axis=1).tolist()) if not top.empty else ""
        row["avoid2"] = ",".join(bottom.apply(_format_tail_row, axis=1).tolist()) if not bottom.empty else ""
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    if "day_of_week" in out.columns:
        out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
    if "dd_mod10" in out.columns:
        out["dd_mod10"] = pd.Categorical(out["dd_mod10"], categories=DD_MOD10_ORDER, ordered=True)
    if "segment" in out.columns:
        out["segment"] = pd.Categorical(out["segment"], categories=SEGMENT_ORDER, ordered=True)
    return out.sort_values(group_cols).reset_index(drop=True)


def _matrix_from_stats(
    stats: pd.DataFrame,
    *,
    index_col: str,
    columns_col: str,
    value_col: str,
    index_order: list[object],
    columns_order: list[object],
) -> pd.DataFrame:
    if stats.empty:
        return pd.DataFrame(index=index_order, columns=columns_order)
    matrix = stats.pivot(index=index_col, columns=columns_col, values=value_col)
    matrix = matrix.reindex(index=index_order, columns=columns_order)
    return matrix


def _rank_cells(
    stats: pd.DataFrame,
    *,
    rank_group_cols: list[str],
    value_col: str = "avg_diff",
) -> pd.DataFrame:
    work = stats.copy()
    work["rank"] = np.nan
    valid = work[value_col].notna()
    if valid.any():
        work.loc[valid, "rank"] = (
            work.loc[valid]
            .groupby(rank_group_cols, observed=False)[value_col]
            .rank(method="first", ascending=False)
        )
    return work


def _prepare_long_stats(
    df: pd.DataFrame,
    group_cols: list[str],
    *,
    min_n: int,
    rank_group_cols: list[str] | None = None,
) -> pd.DataFrame:
    stats = _agg_metrics(df, group_cols)
    if stats.empty:
        cols = group_cols + ["n", "avg_diff", "plus_rate", "hit104_rate"]
        if rank_group_cols is not None:
            cols.append("rank")
        return pd.DataFrame(columns=cols)

    stats = stats.copy()
    stats.loc[stats["n"] < min_n, ["avg_diff", "plus_rate", "hit104_rate"]] = np.nan

    if rank_group_cols is not None:
        stats = _rank_cells(stats, rank_group_cols=rank_group_cols)

    for col, categories in {
        "segment": SEGMENT_ORDER,
        "day_of_week": DOW_ORDER,
        "dd_mod10": DD_MOD10_ORDER,
        "machine_digit": DIGIT_ORDER,
    }.items():
        if col in stats.columns:
            stats[col] = pd.Categorical(stats[col], categories=categories, ordered=True)

    return stats


def _add_axis_ranks(table: pd.DataFrame, *, group_cols: list[str], value_col: str = "avg_diff") -> pd.DataFrame:
    if table.empty:
        return table.copy()
    work = table.copy()
    work["rank"] = np.nan
    valid = work[value_col].notna()
    if valid.any():
        work.loc[valid, "rank"] = (
            work.loc[valid]
            .groupby(group_cols, observed=False)[value_col]
            .rank(method="first", ascending=False)
        )
    return work


def _spearman_by_group(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (dd_mod10, day_of_week), group in df.groupby(["dd_mod10", "day_of_week"], observed=True):
        pivot = group.pivot(index="machine_digit", columns="segment", values="rank")
        common = pivot.dropna(subset=SEGMENT_ORDER, how="any") if set(SEGMENT_ORDER).issubset(pivot.columns) else pd.DataFrame()
        if common.empty:
            rho = np.nan
            n_shared = 0
        else:
            a = common["A"].astype(float)
            n = common["N"].astype(float)
            n_shared = int(len(common))
            rho = float(spearmanr(a, n).correlation) if n_shared >= 3 else np.nan
        rows.append(
            {
                "dd_mod10": int(dd_mod10),
                "day_of_week": day_of_week,
                "spearman_rho": rho,
                "n_shared_digits": n_shared,
                "low_corr": bool(pd.notna(rho) and rho < 0.5),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["dd_mod10"] = pd.Categorical(out["dd_mod10"], categories=DD_MOD10_ORDER, ordered=True)
    out["day_of_week"] = pd.Categorical(out["day_of_week"], categories=DOW_ORDER, ordered=True)
    return out.sort_values(["dd_mod10", "day_of_week"]).reset_index(drop=True)


def _section(title: str, body_parts: list[str]) -> str:
    return f"## {title}\n\n" + "\n\n".join(body_parts).rstrip() + "\n"


def _matrix_block(title: str, matrix: pd.DataFrame) -> list[str]:
    return [f"**{title}**", _table_to_markdown(matrix.reset_index().rename(columns={"index": "dd_mod10"}))]


def main() -> None:
    df = _ensure_orders(_prepare_frame())
    df = df.copy()
    df["dd_mod10"] = pd.to_numeric(df["dd_mod10"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["dd_mod10", "segment", "day_of_week", "machine_digit"]).copy()
    df["dd_mod10"] = df["dd_mod10"].astype(int)
    df["machine_digit"] = df["machine_digit"].astype(str)

    print(
        f"rows={len(df):,}, days={df['date'].nunique()}, "
        f"date_range={df['date'].min()}..{df['date'].max()}"
    )
    print(f"segment counts: {df['segment'].value_counts(dropna=False).to_dict()}")

    report_parts: list[str] = []
    report_parts.append("# 蒲田7 台番号末尾 × セグメント 交互作用分析\n")
    report_parts.append(
        "- 対象: 蒲田7\n"
        f"- 軸: dd_mod10(0-9), 曜日(月-日), segment(A/N), machine_digit(0-9)\n"
        f"- しきい値: Section 2 は n < {MIN_SECTION2_N}, Section 3 は n < {MIN_SECTION3_N}, Section 4 は n < {MIN_SECTION4_N}\n"
        "- 7/7 は _prepare_frame() 側で除外済み\n"
    )

    # Section 1
    seg_tail_stats = _prepare_long_stats(
        df,
        ["segment", "machine_digit"],
        min_n=1,
        rank_group_cols=["segment"],
    )
    seg_tail_stats = seg_tail_stats.sort_values(["segment", "rank", "machine_digit"]).reset_index(drop=True)
    seg_rank_matrix = _matrix_from_stats(
        seg_tail_stats,
        index_col="segment",
        columns_col="machine_digit",
        value_col="rank",
        index_order=SEGMENT_ORDER,
        columns_order=DIGIT_ORDER,
    )
    seg_rank_matrix.index.name = "segment"
    seg_tail_pivot = _matrix_from_stats(
        seg_tail_stats,
        index_col="segment",
        columns_col="machine_digit",
        value_col="avg_diff",
        index_order=SEGMENT_ORDER,
        columns_order=DIGIT_ORDER,
    )
    seg_tail_long = seg_tail_stats[["segment", "machine_digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]].copy()
    seg_tail_long["rank"] = seg_tail_long["rank"].round(0)
    seg_rho_pivot = seg_tail_stats.pivot(index="machine_digit", columns="segment", values="rank").reindex(columns=SEGMENT_ORDER)
    seg_rho_common = seg_rho_pivot.dropna(subset=SEGMENT_ORDER, how="any")
    seg_rho = (
        float(spearmanr(seg_rho_common["A"].astype(float), seg_rho_common["N"].astype(float)).correlation)
        if len(seg_rho_common) >= 3
        else np.nan
    )
    section1 = [
        "**segment別末尾ベースライン(avg_diff)**",
        _table_to_markdown(seg_tail_long),
        "",
        "**segment別 avg_diff matrix**",
        _table_to_markdown(seg_tail_pivot.reset_index()),
        "",
        "**segment別 rank matrix**",
        _table_to_markdown(seg_rank_matrix.reset_index()),
        "",
        f"Spearman rho(A vs N) = {seg_rho:.3f}" if pd.notna(seg_rho) else "Spearman rho(A vs N) = NaN",
    ]
    report_parts.append(_section("Section 1: セグメント別 末尾ベースライン", section1))

    # Section 2
    sec2_stats = _prepare_long_stats(
        df,
        ["dd_mod10", "segment", "machine_digit"],
        min_n=MIN_SECTION2_N,
        rank_group_cols=["dd_mod10", "segment"],
    )
    sec2_stats = sec2_stats.sort_values(["segment", "dd_mod10", "rank", "machine_digit"]).reset_index(drop=True)
    section2_parts: list[str] = []
    for segment in SEGMENT_ORDER:
        seg_stats = sec2_stats[sec2_stats["segment"] == segment].copy()
        avg_matrix = _matrix_from_stats(
            seg_stats,
            index_col="dd_mod10",
            columns_col="machine_digit",
            value_col="avg_diff",
            index_order=DD_MOD10_ORDER,
            columns_order=DIGIT_ORDER,
        )
        rank_matrix = _matrix_from_stats(
            seg_stats,
            index_col="dd_mod10",
            columns_col="machine_digit",
            value_col="rank",
            index_order=DD_MOD10_ORDER,
            columns_order=DIGIT_ORDER,
        )
        section2_parts.extend(
            [
                f"### segment {segment}",
                "**avg_diff matrix**",
                _table_to_markdown(avg_matrix.reset_index().rename(columns={"index": "dd_mod10"})),
                "",
                "**rank matrix**",
                _table_to_markdown(rank_matrix.reset_index().rename(columns={"index": "dd_mod10"})),
                "",
            ]
        )
    section2_parts.append("**cell detail**")
    section2_parts.append(
        _table_to_markdown(
            sec2_stats[["dd_mod10", "segment", "machine_digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]]
        )
    )
    report_parts.append(_section("Section 2: dd_mod10 × 末尾 × セグメント マトリクス", section2_parts))

    # Section 3
    section3_parts: list[str] = []
    for dow in FOCUS_DOWS:
        sub = df[df["day_of_week"] == dow].copy()
        stats = _prepare_long_stats(
            sub,
            ["dd_mod10", "segment", "machine_digit"],
            min_n=MIN_SECTION3_N,
            rank_group_cols=["dd_mod10", "segment"],
        )
        section3_parts.extend([f"### {dow}曜"])
        for segment in SEGMENT_ORDER:
            seg_stats = stats[stats["segment"] == segment].copy()
            avg_matrix = _matrix_from_stats(
                seg_stats,
                index_col="dd_mod10",
                columns_col="machine_digit",
                value_col="avg_diff",
                index_order=DD_MOD10_ORDER,
                columns_order=DIGIT_ORDER,
            )
            section3_parts.extend(
                [
                    f"#### segment {segment}",
                    _table_to_markdown(avg_matrix.reset_index().rename(columns={"index": "dd_mod10"})),
                    "",
                ]
            )
    report_parts.append(_section("Section 3: 曜日 × 末尾 × セグメント マトリクス（水曜・土曜限定）", section3_parts))

    # Section 4
    sec4_stats = _prepare_long_stats(
        df,
        ["dd_mod10", "day_of_week", "segment", "machine_digit"],
        min_n=MIN_SECTION4_N,
        rank_group_cols=["dd_mod10", "day_of_week", "segment"],
    )
    sec4_stats = sec4_stats.sort_values(["dd_mod10", "day_of_week", "segment", "rank", "machine_digit"]).reset_index(drop=True)
    sec4_output = sec4_stats[["dd_mod10", "day_of_week", "segment", "machine_digit", "n", "avg_diff", "plus_rate", "hit104_rate", "rank"]].copy()
    sec4_output.to_csv(FULL_REFERENCE_CSV, index=False, encoding="utf-8-sig")
    section4_parts = [
        f"CSV saved: `{FULL_REFERENCE_CSV.name}`",
        "**top 20 cells by avg_diff**",
        _table_to_markdown(sec4_output.sort_values("avg_diff", ascending=False).head(20)),
        "",
        "**bottom 20 cells by avg_diff**",
        _table_to_markdown(sec4_output.sort_values("avg_diff", ascending=True).head(20)),
    ]
    report_parts.append(_section("Section 4: dd_mod10 × 曜日 × セグメント × 末尾 完全テーブル", section4_parts))

    # Section 5
    quickref = _summarize_tail_list(
        sec4_stats[sec4_stats["day_of_week"].isin(FOCUS_DOWS)].copy(),
        group_cols=["day_of_week", "dd_mod10", "segment"],
    )
    quickref_output = quickref[["day_of_week", "dd_mod10", "segment", "top3", "avoid2"]].copy() if not quickref.empty else quickref
    if not quickref_output.empty:
        quickref_output = quickref_output.sort_values(["day_of_week", "dd_mod10", "segment"]).reset_index(drop=True)
    quickref_output.to_csv(QUICKREF_CSV, index=False, encoding="utf-8-sig")
    section5_parts = [
        f"CSV saved: `{QUICKREF_CSV.name}`",
        _table_to_markdown(
            quickref_output[["day_of_week", "dd_mod10", "segment", "top3", "avoid2"]]
            if not quickref_output.empty
            else pd.DataFrame(columns=["day_of_week", "dd_mod10", "segment", "top3", "avoid2"])
        ),
    ]
    report_parts.append(_section("Section 5: 実戦用早見表（水曜・土曜 × セグメント別）", section5_parts))

    # Section 6
    sec6_stats = _prepare_long_stats(
        df,
        ["dd_mod10", "day_of_week", "segment", "machine_digit"],
        min_n=MIN_SECTION4_N,
        rank_group_cols=["dd_mod10", "day_of_week", "segment"],
    )
    sec6_stats = _add_axis_ranks(sec6_stats, group_cols=["dd_mod10", "day_of_week", "segment"], value_col="avg_diff")
    spearman_df = _spearman_by_group(sec6_stats)
    low_corr = spearman_df[spearman_df["low_corr"]].copy()
    section6_parts = [
        "**Spearman correlation matrix (dd_mod10 × 曜日)**",
        _table_to_markdown(
            spearman_df.pivot(index="dd_mod10", columns="day_of_week", values="spearman_rho").reset_index()
        ),
        "",
        "**low correlation cases (rho < 0.5)**",
        _table_to_markdown(low_corr),
    ]
    report_parts.append(_section("Section 6: セグメント間の末尾ランキング相関", section6_parts))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report_text = "\n".join(report_parts).rstrip() + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(f"[OK] report saved: {REPORT_PATH}")
    print(f"[OK] csv saved: {FULL_REFERENCE_CSV}")
    print(f"[OK] csv saved: {QUICKREF_CSV}")


if __name__ == "__main__":
    main()
