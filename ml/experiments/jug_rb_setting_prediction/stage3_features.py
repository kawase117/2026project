from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_DBS, HALL_SLUGS

STAGE2_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "G",
    "rb",
    "bb",
    "p_high",
]

STAGE3_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "G",
    "rb",
    "bb",
    "p_high",
    "e_setting",
    "e_payout",
    "kakuban_rank_min",
    "kakuban_rank_max",
    "section_size",
    "is_corner1",
    "side_lr",
    "b_machine_90d",
    "b_machine_180d",
    "p_high_lag1",
    "p_high_lag2",
    "p_high_lag1_event",
    "days_since_high",
    "high_freq_same_weekday",
    "weekday",
    "is_mon",
    "is_tue",
    "is_wed",
    "is_thu",
    "is_fri",
    "is_sat",
    "is_sun",
    "day_of_month",
    "day_suffix",
    "is_zorome",
    "is_strong_zorome",
    "is_month_end",
    "is_month_start",
    "is_event_day",
]


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_stage2_csv(hall: str, stage2_csv: Path | None = None) -> Path:
    if stage2_csv is not None:
        return Path(stage2_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage2_daily_posterior.csv"


def _load_stage2_posterior(stage2_csv: Path) -> pd.DataFrame:
    if not stage2_csv.exists():
        raise FileNotFoundError(stage2_csv)
    return pd.read_csv(stage2_csv, encoding="utf-8-sig")


def _load_machine_layout(hall: str) -> pd.DataFrame:
    db_path = HALL_DBS[hall]
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    query = """
        select
            machine_number,
            x,
            section,
            section_min,
            section_max,
            rank_from_min,
            rank_from_max
        from machine_layout
    """
    with sqlite3.connect(str(db_path)) as conn:
        layout = pd.read_sql_query(query, conn)

    required = ["machine_number", "x", "section", "section_min", "section_max", "rank_from_min", "rank_from_max"]
    missing = [column for column in required if column not in layout.columns]
    if missing:
        raise ValueError(f"machine_layout is missing required columns: {missing}")

    numeric_required = [column for column in required if column != "section"]
    for column in numeric_required:
        layout[column] = pd.to_numeric(layout[column], errors="coerce")
    layout["section"] = layout["section"].astype(str)
    layout = layout.dropna(subset=numeric_required).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["kakuban_rank_min"] = layout["rank_from_min"].astype(int)
    layout["kakuban_rank_max"] = layout["rank_from_max"].astype(int)
    layout["section_size"] = (layout["section_max"] - layout["section_min"] + 1).astype(int)
    layout["is_corner1"] = layout[["rank_from_min", "rank_from_max"]].eq(1).any(axis=1).astype(int)
    section_medians = layout.groupby("section", dropna=False)["x"].transform("median")
    layout["side_lr"] = np.where(layout["x"].lt(section_medians), "L", "R")
    return layout.loc[
        :, ["machine_number", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"]
    ].copy()


def _prepare_input(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    missing = [column for column in STAGE2_REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        raise ValueError(f"stage2 frame is missing required columns: {missing}")

    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["machine_name"] = work["machine_name"].astype(str)
    work["G"] = pd.to_numeric(work["G"], errors="coerce")
    work["rb"] = pd.to_numeric(work["rb"], errors="coerce")
    work["bb"] = pd.to_numeric(work["bb"], errors="coerce")
    work["p_high"] = pd.to_numeric(work["p_high"], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "G", "rb", "bb", "p_high"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)
    work["hall"] = hall
    return work


def _add_calendar_features(work: pd.DataFrame) -> pd.DataFrame:
    work = work.copy()
    work["weekday"] = work["date_dt"].dt.weekday.astype(int)
    work["is_mon"] = work["weekday"].eq(0).astype(int)
    work["is_tue"] = work["weekday"].eq(1).astype(int)
    work["is_wed"] = work["weekday"].eq(2).astype(int)
    work["is_thu"] = work["weekday"].eq(3).astype(int)
    work["is_fri"] = work["weekday"].eq(4).astype(int)
    work["is_sat"] = work["weekday"].eq(5).astype(int)
    work["is_sun"] = work["weekday"].eq(6).astype(int)
    work["day_of_month"] = work["date_dt"].dt.day.astype(int)
    work["day_suffix"] = (work["day_of_month"] % 10).astype(int)
    work["is_zorome"] = work["day_of_month"].isin([11, 22]).astype(int)
    work["is_strong_zorome"] = work["day_of_month"].eq(work["date_dt"].dt.month).astype(int)
    work["is_month_end"] = work["date_dt"].dt.is_month_end.astype(int)
    work["is_month_start"] = work["date_dt"].dt.is_month_start.astype(int)
    return work


def _add_lag_features(work: pd.DataFrame) -> pd.DataFrame:
    base = work.loc[:, ["machine_number", "date_dt", "p_high"]].copy()
    lag1 = base.copy()
    lag1["date_dt"] = lag1["date_dt"] + pd.Timedelta(days=1)
    lag1 = lag1.rename(columns={"p_high": "p_high_lag1"})
    lag2 = base.copy()
    lag2["date_dt"] = lag2["date_dt"] + pd.Timedelta(days=2)
    lag2 = lag2.rename(columns={"p_high": "p_high_lag2"})

    merged = work.merge(lag1, on=["machine_number", "date_dt"], how="left", validate="one_to_one")
    merged = merged.merge(lag2, on=["machine_number", "date_dt"], how="left", validate="one_to_one")
    return merged


def _add_same_weekday_feature(work: pd.DataFrame) -> pd.DataFrame:
    grouped = work.groupby(["machine_number", "weekday"], sort=False)["p_high"]
    cumcount = grouped.cumcount()
    cumsum = grouped.cumsum()
    same_weekday = np.where(cumcount > 0, (cumsum - work["p_high"]) / cumcount, np.nan)
    work = work.copy()
    work["high_freq_same_weekday"] = same_weekday
    return work


def _add_event_lag(work: pd.DataFrame) -> pd.DataFrame:
    def _per_machine(group: pd.DataFrame) -> pd.Series:
        previous_event_high = np.nan
        values: list[float] = []
        for is_event, p_high in zip(group["is_event_day"].astype(int), group["p_high"].astype(float)):
            values.append(previous_event_high)
            if is_event:
                previous_event_high = float(p_high)
        return pd.Series(values, index=group.index, dtype=float)

    work = work.copy()
    work["p_high_lag1_event"] = work.groupby("machine_number", group_keys=False, sort=False).apply(_per_machine)
    return work


def _add_days_since_high(work: pd.DataFrame) -> pd.DataFrame:
    def _per_machine(group: pd.DataFrame) -> pd.Series:
        last_high = group["date_dt"].where(group["p_high"].gt(0.5)).ffill().shift(1)
        delta = (group["date_dt"] - last_high).dt.days
        return delta.fillna(30).clip(upper=30)

    work = work.copy()
    work["days_since_high"] = work.groupby("machine_number", group_keys=False).apply(_per_machine)
    return work


def _add_machine_window_features(work: pd.DataFrame) -> pd.DataFrame:
    indexed = work.loc[:, ["machine_number", "date_dt", "p_high"]].copy().set_index("date_dt")
    rolling_90 = (
        indexed.groupby("machine_number")["p_high"]
        .rolling("90D", closed="left")
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "machine_mean_90d", "count": "machine_n_90d"})
    )
    rolling_180 = (
        indexed.groupby("machine_number")["p_high"]
        .rolling("180D", closed="left")
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "machine_mean_180d", "count": "machine_n_180d"})
    )
    merged = work.merge(rolling_90, on=["machine_number", "date_dt"], how="left", validate="one_to_one")
    merged = merged.merge(rolling_180, on=["machine_number", "date_dt"], how="left", validate="one_to_one")
    return merged


