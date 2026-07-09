from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from pandas.api.types import CategoricalDtype
from scipy.stats import kruskal, spearmanr

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eda.core import HALL_DBS, _epsilon_squared, compute_debut_features, load_hall_df
from ml.analysis.kamata_corner_mirror_analysis import _read_machine_master_flags

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "eda" / "results" / "kamata7_debut_deep"
REPORT_PATH = RESULTS_DIR / "kamata7_debut_deep_report.md"
KRUSKAL_PATH = RESULTS_DIR / "kruskal_wallis_results.csv"

HALL = "蒲田7"
DB_PATH = PROJECT_ROOT / "db" / HALL_DBS[HALL]
COORD_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORD_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"

DEBUT_PHASE_LABELS = ["1-14日", "15-60日", "61-180日", "181日+"]
DEBUT_PHASE_ORDER = CategoricalDtype(DEBUT_PHASE_LABELS, ordered=True)
DEBUT_PHASE_FULL_LABELS = ["1-14日", "15-60日", "61-180日", "181日+", "定番(pre)"]
DEBUT_PHASE_FULL_ORDER = CategoricalDtype(DEBUT_PHASE_FULL_LABELS, ordered=True)
FAMILY_ORDER = CategoricalDtype(["jug", "hana", "bt", "other"], ordered=True)
DOW_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
COUNT_GROUP_ORDER = ["XXS", "XS", "S", "M", "L", "XL"]
COUNT_GROUP_THRESHOLDS = [
    (3, "XXS"),
    (10, "XS"),
    (18, "S"),
    (30, "M"),
    (42, "L"),
]
SEGMENT_A_KEYWORDS = ("ジャグラー", "ハナハナ", "クランキー", "ニューパルサー")
JUG_KEYWORDS = ("ジャグラー", "ジャグ", "アイム")
HANA_KEYWORDS = ("ハナハナ", "ハナ", "沖スロ", "ドラゴンハナハナ", "キングハナハナ")
BT_KEYWORDS = ("BT", "ニューパルサーBT", "不二子BT")


@dataclass(frozen=True)
class MetricSummary:
    analysis: str
    hypothesis_type: str
    group_cols: str
    H: float
    p_value: float
    epsilon_sq: float
    n_groups: int
    n_total: int
    significant: bool


def _normalize_machine_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    name = str(value).strip()
    if name.startswith("L") and not name.startswith("LB"):
        return name[1:]
    return name


