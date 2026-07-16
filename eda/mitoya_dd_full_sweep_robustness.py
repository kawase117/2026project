from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "みとや大森町店.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "document"
RUN_DATE = pd.Timestamp.today().strftime("%Y%m%d")


@dataclass(frozen=True)
class SchemaColumns:
    date: str
    machine_name: str
    machine_number: str
    games: str
    diff: str
    section: str
    rank_from_aisle: str
    is_reversed_section: str


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya DD full sweep robustness analysis")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def _require_columns(table: str, available: set[str], required: list[str]) -> None:
    missing = [name for name in required if name not in available]
    if missing:
        raise RuntimeError(f"{table} missing required columns: {missing}")


def _inspect_schema(conn: sqlite3.Connection) -> SchemaColumns:
    layout_cols = {row[1] for row in conn.execute("PRAGMA table_info(machine_layout)")}
    md_cols = {row[1] for row in conn.execute("PRAGMA table_info(machine_detailed_results)")}

    _require_columns(
        "machine_layout",
        layout_cols,
        ["section", "rank_from_aisle", "is_reversed_section", "machine_number"],
    )
    _require_columns(
        "machine_detailed_results",
        md_cols,
        ["date", "machine_name", "machine_number", "games_normalized", "diff_coins_normalized"],
    )
    return SchemaColumns(
        date="date",
        machine_name="machine_name",
        machine_number="machine_number",
        games="games_normalized",
        diff="diff_coins_normalized",
        section="section",
        rank_from_aisle="rank_from_aisle",
        is_reversed_section="is_reversed_section",
    )


def _load_tables(conn: sqlite3.Connection, schema: SchemaColumns) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = pd.read_sql_query(
        """
        SELECT date, total_machines, total_games, total_diff_coins, avg_games_per_machine, avg_diff_per_machine,
               win_rate, day_of_week, last_digit, weekday_nth, is_strong_zorome, is_zorome,
               is_month_start, is_month_end, is_weekend, is_holiday, hall_anniversary, is_x_day,
               week_of_month, is_any_event
        FROM daily_hall_summary
        """,
        conn,
    )
    machine = pd.read_sql_query(
        f"""
        SELECT {schema.date}, {schema.machine_name}, {schema.machine_number},
               {schema.games}, {schema.diff}
        FROM machine_detailed_results
        """,
        conn,
    )
    layout = pd.read_sql_query(
        f"""
        SELECT machine_number, hall_name, section, section_min, section_max,
               rank_from_min, rank_from_max, is_reversed_section, rank_from_aisle
        FROM machine_layout
        """,
        conn,
    )
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


def _detect_anomalous_dates(daily: pd.DataFrame) -> dict[str, str]:
    work = daily.copy()
    work["date"] = work["date"].astype(str)
    special = work.loc[work["date"].str.endswith("0707"), "date"].tolist()
    flagged: dict[str, str] = {}
    for date in special:
        flagged[date] = "known_special_day_0707"
    return flagged


