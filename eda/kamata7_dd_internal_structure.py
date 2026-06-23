"""
蒲田7 DD x 内部構造 交互作用分析

全DD(1-31)について、以下の3軸を一括分析する。
1. segment: A / N
2. kakuban_rank: 角1 / 角2 / 中間 / 角N-1 / 角N
3. machine_digit: 0-9

出力:
  - stdout: セクション別の集計表
  - eda/reports/kamata7_dd_internal_structure_report.md
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from eda.core import HALL_EVENT_DIGITS, load_hall_df

HALL = "蒲田7"
ANNIVERSARY_MMDD = "0707"
EVENT_DDS = set(HALL_EVENT_DIGITS[HALL])
DD_ORDER = list(range(1, 32))
SEGMENT_ORDER = ["A", "N"]
KAKUBAN_ORDER = ["角1", "角2", "中間", "角N-1", "角N"]
DIGIT_ORDER = [str(i) for i in range(10)]
REQUIRED_MIN_N = 200

REPORT_PATH = Path(__file__).parent / "reports" / "kamata7_dd_internal_structure_report.md"
DB_PATH = Path(__file__).parent.parent / "db" / "マルハンメガシティ2000-蒲田7.db"
COORD_PATHS = [
    Path(__file__).parent.parent / "Heatmap" / "2F_floor_coordinates_kamata7.csv",
    Path(__file__).parent.parent / "Heatmap" / "3F_floor_coordinates_kamata7.csv",
]


def _normalize_machine_name(machine_name: str) -> str:
    if machine_name is None:
        return ""
    name = str(machine_name).strip()
    if name.startswith("L") and not name.startswith("LB"):
        return name[1:]
    return name


def _calc_payout_rate(df: pd.DataFrame) -> pd.Series:
    games = pd.to_numeric(df["games"], errors="coerce")
    diff = pd.to_numeric(df["diff"], errors="coerce")
    return np.where(games > 0, (1 + diff / (games * 3)) * 100, np.nan)


def _read_coords(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = pd.read_csv(path)
        frames.append(frame)
    coords = pd.concat(frames, ignore_index=True)
    for col in ["machine_number", "rank_from_min", "rank_from_max"]:
        coords[col] = pd.to_numeric(coords[col], errors="coerce")
    coords = coords.dropna(subset=["machine_number"]).copy()
    coords["machine_number"] = coords["machine_number"].astype(int)
    coords["kakuban_rank"] = coords.apply(_classify_kakuban_rank, axis=1)
    return coords[["machine_number", "kakuban_rank"]].drop_duplicates("machine_number", keep="first")


def _classify_kakuban_rank(row: pd.Series) -> str:
    rank_from_min = pd.to_numeric(row.get("rank_from_min"), errors="coerce")
    rank_from_max = pd.to_numeric(row.get("rank_from_max"), errors="coerce")
    if pd.notna(rank_from_min):
        rank_from_min = int(rank_from_min)
        if rank_from_min == 1:
            return "角1"
        if rank_from_min == 2:
            return "角2"
    if pd.notna(rank_from_max):
        rank_from_max = int(rank_from_max)
        if rank_from_max == 1:
            return "角N"
        if rank_from_max == 2:
            return "角N-1"
    return "中間"


def _load_segment_map(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        master = pd.read_sql_query(
            "SELECT machine_name_normalized, jug_flag, hana_flag FROM machine_master",
            conn,
        )
    finally:
        conn.close()

    for col in ["jug_flag", "hana_flag"]:
        master[col] = pd.to_numeric(master[col], errors="coerce").fillna(0).astype(int)

    master["machine_name_key"] = master["machine_name_normalized"].map(_normalize_machine_name)
    master = master.drop_duplicates(subset=["machine_name_key"], keep="first").copy()
    master["segment"] = np.where((master["jug_flag"] == 1) | (master["hana_flag"] == 1), "A", "N")
    return master[["machine_name_key", "segment"]]


def _prepare_frame() -> pd.DataFrame:
    df = load_hall_df(HALL).copy()
    df["payout_rate"] = _calc_payout_rate(df)
    df["hit104"] = (df["payout_rate"] >= 104.0).astype(int)

    mmdd = df["date"].astype(str).str[4:8]
    before = len(df)
    df = df[mmdd != ANNIVERSARY_MMDD].copy()
    after = len(df)

    seg_map = _load_segment_map(DB_PATH)
    df["machine_name_key"] = df["machine_name"].map(_normalize_machine_name)
    df = df.merge(seg_map, on="machine_name_key", how="left")

    coords = _read_coords(COORD_PATHS)
    df = df.merge(coords, on="machine_number", how="left")
    df["kakuban_rank"] = df["kakuban_rank"].fillna("不明")

    df["machine_digit"] = pd.to_numeric(df["machine_digit"], errors="coerce").astype("Int64")
    df["machine_digit"] = df["machine_digit"].astype("string")

    print(f"7/7除外: {before - after:,} rows. 残り: {after:,} rows, {df['date'].nunique()} days")
    print(f"segment欠損: {(df['segment'].isna()).sum():,} rows")
    print(f"kakuban欠損: {(df['kakuban_rank'].eq('不明')).sum():,} rows")
    df = df.dropna(subset=["segment"]).copy()
    df = df[df["kakuban_rank"].ne("不明")].copy()

    df["segment"] = pd.Categorical(df["segment"], categories=SEGMENT_ORDER, ordered=True)
    df["kakuban_rank"] = pd.Categorical(df["kakuban_rank"], categories=KAKUBAN_ORDER, ordered=True)
    df["machine_digit"] = pd.Categorical(df["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    return df


def _agg_metrics(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        cols = group_cols + ["n", "avg_diff", "plus_rate", "hit104_rate"]
        return pd.DataFrame(columns=cols)
    agg = (
        df.groupby(group_cols, observed=False)
        .agg(
            n=("diff", "count"),
            avg_diff=("diff", "mean"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    agg["avg_diff"] = agg["avg_diff"].round(0)
    agg["plus_rate"] = (agg["plus_rate"] * 100).round(1)
    agg["hit104_rate"] = (agg["hit104_rate"] * 100).round(1)
    return agg


def _baseline_table(df: pd.DataFrame, group_col: str, order: list[str]) -> pd.DataFrame:
    stats = _agg_metrics(df, [group_col])
    stats[group_col] = pd.Categorical(stats[group_col], categories=order, ordered=True)
    return stats.sort_values(group_col).reset_index(drop=True)


def _format_number(value: object, digits: int = 1) -> str:
    if value is None:
        return "NaN"
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return "NaN"
    if isinstance(value, (int, np.integer)):
        return f"{int(value)}"
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _table_to_markdown(df: pd.DataFrame, float_digits: int = 1) -> str:
    if df.empty:
        return "_no rows_"
    work = df.copy()
    lines = []
    cols = list(work.columns)
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for _, row in work.iterrows():
        cells = []
        for col in cols:
            val = row[col]
            if isinstance(val, (float, np.floating)):
                if float(val).is_integer():
                    cells.append(str(int(round(float(val)))))
                else:
                    cells.append(_format_number(val, float_digits))
            elif isinstance(val, (int, np.integer)):
                cells.append(_format_number(val))
            elif pd.isna(val):
                cells.append("NaN")
            else:
                cells.append(str(val))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _print_table(title: str, df: pd.DataFrame) -> None:
    print(f"\n{title}")
    if df.empty:
        print("  (no rows)")
    else:
        print(df.to_string(index=False))


def _cell_matrix(
    df: pd.DataFrame,
    category_col: str,
    category_order: list[str],
    metric: str,
    min_n: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stats = _agg_metrics(df, ["dd", category_col])
    categories = pd.Categorical(stats[category_col], categories=category_order, ordered=True)
    stats[category_col] = categories
    baseline = _agg_metrics(df, [category_col]).set_index(category_col)
    baseline = baseline.reindex(category_order)

    stats["avg_diff_dev"] = stats.apply(
        lambda r: r["avg_diff"] - baseline.loc[r[category_col], "avg_diff"]
        if pd.notna(baseline.loc[r[category_col], "avg_diff"]) else np.nan,
        axis=1,
    )
    stats["plus_rate_dev"] = stats.apply(
        lambda r: r["plus_rate"] - baseline.loc[r[category_col], "plus_rate"]
        if pd.notna(baseline.loc[r[category_col], "plus_rate"]) else np.nan,
        axis=1,
    )
    stats["hit104_rate_dev"] = stats.apply(
        lambda r: r["hit104_rate"] - baseline.loc[r[category_col], "hit104_rate"]
        if pd.notna(baseline.loc[r[category_col], "hit104_rate"]) else np.nan,
        axis=1,
    )
    stats.loc[stats["n"] < min_n, ["avg_diff", "plus_rate", "hit104_rate", "avg_diff_dev", "plus_rate_dev", "hit104_rate_dev"]] = np.nan

    value_pivot = stats.pivot(index="dd", columns=category_col, values=metric).reindex(index=DD_ORDER, columns=category_order)
    dev_pivot = stats.pivot(index="dd", columns=category_col, values=f"{metric}_dev").reindex(index=DD_ORDER, columns=category_order)
    return value_pivot, dev_pivot


def _collect_cells(
    df: pd.DataFrame,
    category_col: str,
    category_order: list[str],
    metric: str = "avg_diff_dev",
    min_n: int = REQUIRED_MIN_N,
) -> pd.DataFrame:
    stats = _agg_metrics(df, ["dd", category_col])
    baseline = _agg_metrics(df, [category_col]).set_index(category_col)
    baseline = baseline.reindex(category_order)

    stats["avg_diff_dev"] = stats.apply(
        lambda r: r["avg_diff"] - baseline.loc[r[category_col], "avg_diff"]
        if pd.notna(baseline.loc[r[category_col], "avg_diff"]) else np.nan,
        axis=1,
    )
    stats["plus_rate_dev"] = stats.apply(
        lambda r: r["plus_rate"] - baseline.loc[r[category_col], "plus_rate"]
        if pd.notna(baseline.loc[r[category_col], "plus_rate"]) else np.nan,
        axis=1,
    )
    stats["hit104_rate_dev"] = stats.apply(
        lambda r: r["hit104_rate"] - baseline.loc[r[category_col], "hit104_rate"]
        if pd.notna(baseline.loc[r[category_col], "hit104_rate"]) else np.nan,
        axis=1,
    )
    stats = stats[stats["n"] >= min_n].copy()
    stats["abs_dev"] = stats[metric].abs()
    stats[category_col] = pd.Categorical(stats[category_col], categories=category_order, ordered=True)
    return stats.sort_values(metric, ascending=False).reset_index(drop=True)


def _event_summary(df: pd.DataFrame, category_col: str, category_order: list[str]) -> pd.DataFrame:
    work = df.copy()
    work["event_type"] = np.where(work["dd"].isin(EVENT_DDS), "event", "non_event")
    stats = (
        work.groupby(["event_type", category_col], observed=False)
        .agg(
            n=("diff", "count"),
            avg_diff=("diff", "mean"),
            plus_rate=("plus", "mean"),
            hit104_rate=("hit104", "mean"),
        )
        .reset_index()
    )
    stats["avg_diff"] = stats["avg_diff"].round(0)
    stats["plus_rate"] = (stats["plus_rate"] * 100).round(1)
    stats["hit104_rate"] = (stats["hit104_rate"] * 100).round(1)
    stats[category_col] = pd.Categorical(stats[category_col], categories=category_order, ordered=True)
    pivot = stats.pivot(index=category_col, columns="event_type")
    pivot = pivot.reindex(category_order)
    rows = []
    for cat in category_order:
        if cat not in pivot.index:
            continue
        row = {
            category_col: cat,
            "event_n": pivot.loc[cat, ("n", "event")] if ("n", "event") in pivot.columns else np.nan,
            "non_event_n": pivot.loc[cat, ("n", "non_event")] if ("n", "non_event") in pivot.columns else np.nan,
            "event_avg_diff": pivot.loc[cat, ("avg_diff", "event")] if ("avg_diff", "event") in pivot.columns else np.nan,
            "non_event_avg_diff": pivot.loc[cat, ("avg_diff", "non_event")] if ("avg_diff", "non_event") in pivot.columns else np.nan,
            "event_plus_rate": pivot.loc[cat, ("plus_rate", "event")] if ("plus_rate", "event") in pivot.columns else np.nan,
            "non_event_plus_rate": pivot.loc[cat, ("plus_rate", "non_event")] if ("plus_rate", "non_event") in pivot.columns else np.nan,
            "event_hit104_rate": pivot.loc[cat, ("hit104_rate", "event")] if ("hit104_rate", "event") in pivot.columns else np.nan,
            "non_event_hit104_rate": pivot.loc[cat, ("hit104_rate", "non_event")] if ("hit104_rate", "non_event") in pivot.columns else np.nan,
        }
        row["diff_avg_diff"] = row["event_avg_diff"] - row["non_event_avg_diff"]
        row["diff_plus_rate"] = row["event_plus_rate"] - row["non_event_plus_rate"]
        row["diff_hit104_rate"] = row["event_hit104_rate"] - row["non_event_hit104_rate"]
        rows.append(row)
    return pd.DataFrame(rows)


def _summarize_cell_table(stats: pd.DataFrame, label_col: str) -> pd.DataFrame:
    if stats.empty:
        return stats
    cols = [label_col, "dd", "n", "avg_diff", "plus_rate", "hit104_rate", "avg_diff_dev", "plus_rate_dev", "hit104_rate_dev"]
    out = stats[cols].copy()
    out["dd"] = out["dd"].apply(lambda x: f"DD{int(x):02d}")
    out["avg_diff"] = out["avg_diff"].round(0)
    out["avg_diff_dev"] = out["avg_diff_dev"].round(0)
    return out


def _print_matrix(title: str, matrix: pd.DataFrame) -> None:
    print(f"\n{title}")
    if matrix.empty:
        print("  (no rows)")
    else:
        print(matrix.to_string())


def _markdown_section(title: str, body: str) -> str:
    return f"## {title}\n\n{body}\n"


def _emit_section(title: str, body_lines: list[str]) -> None:
    print(f"\n{'=' * 88}")
    print(title)
    print(f"{'=' * 88}")
    for line in body_lines:
        print(line)


def main() -> None:
    df = _prepare_frame()
    df["plus"] = (df["diff"] > 0).astype(int)

    baseline_all = pd.DataFrame(
        [{
            "n": len(df),
            "avg_diff": round(df["diff"].mean(), 0),
            "plus_rate": round((df["plus"].mean() * 100), 1),
            "hit104_rate": round((df["hit104"].mean() * 100), 1),
        }]
    )
    baseline_all["n"] = baseline_all["n"].astype(int)

    report_parts: list[str] = []
    report_parts.append(f"# 蒲田7 DD x 内部構造 交互作用分析\n")
    report_parts.append(
        f"- 対象: {HALL}\n- 除外: 0707\n- しきい値: n < {REQUIRED_MIN_N} は NaN 扱い\n- イベントDD: {sorted(EVENT_DDS)}\n"
    )

    _emit_section(
        "Section 1: 全体ベースライン",
        [
            f"rows={len(df):,}, days={df['date'].nunique()}, date_range={df['date'].min()}..{df['date'].max()}",
            "",
            "全体 baseline:",
            baseline_all.to_string(index=False),
            "",
            "segment baseline:",
            _baseline_table(df, "segment", SEGMENT_ORDER).to_string(index=False),
            "",
            "kakuban baseline:",
            _baseline_table(df, "kakuban_rank", KAKUBAN_ORDER).to_string(index=False),
            "",
            "machine_digit baseline:",
            _baseline_table(df, "machine_digit", DIGIT_ORDER).to_string(index=False),
        ],
    )
    report_parts.append(_markdown_section("Section 1: 全体ベースライン", "\n\n".join([
        "**全体 baseline**",
        _table_to_markdown(baseline_all),
        "",
        "**segment baseline**",
        _table_to_markdown(_baseline_table(df, "segment", SEGMENT_ORDER)),
        "",
        "**kakuban baseline**",
        _table_to_markdown(_baseline_table(df, "kakuban_rank", KAKUBAN_ORDER)),
        "",
        "**machine_digit baseline**",
        _table_to_markdown(_baseline_table(df, "machine_digit", DIGIT_ORDER)),
    ])))

    # Section 2: segment
    seg_stats = _agg_metrics(df, ["dd", "segment"])
    seg_stats["segment"] = pd.Categorical(seg_stats["segment"], categories=SEGMENT_ORDER, ordered=True)
    seg_baseline = _baseline_table(df, "segment", SEGMENT_ORDER).set_index("segment")
    seg_stats["avg_diff_dev"] = seg_stats.apply(lambda r: r["avg_diff"] - seg_baseline.loc[r["segment"], "avg_diff"], axis=1)
    seg_stats["plus_rate_dev"] = seg_stats.apply(lambda r: r["plus_rate"] - seg_baseline.loc[r["segment"], "plus_rate"], axis=1)
    seg_stats["hit104_rate_dev"] = seg_stats.apply(lambda r: r["hit104_rate"] - seg_baseline.loc[r["segment"], "hit104_rate"], axis=1)
    seg_stats = seg_stats[seg_stats["n"] >= REQUIRED_MIN_N].copy()
    seg_value = seg_stats.pivot(index="dd", columns="segment", values="avg_diff").reindex(index=DD_ORDER, columns=SEGMENT_ORDER)
    seg_dev = seg_stats.pivot(index="dd", columns="segment", values="avg_diff_dev").reindex(index=DD_ORDER, columns=SEGMENT_ORDER)
    seg_plus_dev = seg_stats.pivot(index="dd", columns="segment", values="plus_rate_dev").reindex(index=DD_ORDER, columns=SEGMENT_ORDER)
    seg_hit_dev = seg_stats.pivot(index="dd", columns="segment", values="hit104_rate_dev").reindex(index=DD_ORDER, columns=SEGMENT_ORDER)
    seg_value.index = [f"DD{dd:02d}{'*' if dd in EVENT_DDS else ''}" for dd in seg_value.index]
    seg_dev.index = seg_value.index
    seg_plus_dev.index = seg_value.index
    seg_hit_dev.index = seg_value.index
    _emit_section(
        "Section 2: DD別 × セグメント(A/N)",
        [
            "avg_diff:",
            seg_value.round(0).to_string(),
            "",
            "baseline deviation (avg_diff):",
            seg_dev.round(0).to_string(),
            "",
            "baseline deviation (plus_rate pp):",
            seg_plus_dev.round(1).to_string(),
            "",
            "baseline deviation (hit104_rate pp):",
            seg_hit_dev.round(1).to_string(),
        ],
    )
    report_parts.append(_markdown_section(
        "Section 2: DD別 × セグメント(A/N)",
        "\n\n".join([
            "**avg_diff**",
            _table_to_markdown(seg_value.reset_index().rename(columns={"index": "dd"})),
            "",
            "**avg_diff deviation**",
            _table_to_markdown(seg_dev.reset_index().rename(columns={"index": "dd"})),
            "",
            "**plus_rate deviation (pp)**",
            _table_to_markdown(seg_plus_dev.reset_index().rename(columns={"index": "dd"})),
            "",
            "**hit104_rate deviation (pp)**",
            _table_to_markdown(seg_hit_dev.reset_index().rename(columns={"index": "dd"})),
        ]),
    ))

    # Section 3: kakuban
    kak_stats = _agg_metrics(df, ["dd", "kakuban_rank"])
    kak_stats["kakuban_rank"] = pd.Categorical(kak_stats["kakuban_rank"], categories=KAKUBAN_ORDER, ordered=True)
    kak_baseline = _baseline_table(df, "kakuban_rank", KAKUBAN_ORDER).set_index("kakuban_rank")
    kak_stats["avg_diff_dev"] = kak_stats.apply(lambda r: r["avg_diff"] - kak_baseline.loc[r["kakuban_rank"], "avg_diff"], axis=1)
    kak_stats["plus_rate_dev"] = kak_stats.apply(lambda r: r["plus_rate"] - kak_baseline.loc[r["kakuban_rank"], "plus_rate"], axis=1)
    kak_stats["hit104_rate_dev"] = kak_stats.apply(lambda r: r["hit104_rate"] - kak_baseline.loc[r["kakuban_rank"], "hit104_rate"], axis=1)
    kak_stats = kak_stats[kak_stats["n"] >= REQUIRED_MIN_N].copy()
    kak_value = kak_stats.pivot(index="dd", columns="kakuban_rank", values="avg_diff").reindex(index=DD_ORDER, columns=KAKUBAN_ORDER)
    kak_dev = kak_stats.pivot(index="dd", columns="kakuban_rank", values="avg_diff_dev").reindex(index=DD_ORDER, columns=KAKUBAN_ORDER)
    kak_plus_dev = kak_stats.pivot(index="dd", columns="kakuban_rank", values="plus_rate_dev").reindex(index=DD_ORDER, columns=KAKUBAN_ORDER)
    kak_hit_dev = kak_stats.pivot(index="dd", columns="kakuban_rank", values="hit104_rate_dev").reindex(index=DD_ORDER, columns=KAKUBAN_ORDER)
    kak_value.index = [f"DD{dd:02d}{'*' if dd in EVENT_DDS else ''}" for dd in kak_value.index]
    kak_dev.index = kak_value.index
    kak_plus_dev.index = kak_value.index
    kak_hit_dev.index = kak_value.index
    _emit_section(
        "Section 3: DD別 × 角番ポジション",
        [
            "avg_diff:",
            kak_value.round(0).to_string(),
            "",
            "baseline deviation (avg_diff):",
            kak_dev.round(0).to_string(),
            "",
            "baseline deviation (plus_rate pp):",
            kak_plus_dev.round(1).to_string(),
            "",
            "baseline deviation (hit104_rate pp):",
            kak_hit_dev.round(1).to_string(),
        ],
    )
    report_parts.append(_markdown_section(
        "Section 3: DD別 × 角番ポジション",
        "\n\n".join([
            "**avg_diff**",
            _table_to_markdown(kak_value.reset_index().rename(columns={"index": "dd"})),
            "",
            "**avg_diff deviation**",
            _table_to_markdown(kak_dev.reset_index().rename(columns={"index": "dd"})),
            "",
            "**plus_rate deviation (pp)**",
            _table_to_markdown(kak_plus_dev.reset_index().rename(columns={"index": "dd"})),
            "",
            "**hit104_rate deviation (pp)**",
            _table_to_markdown(kak_hit_dev.reset_index().rename(columns={"index": "dd"})),
        ]),
    ))

    # Section 4: tail
    tail_stats = _agg_metrics(df, ["dd", "machine_digit"])
    tail_stats["machine_digit"] = pd.Categorical(tail_stats["machine_digit"], categories=DIGIT_ORDER, ordered=True)
    tail_baseline = _baseline_table(df, "machine_digit", DIGIT_ORDER).set_index("machine_digit")
    tail_stats["avg_diff_dev"] = tail_stats.apply(lambda r: r["avg_diff"] - tail_baseline.loc[r["machine_digit"], "avg_diff"], axis=1)
    tail_stats = tail_stats[tail_stats["n"] >= REQUIRED_MIN_N].copy()
    tail_value = tail_stats.pivot(index="dd", columns="machine_digit", values="avg_diff").reindex(index=DD_ORDER, columns=DIGIT_ORDER)
    tail_dev = tail_stats.pivot(index="dd", columns="machine_digit", values="avg_diff_dev").reindex(index=DD_ORDER, columns=DIGIT_ORDER)
    tail_value.index = [f"DD{dd:02d}{'*' if dd in EVENT_DDS else ''}" for dd in tail_value.index]
    tail_dev.index = tail_value.index
    _emit_section(
        "Section 4: DD別 × 台番号末尾",
        [
            "avg_diff:",
            tail_value.round(0).to_string(),
            "",
            "baseline deviation (avg_diff):",
            tail_dev.round(0).to_string(),
        ],
    )
    report_parts.append(_markdown_section(
        "Section 4: DD別 × 台番号末尾",
        "\n\n".join([
            "**avg_diff**",
            _table_to_markdown(tail_value.reset_index().rename(columns={"index": "dd"})),
            "",
            "**avg_diff deviation**",
            _table_to_markdown(tail_dev.reset_index().rename(columns={"index": "dd"})),
        ]),
    ))

    # Section 5: Top / Bottom 20
    top_seg = _collect_cells(df, "segment", SEGMENT_ORDER)
    top_kak = _collect_cells(df, "kakuban_rank", KAKUBAN_ORDER)
    top_tail = _collect_cells(df, "machine_digit", DIGIT_ORDER)
    top_seg["axis"] = "segment"
    top_kak["axis"] = "kakuban"
    top_tail["axis"] = "machine_digit"
    top_seg = top_seg.rename(columns={"segment": "category"})
    top_kak = top_kak.rename(columns={"kakuban_rank": "category"})
    top_tail = top_tail.rename(columns={"machine_digit": "category"})
    all_cells = pd.concat([top_seg, top_kak, top_tail], ignore_index=True)
    all_cells["dd"] = all_cells["dd"].apply(lambda x: f"DD{int(x):02d}")
    all_cells = all_cells[["axis", "dd", "category", "n", "avg_diff", "plus_rate", "hit104_rate", "avg_diff_dev", "plus_rate_dev", "hit104_rate_dev"]].copy()
    top20 = all_cells.sort_values("avg_diff_dev", ascending=False).head(20)
    bottom20 = all_cells.sort_values("avg_diff_dev", ascending=True).head(20)
    _emit_section(
        "Section 5: Top20 / Bottom20 セル",
        [
            "Top20 (n>=200, avg_diff_dev DESC):",
            top20.to_string(index=False),
            "",
            "Bottom20 (n>=200, avg_diff_dev ASC):",
            bottom20.to_string(index=False),
        ],
    )
    report_parts.append(_markdown_section(
        "Section 5: Top20 / Bottom20 セル",
        "\n\n".join([
            "**Top20**",
            _table_to_markdown(top20),
            "",
            "**Bottom20**",
            _table_to_markdown(bottom20),
        ]),
    ))

    # Section 6: event-only summary
    evt_seg = _event_summary(df, "segment", SEGMENT_ORDER)
    evt_kak = _event_summary(df, "kakuban_rank", KAKUBAN_ORDER)
    evt_tail = _event_summary(df, "machine_digit", DIGIT_ORDER)
    _emit_section(
        "Section 6: イベントDD限定の内部構造サマリ",
        [
            "segment:",
            evt_seg.to_string(index=False),
            "",
            "kakuban:",
            evt_kak.to_string(index=False),
            "",
            "machine_digit:",
            evt_tail.to_string(index=False),
        ],
    )
    report_parts.append(_markdown_section(
        "Section 6: イベントDD限定の内部構造サマリ",
        "\n\n".join([
            "**segment**",
            _table_to_markdown(evt_seg),
            "",
            "**kakuban**",
            _table_to_markdown(evt_kak),
            "",
            "**machine_digit**",
            _table_to_markdown(evt_tail),
        ]),
    ))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report_text = "\n".join(report_parts).rstrip() + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(f"\n[OK] report saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