def _format_number(value: object, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "NaN"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _table_to_markdown(df: pd.DataFrame, float_digits: int = 1) -> str:
    if df.empty:
        return "_no rows_"
    columns = list(df.columns)
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in df.iterrows():
        values: list[str] = []
        for col in columns:
            value = row[col]
            if isinstance(value, (int, np.integer)):
                values.append(_format_number(value))
            elif isinstance(value, (float, np.floating)):
                values.append(_format_number(value, digits=float_digits))
            elif pd.isna(value):
                values.append("NaN")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _section_size_group(size: float | int | None) -> str:
    if pd.isna(size):
        return "NaN"
    value = int(size)
    if value <= 8:
        return "S"
    if value <= 14:
        return "M"
    return "L"


def _count_group_kamata7(median_count: float | int | None) -> str:
    if pd.isna(median_count):
        return "NaN"
    value = float(median_count)
    if value <= 3:
        return "XXS"
    if value <= 10:
        return "XS"
    if value <= 18:
        return "S"
    if value <= 30:
        return "M"
    if value <= 42:
        return "L"
    return "XL"


def _classify_seg_keyword(machine_name: object) -> str:
    text = "" if pd.isna(machine_name) else str(machine_name)
    return "A" if any(keyword in text for keyword in SEGMENT_A_KEYWORDS) else "N"


def _classify_family_keyword(machine_name: object) -> str:
    text = "" if pd.isna(machine_name) else str(machine_name)
    if any(keyword in text for keyword in JUG_KEYWORDS):
        return "jug"
    if any(keyword in text for keyword in HANA_KEYWORDS):
        return "hana"
    if any(keyword in text for keyword in BT_KEYWORDS):
        return "bt"
    return "other"


def _load_layout() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in [COORD_2F, COORD_3F]:
        frame = pd.read_csv(path)
        frames.append(frame)
    layout = pd.concat(frames, ignore_index=True)
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
    layout = layout.dropna(subset=["machine_number"]).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["section"] = layout["section"].astype(str)
    layout["floor"] = layout["floor"].astype(str)
    sec_size = layout.groupby(["floor", "section"], as_index=False)["machine_number"].nunique()
    sec_size = sec_size.rename(columns={"machine_number": "section_size"})
    layout = layout.merge(sec_size, on=["floor", "section"], how="left", validate="m:1")
    layout["section_size_group"] = layout["section_size"].apply(_section_size_group)
    return layout[
        [
            "machine_number",
            "floor",
            "section",
            "rank_from_min",
            "rank_from_max",
            "section_size",
            "section_size_group",
        ]
    ].drop_duplicates("machine_number", keep="first")


def _load_machine_master_map() -> pd.DataFrame:
    master = _read_machine_master_flags(DB_PATH)
    if master.empty:
        return master
    master = master.copy()
    master["machine_name_key"] = master["machine_name_normalized"].map(_normalize_machine_name)
    master["seg"] = np.where((master["jug_flag"] == 1) | (master["hana_flag"] == 1), "A", "N")
    master["family"] = np.select(
        [
            master["jug_flag"] == 1,
            master["hana_flag"] == 1,
            master["bt_flag"] == 1,
        ],
        ["jug", "hana", "bt"],
        default="other",
    )
    return master[["machine_name_key", "seg", "family"]].drop_duplicates("machine_name_key", keep="first")


def _attach_seg_and_family(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    work = df.copy()
    work["machine_name_key"] = work["machine_name"].map(_normalize_machine_name)
    master = _load_machine_master_map()
    method = "keyword"

    if not master.empty:
        merged = work.merge(master, on="machine_name_key", how="left", validate="m:1")
        seg_coverage = float(merged["seg"].notna().mean())
        family_coverage = float(merged["family"].notna().mean())
        if seg_coverage >= 0.8 and family_coverage >= 0.8:
            work = merged
            work["seg"] = work["seg"].fillna(work["machine_name"].map(_classify_seg_keyword))
            work["family"] = work["family"].fillna(work["machine_name"].map(_classify_family_keyword))
            method = "machine_master"
        else:
            work["seg"] = work["machine_name"].map(_classify_seg_keyword)
            work["family"] = work["machine_name"].map(_classify_family_keyword)
    else:
        work["seg"] = work["machine_name"].map(_classify_seg_keyword)
        work["family"] = work["machine_name"].map(_classify_family_keyword)

    work["seg"] = work["seg"].fillna("N").astype(str)
    work["family"] = work["family"].fillna("other").astype(str)
    return work, method


def _dd_category(row: pd.Series) -> str:
    dd = int(row["dd"])
    if int(row.get("is_mmdd_zorome", 0)) == 1:
        return "強ゾロ目"
    if dd in (11, 22):
        return "ゾロ目"
    if dd % 10 == 7:
        return "7系"
    if dd % 10 == 1:
        return "1系"
    if int(row.get("is_month_end", 0)) == 1:
        return "月末"
    return "その他"


def _prepare_frame() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    df = load_hall_df(HALL).copy()
    df = compute_debut_features(df, db_start_grace_days=0)

    df["date"] = df["date"].astype(str)
    df["machine_name"] = df["machine_name"].astype(str)
    df["machine_number"] = pd.to_numeric(df["machine_number"], errors="coerce")
    df["diff"] = pd.to_numeric(df["diff"], errors="coerce")
    df["games"] = pd.to_numeric(df["games"], errors="coerce")
    df["machine_count"] = pd.to_numeric(df.get("machine_count"), errors="coerce")
    df["days_since_debut"] = pd.to_numeric(df.get("days_since_debut"), errors="coerce")
    df["pre_existing"] = df.get("pre_existing", False).fillna(False).astype(bool)
    df["is_mmdd_zorome"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").pipe(
        lambda s: (s.dt.month == s.dt.day).astype(int)
    )
    month_end = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce").map(
        lambda d: pd.Timestamp(d).days_in_month if pd.notna(d) else np.nan
    )
    df["is_month_end"] = (df["date"].str[6:8].astype(float) == month_end).astype(int)
    if "day_of_week" not in df.columns:
        dates = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
        df["day_of_week"] = dates.dt.day_name().str[:3]

    df, seg_method = _attach_seg_and_family(df)

    layout = _load_layout()
    df = df.merge(layout, on="machine_number", how="left", validate="m:1")
    if df["floor"].isna().any():
        fallback_floor = np.where(df["machine_number"] < 3000, "2F", "3F")
        df["floor"] = df["floor"].fillna(pd.Series(fallback_floor, index=df.index))

    df["debut_phase"] = pd.cut(
        df["days_since_debut"],
        bins=[-0.5, 14, 60, 180, float("inf")],
        labels=DEBUT_PHASE_LABELS,
        include_lowest=True,
    ).astype(DEBUT_PHASE_ORDER)
    df["debut_phase_full"] = df["debut_phase"].astype("object")
    df.loc[df["pre_existing"], "debut_phase_full"] = "定番(pre)"
    df["debut_phase_full"] = df["debut_phase_full"].astype(DEBUT_PHASE_FULL_ORDER)

    df["floor_seg"] = df["floor"].astype(str) + "_" + df["seg"].astype(str)
    df["kakuban_group"] = np.select(
        [
            pd.to_numeric(df["rank_from_min"], errors="coerce").eq(1),
            pd.to_numeric(df["rank_from_min"], errors="coerce").le(4),
        ],
        ["角1", "角2-4"],
        default="中間5+",
    )
    df["section_size_group"] = df["section_size"].apply(_section_size_group)
    df["count_group"] = (
        df.groupby("machine_name")["machine_count"].transform("median").apply(_count_group_kamata7).astype(str)
    )
    df["median_count"] = df.groupby("machine_name")["machine_count"].transform("median")
    df["dd"] = pd.to_numeric(df["date"].astype(str).str[6:8], errors="coerce").astype("Int64")
    df["dd_category"] = df.apply(_dd_category, axis=1)
    df["is_any_event"] = pd.to_numeric(df.get("is_any_event"), errors="coerce").fillna(0).astype(int)
    df["seg"] = df["seg"].astype(str)
    df["family"] = df["family"].astype(str)

    print(f"[seg] method={seg_method} | A={int((df['seg'] == 'A').sum()):,} N={int((df['seg'] == 'N').sum()):,}")
    print(
        f"[layout] missing floor={int(df['floor'].isna().sum()):,} missing section={int(df['section'].isna().sum()):,}"
    )
    return df, layout, seg_method


def _agg_summary(df: pd.DataFrame, group_cols: list[str], *, note_low_n: int = 30) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"])
    work = df.dropna(subset=group_cols).copy()
    if work.empty:
        return pd.DataFrame(columns=[*group_cols, "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"])
    summary = (
        work.groupby(group_cols, observed=True)
        .agg(
            n=("diff", "size"),
            n_machines=("machine_name", "nunique"),
            avg_diff=("diff", "mean"),
            plus_rate=("diff", lambda s: float((s > 0).mean() * 100)),
            avg_games=("games", "mean"),
        )
        .reset_index()
    )
    summary["avg_diff"] = summary["avg_diff"].round(0).astype("Int64")
    summary["plus_rate"] = summary["plus_rate"].round(1)
    summary["avg_games"] = summary["avg_games"].round(1)
    summary["note"] = np.where(summary["n"] < note_low_n, "low_n", "")
    return summary


def _kruskal_from_frame(
    df: pd.DataFrame, group_cols: list[str], *, value_col: str = "diff"
) -> tuple[float, float, float, int, int]:
    if df.empty:
        return np.nan, np.nan, np.nan, 0, 0
    work = df.dropna(subset=group_cols + [value_col]).copy()
    if work.empty:
        return np.nan, np.nan, np.nan, 0, 0
    groups = [
        grp[value_col].to_numpy(dtype=float) for _, grp in work.groupby(group_cols, observed=True) if len(grp) >= 2
    ]
    if len(groups) < 2:
        return np.nan, np.nan, np.nan, len(groups), int(sum(len(g) for g in groups))
    h_stat, p_value = kruskal(*groups)
    n_total = int(sum(len(g) for g in groups))
    return (
        float(h_stat),
        float(p_value),
        float(_epsilon_squared(float(h_stat), len(groups), n_total)),
        len(groups),
        n_total,
    )


def _combined_key(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    work = df[cols].astype(str).copy()
    return work.agg(" | ".join, axis=1)


def _analysis_result(
    analysis: str,
    hypothesis_type: str,
    group_cols: str,
    frame: pd.DataFrame,
    group_cols_list: list[str],
    *,
    significant_cutoff: float | None,
) -> tuple[pd.DataFrame, MetricSummary]:
    summary = _agg_summary(frame, group_cols_list)
    h_stat, p_value, epsilon_sq, n_groups, n_total = _kruskal_from_frame(frame, group_cols_list)
    significant = bool(significant_cutoff is not None and pd.notna(p_value) and p_value < significant_cutoff)
    metric = MetricSummary(
        analysis=analysis,
        hypothesis_type=hypothesis_type,
        group_cols=group_cols,
        H=h_stat,
        p_value=p_value,
        epsilon_sq=epsilon_sq,
        n_groups=n_groups,
        n_total=n_total,
        significant=significant,
    )
    return summary, metric


def _count_spearman(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for phase in DEBUT_PHASE_LABELS:
        sub = frame[frame["debut_phase"].astype(str) == phase].dropna(subset=["median_count", "diff"])
        if len(sub) < 10:
            rows.append({"debut_phase": phase, "n": int(len(sub)), "rho": np.nan, "p_value": np.nan})
            continue
        rho, p_value = spearmanr(sub["median_count"], sub["diff"])
        rows.append({"debut_phase": phase, "n": int(len(sub)), "rho": float(rho), "p_value": float(p_value)})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["rho"] = out["rho"].round(4)
        out["p_value"] = out["p_value"].round(4)
    return out


def _top_detail(summary: pd.DataFrame, group_cols: list[str], detail_key: str, top_n: int = 10) -> pd.DataFrame:
    if summary.empty or detail_key not in summary.columns:
        return pd.DataFrame(
            columns=[*group_cols, detail_key, "n", "n_machines", "avg_diff", "plus_rate", "avg_games", "note"]
        )
    work = summary.copy()
    work = (
        work.sort_values(["avg_diff", "n"], ascending=[False, False])
        .groupby(group_cols, as_index=False, observed=True)
        .head(top_n)
    )
    return work.reset_index(drop=True)


def run_analysis() -> tuple[list[MetricSummary], dict[str, pd.DataFrame]]:
    df, layout, seg_method = _prepare_frame()
    outputs: dict[str, pd.DataFrame] = {}
    metrics: list[MetricSummary] = []

    # 1: pre_existing除外のセグメント別3フェーズ
    df_new = df.loc[~df["pre_existing"]].copy()
    df_new = df_new.dropna(subset=["debut_phase"]).copy()
    df_new["debut_phase"] = df_new["debut_phase"].astype(DEBUT_PHASE_ORDER)
    df_new["floor_seg"] = df_new["floor"].astype(str) + "_" + df_new["seg"].astype(str)
    seg_summary = _agg_summary(df_new, ["floor_seg", "debut_phase"])
    seg_detail = _top_detail(seg_summary, ["floor_seg", "debut_phase"], "floor_seg", top_n=10)
    outputs["1_segment/debut_floor_seg.csv"] = seg_summary
    outputs["1_segment/debut_floor_seg_detail.csv"] = seg_detail
    _, metric = _analysis_result(
        "1_segment", "primary", "floor_seg+debut_phase", df_new, ["floor_seg", "debut_phase"], significant_cutoff=0.017
    )
    metrics.append(metric)

    # 2: 角番/セクション
    pos_summary = _agg_summary(df_new, ["debut_phase", "kakuban_group"])
    sec_summary = _agg_summary(df_new, ["debut_phase", "section_size_group"])
    cross_summary = _agg_summary(df_new, ["debut_phase", "kakuban_group", "section_size_group"])
    outputs["2_position/debut_kakuban_group.csv"] = pos_summary
    outputs["2_position/debut_section_size.csv"] = sec_summary
    outputs["2_position/debut_kakuban_section_cross.csv"] = cross_summary
    _, metric = _analysis_result(
        "2_position_kakuban",
        "exploratory",
        "debut_phase+kakuban_group",
        df_new,
        ["debut_phase", "kakuban_group"],
        significant_cutoff=None,
    )
    metrics.append(metric)
    _, metric = _analysis_result(
        "2_position_section_size",
        "exploratory",
        "debut_phase+section_size_group",
        df_new,
        ["debut_phase", "section_size_group"],
        significant_cutoff=None,
    )
    metrics.append(metric)

    # 3: pre_existing含む完全分析
    df_full = df.copy()
    df_full["debut_phase_full"] = df_full["debut_phase"].astype("object")
    df_full.loc[df_full["pre_existing"], "debut_phase_full"] = "定番(pre)"
    df_full["debut_phase_full"] = df_full["debut_phase_full"].astype(DEBUT_PHASE_FULL_ORDER)
    full_event_summary = _agg_summary(df_full, ["debut_phase_full", "is_any_event"])
    full_dd_summary = _agg_summary(df_full, ["debut_phase_full", "dd_category"])
    family_compare = _agg_summary(
        df_full[df_full["debut_phase_full"].isin(["181日+", "定番(pre)"])],
        ["debut_phase_full", "family", "is_any_event"],
    )
    outputs["3_preexisting/debut_full_event.csv"] = full_event_summary
    outputs["3_preexisting/debut_full_dd_category.csv"] = full_dd_summary
    outputs["3_preexisting/preexisting_vs_181plus_by_family.csv"] = family_compare
    _, metric = _analysis_result(
        "3_preexisting_full_event",
        "primary",
        "debut_phase_full+is_any_event",
        df_full,
        ["debut_phase_full", "is_any_event"],
        significant_cutoff=0.017,
    )
    metrics.append(metric)
    _, metric = _analysis_result(
        "3_preexisting_full_dd_category",
        "primary",
        "debut_phase_full+dd_category",
        df_full,
        ["debut_phase_full", "dd_category"],
        significant_cutoff=0.017,
    )
    metrics.append(metric)
    _, metric = _analysis_result(
        "3_preexisting_family_compare",
        "primary",
        "debut_phase_full+family+is_any_event",
        df_full[df_full["debut_phase_full"].isin(["181日+", "定番(pre)"])],
        ["debut_phase_full", "family", "is_any_event"],
        significant_cutoff=0.017,
    )
    metrics.append(metric)

    # 4: 曜日
    weekday_summary = _agg_summary(df_new, ["debut_phase", "day_of_week"])
    full_weekday_summary = _agg_summary(df_full, ["debut_phase_full", "day_of_week"])
    outputs["4_weekday/debut_weekday.csv"] = weekday_summary
    outputs["4_weekday/debut_full_weekday.csv"] = full_weekday_summary
    _, metric = _analysis_result(
        "4_weekday",
        "exploratory",
        "debut_phase+day_of_week",
        df_new,
        ["debut_phase", "day_of_week"],
        significant_cutoff=None,
    )
    metrics.append(metric)

    # 5: DD個別
    raw_dd_summary = _agg_summary(df_new, ["debut_phase", "dd"])
    dd_cat_summary = _agg_summary(df_new, ["debut_phase", "dd_category"])
    dd_cat_full_summary = _agg_summary(df_full, ["debut_phase_full", "dd_category"])
    newtai_dd = _agg_summary(df_new[df_new["debut_phase"] == "1-14日"], ["dd"])
    growth_dd = _agg_summary(df_new[df_new["debut_phase"] == "15-60日"], ["dd"])
    outputs["5_dd_detail/debut_dd_raw.csv"] = raw_dd_summary
    outputs["5_dd_detail/debut_dd_category.csv"] = dd_cat_summary
    outputs["5_dd_detail/debut_dd_category_full.csv"] = dd_cat_full_summary
    outputs["5_dd_detail/newtai_dd_individual.csv"] = newtai_dd
    outputs["5_dd_detail/growth_dd_individual.csv"] = growth_dd
    _, metric = _analysis_result(
        "5_dd_category",
        "primary",
        "debut_phase+dd_category",
        df_new,
        ["debut_phase", "dd_category"],
        significant_cutoff=0.017,
    )
    metrics.append(metric)
    _, metric = _analysis_result(
        "5_dd_category_full",
        "primary",
        "debut_phase_full+dd_category",
        df_full,
        ["debut_phase_full", "dd_category"],
        significant_cutoff=0.017,
    )
    metrics.append(metric)

    # 6: 台数
    count_summary = _agg_summary(df_new, ["debut_phase", "count_group"])
    count_spearman = _count_spearman(df_new)
    outputs["6_count_group/debut_count_group.csv"] = count_summary
    outputs["6_count_group/debut_count_spearman.csv"] = count_spearman
    _, metric = _analysis_result(
        "6_count_group",
        "exploratory",
        "debut_phase+count_group",
        df_new,
        ["debut_phase", "count_group"],
        significant_cutoff=None,
    )
    metrics.append(metric)

    # 検証用の補助データ
    outputs["_meta/layout_sample.csv"] = layout.head(20)
    outputs["_meta/seg_distribution.csv"] = (
        df.groupby("seg", observed=True).size().reset_index(name="n").sort_values("seg")
    )
    outputs["_meta/family_distribution.csv"] = (
        df.groupby("family", observed=True).size().reset_index(name="n").sort_values("family")
    )

    return metrics, outputs


def build_report(metrics: list[MetricSummary], outputs: dict[str, pd.DataFrame]) -> str:
    by_analysis = {m.analysis: m for m in metrics}
    lines = [
        "# 蒲田7 新台/経過日数 包括的深堀りEDA",
        "実行日: " + pd.Timestamp.today().date().isoformat(),
        "対象: 蒲田7",
        "多重比較: 主仮説3領域に Bonferroni 補正 (p < 0.017)。補助3領域は探索的（有意判定なし）。",
        "",
        "## サマリ",
        "| 領域 | 種別 | 交差軸 | p値 | ε² | 有意(p<0.017) |",
        "|------|------|--------|-----|-----|---------------|",
    ]
    for key, label, kind in [
        ("3_preexisting_full_event", "3", "主"),
        ("1_segment", "1", "主"),
        ("5_dd_category_full", "5", "主"),
        ("2_position_kakuban", "2", "補助"),
        ("4_weekday", "4", "補助"),
        ("6_count_group", "6", "補助"),
    ]:
        metric = by_analysis.get(key)
        if metric is None:
            continue
        p_text = _format_number(metric.p_value, digits=4)
        eps_text = _format_number(metric.epsilon_sq, digits=4)
        sig_text = "Yes" if metric.significant else "No"
        lines.append(f"| {label} | {kind} | {metric.group_cols} | {p_text} | {eps_text} | {sig_text} |")

    lines.extend(
        [
            "",
            "## 主仮説",
            "### 3: pre_existing含む完全版",
            _table_to_markdown(outputs["3_preexisting/debut_full_event.csv"]),
            "",
            _table_to_markdown(outputs["3_preexisting/debut_full_dd_category.csv"]),
            "",
            _table_to_markdown(outputs["3_preexisting/preexisting_vs_181plus_by_family.csv"]),
            "",
            "### 1: セグメント別3フェーズ",
            _table_to_markdown(outputs["1_segment/debut_floor_seg.csv"]),
            "",
            _table_to_markdown(outputs["1_segment/debut_floor_seg_detail.csv"]),
            "",
            "### 5: DD個別精密分析",
            "#### raw DD",
            _table_to_markdown(outputs["5_dd_detail/debut_dd_raw.csv"]),
            "",
            "#### dd_category",
            _table_to_markdown(outputs["5_dd_detail/debut_dd_category.csv"]),
            "",
            "#### newtai_dd_individual",
            _table_to_markdown(outputs["5_dd_detail/newtai_dd_individual.csv"]),
            "",
            "#### growth_dd_individual",
            _table_to_markdown(outputs["5_dd_detail/growth_dd_individual.csv"]),
            "",
            "## 補助仮説",
            "### 2: 角番/セクション",
            _table_to_markdown(outputs["2_position/debut_kakuban_group.csv"]),
            "",
            _table_to_markdown(outputs["2_position/debut_section_size.csv"]),
            "",
            "### 4: 曜日",
            _table_to_markdown(outputs["4_weekday/debut_weekday.csv"]),
            "",
            _table_to_markdown(outputs["4_weekday/debut_full_weekday.csv"]),
            "",
            "### 6: 台数",
            _table_to_markdown(outputs["6_count_group/debut_count_group.csv"]),
            "",
            _table_to_markdown(outputs["6_count_group/debut_count_spearman.csv"]),
            "",
            "## 総合判定",
            "- 主仮説3領域は Bonferroni 補正で判定",
            "- 補助3領域は探索的に解釈",
            "- seg 分類は machine_master 優先、不可ならキーワードにフォールバック",
            "- floor/section は Heatmap 座標に基づく",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    global RESULTS_DIR, REPORT_PATH, KRUSKAL_PATH
    parser = argparse.ArgumentParser(description="Kamata7 debut deep dive EDA")
    parser.add_argument("--outdir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    RESULTS_DIR = args.outdir
    REPORT_PATH = RESULTS_DIR / "kamata7_debut_deep_report.md"
    KRUSKAL_PATH = RESULTS_DIR / "kruskal_wallis_results.csv"

    metrics, outputs = run_analysis()

    rows = [
        {
            "analysis": m.analysis,
            "hypothesis_type": m.hypothesis_type,
            "group_col": m.group_cols,
            "H": m.H,
            "p_value": m.p_value,
            "epsilon_sq": m.epsilon_sq,
            "n_groups": m.n_groups,
            "n_total": m.n_total,
            "significant": m.significant,
        }
        for m in metrics
    ]
    kruskal = pd.DataFrame(rows)

    for rel_path, frame in outputs.items():
        _write_csv(frame, RESULTS_DIR / rel_path)
    _write_csv(kruskal, KRUSKAL_PATH)

    report = build_report(metrics, outputs)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(f"wrote {REPORT_PATH}")
    print(f"wrote {KRUSKAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
