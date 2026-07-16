from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "document"
RUN_DATE = pd.Timestamp.today().strftime("%Y%m%d")


@dataclass(frozen=True)
class HallConfig:
    hall_key: str
    hall_name: str
    db_name: str
    segment_definitions: Callable[[pd.DataFrame], None]
    min_games: int = 400

    @property
    def db_path(self) -> Path:
        return PROJECT_ROOT / "db" / self.db_name


@dataclass(frozen=True)
class SchemaColumns:
    detail_date: str
    detail_machine_name: str
    detail_machine_number: str
    detail_games: str
    detail_diff: str
    detail_rate_source: str | None
    daily_date: str
    daily_total_games: str
    daily_total_diff: str
    daily_rate_source: str | None
    layout_machine_number: str
    layout_section: str
    layout_rank_from_aisle: str | None


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _require_columns(table: str, available: set[str], required: list[str]) -> None:
    missing = [name for name in required if name not in available]
    if missing:
        raise RuntimeError(f"{table} missing required columns: {missing}")


def _pick_rate_source(available: set[str]) -> str | None:
    if "win_rate" in available:
        return "win_rate"
    if "payout_rate" in available:
        return "payout_rate"
    return None


def _inspect_schema(conn: sqlite3.Connection) -> SchemaColumns:
    detail_cols = _table_columns(conn, "machine_detailed_results")
    layout_cols = _table_columns(conn, "machine_layout")
    daily_cols = _table_columns(conn, "daily_hall_summary")

    _require_columns(
        "machine_detailed_results",
        detail_cols,
        ["date", "machine_name", "machine_number", "games_normalized", "diff_coins_normalized"],
    )
    _require_columns("machine_layout", layout_cols, ["machine_number", "section"])
    _require_columns("daily_hall_summary", daily_cols, ["date", "total_games", "total_diff_coins"])

    return SchemaColumns(
        detail_date="date",
        detail_machine_name="machine_name",
        detail_machine_number="machine_number",
        detail_games="games_normalized",
        detail_diff="diff_coins_normalized",
        detail_rate_source=_pick_rate_source(detail_cols),
        daily_date="date",
        daily_total_games="total_games",
        daily_total_diff="total_diff_coins",
        daily_rate_source=_pick_rate_source(daily_cols),
        layout_machine_number="machine_number",
        layout_section="section",
        layout_rank_from_aisle="rank_from_aisle" if "rank_from_aisle" in layout_cols else None,
    )


def _load_tables(conn: sqlite3.Connection, schema: SchemaColumns) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail_select = [
        schema.detail_date,
        schema.detail_machine_name,
        schema.detail_machine_number,
        schema.detail_games,
        schema.detail_diff,
    ]
    if schema.detail_rate_source:
        detail_select.append(schema.detail_rate_source)

    daily_select = [
        schema.daily_date,
        "total_machines",
        schema.daily_total_games,
        schema.daily_total_diff,
        "avg_games_per_machine",
        "avg_diff_per_machine",
    ]
    if schema.daily_rate_source:
        daily_select.append(schema.daily_rate_source)

    layout_select = [
        schema.layout_machine_number,
        "hall_name",
        "x",
        "y",
        "display_y",
        schema.layout_section,
        "section_min",
        "section_max",
        "rank_from_min",
        "rank_from_max",
    ]
    if schema.layout_rank_from_aisle:
        layout_select.append(schema.layout_rank_from_aisle)

    daily = pd.read_sql_query(f"SELECT {', '.join(daily_select)} FROM daily_hall_summary", conn)
    machine = pd.read_sql_query(f"SELECT {', '.join(detail_select)} FROM machine_detailed_results", conn)
    layout = pd.read_sql_query(f"SELECT {', '.join(layout_select)} FROM machine_layout", conn)
    return daily, machine, layout


def _normalize_dates(frame: pd.DataFrame, date_col: str) -> pd.DataFrame:
    work = frame.copy()
    work[date_col] = work[date_col].astype(str).str.strip()
    if not work[date_col].str.fullmatch(r"\d{8}").all():
        bad = work.loc[~work[date_col].str.fullmatch(r"\d{8}"), date_col].head(10).tolist()
        raise RuntimeError(f"unexpected date format values: {bad}")
    work["date_dt"] = pd.to_datetime(work[date_col], format="%Y%m%d", errors="raise")
    work["dd"] = work["date_dt"].dt.day.astype(int)
    return work


