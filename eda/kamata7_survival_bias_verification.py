from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from pandas.api.types import CategoricalDtype
from scipy.stats import mannwhitneyu

from eda.core import HALL_DBS, compute_debut_features, load_hall_df


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HALL = "蒲田7"
DB_PATH = PROJECT_ROOT / "db" / HALL_DBS[HALL]
COORD_2F = PROJECT_ROOT / "Heatmap" / "2F_floor_coordinates_kamata7.csv"
COORD_3F = PROJECT_ROOT / "Heatmap" / "3F_floor_coordinates_kamata7.csv"

OUTPUT_DIR = PROJECT_ROOT / "tmp" / "kamata7_survival_bias"
REPORT_PATH = OUTPUT_DIR / "report.md"

DEBUT_BIN_LABELS = ["1-14日", "15-60日", "61-180日", "181日+"]
DEBUT_BIN_ORDER = CategoricalDtype(DEBUT_BIN_LABELS, ordered=True)
SURVIVAL_GROUP_ORDER = CategoricalDtype(["survived", "removed", "censored", "pre_existing"], ordered=True)
EVENT_SCOPE_ORDER = CategoricalDtype(["event", "non_event"], ordered=True)

SEGMENT_A_KEYWORDS = ("ジャグラー", "ハナハナ", "クランキー", "ニューパルサー")


@dataclass(frozen=True)
class MetricSummary:
    analysis: str
    group_cols: str
    p_value: float
    n_groups: int
    n_total: int
    significant: bool