def _add_hall_window_features(work: pd.DataFrame) -> pd.DataFrame:
    daily = (
        work.groupby("date_dt", sort=True)["p_high"]
        .agg(hall_sum="sum", hall_n="size")
        .reset_index()
        .set_index("date_dt")
    )
    hall_90_sum = daily["hall_sum"].rolling("90D", closed="left").sum()
    hall_90_n = daily["hall_n"].rolling("90D", closed="left").sum()
    hall_180_sum = daily["hall_sum"].rolling("180D", closed="left").sum()
    hall_180_n = daily["hall_n"].rolling("180D", closed="left").sum()
    hall_daily = pd.DataFrame(
        {
            "hall_mean_90d": np.divide(hall_90_sum, hall_90_n, out=np.full(len(daily), np.nan), where=hall_90_n.gt(0)),
            "hall_mean_180d": np.divide(
                hall_180_sum, hall_180_n, out=np.full(len(daily), np.nan), where=hall_180_n.gt(0)
            ),
        }
    ).reset_index(names="date_dt")
    return work.merge(hall_daily, on="date_dt", how="left", validate="many_to_one")


def _shrink_toward_hall(machine_mean: pd.Series, machine_n: pd.Series, hall_mean: pd.Series) -> pd.Series:
    weight = machine_n / (machine_n + 20.0)
    shrunk = weight * machine_mean + (1.0 - weight) * hall_mean
    return pd.Series(np.where(machine_n.gt(0), shrunk, hall_mean), index=machine_mean.index, dtype=float)