def _detect_jug(machine_name: pd.Series) -> pd.Series:
    return machine_name.astype(str).str.contains("ジャグラー", na=False)


def _compute_rate_metric(games: pd.Series, diff: pd.Series) -> pd.Series:
    games_num = pd.to_numeric(games, errors="coerce")
    diff_num = pd.to_numeric(diff, errors="coerce")
    denom = games_num * 3.0
    rate = pd.Series(np.nan, index=games_num.index, dtype="float64")
    valid = denom.notna() & diff_num.notna() & denom.ne(0)
    rate.loc[valid] = ((denom.loc[valid] + diff_num.loc[valid]) / denom.loc[valid]) * 100.0
    return rate


def _attach_rate_metric(
    frame: pd.DataFrame,
    *,
    source_col: str | None,
    games_col: str,
    diff_col: str,
    metric_col: str,
) -> pd.DataFrame:
    work = frame.copy()
    if source_col and source_col in work.columns:
        work[metric_col] = pd.to_numeric(work[source_col], errors="coerce")
    else:
        work[metric_col] = _compute_rate_metric(work[games_col], work[diff_col])
    return work


def _build_instances(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.sort_values(["machine_number", "date_dt"], kind="mergesort").copy()
    work["machine_name"] = work["machine_name"].astype(str)
    work["prev_name"] = work.groupby("machine_number")["machine_name"].shift(1)
    work["name_change"] = work["machine_name"].ne(work["prev_name"]).fillna(True)
    work["instance_seq"] = work.groupby("machine_number")["name_change"].cumsum().astype(int)
    instance_meta = work.groupby(["machine_number", "instance_seq"], as_index=False).agg(
        machine_name=("machine_name", "first"),
        instance_start=("date_dt", "min"),
        instance_end=("date_dt", "max"),
        instance_days=("date_dt", "size"),
        first_14_games_mean=("games_normalized", lambda s: float(pd.to_numeric(s, errors="coerce").head(14).mean())),
    )
    instance_meta["machine_instance_id"] = instance_meta.apply(
        lambda row: (
            f"{int(row['machine_number'])}|{row['machine_name']}|"
            f"{row['instance_start'].strftime('%Y%m%d')}-{row['instance_end'].strftime('%Y%m%d')}"
        ),
        axis=1,
    )
    work = work.merge(
        instance_meta.loc[
            :,
            [
                "machine_number",
                "instance_seq",
                "machine_instance_id",
                "instance_start",
                "instance_end",
                "instance_days",
                "first_14_games_mean",
            ],
        ],
        on=["machine_number", "instance_seq"],
        how="left",
        validate="many_to_one",
    )
    work["instance_day_index"] = work.groupby(["machine_number", "instance_seq"]).cumcount() + 1
    work["new_machine_flag"] = (
        (work["instance_day_index"] <= 14)
        & (work["instance_days"] >= 14)
        & (pd.to_numeric(work["games_normalized"], errors="coerce") >= 3500)
    )
    work["machine_name_is_jug"] = _detect_jug(work["machine_name"])
    return work


def _aggregate_dd_metrics(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    instance_col: str,
    excluded_dates: set[str],
) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = work["date"].astype(str)
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["rate_metric"] = pd.to_numeric(work["rate_metric"], errors="coerce")

    work["exclusion_flag"] = work["date"].isin(excluded_dates)
    work["exclusion_reason"] = np.where(work["exclusion_flag"], "known_special_day", "")
    included = work.loc[~work["exclusion_flag"]].copy()

    output_columns = group_cols + [
        instance_col,
        "dd",
        "avg_diff_on_dd",
        "n_dd",
        "rate_104_on_dd",
        "avg_winrate_on_dd",
        "avg_diff_non_dd",
        "rate_104_non_dd",
        "avg_winrate_non_dd",
    ]
    if included.empty:
        return pd.DataFrame(columns=output_columns)

    agg_rows: list[dict[str, object]] = []
    for keys, group in included.groupby(group_cols + [instance_col], dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_map = dict(zip(group_cols + [instance_col], keys))

        for dd, dd_group in group.groupby("dd", dropna=False, sort=True):
            dd_rates = dd_group["rate_metric"].dropna()
            dd_n = int(len(dd_group))
            dd_rate_104 = float(dd_rates.ge(104).mean()) if len(dd_rates) else np.nan
            dd_rate_mean = float(dd_rates.mean()) if len(dd_rates) else np.nan
            dd_diff = float(dd_group["diff_coins_normalized"].mean())

            non_dd_group = group.loc[group["dd"] != dd]
            non_dd_rates = non_dd_group["rate_metric"].dropna()
            non_dd_rate_104 = float(non_dd_rates.ge(104).mean()) if len(non_dd_rates) else np.nan
            non_dd_rate_mean = float(non_dd_rates.mean()) if len(non_dd_rates) else np.nan
            non_dd_diff = float(non_dd_group["diff_coins_normalized"].mean()) if len(non_dd_group) else np.nan

            agg_rows.append(
                {
                    **key_map,
                    "dd": int(dd),
                    "avg_diff_on_dd": dd_diff,
                    "n_dd": dd_n,
                    "rate_104_on_dd": dd_rate_104,
                    "avg_winrate_on_dd": dd_rate_mean,
                    "avg_diff_non_dd": non_dd_diff,
                    "rate_104_non_dd": non_dd_rate_104,
                    "avg_winrate_non_dd": non_dd_rate_mean,
                }
            )

    result = pd.DataFrame(agg_rows)
    if result.empty:
        return result

    result["low_confidence"] = result["n_dd"] < 10
    result = result.merge(
        included.loc[
            :, group_cols + [instance_col, "new_machine_flag", "exclusion_flag", "exclusion_reason"]
        ].drop_duplicates(subset=group_cols + [instance_col]),
        on=group_cols + [instance_col],
        how="left",
        validate="many_to_one",
    )
    result["new_machine_flag"] = result["new_machine_flag"].fillna(False).astype(bool)
    result["exclusion_flag"] = result["exclusion_flag"].fillna(False).astype(bool)
    result["exclusion_reason"] = result["exclusion_reason"].fillna("")
    return result


def _define_kamata7_segments(frame: pd.DataFrame) -> None:
    frame["segment"] = frame["section"].astype("string")


def _define_kamata1_segments(frame: pd.DataFrame) -> None:
    frame["segment"] = frame["section"].astype("string")


def _define_rakuen_segments(frame: pd.DataFrame) -> None:
    frame["segment"] = frame["section"].astype("string")


def _build_baseline(daily: pd.DataFrame, excluded_dates: set[str]) -> pd.DataFrame:
    work = daily.copy()
    work["date"] = work["date"].astype(str)
    work["total_diff_coins"] = pd.to_numeric(work["total_diff_coins"], errors="coerce")
    work["rate_metric"] = pd.to_numeric(work["rate_metric"], errors="coerce")
    work["dd"] = pd.to_datetime(work["date"], format="%Y%m%d").dt.day

    included = work.loc[~work["date"].isin(excluded_dates)].copy()
    overall_diff = float(included["total_diff_coins"].mean())
    overall_rate = float(included["rate_metric"].mean())

    rows = []
    for dd, group in included.groupby("dd", sort=True):
        rows.append(
            {
                "dd": int(dd),
                "hall_avg_diff_on_dd": float(group["total_diff_coins"].mean()),
                "hall_overall_avg_diff": overall_diff,
                "hallwide_dd_baseline_lift": float(group["total_diff_coins"].mean()) - overall_diff,
                "hall_avg_winrate_on_dd": float(group["rate_metric"].mean()),
                "hall_overall_avg_winrate": overall_rate,
                "n_days": int(len(group)),
            }
        )
    return pd.DataFrame(rows).sort_values("dd").reset_index(drop=True)


def _summarize_output(frame: pd.DataFrame, label: str) -> None:
    print(f"== {label} ==")
    print(f"rows: {len(frame)}")
    if not frame.empty:
        print(f"segments: {sorted(frame['segment'].dropna().astype(str).unique().tolist())}")
        print(f"low_confidence_rate: {frame['low_confidence'].mean():.3f}")
        print(frame.head(3).to_string(index=False))
    print()


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Multi-hall DD sweep analysis")
    parser.add_argument("--hall", choices=["kamata7", "kamata1", "rakuen"], required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    configs = {
        "kamata7": HallConfig(
            "kamata7", "マルハンメガシティ2000-蒲田7", "マルハンメガシティ2000-蒲田7.db", _define_kamata7_segments
        ),
        "kamata1": HallConfig(
            "kamata1", "マルハンメガシティ2000-蒲田1", "マルハンメガシティ2000-蒲田1.db", _define_kamata1_segments
        ),
        "rakuen": HallConfig("rakuen", "楽園蒲田店", "楽園蒲田店.db", _define_rakuen_segments),
    }

    config = configs[args.hall]
    if not config.db_path.exists():
        raise FileNotFoundError(config.db_path)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(config.db_path)) as conn:
        schema = _inspect_schema(conn)
        daily, machine, layout = _load_tables(conn, schema)

    daily = _normalize_dates(daily, "date")
    machine = _normalize_dates(machine, "date")

    daily = _attach_rate_metric(
        daily,
        source_col=schema.daily_rate_source,
        games_col="total_games",
        diff_col="total_diff_coins",
        metric_col="rate_metric",
    )
    machine = _attach_rate_metric(
        machine,
        source_col=schema.detail_rate_source,
        games_col="games_normalized",
        diff_col="diff_coins_normalized",
        metric_col="rate_metric",
    )

    layout = layout.copy()
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce").astype("Int64")
    if "rank_from_aisle" in layout.columns:
        layout["rank_from_aisle"] = pd.to_numeric(layout["rank_from_aisle"], errors="coerce").astype("Int64")

    machine = machine.merge(
        layout.loc[:, ["machine_number", "section", "rank_from_aisle"]],
        on="machine_number",
        how="left",
        validate="many_to_one",
    )
    machine["machine_name_is_jug"] = _detect_jug(machine["machine_name"])
    config.segment_definitions(machine)

    instance_frame = _build_instances(machine)
    instance_frame["machine_name_is_jug"] = _detect_jug(instance_frame["machine_name"])
    instance_frame = instance_frame.merge(
        layout.loc[:, ["machine_number", "section", "rank_from_aisle"]],
        on="machine_number",
        how="left",
        suffixes=("", "_layout"),
        validate="many_to_one",
    )
    config.segment_definitions(instance_frame)

    included_machine = instance_frame.loc[instance_frame["segment"].notna()].copy()
    excluded_dates: set[str] = set()

    primary = _aggregate_dd_metrics(
        included_machine,
        group_cols=["segment"],
        instance_col="machine_instance_id",
        excluded_dates=excluded_dates,
    )
    primary = primary.merge(
        included_machine.loc[
            :,
            [
                "machine_instance_id",
                "machine_number",
                "machine_name",
                "section",
                "rank_from_aisle",
                "instance_start",
                "instance_end",
            ],
        ].drop_duplicates(subset=["machine_instance_id"]),
        on="machine_instance_id",
        how="left",
        validate="many_to_one",
    )
    primary["instance_start"] = pd.to_datetime(primary["instance_start"]).dt.strftime("%Y%m%d")
    primary["instance_end"] = pd.to_datetime(primary["instance_end"]).dt.strftime("%Y%m%d")
    primary = primary.sort_values(["dd", "segment", "machine_instance_id"], kind="mergesort").reset_index(drop=True)

    reference = _aggregate_dd_metrics(
        included_machine,
        group_cols=["segment"],
        instance_col="machine_number",
        excluded_dates=excluded_dates,
    )
    reference = reference.merge(
        included_machine.loc[:, ["machine_number", "machine_name", "section", "rank_from_aisle"]].drop_duplicates(
            subset=["machine_number"]
        ),
        on="machine_number",
        how="left",
        validate="many_to_one",
    )
    reference["machine_instance_id"] = reference["machine_number"].map(lambda value: f"slot_{int(value)}")
    reference["machine_name"] = "ALL_MODELS"
    reference = reference.sort_values(["dd", "segment", "machine_number"], kind="mergesort").reset_index(drop=True)

    baseline = _build_baseline(daily, excluded_dates)

    prefix = config.hall_name.replace(" ", "").replace("/", "_")
    primary_path = args.output_dir / f"{prefix}_dd_sweep_primary_{RUN_DATE}.csv"
    reference_path = args.output_dir / f"{prefix}_dd_sweep_reference_{RUN_DATE}.csv"
    baseline_path = args.output_dir / f"{prefix}_dd_hallwide_baseline_{RUN_DATE}.csv"

    primary.to_csv(primary_path, index=False, encoding="utf-8-sig")
    reference.to_csv(reference_path, index=False, encoding="utf-8-sig")
    baseline.to_csv(baseline_path, index=False, encoding="utf-8-sig")

    print(f"written: {primary_path}")
    print(f"written: {reference_path}")
    print(f"written: {baseline_path}")

    _summarize_output(primary, "primary")
    _summarize_output(reference, "reference")
    print("baseline rows:", len(baseline))
    print(baseline.head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
