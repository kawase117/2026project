from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.hall_budget_allocation_light import (
    _machine_category_from_name,
    build_plan_allocation_by_axis,
    prepare_plan_source_frame,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_HALLS = ["楽園", "金時", "レイトギャップ", "ザシティ"]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "eda" / "results" / "hall_budget_allocation_splithalf"
SUMMARY_COLUMNS = [
    "hall",
    "axis_value",
    "n_days_full",
    "t_full",
    "mean_excess_full",
    "n_days_first",
    "t_first",
    "n_days_second",
    "t_second",
    "verdict",
    "category_note",
]


def _ensure_output_root(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _finite_float(value: object) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result):
        return None
    return result


def _t_stat(values: pd.Series) -> tuple[int, float | None, float | None]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    n = int(len(numeric))
    if n < 2:
        return n, None, None
    mean_value = float(numeric.mean())
    std_value = float(numeric.std(ddof=1))
    if not math.isfinite(std_value) or std_value <= 0:
        return n, None, mean_value if math.isfinite(mean_value) else None
    t_value = mean_value / (std_value / math.sqrt(n))
    return n, _finite_float(t_value), mean_value if math.isfinite(mean_value) else None


def _split_dates(section_frame: pd.DataFrame) -> tuple[set[str], set[str]]:
    dates = sorted(section_frame["date"].astype(str).dropna().unique().tolist())
    midpoint = len(dates) // 2
    return set(dates[:midpoint]), set(dates[midpoint:])


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _verdict(t_full: float, t_first: float, t_second: float) -> str:
    full_sign = _sign(t_full)
    first_sign = _sign(t_first)
    second_sign = _sign(t_second)
    if first_sign * full_sign < 0 or second_sign * full_sign < 0:
        return "sign_flip"
    if abs(t_first) < 1.0 or abs(t_second) < 1.0:
        return "weak_in_one_half"
    return "stable"


def _category_note(source_frame: pd.DataFrame, axis_value: object) -> str:
    if source_frame.empty or "section" not in source_frame.columns:
        return "category_diverse"

    frame = source_frame.loc[source_frame["section"].astype(str).eq(str(axis_value))].copy()
    if frame.empty:
        return "category_diverse"
    if "machine_category" not in frame.columns:
        frame["machine_category"] = frame["machine_name"].map(_machine_category_from_name)
    if "games" not in frame.columns:
        return "category_diverse"

    frame["games"] = pd.to_numeric(frame["games"], errors="coerce")
    grouped = frame.dropna(subset=["games"]).groupby("machine_category", sort=True)["games"].sum()
    total_games = float(grouped.sum()) if not grouped.empty else 0.0
    if total_games <= 0:
        return "category_diverse"

    shares = (grouped / total_games).sort_values(ascending=False, kind="mergesort")
    if shares.empty:
        return "category_diverse"
    if float(shares.iloc[0]) >= 0.70:
        return f"dominated_by_{shares.index[0]}"
    if len(shares) >= 2 and float(shares.iloc[:2].sum()) >= 0.70:
        return f"dominated_by_{shares.index[0]}+{shares.index[1]}"
    return "category_diverse"


def _category_shares(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "games" not in frame.columns:
        return pd.Series(dtype=float)
    working = frame.copy()
    if "machine_category" not in working.columns:
        working["machine_category"] = working["machine_name"].map(_machine_category_from_name)
    working["games"] = pd.to_numeric(working["games"], errors="coerce")
    grouped = working.dropna(subset=["games"]).groupby("machine_category", sort=True)["games"].sum()
    total_games = float(grouped.sum()) if not grouped.empty else 0.0
    if total_games <= 0:
        return pd.Series(dtype=float)
    return (grouped / total_games).sort_values(ascending=False, kind="mergesort")


def build_category_control_frame(summary: pd.DataFrame, source_frame: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "axis_value",
        "bin_top1_category",
        "bin_top1_share",
        "bin_top2_share",
        "hall_top1_category",
        "hall_top1_share",
        "category_note",
    ]
    if summary.empty or source_frame.empty or "section" not in source_frame.columns:
        return pd.DataFrame(columns=columns)

    stable = summary.loc[summary["verdict"].astype(str).eq("stable")].copy()
    if stable.empty:
        return pd.DataFrame(columns=columns)

    hall_shares = _category_shares(source_frame)
    hall_top1_category = str(hall_shares.index[0]) if not hall_shares.empty else ""
    hall_top1_share = float(hall_shares.iloc[0]) if not hall_shares.empty else 0.0

    rows: list[dict[str, object]] = []
    for row in stable.itertuples(index=False):
        bin_frame = source_frame.loc[source_frame["section"].astype(str).eq(str(row.axis_value))]
        bin_shares = _category_shares(bin_frame)
        rows.append(
            {
                "axis_value": str(row.axis_value),
                "bin_top1_category": str(bin_shares.index[0]) if not bin_shares.empty else "",
                "bin_top1_share": float(bin_shares.iloc[0]) if not bin_shares.empty else 0.0,
                "bin_top2_share": float(bin_shares.iloc[:2].sum()) if not bin_shares.empty else 0.0,
                "hall_top1_category": hall_top1_category,
                "hall_top1_share": hall_top1_share,
                "category_note": str(row.category_note),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_splithalf_summary(
    hall: str,
    allocation: pd.DataFrame,
    source_frame: pd.DataFrame,
    *,
    t_threshold: float = 3.5,
) -> pd.DataFrame:
    section_frame = allocation.loc[allocation["axis"].astype(str).eq("section")].copy()
    if section_frame.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    section_frame["date"] = section_frame["date"].astype(str)
    section_frame["excess_vs_hall_day"] = pd.to_numeric(section_frame["excess_vs_hall_day"], errors="coerce")
    section_frame = section_frame.dropna(subset=["date", "axis_value", "excess_vs_hall_day"]).copy()
    if section_frame.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    first_dates, second_dates = _split_dates(section_frame)
    if not first_dates or not second_dates:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    rows: list[dict[str, object]] = []
    for axis_value, axis_frame in section_frame.groupby("axis_value", sort=True, dropna=True):
        n_full, t_full, mean_full = _t_stat(axis_frame["excess_vs_hall_day"])
        if t_full is None or mean_full is None or abs(t_full) <= t_threshold:
            continue

        first_frame = axis_frame.loc[axis_frame["date"].isin(first_dates)]
        second_frame = axis_frame.loc[axis_frame["date"].isin(second_dates)]
        n_first, t_first, _ = _t_stat(first_frame["excess_vs_hall_day"])
        n_second, t_second, _ = _t_stat(second_frame["excess_vs_hall_day"])
        if t_first is None or t_second is None or n_first == 0 or n_second == 0:
            continue

        rows.append(
            {
                "hall": hall,
                "axis_value": str(axis_value),
                "n_days_full": int(n_full),
                "t_full": float(t_full),
                "mean_excess_full": float(mean_full),
                "n_days_first": int(n_first),
                "t_first": float(t_first),
                "n_days_second": int(n_second),
                "t_second": float(t_second),
                "verdict": _verdict(float(t_full), float(t_first), float(t_second)),
                "category_note": _category_note(source_frame, axis_value),
            }
        )

    summary = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    if summary.empty:
        return summary
    return summary.sort_values(["hall", "verdict", "axis_value"], kind="mergesort").reset_index(drop=True)


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.3f}"
    if isinstance(value, (np.floating,)):
        value_float = float(value)
        if not math.isfinite(value_float):
            return ""
        return f"{value_float:.3f}"
    return str(value)


def _markdown_table(frame: pd.DataFrame, columns: Iterable[str]) -> str:
    cols = list(columns)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for row in frame.loc[:, cols].itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_format_cell(value) for value in row) + " |")
    return "\n".join(lines)


def build_markdown_report(hall: str, summary: pd.DataFrame, category_control: pd.DataFrame | None = None) -> str:
    lines = [f"# {hall} Split-half Section Stability", ""]
    lines.append(f"- candidate bins: {len(summary)}")
    if not summary.empty:
        counts = summary["verdict"].value_counts().to_dict()
        for verdict in ["stable", "sign_flip", "weak_in_one_half"]:
            lines.append(f"- {verdict}: {int(counts.get(verdict, 0))}")
    lines.append("")
    lines.append("## Summary")
    if summary.empty:
        lines.append("- no bins passed |t_full| > 3.5 with valid split-half statistics")
    else:
        report_columns = [
            "axis_value",
            "n_days_full",
            "t_full",
            "mean_excess_full",
            "n_days_first",
            "t_first",
            "n_days_second",
            "t_second",
            "verdict",
            "category_note",
        ]
        lines.append(_markdown_table(summary, report_columns))
    lines.append("")
    lines.append("## Category Control")
    if category_control is None or category_control.empty:
        lines.append("- no stable bins for category control")
    else:
        lines.append(
            _markdown_table(
                category_control,
                [
                    "axis_value",
                    "bin_top1_category",
                    "bin_top1_share",
                    "bin_top2_share",
                    "hall_top1_category",
                    "hall_top1_share",
                    "category_note",
                ],
            )
        )
    lines.append("")
    return "\n".join(lines)


def run_hall(
    hall: str,
    raw: pd.DataFrame | None = None,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    min_games: int = 0,
    t_threshold: float = 3.5,
) -> pd.DataFrame:
    if raw is None:
        raw = load_hall_df(hall)

    output_root = _ensure_output_root(Path(output_root))
    source_frame = prepare_plan_source_frame(raw, hall=hall, min_games=min_games)
    allocation = build_plan_allocation_by_axis(source_frame)
    summary = build_splithalf_summary(hall, allocation, source_frame, t_threshold=t_threshold)
    category_control = build_category_control_frame(summary, source_frame)
    report_text = build_markdown_report(hall, summary, category_control)
    (output_root / f"{hall}_splithalf_report.md").write_text(report_text, encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="split-half stability check for hall budget section allocation")
    parser.add_argument("--halls", nargs="+", default=TARGET_HALLS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--min-games", type=int, default=0)
    parser.add_argument("--t-threshold", type=float, default=3.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = _ensure_output_root(Path(args.output_root))
    summary_frames: list[pd.DataFrame] = []

    for hall in args.halls:
        if hall not in TARGET_HALLS:
            raise ValueError(f"unsupported hall for splithalf check: {hall}")
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        summary_frames.append(
            run_hall(
                hall,
                raw=None,
                output_root=output_root,
                min_games=args.min_games,
                t_threshold=args.t_threshold,
            )
        )

    summary = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame(columns=SUMMARY_COLUMNS)
    if not summary.empty:
        summary = summary.loc[:, SUMMARY_COLUMNS].copy()
        summary["category_note"] = summary["category_note"].fillna("category_diverse")
    summary.to_csv(output_root / "summary_splithalf.csv", index=False, encoding="utf-8")
    print(f"written: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
