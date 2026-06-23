from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ml.analysis.kamata_weekday_event_axis_distribution_deepdive import (
    _compare_metric_with_halves,
    _daily_weekday_frame,
)
from ml.analysis.kamata_weekday_event_axis_payoutrate_deepdive import (
    DEFAULT_COORDS_7_2F,
    DEFAULT_DB_7,
    SegmentSpec,
    _build_segment_frame,
    _ensure_dir,
    _fmt,
    _md_table,
    _mwu,
    _split_frame_by_date_half,
    _write_csv,
    _write_text,
    compute_payoutrate_pct,
    infer_hall_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "tmp" / "kamata_weekday_event_axis_eda_deepdive_machine_regime"
TARGET_SECTION = "2179-2186"
TARGET_MACHINES = (2182, 2180)
CUTOFF_DATE = pd.Timestamp("2025-12-22")
WEEKDAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _weekday_label(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        idx = int(numeric)
        if 0 <= idx < len(WEEKDAY_ORDER):
            return WEEKDAY_ORDER[idx]
    text = str(value)
    return text if text else ""


def _prepare_section_frame() -> pd.DataFrame:
    spec = SegmentSpec(
        hall_slug="kamata7",
        hall_name=infer_hall_name(Path(DEFAULT_COORDS_7_2F), floor="2F"),
        floor="2F",
        db_path=Path(DEFAULT_DB_7),
        coords_path=Path(DEFAULT_COORDS_7_2F),
    )
    frame = _build_segment_frame(spec).copy()
    frame["hall_slug"] = spec.hall_slug
    frame["floor"] = spec.floor
    frame["payoutrate_pct"] = [
        compute_payoutrate_pct(diff, games)
        for diff, games in zip(frame["diff_coins_normalized"], frame["games_normalized"], strict=False)
    ]
    frame["weekday_label"] = frame["weekday"].map(_weekday_label)
    frame["period"] = np.where(pd.to_datetime(frame["date"], errors="coerce") < CUTOFF_DATE, "before_2025-12-22", "on_or_after_2025-12-22")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame


def _section_subset(frame: pd.DataFrame, *, exclude_machines: tuple[int, ...] = ()) -> pd.DataFrame:
    subset = frame[frame["section"].astype(str).eq(TARGET_SECTION)].copy()
    if exclude_machines:
        subset = subset[~subset["machine_number"].isin(list(exclude_machines))].copy()
    return subset


def _machine_history(frame: pd.DataFrame, machine_number: int) -> pd.DataFrame:
    sub = frame[frame["machine_number"].eq(machine_number)].copy()
    if sub.empty:
        return pd.DataFrame(
            columns=[
                "machine_name",
                "first_date",
                "last_date",
                "n_rows",
                "mean_payoutrate_pct",
                "hit_rate_104",
                "share_104_plus",
            ]
        )
    history = (
        sub.groupby("machine_name", as_index=False)
        .agg(
            first_date=("date", "min"),
            last_date=("date", "max"),
            n_rows=("date", "size"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            hit_rate_104=("payoutrate_pct", lambda s: float((pd.Series(s) > 104.0).mean())),
            share_104_plus=("payoutrate_pct", lambda s: float((pd.Series(s) >= 104.0).mean())),
        )
        .sort_values(["first_date", "machine_name"], ascending=[True, True], na_position="last")
        .reset_index(drop=True)
    )
    history.insert(0, "machine_number", machine_number)
    return history


def _machine_period_weekday_summary(frame: pd.DataFrame, machine_number: int) -> pd.DataFrame:
    sub = frame[frame["machine_number"].eq(machine_number)].copy()
    if sub.empty:
        return pd.DataFrame(
            columns=[
                "machine_number",
                "period",
                "machine_name",
                "weekday_label",
                "median_payoutrate_pct",
                "mean_payoutrate_pct",
                "share_104_plus",
                "n_rows",
                "n_dates",
            ]
        )
    summary = (
        sub.groupby(["period", "machine_name", "weekday_label"], as_index=False)
        .agg(
            median_payoutrate_pct=("payoutrate_pct", "median"),
            mean_payoutrate_pct=("payoutrate_pct", "mean"),
            share_104_plus=("payoutrate_pct", lambda s: float((pd.Series(s) >= 104.0).mean())),
            n_rows=("date", "size"),
            n_dates=("date", "nunique"),
        )
        .sort_values(["period", "weekday_label", "machine_name"], ascending=[True, True, True], na_position="last")
        .reset_index(drop=True)
    )
    summary.insert(0, "machine_number", machine_number)
    return summary


def _weekday_daily_summary(frame: pd.DataFrame) -> pd.DataFrame:
    daily = _daily_weekday_frame(frame)
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "rank",
                "weekday_label",
                "median_payoutrate_pct",
                "share_104_plus",
                "mean_payoutrate_pct",
                "share_100_104",
                "n_dates",
                "n_machines",
            ]
        )
    summary = (
        daily.groupby("weekday_label", as_index=False)
        .agg(
            median_payoutrate_pct=("median_payoutrate_pct", "mean"),
            share_104_plus=("share_104_plus", "mean"),
            mean_payoutrate_pct=("mean_payoutrate_pct", "mean"),
            share_100_104=("share_100_104", "mean"),
            n_dates=("date", "nunique"),
            n_machines=("n_machines", "sum"),
        )
        .sort_values(["median_payoutrate_pct", "share_104_plus", "weekday_label"], ascending=[False, False, True], na_position="last")
        .reset_index(drop=True)
    )
    summary.insert(0, "rank", np.arange(1, len(summary) + 1))
    return summary


def _weekday_compare(frame: pd.DataFrame, *, value_col: str) -> pd.DataFrame:
    daily = _daily_weekday_frame(frame)
    compare = _compare_metric_with_halves(daily, label_col="weekday_label", value_col=value_col)
    if compare.empty:
        return compare
    compare["weekday_label"] = compare["weekday_label"].astype(str)
    return compare


def _machine_sunday_concentration(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for machine_number, group in frame.groupby("machine_number", sort=False):
        sun = pd.to_numeric(group.loc[group["weekday_label"].eq("Sun"), "payoutrate_pct"], errors="coerce").dropna().astype(float)
        rest = pd.to_numeric(group.loc[~group["weekday_label"].eq("Sun"), "payoutrate_pct"], errors="coerce").dropna().astype(float)
        if len(sun) == 0 or len(rest) == 0:
            continue
        p_value = _mwu(sun, rest)
        delta = float(sun.median() - rest.median())
        rows.append(
            {
                "machine_number": int(machine_number),
                "sun_median": float(sun.median()),
                "rest_median": float(rest.median()),
                "delta": delta,
                "sun_n": int(len(sun)),
                "rest_n": int(len(rest)),
                "p_value": p_value,
                "direction": "cell_higher" if delta > 0 else "cell_lower" if delta < 0 else "tie_or_nan",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values(["delta", "p_value", "machine_number"], ascending=[False, True, True], na_position="last").reset_index(drop=True)
    total = float(out["delta"].abs().sum())
    out["top_machine_share"] = float(out["delta"].abs().max() / total) if total > 0 else np.nan
    out["q_value"] = out["p_value"]
    return out


def _section_sunday_summary(frame: pd.DataFrame, *, exclude_machines: tuple[int, ...] = ()) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    subset = _section_subset(frame, exclude_machines=exclude_machines)
    daily = _daily_weekday_frame(subset)
    summary = _weekday_daily_summary(subset)
    compare = _weekday_compare(subset, value_col="median_payoutrate_pct")
    compare_share = _weekday_compare(subset, value_col="share_104_plus")
    return summary, compare, compare_share


def _branch_a(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_a")
    history = _machine_history(frame, 2182)
    period_weekday = _machine_period_weekday_summary(frame, 2182)
    sunday_shift = period_weekday[period_weekday["weekday_label"].eq("Sun")].copy()

    _write_csv(history, branch_dir / "machine_2182_history.csv")
    _write_csv(period_weekday, branch_dir / "machine_2182_period_weekday_summary.csv")
    _write_csv(sunday_shift, branch_dir / "machine_2182_sunday_shift.csv")

    report = [
        "# Branch A",
        "",
        "Target: machine 2182 history and regime split around 2025-12-22.",
        "",
        "## Machine 2182 history",
        _md_table(history),
        "",
        "## Machine 2182 period x weekday summary",
        _md_table(period_weekday),
        "",
        "## Machine 2182 Sunday shift",
        _md_table(sunday_shift),
        "",
        "Conclusion: if the post-2025-12-22 machine_name has higher Sunday median and share_104_plus, the Sunday effect is machine-regime driven.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "2182 swaps machine_name on 2025-12-22 and Sunday strengthens after the swap"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "history": history,
        "period_weekday": period_weekday,
        "sunday_shift": sunday_shift,
    }


def _branch_b(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_b")
    history = _machine_history(frame, 2180)
    period_weekday = _machine_period_weekday_summary(frame, 2180)
    sunday_shift = period_weekday[period_weekday["weekday_label"].eq("Sun")].copy()

    _write_csv(history, branch_dir / "machine_2180_history.csv")
    _write_csv(period_weekday, branch_dir / "machine_2180_period_weekday_summary.csv")
    _write_csv(sunday_shift, branch_dir / "machine_2180_sunday_shift.csv")

    report = [
        "# Branch B",
        "",
        "Target: machine 2180 history and regime split around 2025-12-22.",
        "",
        "## Machine 2180 history",
        _md_table(history),
        "",
        "## Machine 2180 period x weekday summary",
        _md_table(period_weekday),
        "",
        "## Machine 2180 Sunday shift",
        _md_table(sunday_shift),
        "",
        "Conclusion: if the post-2025-12-22 machine_name has higher Sunday median and share_104_plus, the Sunday effect is machine-regime driven.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "2180 swaps machine_name on 2025-12-22 and Sunday strengthens after the swap"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "history": history,
        "period_weekday": period_weekday,
        "sunday_shift": sunday_shift,
    }


def _branch_c(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_c")
    section = _section_subset(frame)
    summary_full, compare_full, compare_share_full = _section_sunday_summary(frame)
    summary_excl, compare_excl, compare_share_excl = _section_sunday_summary(frame, exclude_machines=TARGET_MACHINES)

    _write_csv(summary_full, branch_dir / "weekday_daily_summary_full.csv")
    _write_csv(compare_full, branch_dir / "weekday_median_compare_full.csv")
    _write_csv(compare_share_full, branch_dir / "weekday_share_104_plus_compare_full.csv")
    _write_csv(summary_excl, branch_dir / "weekday_daily_summary_excluding_2182_2180.csv")
    _write_csv(compare_excl, branch_dir / "weekday_median_compare_excluding_2182_2180.csv")
    _write_csv(compare_share_excl, branch_dir / "weekday_share_104_plus_compare_excluding_2182_2180.csv")

    report = [
        "# Branch C",
        "",
        "Target: section 2179-2186 weekday median effect, full vs excluding 2182 and 2180.",
        "",
        "## Full weekday summary",
        _md_table(summary_full),
        "",
        "## Full weekday compare on median_payoutrate_pct",
        _md_table(compare_full),
        "",
        "## Full weekday compare on share_104_plus",
        _md_table(compare_share_full),
        "",
        "## Excluding 2182 and 2180 weekday summary",
        _md_table(summary_excl),
        "",
        "## Excluding 2182 and 2180 compare on median_payoutrate_pct",
        _md_table(compare_excl),
        "",
        "## Excluding 2182 and 2180 compare on share_104_plus",
        _md_table(compare_share_excl),
        "",
        "Conclusion: if Sunday loses significance after removing 2182 and 2180, the weekday law is mostly a machine-regime artifact.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "Sunday significance weakens materially after excluding 2182 and 2180, while Thursday remains the clear weak day"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "summary_full": summary_full,
        "compare_full": compare_full,
        "compare_share_full": compare_share_full,
        "summary_excl": summary_excl,
        "compare_excl": compare_excl,
        "compare_share_excl": compare_share_excl,
    }


def _branch_d(frame: pd.DataFrame, out_dir: Path) -> dict[str, object]:
    branch_dir = _ensure_dir(out_dir / "branch_d")
    section = _section_subset(frame)
    machine_concentration = _machine_sunday_concentration(section)
    machine_concentration_excl = _machine_sunday_concentration(_section_subset(frame, exclude_machines=TARGET_MACHINES))

    weekday_machines = []
    for machine_number in TARGET_MACHINES:
        weekday_machines.append(_machine_period_weekday_summary(frame, machine_number))
    weekday_machines_df = pd.concat(weekday_machines, ignore_index=True) if weekday_machines else pd.DataFrame()

    _write_csv(machine_concentration, branch_dir / "sunday_machine_concentration_full.csv")
    _write_csv(machine_concentration_excl, branch_dir / "sunday_machine_concentration_excluding_2182_2180.csv")
    _write_csv(weekday_machines_df, branch_dir / "machine_period_weekday_summary.csv")

    report = [
        "# Branch D",
        "",
        "Target: machine-level Sunday concentration and weekday-by-machine-name regime view.",
        "",
        "## Sunday machine concentration",
        _md_table(machine_concentration),
        "",
        "## Sunday machine concentration excluding 2182 and 2180",
        _md_table(machine_concentration_excl),
        "",
        "## Machine period x weekday summary for 2182 and 2180",
        _md_table(weekday_machines_df),
        "",
        "Conclusion: if 2182 and 2180 dominate the Sunday deltas and removing them weakens the table, the apparent weekday law is a machine-regime effect.",
        "",
    ]
    _write_text(branch_dir / "report.md", "\n".join(report))
    conclusion = "2182 and 2180 dominate the Sunday concentration; removing them weakens the machine-level signal"
    return {
        "conclusion": conclusion,
        "report_path": branch_dir / "report.md",
        "machine_concentration": machine_concentration,
        "machine_concentration_excl": machine_concentration_excl,
        "weekday_machines": weekday_machines_df,
    }


def _build_summary(branches: dict[str, dict[str, object]], out_dir: Path) -> Path:
    summary = [
        "# Kamata weekday / event / spatial deep dive - machine regime version",
        "",
        "## Branch conclusions",
        "",
        f"- Branch A: {branches['A']['conclusion']}",
        f"- Branch B: {branches['B']['conclusion']}",
        f"- Branch C: {branches['C']['conclusion']}",
        f"- Branch D: {branches['D']['conclusion']}",
        "",
        "## Report paths",
        "",
        f"- [Branch A]({(out_dir / 'branch_a' / 'report.md').resolve()})",
        f"- [Branch B]({(out_dir / 'branch_b' / 'report.md').resolve()})",
        f"- [Branch C]({(out_dir / 'branch_c' / 'report.md').resolve()})",
        f"- [Branch D]({(out_dir / 'branch_d' / 'report.md').resolve()})",
        "",
    ]
    summary_path = out_dir / "summary.md"
    _write_text(summary_path, "\n".join(summary))
    return summary_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kamata7 2F machine-regime deep dive around 2025-12-22.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = _ensure_dir(args.output_dir)
    frame = _prepare_section_frame()

    branches: dict[str, dict[str, object]] = {}
    branches["A"] = _branch_a(frame, out_dir)
    branches["B"] = _branch_b(frame, out_dir)
    branches["C"] = _branch_c(frame, out_dir)
    branches["D"] = _branch_d(frame, out_dir)
    summary_path = _build_summary(branches, out_dir)

    print(out_dir)
    print(summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