def _detect_jug(machine_name: pd.Series) -> pd.Series:
    return machine_name.astype(str).str.contains("ジャグラー", na=False)


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
        early_games_mean=("games_normalized", lambda s: float(pd.to_numeric(s, errors="coerce").head(14).mean())),
        first_14_games_mean=("games_normalized", lambda s: float(pd.to_numeric(s, errors="coerce").head(14).mean())),
    )
    instance_meta["machine_instance_id"] = instance_meta.apply(
        lambda row: (
            f"{int(row['machine_number'])}|{row['machine_name']}|{row['instance_start'].strftime('%Y%m%d')}-{row['instance_end'].strftime('%Y%m%d')}"
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


def _aggregate_dd_lift(
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
    work["exclusion_flag"] = work["date"].isin(excluded_dates)
    work["exclusion_reason"] = np.where(work["exclusion_flag"], "known_special_day_0707", "")
    included = work.loc[~work["exclusion_flag"]].copy()
    if included.empty:
        return pd.DataFrame(
            columns=group_cols
            + [instance_col, "avg_diff_on_dd", "n_dd", "avg_diff_non_dd", "n_non_dd", "dd_specific_lift"]
        )

    agg_rows: list[dict[str, object]] = []
    for keys, group in included.groupby(group_cols + [instance_col], dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_map = dict(zip(group_cols + [instance_col], keys, strict=False))
        for dd, dd_group in group.groupby("dd", dropna=False, sort=True):
            dd_diff = dd_group["diff_coins_normalized"].mean()
            dd_n = int(len(dd_group))
            non_dd_group = group.loc[group["dd"] != dd]
            non_dd_diff = float(non_dd_group["diff_coins_normalized"].mean()) if len(non_dd_group) else np.nan
            non_dd_n = int(len(non_dd_group))
            agg_rows.append(
                {
                    **key_map,
                    "dd": int(dd),
                    "avg_diff_on_dd": float(dd_diff),
                    "n_dd": dd_n,
                    "avg_diff_non_dd": non_dd_diff,
                    "n_non_dd": non_dd_n,
                    "dd_specific_lift": float(dd_diff - non_dd_diff) if pd.notna(non_dd_diff) else np.nan,
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


def _attach_single_machine_dominance_flag(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if work.empty:
        work["single_machine_dominance_flag"] = pd.Series(dtype="bool")
        return work

    contribution = pd.to_numeric(work["avg_diff_on_dd"], errors="coerce") * pd.to_numeric(work["n_dd"], errors="coerce")
    work["_dominance_contribution"] = contribution.abs()
    group_total = work.groupby(["segment", "rank_from_aisle", "dd"], dropna=False)["_dominance_contribution"].transform(
        "sum"
    )
    work["single_machine_dominance_flag"] = (group_total > 0) & ((work["_dominance_contribution"] / group_total) >= 0.5)
    work = work.drop(columns=["_dominance_contribution"])
    return work


def _build_baseline(daily: pd.DataFrame, excluded_dates: set[str]) -> pd.DataFrame:
    work = daily.copy()
    work["date"] = work["date"].astype(str)
    work["total_diff_coins"] = pd.to_numeric(work["total_diff_coins"], errors="coerce")
    work["dd"] = pd.to_datetime(work["date"], format="%Y%m%d").dt.day
    included = work.loc[~work["date"].isin(excluded_dates)].copy()
    overall = float(included["total_diff_coins"].mean())
    rows = []
    for dd, group in included.groupby("dd", sort=True):
        dd_avg = float(group["total_diff_coins"].mean())
        rows.append(
            {
                "dd": int(dd),
                "hall_avg_diff_on_dd": dd_avg,
                "hall_overall_avg_diff": overall,
                "hallwide_dd_baseline_lift": dd_avg - overall,
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
        print(f"new_machine_flag_rate: {frame['new_machine_flag'].mean():.3f}")
        print(frame.head(3).to_string(index=False))
    print()


def _cross_check(primary: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    checks = [
        {
            "source": "reference",
            "machine_number": 518,
            "dd": 14,
            "machine_name_contains": None,
            "label": "slot_518_dd14_reference",
        },
        {
            "source": "reference",
            "machine_number": 519,
            "dd": 14,
            "machine_name_contains": None,
            "label": "slot_519_dd14_reference",
        },
        {
            "source": "primary",
            "machine_number": 608,
            "dd": 14,
            "machine_name_contains": "化物語",
            "label": "slot_608_dd14_current_machine",
        },
        {
            "source": "reference",
            "machine_number": 608,
            "dd": 14,
            "machine_name_contains": None,
            "label": "slot_608_dd14_all_models_reference",
        },
    ]
    rows = []
    for check in checks:
        frame = primary if check["source"] == "primary" else reference
        sub = frame.loc[frame["machine_number"] == check["machine_number"]].copy()
        if check["machine_name_contains"]:
            sub = sub.loc[sub["machine_name"].astype(str).str.contains(check["machine_name_contains"], na=False)]
        sub = sub.loc[sub["dd"] == check["dd"]]
        if sub.empty:
            rows.append({**check, "avg_diff_on_dd": np.nan, "n_dd": 0, "status": "missing"})
            continue
        rows.append(
            {
                **check,
                "avg_diff_on_dd": float(sub["avg_diff_on_dd"].iloc[0]),
                "n_dd": int(sub["n_dd"].iloc[0]),
                "status": "ok",
            }
        )
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = _build_parser().parse_args(argv)
    db_path = args.db_path
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(str(db_path)) as conn:
        schema = _inspect_schema(conn)
        daily, machine, layout = _load_tables(conn, schema)

    daily = _normalize_dates(daily, "date")
    machine = _normalize_dates(machine, "date")
    layout = layout.copy()
    layout["machine_number"] = pd.to_numeric(layout["machine_number"], errors="coerce").astype("Int64")
    layout["machine_name_is_jug"] = False

    machine = machine.merge(
        layout.loc[:, ["machine_number", "section", "rank_from_aisle", "is_reversed_section"]],
        on="machine_number",
        how="left",
        validate="many_to_one",
    )
    machine["machine_name_is_jug"] = _detect_jug(machine["machine_name"])

    # derive segment using layout blocks and jug/nonjug naming
    machine["segment"] = pd.NA
    machine.loc[machine["machine_number"] >= 805, "segment"] = "mixed_805"
    machine.loc[(machine["machine_number"] >= 692) & (machine["machine_number"] <= 711), "segment"] = "v_nonjug"
    machine.loc[(machine["machine_number"] >= 745) & (machine["machine_number"] <= 755), "segment"] = "v_nonjug"
    machine.loc[
        (machine["machine_number"] >= 712) & (machine["machine_number"] <= 744) & machine["machine_name_is_jug"],
        "segment",
    ] = "v_jug"
    machine.loc[
        (machine["machine_number"] >= 712) & (machine["machine_number"] <= 744) & ~machine["machine_name_is_jug"],
        "segment",
    ] = "v_nonjug"
    machine.loc[
        (machine["machine_number"] >= 641) & (machine["machine_number"] <= 691) & machine["machine_name_is_jug"],
        "segment",
    ] = "h_jug"
    machine.loc[
        (machine["machine_number"] >= 641) & (machine["machine_number"] <= 691) & ~machine["machine_name_is_jug"],
        "segment",
    ] = "h_nonjug"
    machine.loc[(machine["machine_number"] >= 501) & (machine["machine_number"] <= 640), "segment"] = "h_nonjug"

    excluded_dates = _detect_anomalous_dates(daily)
    if excluded_dates:
        print(f"excluded_dates: {excluded_dates}")
    else:
        print("excluded_dates: none")

    instance_frame = _build_instances(machine)

    # Refresh jug flag after instance construction for downstream merging.
    instance_frame["machine_name_is_jug"] = _detect_jug(instance_frame["machine_name"])
    instance_frame = instance_frame.merge(
        layout.loc[:, ["machine_number", "section", "rank_from_aisle", "is_reversed_section"]],
        on="machine_number",
        how="left",
        suffixes=("", "_layout"),
        validate="many_to_one",
    )
    instance_frame["segment"] = pd.NA
    instance_frame.loc[instance_frame["machine_number"] >= 805, "segment"] = "mixed_805"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 692) & (instance_frame["machine_number"] <= 711), "segment"
    ] = "v_nonjug"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 745) & (instance_frame["machine_number"] <= 755), "segment"
    ] = "v_nonjug"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 712)
        & (instance_frame["machine_number"] <= 744)
        & instance_frame["machine_name_is_jug"],
        "segment",
    ] = "v_jug"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 712)
        & (instance_frame["machine_number"] <= 744)
        & ~instance_frame["machine_name_is_jug"],
        "segment",
    ] = "v_nonjug"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 641)
        & (instance_frame["machine_number"] <= 691)
        & instance_frame["machine_name_is_jug"],
        "segment",
    ] = "h_jug"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 641)
        & (instance_frame["machine_number"] <= 691)
        & ~instance_frame["machine_name_is_jug"],
        "segment",
    ] = "h_nonjug"
    instance_frame.loc[
        (instance_frame["machine_number"] >= 501) & (instance_frame["machine_number"] <= 640), "segment"
    ] = "h_nonjug"

    included_machine = instance_frame.loc[~instance_frame["date"].isin(excluded_dates)].copy()
    included_machine = included_machine.dropna(subset=["segment", "rank_from_aisle"]).copy()

    primary = _aggregate_dd_lift(
        included_machine,
        group_cols=["segment", "rank_from_aisle"],
        instance_col="machine_instance_id",
        excluded_dates=set(excluded_dates.keys()),
    )
    primary = primary.merge(
        included_machine.loc[
            :, ["machine_instance_id", "machine_number", "machine_name", "instance_start", "instance_end"]
        ].drop_duplicates(subset=["machine_instance_id"]),
        on="machine_instance_id",
        how="left",
        validate="many_to_one",
    )
    primary["instance_start"] = pd.to_datetime(primary["instance_start"]).dt.strftime("%Y%m%d")
    primary["instance_end"] = pd.to_datetime(primary["instance_end"]).dt.strftime("%Y%m%d")
    primary = primary.loc[
        :,
        [
            "dd",
            "segment",
            "rank_from_aisle",
            "machine_instance_id",
            "machine_number",
            "machine_name",
            "instance_start",
            "instance_end",
            "avg_diff_on_dd",
            "n_dd",
            "avg_diff_non_dd",
            "n_non_dd",
            "dd_specific_lift",
            "low_confidence",
            "new_machine_flag",
            "exclusion_flag",
            "exclusion_reason",
        ],
    ].copy()
    primary = _attach_single_machine_dominance_flag(primary)
    primary = primary.sort_values(
        ["dd", "segment", "rank_from_aisle", "machine_instance_id"], kind="mergesort"
    ).reset_index(drop=True)

    reference = _aggregate_dd_lift(
        included_machine,
        group_cols=["segment", "rank_from_aisle"],
        instance_col="machine_number",
        excluded_dates=set(excluded_dates.keys()),
    )
    reference = reference.merge(
        included_machine.loc[:, ["machine_number", "machine_name"]].drop_duplicates(subset=["machine_number"]),
        on="machine_number",
        how="left",
        validate="many_to_one",
    )
    reference["machine_instance_id"] = reference["machine_number"].map(lambda value: f"slot_{int(value)}")
    reference["machine_name"] = "ALL_MODELS"
    reference = _attach_single_machine_dominance_flag(reference)
    reference = reference.loc[
        :,
        [
            "dd",
            "segment",
            "rank_from_aisle",
            "machine_instance_id",
            "machine_number",
            "machine_name",
            "avg_diff_on_dd",
            "n_dd",
            "avg_diff_non_dd",
            "n_non_dd",
            "dd_specific_lift",
            "low_confidence",
            "new_machine_flag",
            "exclusion_flag",
            "exclusion_reason",
            "single_machine_dominance_flag",
        ],
    ].copy()
    reference = reference.sort_values(
        ["dd", "segment", "rank_from_aisle", "machine_number"], kind="mergesort"
    ).reset_index(drop=True)

    baseline = _build_baseline(daily, set(excluded_dates.keys()))

    primary_path = args.output_dir / f"mitoya_dd_full_sweep_{RUN_DATE}.csv"
    reference_path = args.output_dir / f"mitoya_dd_full_sweep_positionbased_reference_{RUN_DATE}.csv"
    baseline_path = args.output_dir / f"mitoya_dd_hallwide_baseline_{RUN_DATE}.csv"

    primary.to_csv(primary_path, index=False, encoding="utf-8-sig")
    reference.to_csv(reference_path, index=False, encoding="utf-8-sig")
    baseline.to_csv(baseline_path, index=False, encoding="utf-8-sig")

    print(f"written: {primary_path}")
    print(f"written: {reference_path}")
    print(f"written: {baseline_path}")
    _summarize_output(primary, "primary")
    _summarize_output(reference, "reference")
    print("baseline rows:", len(baseline))
    print(baseline.head(5).to_string(index=False))

    check = _cross_check(primary, reference)
    print("cross_check:")
    print(check.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