def _add_layout_features(work: pd.DataFrame, *, hall: str, layout_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    layout = layout_frame.copy() if layout_frame is not None else _load_machine_layout(hall)
    required = ["machine_number", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"]
    missing = [column for column in required if column not in layout.columns]
    if missing:
        raise ValueError(f"layout frame is missing required columns: {missing}")

    layout = layout.loc[:, required].copy()
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce")
    for column in ["kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1"]:
        layout[column] = pd.to_numeric(layout[column], errors="coerce")
    layout["side_lr"] = layout["side_lr"].astype(str)
    layout = layout.dropna(
        subset=["machine_number", "kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1"]
    ).copy()
    layout["machine_number"] = layout["machine_number"].astype(int)
    layout["kakuban_rank_min"] = layout["kakuban_rank_min"].astype(int)
    layout["kakuban_rank_max"] = layout["kakuban_rank_max"].astype(int)
    layout["section_size"] = layout["section_size"].astype(int)
    layout["is_corner1"] = layout["is_corner1"].astype(int)

    if layout.empty or not work["machine_number"].isin(set(layout["machine_number"].astype(int).tolist())).any():
        work = work.copy()
        for column in ["kakuban_rank_min", "kakuban_rank_max", "section_size", "is_corner1", "side_lr"]:
            work[column] = np.nan
        return work

    return work.merge(layout, on="machine_number", how="left", validate="many_to_one")


def _add_event_flag(work: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = work.copy()
    if _hall_slug(hall) != "kamata7":
        work["is_event_day"] = 0
        return work

    day = work["day_of_month"]
    month_end = work["date_dt"].dt.days_in_month
    event_day = day.isin([1, 7, 11, 17, 21, 27, 30]) | day.eq(22) | day.eq(work["date_dt"].dt.month) | day.eq(month_end)
    work["is_event_day"] = event_day.astype(int)
    return work


def build_stage3_features(frame: pd.DataFrame, *, hall: str, layout_frame: pd.DataFrame | None = None) -> pd.DataFrame:
    work = _prepare_input(frame, hall=hall)
    if work.empty:
        return pd.DataFrame(columns=STAGE3_COLUMNS)

    work = _add_calendar_features(work)
    work = _add_lag_features(work)
    work = _add_same_weekday_feature(work)
    work = _add_days_since_high(work)
    work = _add_machine_window_features(work)
    work = _add_hall_window_features(work)
    work = _add_layout_features(work, hall=hall, layout_frame=layout_frame)

    work["b_machine_90d"] = _shrink_toward_hall(work["machine_mean_90d"], work["machine_n_90d"], work["hall_mean_90d"])
    work["b_machine_180d"] = _shrink_toward_hall(
        work["machine_mean_180d"], work["machine_n_180d"], work["hall_mean_180d"]
    )
    work = _add_event_flag(work, hall=hall)
    work = _add_event_lag(work)

    return work.loc[:, STAGE3_COLUMNS].copy()


def save_stage3_features(features: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    features.to_csv(output_dir / "stage3_features.csv", index=False, encoding="utf-8-sig")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 3 juggler RB setting features")
    parser.add_argument("--hall", choices=tuple(HALL_SLUGS.keys()), default=DEFAULT_HALL)
    parser.add_argument("--stage2-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    args = build_parser().parse_args(argv)
    stage2_csv = _resolve_stage2_csv(args.hall, args.stage2_csv)
    output_dir = Path(args.output_dir) if args.output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall)
    frame = _load_stage2_posterior(stage2_csv)
    features = build_stage3_features(frame, hall=args.hall)
    save_stage3_features(features, output_dir)
    print(output_dir / "stage3_features.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
