from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
from scipy import stats

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from eda.core import HALL_DBS, load_hall_df
from eda.kamata7_debut_deep_dive import _attach_seg_and_family, _load_layout, _normalize_machine_name
from eda.kamata7_lastdigit_lr_eda import build_floor_side_map

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTDIR = PROJECT_ROOT / "tmp" / "kamata7_machine_dependency"
REPORT_NAME = "report.md"

HALL = "蒲田7"
MIN_DATE = "20250101"
MAX_DATE = "20261231"
MIN_GAMES = 1500

SEGMENT_ORDER = ["2F_L_N", "2F_R_N", "3F_L_A", "3F_L_N", "3F_R_A", "3F_R_N"]
TARGET_SEGMENT_D8_D9 = "3F_L_N"
TARGET_SEGMENT_KAKUBAN = "3F_L_A"
TARGET_SEGMENT_DD = "3F_R_A"

DD_BINS: list[tuple[str, int, int]] = [
    ("DD01-06", 1, 6),
    ("DD07-12", 7, 12),
    ("DD13-18", 13, 18),
    ("DD19-24", 19, 24),
    ("DD25-31", 25, 31),
]
TARGET_ZOROME_DIGITS = [f"{i:02d}" for i in range(10)]
KAKUBAN_EDGE_BANDS = {"1-3"}
KAKUBAN_MID_BANDS = {"5-11"}
REVERSED_SECTIONS = {"2330-2351", "3191-3208", "3341-3362"}


@dataclass(frozen=True)
class DependencyResult:
    axis: str
    segment: str
    target: str
    top2_share: float
    original_p: float
    excluded_p: float
    verdict: str