def _normalize_machine_name(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.startswith("L") and not text.startswith("LB"):
        return text[1:]
    return text


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


def _classify_seg_keyword(machine_name: object) -> str:
    text = "" if pd.isna(machine_name) else str(machine_name)
    return "A" if any(keyword in text for keyword in SEGMENT_A_KEYWORDS) else "N"


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
    section_size = layout.groupby(["floor", "section"], as_index=False)["machine_number"].nunique()
    section_size = section_size.rename(columns={"machine_number": "section_size"})
    layout = layout.merge(section_size, on=["floor", "section"], how="left", validate="m:1")
    return layout[
        [
            "machine_number",
            "floor",
            "section",
            "rank_from_min",
            "rank_from_max",
            "section_size",
        ]
    ].drop_duplicates("machine_number", keep="first")


def _attach_layout(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    layout = _load_layout()
    merged = work.merge(layout, on="machine_number", how="left", validate="m:1")
    if merged["floor"].isna().any():
        fallback_floor = np.where(merged["machine_number"] < 3000, "2F", "3F")
        merged["floor"] = merged["floor"].fillna(pd.Series(fallback_floor, index=merged.index))
    if "seg" not in merged.columns:
        merged["seg"] = merged["machine_name"].map(_classify_seg_keyword)
    merged["seg"] = merged["seg"].fillna("N").astype(str)
    merged["floor"] = merged["floor"].fillna("unknown").astype(str)
    merged["floor_seg"] = merged["floor"].astype(str) + "_" + merged["seg"].astype(str)
    return merged


def _ensure_event_flag(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "is_any_event" in work.columns:
        work["is_any_event"] = pd.to_numeric(work["is_any_event"], errors="coerce").fillna(0).astype(int)
        return work
    dates = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    dd = dates.dt.day
    mm = dates.dt.month
    month_end = dates.map(lambda d: pd.Timestamp(d).days_in_month if pd.notna(d) else np.nan)
    work["is_any_event"] = (dd.isin([1, 7, 11, 17, 21, 22, 27, 31]) | (dd == month_end) | (dd == mm)).astype(int)
    return work


def _ensure_floor_seg(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "floor_seg" not in work.columns:
        if "floor" in work.columns and "seg" in work.columns:
            work["floor_seg"] = work["floor"].astype(str) + "_" + work["seg"].astype(str)
        else:
            work["floor_seg"] = "unknown"
    return work


def _assign_survival_status(df: pd.DataFrame, *, censor_window_days: int = 30) -> pd.DataFrame:
    work = df.copy()
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["days_since_debut"] = pd.to_numeric(work["days_since_debut"], errors="coerce")
    if "pre_existing" not in work.columns:
        work["pre_existing"] = False
    work["pre_existing"] = work["pre_existing"].fillna(False).astype(bool)
    obs_end = work["date_dt"].max()

    stats = (
        work.groupby("machine_name", dropna=False)
        .agg(
            last_seen=("date_dt", "max"),
            max_days_since_debut=("days_since_debut", "max"),
            pre_existing=("pre_existing", "max"),
        )
        .reset_index()
    )

    status_map: dict[str, str] = {}
    gap_map: dict[str, float] = {}
    for _, row in stats.iterrows():
        name = str(row["machine_name"])
        if bool(row["pre_existing"]):
            status = "pre_existing"
        else:
            gap = (obs_end - row["last_seen"]).days if pd.notna(obs_end) and pd.notna(row["last_seen"]) else np.nan
            gap_map[name] = float(gap) if pd.notna(gap) else np.nan
            if pd.notna(gap) and gap < censor_window_days:
                status = "censored"
            elif pd.notna(row["max_days_since_debut"]) and float(row["max_days_since_debut"]) >= 181:
                status = "survived"
            else:
                status = "removed"
        status_map[name] = status

    work["survival_status"] = work["machine_name"].astype(str).map(status_map).fillna("removed")
    work["last_seen_gap_days"] = work["machine_name"].astype(str).map(gap_map)
    return work.drop(columns=["date_dt"], errors="ignore")


def _debut_window_frame(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["days_since_debut"] = pd.to_numeric(work["days_since_debut"], errors="coerce")
    return work.loc[work["days_since_debut"].between(1, 60, inclusive="both")].copy()


def _comparison_subset(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    if "survival_status" not in work.columns:
        work = _assign_survival_status(work)
    work = _ensure_floor_seg(work)
    return work.loc[work["survival_status"].isin(["survived", "removed"])].copy()


def _prepare_frame(df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df is None:
        work = load_hall_df(HALL).copy()
        work = compute_debut_features(work, db_start_grace_days=0)
    else:
        work = df.copy()

    work["date"] = work["date"].astype(str)
    work["machine_name"] = work["machine_name"].astype(str)
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["diff"] = pd.to_numeric(work["diff"], errors="coerce")
    work["games"] = pd.to_numeric(work["games"], errors="coerce")
    work["days_since_debut"] = pd.to_numeric(work.get("days_since_debut"), errors="coerce")
    if "pre_existing" not in work.columns:
        work["pre_existing"] = False
    work["pre_existing"] = pd.to_numeric(work["pre_existing"], errors="coerce").fillna(0).astype(bool)

    if "floor" not in work.columns or "seg" not in work.columns:
        work = _attach_layout(work)
    else:
        work["floor"] = work["floor"].astype(str)
        work["seg"] = work["seg"].astype(str)
        work["floor_seg"] = work["floor"].astype(str) + "_" + work["seg"].astype(str)

    if "debut_phase" not in work.columns:
        work["debut_phase"] = pd.cut(
            work["days_since_debut"],
            bins=[-0.5, 14, 60, 180, float("inf")],
            labels=DEBUT_BIN_LABELS,
            include_lowest=True,
        )
    work["debut_phase"] = work["debut_phase"].astype(DEBUT_BIN_ORDER)

    work = _ensure_event_flag(work)
    if "is_mmdd_zorome" not in work.columns:
        dates = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        work["is_mmdd_zorome"] = (dates.dt.month == dates.dt.day).astype(int)

    if "is_month_end" not in work.columns:
        dates = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
        work["is_month_end"] = dates.map(
            lambda d: int(pd.Timestamp(d).day == pd.Timestamp(d).days_in_month) if pd.notna(d) else 0
        )

    work = _assign_survival_status(work)
    work = _ensure_floor_seg(work)
    return work


def _build_step1_survival_groups(work: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_floor_seg(work)
    rows: list[dict[str, object]] = []
    for segment, seg_frame in work.groupby("floor_seg", dropna=False, sort=False):
        seg_frame = seg_frame.copy()
        for group in ["survived", "removed", "censored", "pre_existing"]:
            group_frame = seg_frame.loc[seg_frame["survival_status"].eq(group)].copy()
            if group_frame.empty:
                continue
            debut_frame = _debut_window_frame(group_frame)
            debut_values = pd.to_numeric(debut_frame["diff"], errors="coerce").dropna()
            if debut_values.empty:
                continue
            max_days = pd.to_numeric(
                group_frame.groupby("machine_name", dropna=False)["days_since_debut"].max(), errors="coerce"
            ).dropna()
            rows.append(
                {
                    "segment": str(segment),
                    "group": group,
                    "debut_avg_diff": float(debut_values.mean()),
                    "debut_n": int(len(debut_values)),
                    "max_days_median": float(max_days.median()) if not max_days.empty else np.nan,
                    "n_machines": int(group_frame["machine_name"].astype(str).nunique()),
                }
            )
    table = pd.DataFrame(
        rows, columns=["segment", "group", "debut_avg_diff", "debut_n", "max_days_median", "n_machines"]
    )
    if table.empty:
        return table
    table["group"] = table["group"].astype(SURVIVAL_GROUP_ORDER)
    table = table.sort_values(["segment", "group"], kind="mergesort").reset_index(drop=True)
    table["group"] = table["group"].astype(str)
    return table


def _step1_survival_groups(work: pd.DataFrame) -> pd.DataFrame:
    return _build_step1_survival_groups(work)


def _step2_mwu(work: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_floor_seg(work)
    rows: list[dict[str, object]] = []
    for segment, seg_frame in _comparison_subset(work).groupby("floor_seg", dropna=False, sort=False):
        debut_frame = _debut_window_frame(seg_frame)
        survived_values = pd.to_numeric(
            debut_frame.loc[debut_frame["survival_status"].eq("survived"), "diff"],
            errors="coerce",
        ).dropna()
        removed_values = pd.to_numeric(
            debut_frame.loc[debut_frame["survival_status"].eq("removed"), "diff"],
            errors="coerce",
        ).dropna()
        if survived_values.empty or removed_values.empty:
            continue
        try:
            u_stat, p_value = mannwhitneyu(survived_values, removed_values, alternative="two-sided")
        except ValueError:
            u_stat, p_value = np.nan, np.nan
        rows.append(
            {
                "segment": str(segment),
                "u_stat": float(u_stat),
                "p_value": float(p_value),
                "survived_debut_avg": float(survived_values.mean()),
                "removed_debut_avg": float(removed_values.mean()),
                "diff": float(survived_values.mean() - removed_values.mean()),
                "n_survived": int(len(survived_values)),
                "n_removed": int(len(removed_values)),
            }
        )
    table = pd.DataFrame(
        rows,
        columns=[
            "segment",
            "u_stat",
            "p_value",
            "survived_debut_avg",
            "removed_debut_avg",
            "diff",
            "n_survived",
            "n_removed",
        ],
    )
    if table.empty:
        return table
    return table.sort_values("segment", kind="mergesort").reset_index(drop=True)


def _step3_cohort_tracking(work: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_floor_seg(work)
    rows: list[dict[str, object]] = []
    debut_frame = work.loc[~work["pre_existing"]].copy()
    for segment, seg_frame in debut_frame.groupby("floor_seg", dropna=False, sort=False):
        seg_frame = seg_frame.copy()
        for label in DEBUT_BIN_LABELS:
            bin_frame = seg_frame.loc[seg_frame["debut_phase"].astype(str).eq(label)].copy()
            if bin_frame.empty:
                continue
            values = pd.to_numeric(bin_frame["diff"], errors="coerce").dropna()
            if values.empty:
                continue
            rows.append(
                {
                    "segment": str(segment),
                    "debut_bin": label,
                    "n": int(len(values)),
                    "avg_diff": float(values.mean()),
                    "plus_rate": float((values > 0).mean() * 100),
                    "n_machines": int(bin_frame["machine_name"].astype(str).nunique()),
                }
            )
    table = pd.DataFrame(rows, columns=["segment", "debut_bin", "n", "avg_diff", "plus_rate", "n_machines"])
    if table.empty:
        return table
    table["debut_bin"] = table["debut_bin"].astype(DEBUT_BIN_ORDER)
    table = table.sort_values(["segment", "debut_bin"], kind="mergesort").reset_index(drop=True)
    table["debut_bin"] = table["debut_bin"].astype(str)
    return table


def _step4_event_debut_premium(work: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_floor_seg(work)
    rows: list[dict[str, object]] = []
    debut_frame = work.loc[~work["pre_existing"]].copy()
    debut_frame["event_scope"] = np.where(debut_frame["is_any_event"].astype(int) == 1, "event", "non_event")
    debut_frame["event_scope"] = debut_frame["event_scope"].astype(EVENT_SCOPE_ORDER)
    for segment, seg_frame in debut_frame.groupby("floor_seg", dropna=False, sort=False):
        seg_frame = seg_frame.copy()
        for group in ["survived", "removed", "censored"]:
            group_frame = seg_frame.loc[seg_frame["survival_status"].eq(group)].copy()
            if group_frame.empty:
                continue
            for scope in ["event", "non_event"]:
                scope_frame = group_frame.loc[group_frame["event_scope"].astype(str).eq(scope)].copy()
                if scope_frame.empty:
                    continue
                for label in ["1-14日", "15-60日"]:
                    bin_frame = scope_frame.loc[scope_frame["debut_phase"].astype(str).eq(label)].copy()
                    if bin_frame.empty:
                        continue
                    values = pd.to_numeric(bin_frame["diff"], errors="coerce").dropna()
                    if values.empty:
                        continue
                    rows.append(
                        {
                            "segment": str(segment),
                            "group": group,
                            "scope": scope,
                            "debut_bin": label,
                            "n": int(len(values)),
                            "avg_diff": float(values.mean()),
                        }
                    )
    table = pd.DataFrame(rows, columns=["segment", "group", "scope", "debut_bin", "n", "avg_diff"])
    if table.empty:
        return table
    table["group"] = table["group"].astype(SURVIVAL_GROUP_ORDER)
    table["scope"] = table["scope"].astype(EVENT_SCOPE_ORDER)
    table["debut_bin"] = table["debut_bin"].astype(DEBUT_BIN_ORDER)
    table = table.sort_values(["segment", "group", "scope", "debut_bin"], kind="mergesort").reset_index(drop=True)
    table["group"] = table["group"].astype(str)
    table["scope"] = table["scope"].astype(str)
    table["debut_bin"] = table["debut_bin"].astype(str)
    return table


def _step5_floor_comparison(work: pd.DataFrame) -> pd.DataFrame:
    work = _ensure_floor_seg(work)
    rows: list[dict[str, object]] = []
    comp = _comparison_subset(work).copy()
    for floor_type, floor_frame in comp.groupby("floor_seg", dropna=False, sort=False):
        debut_frame = _debut_window_frame(floor_frame)
        survived_values = pd.to_numeric(
            debut_frame.loc[debut_frame["survival_status"].eq("survived"), "diff"],
            errors="coerce",
        ).dropna()
        removed_values = pd.to_numeric(
            debut_frame.loc[debut_frame["survival_status"].eq("removed"), "diff"],
            errors="coerce",
        ).dropna()
        if survived_values.empty or removed_values.empty:
            continue
        try:
            _, p_value = mannwhitneyu(survived_values, removed_values, alternative="two-sided")
        except ValueError:
            p_value = np.nan
        rows.append(
            {
                "floor_type": str(floor_type),
                "survived_debut_avg": float(survived_values.mean()),
                "removed_debut_avg": float(removed_values.mean()),
                "mwu_p": float(p_value),
                "bias_magnitude": float(survived_values.mean() - removed_values.mean()),
                "n_survived": int(len(survived_values)),
                "n_removed": int(len(removed_values)),
                "note": "補助的参考。floor差とA/N構成差の混入に注意",
            }
        )
    table = pd.DataFrame(
        rows,
        columns=[
            "floor_type",
            "survived_debut_avg",
            "removed_debut_avg",
            "mwu_p",
            "bias_magnitude",
            "n_survived",
            "n_removed",
            "note",
        ],
    )
    if table.empty:
        return table
    table = table.sort_values("floor_type", kind="mergesort").reset_index(drop=True)
    return table


def _metric_summary(analysis: str, group_cols: str, p_value: float, n_groups: int, n_total: int) -> MetricSummary:
    significant = bool(pd.notna(p_value) and p_value < 0.05)
    return MetricSummary(
        analysis=analysis,
        group_cols=group_cols,
        p_value=float(p_value),
        n_groups=int(n_groups),
        n_total=int(n_total),
        significant=significant,
    )


def run_analysis(df: pd.DataFrame | None = None) -> tuple[list[MetricSummary], dict[str, pd.DataFrame]]:
    work = _prepare_frame(df)
    outputs: dict[str, pd.DataFrame] = {}
    metrics: list[MetricSummary] = []

    step1 = _step1_survival_groups(work)
    step2 = _step2_mwu(work)
    step3 = _step3_cohort_tracking(work)
    step4 = _step4_event_debut_premium(work)
    step5 = _step5_floor_comparison(work)

    outputs["step1_survival_groups.csv"] = step1
    outputs["step2_mwu.csv"] = step2
    outputs["step3_cohort_tracking.csv"] = step3
    outputs["step4_event_debut_premium.csv"] = step4
    outputs["step5_floor_comparison.csv"] = step5

    if not step2.empty:
        metrics.append(
            _metric_summary(
                "step2",
                "segment",
                float(step2["p_value"].min()),
                len(step2),
                int(step2[["n_survived", "n_removed"]].sum().sum()),
            )
        )
    if not step5.empty:
        metrics.append(
            _metric_summary(
                "step5",
                "floor_type",
                float(step5["mwu_p"].min()),
                len(step5),
                int(step5[["n_survived", "n_removed"]].sum().sum()),
            )
        )
    return metrics, outputs


def build_report(metrics: list[MetricSummary], outputs: dict[str, pd.DataFrame]) -> str:
    lines = [
        "# 蒲田7 経過日数3フェーズモデルの生存バイアス検証",
        "",
        f"実行日: {pd.Timestamp.today().date().isoformat()}",
        "",
        "## 概要",
        "- Step 1: survived / removed / censored の分類",
        "- Step 2: survived と removed の MWU 比較",
        "- Step 3: debut_bin 別コホート追跡",
        "- Step 4: イベント日限定の debut プレミアム",
        "- Step 5: 補助的参考として floor_type 比較",
        "- Step 1 の censored は、最終出現日が観測末 30 日未満の台を除外するために追加",
        "- Step 5 は floor差とA/N構成差の混入を注記した補助分析",
        "",
        "## Step 1",
        _table_to_markdown(outputs.get("step1_survival_groups.csv", pd.DataFrame())),
        "",
        "## Step 2",
        _table_to_markdown(outputs.get("step2_mwu.csv", pd.DataFrame())),
        "",
        "## Step 3",
        _table_to_markdown(outputs.get("step3_cohort_tracking.csv", pd.DataFrame())),
        "",
        "## Step 4",
        _table_to_markdown(outputs.get("step4_event_debut_premium.csv", pd.DataFrame())),
        "",
        "## Step 5",
        _table_to_markdown(outputs.get("step5_floor_comparison.csv", pd.DataFrame())),
    ]
    if metrics:
        metric_rows = pd.DataFrame(
            [
                {
                    "analysis": metric.analysis,
                    "group_cols": metric.group_cols,
                    "p_value": metric.p_value,
                    "n_groups": metric.n_groups,
                    "n_total": metric.n_total,
                    "significant": metric.significant,
                }
                for metric in metrics
            ]
        )
        lines.extend(["", "## Metrics", _table_to_markdown(metric_rows, float_digits=4)])
    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(output_dir: Path, metrics: list[MetricSummary], outputs: dict[str, pd.DataFrame]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        _write_csv(frame, output_dir / name)
    report = build_report(metrics, outputs)
    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kamata7 survival bias verification")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metrics, outputs = run_analysis()
    report_path = write_artifacts(args.output_dir, metrics, outputs)
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
