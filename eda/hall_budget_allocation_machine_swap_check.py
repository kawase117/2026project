from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, load_hall_df
from eda.hall_budget_allocation_light import build_plan_allocation_by_axis, prepare_plan_source_frame
from eda.hall_budget_allocation_splithalf_check import _markdown_table, _t_stat

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_HALLS = ["楽園", "金時", "レイトギャップ", "ザシティ"]
DEFAULT_SPLITHALF_SUMMARY_PATH = (
    PROJECT_ROOT / "eda" / "results" / "hall_budget_allocation_splithalf" / "summary_splithalf.csv"
)
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "eda" / "results" / "hall_budget_allocation_machine_swap"

RESIDUAL_COLUMNS = [
    "hall",
    "axis_value",
    "t_full_original",
    "t_full_residual",
    "residual_verdict",
]
SWAP_COLUMNS = [
    "hall",
    "axis_value",
    "swap_date",
    "n_days_before",
    "t_before",
    "n_days_after",
    "t_after",
    "swap_verdict",
]
HISTORY_COLUMNS = [
    "axis_value",
    "swap_date",
    "n_machines_in_band",
    "n_machines_swapped_on_date",
    "machine_names_before",
    "machine_names_after",
]


def _ensure_output_root(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_t(values: pd.Series) -> tuple[int, float | None]:
    n, t_value, _ = _t_stat(values)
    if t_value is not None:
        return n, t_value
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    n = int(len(numeric))
    if n < 2:
        return n, None
    mean_value = float(numeric.mean())
    std_value = float(numeric.std(ddof=1))
    if math.isfinite(mean_value) and (not math.isfinite(std_value) or std_value <= 0):
        if abs(mean_value) < 1e-12:
            return n, 0.0
        return n, 1_000_000_000.0 if mean_value > 0 else -1_000_000_000.0
    return n, t_value


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def load_stable_targets_from_frame(summary: pd.DataFrame, *, halls: list[str] | None = None) -> pd.DataFrame:
    required = {"hall", "axis_value", "t_full", "verdict"}
    missing = required.difference(summary.columns)
    if missing:
        raise ValueError(f"split-half summary missing columns: {sorted(missing)}")

    targets = summary.loc[summary["verdict"].astype(str).eq("stable")].copy()
    if halls is not None:
        targets = targets.loc[targets["hall"].astype(str).isin([str(hall) for hall in halls])].copy()
    targets = targets.rename(columns={"t_full": "t_full_original"})
    targets["hall"] = targets["hall"].astype(str)
    targets["axis_value"] = targets["axis_value"].astype(str)
    targets["t_full_original"] = pd.to_numeric(targets["t_full_original"], errors="coerce")
    targets = targets.dropna(subset=["hall", "axis_value", "t_full_original"]).copy()
    return (
        targets.loc[:, ["hall", "axis_value", "t_full_original"]]
        .sort_values(["hall", "axis_value"], kind="mergesort")
        .reset_index(drop=True)
    )


def load_stable_targets(path: Path, *, halls: list[str] | None = None) -> pd.DataFrame:
    return load_stable_targets_from_frame(pd.read_csv(path, encoding="utf-8"), halls=halls)


def _band_frame(source_frame: pd.DataFrame, axis_value: object) -> pd.DataFrame:
    if source_frame.empty or "section" not in source_frame.columns:
        return pd.DataFrame(columns=source_frame.columns)
    frame = source_frame.loc[source_frame["section"].astype(str).eq(str(axis_value))].copy()
    if frame.empty:
        return frame
    frame["date"] = frame["date"].astype(str)
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["diff"] = pd.to_numeric(frame["diff"], errors="coerce")
    frame["games"] = pd.to_numeric(frame["games"], errors="coerce")
    frame = frame.dropna(subset=["date", "machine_number", "diff", "games"]).copy()
    frame = frame.loc[frame["games"] > 0].copy()
    if frame.empty:
        return frame
    frame["machine_number"] = frame["machine_number"].astype(int)
    return frame


def _with_machine_weighted_residuals(source_frame: pd.DataFrame, axis_value: object) -> pd.DataFrame:
    frame = _band_frame(source_frame, axis_value)
    if frame.empty:
        return frame

    frame["rate"] = frame["diff"] / frame["games"] * 100.0
    machine_totals = frame.groupby("machine_number", as_index=False).agg(
        total_diff=("diff", "sum"), total_games=("games", "sum")
    )
    machine_totals = machine_totals.loc[machine_totals["total_games"] > 0].copy()
    if machine_totals.empty:
        return pd.DataFrame(columns=list(frame.columns) + ["machine_weighted_mean_rate", "machine_residual"])
    machine_totals["machine_weighted_mean_rate"] = machine_totals["total_diff"] / machine_totals["total_games"] * 100.0
    frame = frame.merge(
        machine_totals.loc[:, ["machine_number", "machine_weighted_mean_rate"]], on="machine_number", how="inner"
    )
    frame["machine_residual"] = frame["rate"] - frame["machine_weighted_mean_rate"]
    return frame


def _residual_t_for_band(source_frame: pd.DataFrame, axis_value: object) -> float | None:
    frame = _with_machine_weighted_residuals(source_frame, axis_value)
    if frame.empty:
        return None

    frame["weighted_residual"] = frame["machine_residual"] * frame["games"]
    daily = frame.groupby("date", as_index=False, sort=True).agg(
        weighted_residual=("weighted_residual", "sum"), total_games=("games", "sum")
    )
    daily = daily.loc[daily["total_games"] > 0].copy()
    if daily.empty:
        return None
    daily["band_residual_excess"] = daily["weighted_residual"] / daily["total_games"]
    _, t_value = _safe_t(daily["band_residual_excess"])
    return t_value


def _residual_verdict(t_original: float, t_residual: float) -> str:
    if abs(t_residual) < abs(t_original) * 0.5:
        return "explained_by_machine_identity"
    if abs(t_residual) >= 2.0:
        return "band_effect_survives_residualization"
    return "partially_explained"


def build_machine_residual_summary(hall: str, targets: pd.DataFrame, source_frame: pd.DataFrame) -> pd.DataFrame:
    hall_targets = targets.loc[targets["hall"].astype(str).eq(str(hall))].copy()
    rows: list[dict[str, object]] = []
    for target in hall_targets.itertuples(index=False):
        t_original = float(target.t_full_original)
        t_residual = _residual_t_for_band(source_frame, target.axis_value)
        if t_residual is None or not math.isfinite(float(t_residual)):
            continue
        rows.append(
            {
                "hall": hall,
                "axis_value": str(target.axis_value),
                "t_full_original": t_original,
                "t_full_residual": float(t_residual),
                "residual_verdict": _residual_verdict(t_original, float(t_residual)),
            }
        )
    return pd.DataFrame(rows, columns=RESIDUAL_COLUMNS)


def _section_allocation_frame(allocation: pd.DataFrame, axis_value: object) -> pd.DataFrame:
    frame = allocation.loc[
        allocation["axis"].astype(str).eq("section") & allocation["axis_value"].astype(str).eq(str(axis_value))
    ].copy()
    if frame.empty:
        return frame
    frame["date"] = frame["date"].astype(str)
    frame["excess_vs_hall_day"] = pd.to_numeric(frame["excess_vs_hall_day"], errors="coerce")
    return (
        frame.dropna(subset=["date", "excess_vs_hall_day"]).sort_values("date", kind="mergesort").reset_index(drop=True)
    )


def _machine_daily_names(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["date", "machine_number", "machine_name"])
    names = (
        frame.loc[:, ["date", "machine_number", "machine_name"]]
        .sort_values(["machine_number", "date"], kind="mergesort")
        .drop_duplicates(subset=["machine_number", "date"], keep="last")
        .reset_index(drop=True)
    )
    names["machine_name"] = names["machine_name"].astype(str)
    return names


def _swap_counts(frame: pd.DataFrame) -> pd.DataFrame:
    names = _machine_daily_names(frame)
    if names.empty:
        return pd.DataFrame(columns=["date", "n_swapped"])
    names["prev_machine_name"] = names.groupby("machine_number")["machine_name"].shift(1)
    changes = names.loc[
        names["prev_machine_name"].notna() & names["machine_name"].ne(names["prev_machine_name"])
    ].copy()
    if changes.empty:
        return pd.DataFrame(columns=["date", "n_swapped"])
    return changes.groupby("date", as_index=False, sort=True).agg(n_swapped=("machine_number", "nunique"))


def _select_swap_date(frame: pd.DataFrame) -> tuple[str, int, int]:
    machine_count = int(frame["machine_number"].nunique()) if not frame.empty else 0
    counts = _swap_counts(frame)
    if machine_count == 0 or counts.empty:
        return "", 0, machine_count
    counts = counts.sort_values(["n_swapped", "date"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    top = counts.iloc[0]
    n_swapped = int(top["n_swapped"])
    if n_swapped <= machine_count / 2:
        return "", n_swapped, machine_count
    return str(top["date"]), n_swapped, machine_count


def _swap_verdict(t_original: float, t_before: float, t_after: float) -> str:
    original_sign = _sign(t_original)
    if _sign(t_after) * original_sign < 0:
        return "reverses_after_swap"
    if (
        _sign(t_before) == original_sign
        and _sign(t_after) == original_sign
        and abs(t_before) >= 1.0
        and abs(t_after) >= 1.0
    ):
        return "persists_across_swap"
    return "weakens_after_swap"


def build_machine_swap_summary(
    hall: str, targets: pd.DataFrame, source_frame: pd.DataFrame, allocation: pd.DataFrame
) -> pd.DataFrame:
    hall_targets = targets.loc[targets["hall"].astype(str).eq(str(hall))].copy()
    rows: list[dict[str, object]] = []
    for target in hall_targets.itertuples(index=False):
        band = _band_frame(source_frame, target.axis_value)
        swap_date, _, _ = _select_swap_date(band)
        if not swap_date:
            rows.append(
                {
                    "hall": hall,
                    "axis_value": str(target.axis_value),
                    "swap_date": "",
                    "n_days_before": 0,
                    "t_before": 0.0,
                    "n_days_after": 0,
                    "t_after": 0.0,
                    "swap_verdict": "no_clear_swap_in_window",
                }
            )
            continue

        section = _section_allocation_frame(allocation, target.axis_value)
        before = section.loc[section["date"] < swap_date]
        after = section.loc[section["date"] >= swap_date]
        n_before, t_before = _safe_t(before["excess_vs_hall_day"])
        n_after, t_after = _safe_t(after["excess_vs_hall_day"])
        if t_before is None or t_after is None or n_before == 0 or n_after == 0:
            continue
        rows.append(
            {
                "hall": hall,
                "axis_value": str(target.axis_value),
                "swap_date": swap_date,
                "n_days_before": int(n_before),
                "t_before": float(t_before),
                "n_days_after": int(n_after),
                "t_after": float(t_after),
                "swap_verdict": _swap_verdict(float(target.t_full_original), float(t_before), float(t_after)),
            }
        )
    return pd.DataFrame(rows, columns=SWAP_COLUMNS)


def _names_around_swap(frame: pd.DataFrame, swap_date: str) -> tuple[str, str]:
    if frame.empty:
        return "", ""
    if not swap_date:
        names = sorted(frame["machine_name"].astype(str).dropna().unique().tolist())
        joined = ", ".join(names)
        return joined, joined
    before = sorted(
        frame.loc[frame["date"].astype(str) < swap_date, "machine_name"].astype(str).dropna().unique().tolist()
    )
    after = sorted(
        frame.loc[frame["date"].astype(str) >= swap_date, "machine_name"].astype(str).dropna().unique().tolist()
    )
    return ", ".join(before), ", ".join(after)


def build_machine_history_summary(
    hall: str, targets: pd.DataFrame, source_frame: pd.DataFrame, swap_summary: pd.DataFrame
) -> pd.DataFrame:
    hall_targets = targets.loc[targets["hall"].astype(str).eq(str(hall))].copy()
    swap_by_axis = (
        swap_summary.set_index("axis_value")
        if not swap_summary.empty
        else pd.DataFrame(columns=SWAP_COLUMNS).set_index("axis_value")
    )
    rows: list[dict[str, object]] = []
    for target in hall_targets.itertuples(index=False):
        axis_value = str(target.axis_value)
        band = _band_frame(source_frame, axis_value)
        selected_date, n_swapped, machine_count = _select_swap_date(band)
        swap_date = selected_date
        if axis_value in swap_by_axis.index:
            swap_date = str(swap_by_axis.loc[axis_value, "swap_date"])
        before_names, after_names = _names_around_swap(band, swap_date)
        rows.append(
            {
                "axis_value": axis_value,
                "swap_date": swap_date,
                "n_machines_in_band": int(machine_count),
                "n_machines_swapped_on_date": int(n_swapped),
                "machine_names_before": before_names,
                "machine_names_after": after_names,
            }
        )
    return pd.DataFrame(rows, columns=HISTORY_COLUMNS)


def build_hall_report(hall: str, residual: pd.DataFrame, swap: pd.DataFrame, history: pd.DataFrame) -> str:
    lines = [f"# {hall} Machine Residual and Swap Check", ""]
    lines.append(f"- target bins: {len(residual) if not residual.empty else len(swap)}")
    if not swap.empty:
        no_clear = int((swap["swap_verdict"] == "no_clear_swap_in_window").sum())
        total = int(len(swap))
        rate = no_clear / total if total else 0.0
        lines.append(f"- no_clear_swap_in_window: {no_clear}/{total} ({rate:.1%})")
    lines.append("")
    lines.append("## Machine Residual")
    lines.append("- none" if residual.empty else _markdown_table(residual, RESIDUAL_COLUMNS))
    lines.append("")
    lines.append("## Swap Stability")
    lines.append("- none" if swap.empty else _markdown_table(swap, SWAP_COLUMNS))
    lines.append("")
    lines.append("## Machine Names Around Swap")
    lines.append("- none" if history.empty else _markdown_table(history, HISTORY_COLUMNS))
    lines.append("")
    return "\n".join(lines)


def run_hall(
    hall: str,
    targets: pd.DataFrame,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    min_games: int = 0,
    raw: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if raw is None:
        raw = load_hall_df(hall)
    output_root = _ensure_output_root(Path(output_root))
    source_frame = prepare_plan_source_frame(raw, hall=hall, min_games=min_games)
    allocation = build_plan_allocation_by_axis(source_frame)
    residual = build_machine_residual_summary(hall, targets, source_frame)
    swap = build_machine_swap_summary(hall, targets, source_frame, allocation)
    history = build_machine_history_summary(hall, targets, source_frame, swap)
    report = build_hall_report(hall, residual, swap, history)
    (output_root / f"{hall}_machine_swap_report.md").write_text(report, encoding="utf-8")
    return residual, swap


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="machine residual and swap check for stable section bins")
    parser.add_argument("--halls", nargs="+", default=TARGET_HALLS)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SPLITHALF_SUMMARY_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--min-games", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = _ensure_output_root(Path(args.output_root))
    for hall in args.halls:
        if hall not in TARGET_HALLS:
            raise ValueError(f"unsupported hall for machine swap check: {hall}")
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")

    targets = load_stable_targets(Path(args.summary_path), halls=list(args.halls))
    residual_frames: list[pd.DataFrame] = []
    swap_frames: list[pd.DataFrame] = []
    for hall in args.halls:
        residual, swap = run_hall(hall, targets, output_root=output_root, min_games=args.min_games)
        residual_frames.append(residual)
        swap_frames.append(swap)

    residual_summary = (
        pd.concat(residual_frames, ignore_index=True) if residual_frames else pd.DataFrame(columns=RESIDUAL_COLUMNS)
    )
    swap_summary = pd.concat(swap_frames, ignore_index=True) if swap_frames else pd.DataFrame(columns=SWAP_COLUMNS)
    residual_summary = residual_summary.loc[:, RESIDUAL_COLUMNS].copy()
    swap_summary = swap_summary.loc[:, SWAP_COLUMNS].copy()
    residual_summary.to_csv(output_root / "summary_machine_residual.csv", index=False, encoding="utf-8")
    swap_summary.to_csv(output_root / "summary_machine_swap.csv", index=False, encoding="utf-8")

    total = int(len(swap_summary))
    no_clear = int((swap_summary["swap_verdict"] == "no_clear_swap_in_window").sum()) if total else 0
    rate = no_clear / total if total else 0.0
    print(f"written: {output_root}")
    print(f"no_clear_swap_in_window: {no_clear}/{total} ({rate:.1%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