def _fmt_number(value: object, digits: int = 1) -> str:
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
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        cells: list[str] = []
        for col in cols:
            value = row[col]
            if isinstance(value, (int, np.integer)):
                cells.append(str(int(value)))
            elif isinstance(value, (float, np.floating)):
                cells.append(_fmt_number(value, digits=float_digits))
            elif pd.isna(value):
                cells.append("NaN")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if "date" not in work.columns:
        raise KeyError("date column is required")
    work["date"] = work["date"].astype(str)
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games"] = pd.to_numeric(work["games"], errors="coerce")
    work["diff"] = pd.to_numeric(work["diff"], errors="coerce")
    if "machine_name" in work.columns:
        work["machine_name"] = work["machine_name"].astype(str)
    else:
        work["machine_name"] = ""

    if not {"floor", "side"}.issubset(work.columns):
        work = work.drop(columns=[c for c in ["floor", "side", "floor_side"] if c in work.columns], errors="ignore")
        floor_side = build_floor_side_map().copy()
        floor_side["machine_number"] = pd.to_numeric(floor_side["machine_number"], errors="coerce")
        floor_side = floor_side.dropna(subset=["machine_number"]).copy()
        floor_side["machine_number"] = floor_side["machine_number"].astype(int)
        work = work.merge(
            floor_side[["machine_number", "floor", "side"]], on="machine_number", how="left", validate="m:1"
        )

    if not {"section", "rank_from_min", "rank_from_max"}.issubset(work.columns):
        work = work.drop(
            columns=[
                c
                for c in ["section", "rank_from_min", "rank_from_max", "section_size", "section_size_group"]
                if c in work.columns
            ],
            errors="ignore",
        )
        layout = _load_layout().copy()
        layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
        layout = layout.dropna(subset=["machine_number"]).copy()
        layout["machine_number"] = layout["machine_number"].astype(int)
        work = work.merge(layout, on="machine_number", how="left", validate="m:1")

    if "seg" not in work.columns:
        work, _ = _attach_seg_and_family(work)

    for base in ["floor", "side", "seg", "section", "rank_from_min", "rank_from_max"]:
        if base in work.columns:
            continue
        suffix_cols = [col for col in work.columns if col in {f"{base}_x", f"{base}_y"}]
        if suffix_cols:
            combined = work[suffix_cols[0]]
            for col in suffix_cols[1:]:
                combined = combined.combine_first(work[col])
            work[base] = combined

    for col in ["floor", "side", "seg", "section"]:
        if col in work.columns:
            work[col] = work[col].astype(str)

    if "rank_from_min" in work.columns:
        work["rank_from_min"] = pd.to_numeric(work["rank_from_min"], errors="coerce")
    if "rank_from_max" in work.columns:
        work["rank_from_max"] = pd.to_numeric(work["rank_from_max"], errors="coerce")
    if "kakuban" not in work.columns:
        if {"section", "rank_from_min", "rank_from_max"}.issubset(work.columns):
            work["kakuban"] = np.where(
                work["section"].isin(REVERSED_SECTIONS),
                work["rank_from_max"],
                work["rank_from_min"],
            )
        else:
            work["kakuban"] = np.nan
    work["kakuban"] = pd.to_numeric(work["kakuban"], errors="coerce")

    if "machine_digit" in work.columns:
        work["machine_digit"] = work["machine_digit"].astype(str)
    else:
        work["machine_digit"] = (work["machine_number"] % 10).astype("Int64").astype(str)

    work["dd"] = pd.to_numeric(work["date"].str[6:8], errors="coerce")
    work["dd_bin"] = pd.cut(
        work["dd"],
        bins=[0, 6, 12, 18, 24, 31],
        labels=[label for label, _, _ in DD_BINS],
        include_lowest=True,
        right=True,
    )
    work["day_of_week"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce").dt.day_name()
    work["segment6"] = work["floor"].astype(str) + "_" + work["side"].astype(str) + "_" + work["seg"].astype(str)
    machine_numbers = pd.to_numeric(work["machine_number"], errors="coerce")
    tail2 = machine_numbers.mod(100)
    work["is_zorome"] = ((tail2 // 10) == (tail2 % 10)).fillna(False).astype(int)
    work = work.dropna(subset=["machine_number", "games", "diff", "segment6", "kakuban"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["is_zorome"] = work["is_zorome"].astype(int)
    work["dd"] = work["dd"].astype(int)
    work["kakuban"] = work["kakuban"].astype(int)
    work["machine_digit"] = work["machine_digit"].astype(str)
    return work.reset_index(drop=True)


def _load_work_frame() -> pd.DataFrame:
    work = load_hall_df(HALL).copy()
    work = _normalize_frame(work)
    work = work[(work["date"] >= MIN_DATE) & (work["date"] <= MAX_DATE)].copy()
    work = work[work["games"] >= MIN_GAMES].copy()
    work = work[work["segment6"].isin(SEGMENT_ORDER)].copy()
    work = work[work["machine_digit"].isin([str(i) for i in range(10)])].copy()
    return work.reset_index(drop=True)


def _machine_stats(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["machine_number", "machine_name", "n", "avg_diff", "share_pct"])
    stats_df = (
        frame.groupby(["machine_number", "machine_name"], dropna=False)
        .agg(n=("diff", "size"), avg_diff=("diff", "mean"))
        .reset_index()
        .sort_values(["avg_diff", "machine_number"], ascending=[False, True], kind="mergesort")
        .reset_index(drop=True)
    )
    denom = abs(float(stats_df["avg_diff"].sum()))
    stats_df["share_pct"] = stats_df["avg_diff"] / denom * 100 if denom > 1e-12 else np.nan
    return stats_df


def _mwu_p(a: pd.Series | np.ndarray, b: pd.Series | np.ndarray) -> float:
    a = pd.Series(a).dropna().to_numpy(dtype=float)
    b = pd.Series(b).dropna().to_numpy(dtype=float)
    if len(a) < 5 or len(b) < 5:
        return float("nan")
    _, p_value = stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(p_value)


def _verdict(top2_share: float, excluded_p: float) -> str:
    if pd.isna(top2_share) or pd.isna(excluded_p):
        return "未判定"
    if excluded_p >= 0.05:
        return "偽シグナル"
    if top2_share < 20:
        return "構造シグナル"
    if top2_share < 50:
        return "少数台依存"
    return "個体効果"


def _summarize_machine_dependency(
    frame: pd.DataFrame,
    target_mask: pd.Series,
    compare_mask: pd.Series,
    *,
    axis: str,
    segment: str,
    target: str,
) -> tuple[pd.DataFrame, pd.DataFrame, DependencyResult]:
    target_frame = frame[target_mask].copy()
    compare_frame = frame[compare_mask].copy()
    target_stats = _machine_stats(target_frame)
    top2_machines = target_stats.head(2)["machine_number"].astype(str).tolist()
    top2_share = (
        float(target_stats.head(2)["avg_diff"].sum() / abs(target_stats["avg_diff"].sum()) * 100)
        if not target_stats.empty and abs(float(target_stats["avg_diff"].sum())) > 1e-12
        else float("nan")
    )

    excluded_frame = (
        frame[~frame["machine_number"].isin(target_stats.head(2)["machine_number"].tolist())].copy()
        if not target_stats.empty
        else frame.copy()
    )
    excluded_target = excluded_frame[target_mask.loc[excluded_frame.index]].copy()
    excluded_compare = excluded_frame[compare_mask.loc[excluded_frame.index]].copy()

    original_p = _mwu_p(target_frame["diff"], compare_frame["diff"])
    excluded_p = _mwu_p(excluded_target["diff"], excluded_compare["diff"])

    detail = target_stats.copy()
    if not detail.empty:
        detail["row_type"] = "machine"
        detail["axis"] = axis
        detail["segment"] = segment
        detail["target"] = target
        detail["top2_share"] = top2_share
        detail["top2_machines"] = ",".join(top2_machines)
        detail["original_p"] = original_p
        detail["excluded_p"] = excluded_p
        detail["verdict"] = _verdict(top2_share, excluded_p)
        detail = detail[
            [
                "row_type",
                "axis",
                "segment",
                "target",
                "machine_number",
                "machine_name",
                "n",
                "avg_diff",
                "share_pct",
                "top2_share",
                "top2_machines",
                "original_p",
                "excluded_p",
                "verdict",
            ]
        ]

    summary = pd.DataFrame(
        [
            {
                "row_type": "summary",
                "axis": axis,
                "segment": segment,
                "target": target,
                "machine_number": "",
                "machine_name": "",
                "n": int(target_frame.shape[0]),
                "avg_diff": float(target_frame["diff"].mean()) if not target_frame.empty else np.nan,
                "share_pct": np.nan,
                "top2_share": top2_share,
                "top2_machines": ",".join(top2_machines),
                "original_p": original_p,
                "excluded_p": excluded_p,
                "verdict": _verdict(top2_share, excluded_p),
            }
        ]
    )

    result = DependencyResult(
        axis=axis,
        segment=segment,
        target=target,
        top2_share=top2_share,
        original_p=original_p,
        excluded_p=excluded_p,
        verdict=_verdict(top2_share, excluded_p),
    )
    return detail, summary, result


def _build_step1_digit_dependency(work: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, DependencyResult]]:
    segment = TARGET_SEGMENT_D8_D9
    rows: list[pd.DataFrame] = []
    summary_map: dict[str, DependencyResult] = {}
    for digit in ["8", "9"]:
        target_mask = work["segment6"].eq(segment) & work["machine_digit"].eq(digit)
        compare_mask = work["segment6"].eq(segment) & ~work["machine_digit"].eq(digit)
        detail, summary, result = _summarize_machine_dependency(
            work,
            target_mask,
            compare_mask,
            axis=f"digit_{digit}",
            segment=segment,
            target=f"d{digit}",
        )
        rows.extend([detail, summary])
        summary_map[f"d{digit}"] = result
    table = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return table, summary_map


def _build_step2_saturday_dependency(work: pd.DataFrame) -> tuple[pd.DataFrame, DependencyResult]:
    segment = "all_N"
    rows: list[pd.DataFrame] = []
    target_mask = work["seg"].eq("N") & (work["day_of_week"] == "Saturday")
    compare_mask = work["seg"].eq("N") & (work["day_of_week"] != "Saturday")
    detail, summary, result = _summarize_machine_dependency(
        work,
        target_mask,
        compare_mask,
        axis="saturday_at",
        segment=segment,
        target="sat vs other",
    )
    rows.extend([detail, summary])
    return pd.concat(rows, ignore_index=True), result


def _kakuban_band(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    k = int(value)
    if 1 <= k <= 3:
        return "1-3"
    if 5 <= k <= 11:
        return "5-11"
    return None


def _build_step3_kakuban_dependency(work: pd.DataFrame) -> tuple[pd.DataFrame, DependencyResult]:
    rows: list[pd.DataFrame] = []
    summaries: list[DependencyResult] = []
    for segment in SEGMENT_ORDER:
        sub = work[work["segment6"].eq(segment)].copy()
        sub["kakuban_band"] = sub["kakuban"].map(_kakuban_band)
        focal = sub[sub["kakuban_band"].eq("5-11")].copy()
        compare = sub[sub["kakuban_band"].eq("1-3")].copy()
        if focal.empty or compare.empty:
            summary = pd.DataFrame(
                [
                    {
                        "row_type": "summary",
                        "axis": "kakuban_mid",
                        "segment": segment,
                        "target": "5-11 vs 1-3",
                        "machine_number": "",
                        "machine_name": "",
                        "n": int(focal.shape[0]),
                        "avg_diff": float(focal["diff"].mean()) if not focal.empty else np.nan,
                        "share_pct": np.nan,
                        "top2_share": np.nan,
                        "top2_machines": "",
                        "original_p": np.nan,
                        "excluded_p": np.nan,
                        "verdict": "未判定",
                    }
                ]
            )
            rows.append(summary)
            summaries.append(DependencyResult("kakuban_mid", segment, "5-11 vs 1-3", np.nan, np.nan, np.nan, "未判定"))
            continue
        target_stats = _machine_stats(focal)
        top2_machines = target_stats.head(2)["machine_number"].astype(str).tolist()
        top2_share = (
            float(target_stats.head(2)["avg_diff"].sum() / abs(target_stats["avg_diff"].sum()) * 100)
            if not target_stats.empty and abs(float(target_stats["avg_diff"].sum())) > 1e-12
            else float("nan")
        )
        excluded = sub[~sub["machine_number"].isin(target_stats.head(2)["machine_number"].tolist())].copy()
        excluded_focal = excluded[excluded["kakuban_band"].eq("5-11")]
        excluded_compare = excluded[excluded["kakuban_band"].eq("1-3")]
        original_p = _mwu_p(focal["diff"], compare["diff"])
        excluded_p = _mwu_p(excluded_focal["diff"], excluded_compare["diff"])
        detail = target_stats.copy()
        detail["row_type"] = "machine"
        detail["axis"] = "kakuban_mid"
        detail["segment"] = segment
        detail["target"] = "5-11 vs 1-3"
        detail["top2_share"] = top2_share
        detail["top2_machines"] = ",".join(top2_machines)
        detail["original_p"] = original_p
        detail["excluded_p"] = excluded_p
        detail["verdict"] = _verdict(top2_share, excluded_p)
        detail = detail[
            [
                "row_type",
                "axis",
                "segment",
                "target",
                "machine_number",
                "machine_name",
                "n",
                "avg_diff",
                "share_pct",
                "top2_share",
                "top2_machines",
                "original_p",
                "excluded_p",
                "verdict",
            ]
        ]
        summary = pd.DataFrame(
            [
                {
                    "row_type": "summary",
                    "axis": "kakuban_mid",
                    "segment": segment,
                    "target": "5-11 vs 1-3",
                    "machine_number": "",
                    "machine_name": "",
                    "n": int(focal.shape[0]),
                    "avg_diff": float(focal["diff"].mean()) if not focal.empty else np.nan,
                    "share_pct": np.nan,
                    "top2_share": top2_share,
                    "top2_machines": ",".join(top2_machines),
                    "original_p": original_p,
                    "excluded_p": excluded_p,
                    "verdict": _verdict(top2_share, excluded_p),
                }
            ]
        )
        rows.extend([detail, summary])
        summaries.append(
            DependencyResult(
                "kakuban_mid",
                segment,
                "5-11 vs 1-3",
                top2_share,
                original_p,
                excluded_p,
                _verdict(top2_share, excluded_p),
            )
        )
    table = pd.concat(rows, ignore_index=True)
    best = sorted(
        [r for r in summaries if pd.notna(r.excluded_p)],
        key=lambda r: (-abs(r.top2_share if pd.notna(r.top2_share) else -1.0), r.excluded_p),
    )
    return table, best[0] if best else DependencyResult(
        "kakuban_mid", TARGET_SEGMENT_KAKUBAN, "5-11 vs 1-3", np.nan, np.nan, np.nan, "未判定"
    )


def _build_step4_dd_kakuban_dependency(work: pd.DataFrame) -> tuple[pd.DataFrame, DependencyResult]:
    rows: list[pd.DataFrame] = []
    summaries: list[DependencyResult] = []
    for segment in SEGMENT_ORDER:
        sub = work[work["segment6"].eq(segment)].copy()
        if sub.empty:
            continue
        for dd_label, dd_lo, dd_hi in DD_BINS:
            dd_frame = sub[(sub["dd"] >= dd_lo) & (sub["dd"] <= dd_hi)].copy()
            if dd_frame.empty:
                continue
            for kakuban in sorted(dd_frame["kakuban"].dropna().astype(int).unique()):
                cell = dd_frame[dd_frame["kakuban"].eq(kakuban)].copy()
                if cell.empty:
                    continue
                cell_stats = _machine_stats(cell)
                top2_machines = cell_stats.head(2)["machine_number"].astype(str).tolist()
                denom = abs(float(cell_stats["avg_diff"].sum()))
                top2_share = (
                    float(cell_stats.head(2)["avg_diff"].sum() / denom * 100) if denom > 1e-12 else float("nan")
                )
                excluded = cell[~cell["machine_number"].isin(cell_stats.head(2)["machine_number"].tolist())].copy()
                excluded_avg_diff = float(excluded["diff"].mean()) if not excluded.empty else np.nan
                verdict = _verdict(top2_share, 0.0 if not pd.isna(excluded_avg_diff) else np.nan)
                detail = cell_stats.copy()
                detail["row_type"] = "machine"
                detail["axis"] = "dd_kakuban"
                detail["segment"] = segment
                detail["target"] = f"{dd_label}×角{kakuban}"
                detail["dd_bin"] = dd_label
                detail["kakuban"] = kakuban
                detail["top2_share"] = top2_share
                detail["top2_machines"] = ",".join(top2_machines)
                detail["original_avg_diff"] = float(cell["diff"].mean())
                detail["excluded_avg_diff"] = excluded_avg_diff
                original_p = _mwu_p(cell["diff"], dd_frame.loc[~dd_frame.index.isin(cell.index), "diff"])
                excluded_p = _mwu_p(excluded["diff"], dd_frame.loc[~dd_frame.index.isin(excluded.index), "diff"])
                detail["original_p"] = original_p
                detail["excluded_p"] = excluded_p
                detail["verdict"] = _verdict(top2_share, excluded_p)
                detail = detail[
                    [
                        "row_type",
                        "axis",
                        "segment",
                        "target",
                        "dd_bin",
                        "kakuban",
                        "machine_number",
                        "machine_name",
                        "n",
                        "avg_diff",
                        "share_pct",
                        "top2_share",
                        "top2_machines",
                        "original_avg_diff",
                        "excluded_avg_diff",
                        "original_p",
                        "excluded_p",
                        "verdict",
                    ]
                ]
                summary = pd.DataFrame(
                    [
                        {
                            "row_type": "summary",
                            "axis": "dd_kakuban",
                            "segment": segment,
                            "target": f"{dd_label}×角{kakuban}",
                            "dd_bin": dd_label,
                            "kakuban": kakuban,
                            "machine_number": "",
                            "machine_name": "",
                            "n": int(cell.shape[0]),
                            "avg_diff": float(cell["diff"].mean()),
                            "share_pct": np.nan,
                            "top2_share": top2_share,
                            "top2_machines": ",".join(top2_machines),
                            "original_avg_diff": float(cell["diff"].mean()),
                            "excluded_avg_diff": excluded_avg_diff,
                            "original_p": original_p,
                            "excluded_p": excluded_p,
                            "verdict": _verdict(top2_share, excluded_p),
                        }
                    ]
                )
                rows.extend([detail, summary])
                summaries.append(
                    DependencyResult(
                        "dd_kakuban",
                        segment,
                        f"{dd_label}×角{kakuban}",
                        top2_share,
                        original_p,
                        excluded_p,
                        _verdict(top2_share, excluded_p),
                    )
                )
    table = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    best = sorted(
        summaries,
        key=lambda r: (
            -(r.top2_share if pd.notna(r.top2_share) else -1.0),
            r.segment,
            r.target,
        ),
    )
    return table, best[0] if best else DependencyResult(
        "dd_kakuban", TARGET_SEGMENT_DD, "", np.nan, np.nan, np.nan, "未判定"
    )


def _build_step5_zorome_dependency(work: pd.DataFrame) -> tuple[pd.DataFrame, DependencyResult]:
    rows: list[pd.DataFrame] = []
    summaries: list[DependencyResult] = []
    zoro = work[work["is_zorome"] == 1].copy()
    non_zoro = work[work["is_zorome"] == 0].copy()
    for digit in TARGET_ZOROME_DIGITS:
        sub = zoro[zoro["machine_number"].astype(str).str[-2:] == digit].copy()
        if sub.empty:
            continue
        stats_df = _machine_stats(sub)
        top2_machines = stats_df.head(2)["machine_number"].astype(str).tolist()
        denom = abs(float(stats_df["avg_diff"].sum()))
        top2_share = float(stats_df.head(2)["avg_diff"].sum() / denom * 100) if denom > 1e-12 else np.nan
        excluded = sub[~sub["machine_number"].isin(stats_df.head(2)["machine_number"].tolist())].copy()
        detail = stats_df.copy()
        detail["row_type"] = "machine"
        detail["axis"] = "zorome"
        detail["segment"] = "all"
        detail["target"] = digit
        detail["top2_share"] = top2_share
        detail["top2_machines"] = ",".join(top2_machines)
        detail["verdict"] = _verdict(top2_share, 0.0 if not excluded.empty else np.nan)
        detail = detail[
            [
                "row_type",
                "axis",
                "segment",
                "target",
                "machine_number",
                "machine_name",
                "n",
                "avg_diff",
                "share_pct",
                "top2_share",
                "top2_machines",
                "verdict",
            ]
        ]
        summary = pd.DataFrame(
            [
                {
                    "row_type": "summary",
                    "axis": "zorome",
                    "segment": "all",
                    "target": digit,
                    "machine_number": "",
                    "machine_name": "",
                    "n": int(sub.shape[0]),
                    "avg_diff": float(sub["diff"].mean()) if not sub.empty else np.nan,
                    "share_pct": np.nan,
                    "top2_share": top2_share,
                    "top2_machines": ",".join(top2_machines),
                    "verdict": _verdict(top2_share, 0.0 if not excluded.empty else np.nan),
                }
            ]
        )
        rows.extend([detail, summary])
        summaries.append(
            DependencyResult(
                "zorome",
                "all",
                digit,
                top2_share,
                np.nan,
                np.nan,
                _verdict(top2_share, 0.0 if not excluded.empty else np.nan),
            )
        )

    zoro_detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    zoro_summary_frame = work.copy()
    zoro_target = zoro_summary_frame[zoro_summary_frame["is_zorome"] == 1].copy()
    zoro_compare = zoro_summary_frame[zoro_summary_frame["is_zorome"] == 0].copy()
    zoro_stats = _machine_stats(zoro_target)
    zoro_top2_share = (
        float(zoro_stats.head(2)["avg_diff"].sum() / abs(zoro_stats["avg_diff"].sum()) * 100)
        if not zoro_stats.empty and abs(float(zoro_stats["avg_diff"].sum())) > 1e-12
        else float("nan")
    )
    zoro_excluded = (
        zoro_target[~zoro_target["machine_number"].isin(zoro_stats.head(2)["machine_number"].tolist())].copy()
        if not zoro_stats.empty
        else zoro_target.copy()
    )
    original_p = _mwu_p(zoro_target["diff"], zoro_compare["diff"])
    excluded_p = _mwu_p(zoro_excluded["diff"], zoro_compare["diff"])
    best = DependencyResult(
        "zorome", "all", "zoro vs non", zoro_top2_share, original_p, excluded_p, _verdict(zoro_top2_share, excluded_p)
    )
    return zoro_detail, best


def build_step6_summary(results: dict[str, pd.DataFrame | DependencyResult]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    step1_map: dict[str, DependencyResult] = results["step1_summary"]  # type: ignore[assignment]
    step2: DependencyResult = results["step2_summary"]  # type: ignore[assignment]
    step3: DependencyResult = results["step3_summary"]  # type: ignore[assignment]
    step4: DependencyResult = results["step4_summary"]  # type: ignore[assignment]
    step5: DependencyResult = results["step5_summary"]  # type: ignore[assignment]
    rows.append(
        {
            "axis": "digit_d8",
            "segment": TARGET_SEGMENT_D8_D9,
            "target": "d8",
            "top2_share": step1_map["d8"].top2_share,
            "original_p": step1_map["d8"].original_p,
            "excluded_p": step1_map["d8"].excluded_p,
            "verdict": step1_map["d8"].verdict,
        }
    )
    rows.append(
        {
            "axis": "digit_d9",
            "segment": TARGET_SEGMENT_D8_D9,
            "target": "d9",
            "top2_share": step1_map["d9"].top2_share,
            "original_p": step1_map["d9"].original_p,
            "excluded_p": step1_map["d9"].excluded_p,
            "verdict": step1_map["d9"].verdict,
        }
    )
    rows.append(
        {
            "axis": "saturday_at",
            "segment": "all_N",
            "target": "sat vs other",
            "top2_share": step2.top2_share,
            "original_p": step2.original_p,
            "excluded_p": step2.excluded_p,
            "verdict": step2.verdict,
        }
    )
    rows.append(
        {
            "axis": "kakuban_mid",
            "segment": step3.segment,
            "target": "5-11 vs 1-3",
            "top2_share": step3.top2_share,
            "original_p": step3.original_p,
            "excluded_p": step3.excluded_p,
            "verdict": step3.verdict,
        }
    )
    rows.append(
        {
            "axis": "dd_kakuban",
            "segment": step4.segment,
            "target": step4.target,
            "top2_share": step4.top2_share,
            "original_p": step4.original_p,
            "excluded_p": step4.excluded_p,
            "verdict": step4.verdict,
        }
    )
    rows.append(
        {
            "axis": "zorome",
            "segment": "all",
            "target": "zoro vs non",
            "top2_share": step5.top2_share,
            "original_p": step5.original_p,
            "excluded_p": step5.excluded_p,
            "verdict": step5.verdict,
        }
    )
    return pd.DataFrame(
        rows, columns=["axis", "segment", "target", "top2_share", "original_p", "excluded_p", "verdict"]
    )


def build_all_artifacts(work: pd.DataFrame | None = None) -> dict[str, pd.DataFrame | DependencyResult]:
    frame = _load_work_frame() if work is None else _normalize_frame(work)
    if work is not None:
        frame = frame[(frame["date"] >= MIN_DATE) & (frame["date"] <= MAX_DATE)].copy()
        frame = frame[frame["games"] >= MIN_GAMES].copy()
        frame = frame[frame["segment6"].isin(SEGMENT_ORDER)].copy()
    step1_table, step1_summary_map = _build_step1_digit_dependency(frame)
    step2_table, step2_summary = _build_step2_saturday_dependency(frame)
    step3_table, step3_summary = _build_step3_kakuban_dependency(frame)
    step4_table, step4_summary = _build_step4_dd_kakuban_dependency(frame)
    step5_table, step5_summary = _build_step5_zorome_dependency(frame)
    step6_summary = build_step6_summary(
        {
            "step1_summary": step1_summary_map,
            "step2_summary": step2_summary,
            "step3_summary": step3_summary,
            "step4_summary": step4_summary,
            "step5_summary": step5_summary,
        }
    )
    return {
        "step1_digit_dependency": step1_table,
        "step2_saturday_dependency": step2_table,
        "step3_kakuban_dependency": step3_table,
        "step4_dd_kakuban_dependency": step4_table,
        "step5_zorome_dependency": step5_table,
        "step6_summary": step6_summary,
        "step1_summary": step1_summary_map,
        "step2_summary": step2_summary,
        "step3_summary": step3_summary,
        "step4_summary": step4_summary,
        "step5_summary": step5_summary,
    }


def build_report(artifacts: dict[str, pd.DataFrame | DependencyResult]) -> str:
    lines: list[str] = []
    lines.append("# 蒲田7 machine dependency audit")
    lines.append("")
    lines.append(f"- hall: {HALL}")
    lines.append(f"- date_range: {MIN_DATE} to {MAX_DATE}")
    lines.append(f"- min_games: {MIN_GAMES}")
    lines.append(f"- db: {HALL_DBS[HALL]}")
    lines.append("")
    lines.append("## Step 1: 3F_L_N d8/d9")
    lines.append(_table_to_markdown(cast(pd.DataFrame, artifacts["step1_digit_dependency"])))
    lines.append("")
    lines.append("## Step 2: all_N Saturday")
    lines.append(_table_to_markdown(cast(pd.DataFrame, artifacts["step2_saturday_dependency"])))
    lines.append("")
    lines.append("## Step 3: kakuban mid vs edge")
    lines.append(_table_to_markdown(cast(pd.DataFrame, artifacts["step3_kakuban_dependency"])))
    lines.append("")
    lines.append("## Step 4: DD x kakuban cells")
    lines.append(_table_to_markdown(cast(pd.DataFrame, artifacts["step4_dd_kakuban_dependency"])))
    lines.append("")
    lines.append("## Step 5: zorome")
    lines.append(_table_to_markdown(cast(pd.DataFrame, artifacts["step5_zorome_dependency"])))
    lines.append("")
    lines.append("## Step 6: summary")
    lines.append(_table_to_markdown(cast(pd.DataFrame, artifacts["step6_summary"]), float_digits=4))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kamata7 machine dependency audit")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    args = parser.parse_args(argv)

    artifacts = build_all_artifacts()
    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    _write_csv(cast(pd.DataFrame, artifacts["step1_digit_dependency"]), outdir / "step1_digit_dependency.csv")
    _write_csv(cast(pd.DataFrame, artifacts["step2_saturday_dependency"]), outdir / "step2_saturday_dependency.csv")
    _write_csv(cast(pd.DataFrame, artifacts["step3_kakuban_dependency"]), outdir / "step3_kakuban_dependency.csv")
    _write_csv(cast(pd.DataFrame, artifacts["step4_dd_kakuban_dependency"]), outdir / "step4_dd_kakuban_dependency.csv")
    _write_csv(cast(pd.DataFrame, artifacts["step5_zorome_dependency"]), outdir / "step5_zorome_dependency.csv")
    _write_csv(cast(pd.DataFrame, artifacts["step6_summary"]), outdir / "step6_summary.csv")
    _write_text(outdir / REPORT_NAME, build_report(artifacts))
    print(f"wrote {outdir / REPORT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
