from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from ml.last_digit.utils import resolve_db_path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


AT_ISLAND = "AT島"
JUGGLER_ISLAND = "ジャグラー島"
VARIETY_ISLAND = "バラエティ島"

ISLAND_ORDER = {
    AT_ISLAND: 0,
    JUGGLER_ISLAND: 1,
    VARIETY_ISLAND: 2,
}

MIN_RECORDS_PER_DIGIT = 3
MIN_PAIRS_PER_DIGIT = 5
TOP_K = 3
BOTTOM_K = 3


def assign_island(machine_number: int) -> str:
    number = int(machine_number)
    if 501 <= number <= 640:
        return AT_ISLAND
    if 641 <= number <= 691:
        return JUGGLER_ISLAND
    if 692 <= number <= 755:
        return VARIETY_ISLAND
    return "unknown"


def is_x_day(value: object) -> bool:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return False
    return int(ts.day) % 10 in {4, 7}


def dd_group_for_date(value: object) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return "unknown"
    day = int(ts.day)
    mod = day % 10
    if mod == 4:
        return "4系"
    if mod == 7:
        return "7系"
    return "unknown"


def classify_dd_group_transition(prev_date: object, curr_date: object) -> str:
    prev_group = dd_group_for_date(prev_date)
    curr_group = dd_group_for_date(curr_date)
    if prev_group == "unknown" or curr_group == "unknown":
        return "unknown"
    return "intra" if prev_group == curr_group else "inter"


def _load_rows(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as con:
        df = pd.read_sql_query(
            """
            SELECT date, machine_number, last_digit, diff_coins_normalized, games_normalized
            FROM machine_detailed_results
            """,
            con,
        )
    if df.empty:
        return df

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work = work.dropna(subset=["date", "machine_number", "last_digit", "diff_coins_normalized", "games_normalized"]).copy()
    work = work[work["games_normalized"] >= 100].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["last_digit"] = work["last_digit"].astype(str)
    work["island"] = work["machine_number"].map(assign_island)
    work = work[work["island"].isin(ISLAND_ORDER)].copy()
    work["x_day"] = work["date"].map(is_x_day)
    work["dd_group"] = work["date"].map(dd_group_for_date)
    work = work[work["x_day"]].copy()
    return work.reset_index(drop=True)


def _empty_outputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cont_cols = ["island", "last_digit", "continuation_rate", "recovery_rate", "n_pairs", "baseline_diff"]
    streak_cols = ["island", "last_digit", "max_streak", "avg_streak", "n_xday_appearances"]
    dd_cols = ["island", "last_digit", "dd_group_transition", "continuation_rate", "n_pairs", "mean_gap_days"]
    return pd.DataFrame(columns=cont_cols), pd.DataFrame(columns=streak_cols), pd.DataFrame(columns=dd_cols)


def build_xday_daily_rankings(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=["date", "island", "last_digit", "avg_diff", "n_records", "dd_group", "rank"])

    work = raw.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["last_digit"] = work["last_digit"].astype(str).str.strip()
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work = work.dropna(subset=["date", "diff_coins_normalized", "games_normalized", "machine_number"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work = work[work["games_normalized"] >= 100].copy()
    work = work[work["last_digit"].str.fullmatch(r"[0-9]")].copy()
    work["island"] = work["machine_number"].map(assign_island)
    work = work[work["island"].isin(ISLAND_ORDER)].copy()
    work["x_day"] = work["date"].map(is_x_day)
    work = work[work["x_day"]].copy()
    if work.empty:
        return pd.DataFrame(columns=["date", "island", "last_digit", "avg_diff", "n_records", "dd_group", "rank"])

    daily = (
        work.groupby(["date", "island", "last_digit"], sort=True)
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            n_records=("diff_coins_normalized", "size"),
            dd_group=("date", lambda s: dd_group_for_date(s.iloc[0])),
        )
        .reset_index()
    )
    daily = daily[daily["n_records"] >= MIN_RECORDS_PER_DIGIT].copy()
    if daily.empty:
        return pd.DataFrame(columns=["date", "island", "last_digit", "avg_diff", "n_records", "dd_group", "rank"])

    daily["rank"] = (
        daily.groupby(["date", "island"], sort=True)["avg_diff"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    daily = daily.sort_values(["island", "date", "rank", "last_digit"], ascending=[True, True, True, True]).reset_index(drop=True)
    return daily


def build_xday_lag1_cycle_tables(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if raw.empty:
        return _empty_outputs()

    daily = build_xday_daily_rankings(raw)
    if daily.empty:
        return _empty_outputs()

    xday_dates = sorted(pd.to_datetime(daily["date"].unique()).tolist())
    pair_rows: list[dict[str, Any]] = []
    for prev_date, curr_date in zip(xday_dates[:-1], xday_dates[1:]):
        prev_ts = pd.Timestamp(prev_date).normalize()
        curr_ts = pd.Timestamp(curr_date).normalize()
        gap_days = max(int((curr_ts - prev_ts).days) - 1, 0)
        prev_df = daily.loc[daily["date"].eq(prev_ts)].copy()
        curr_df = daily.loc[daily["date"].eq(curr_ts)].copy()
        merged = prev_df.merge(
            curr_df,
            on=["island", "last_digit"],
            suffixes=("_prev", "_curr"),
            how="inner",
        )
        if merged.empty:
            continue
        merged["gap_days"] = gap_days
        merged["dd_group_transition"] = [
            classify_dd_group_transition(prev_ts, curr_ts) for _ in range(len(merged))
        ]
        merged["prev_top3"] = merged["rank_prev"] <= TOP_K
        merged["curr_top3"] = merged["rank_curr"] <= TOP_K
        merged["prev_bottom3"] = merged["rank_prev"] >= 8
        merged["continuation_hit"] = merged["prev_top3"] & merged["curr_top3"]
        merged["recovery_hit"] = merged["prev_bottom3"] & merged["curr_top3"]
        pair_rows.extend(
            merged[
                [
                    "date_prev",
                    "date_curr",
                    "island",
                    "last_digit",
                    "rank_prev",
                    "rank_curr",
                    "gap_days",
                    "dd_group_transition",
                    "prev_top3",
                    "curr_top3",
                    "prev_bottom3",
                    "continuation_hit",
                    "recovery_hit",
                ]
            ]
            .rename(columns={"date_prev": "prev_date", "date_curr": "curr_date"})
            .to_dict("records")
        )

    pairs = pd.DataFrame(pair_rows)
    if pairs.empty:
        return _empty_outputs()

    cont_records = (
        pairs.groupby(["island", "last_digit"], sort=True)
        .agg(
            continuation_hits=("continuation_hit", "sum"),
            continuation_candidates=("prev_top3", "sum"),
            recovery_hits=("recovery_hit", "sum"),
            recovery_candidates=("prev_bottom3", "sum"),
            n_pairs=("continuation_hit", "size"),
        )
        .reset_index()
    )
    cont_records["continuation_rate"] = cont_records.apply(
        lambda row: float(row["continuation_hits"] / row["continuation_candidates"])
        if float(row["continuation_candidates"]) > 0
        else float("nan"),
        axis=1,
    )
    cont_records["recovery_rate"] = cont_records.apply(
        lambda row: float(row["recovery_hits"] / row["recovery_candidates"])
        if float(row["recovery_candidates"]) > 0
        else float("nan"),
        axis=1,
    )
    cont_records["baseline_diff"] = cont_records["continuation_rate"] - 0.30
    cont_records = cont_records[cont_records["n_pairs"] >= MIN_PAIRS_PER_DIGIT].copy()
    cont_records = cont_records.drop(columns=["continuation_hits", "continuation_candidates", "recovery_hits", "recovery_candidates"])

    streak_rows: list[dict[str, Any]] = []
    for (island, last_digit), grp in daily.groupby(["island", "last_digit"], sort=True):
        grp = grp.sort_values("date").reset_index(drop=True)
        flags = (grp["rank"] <= TOP_K).astype(int).tolist()
        streaks: list[int] = []
        current = 0
        max_streak = 0
        for flag in flags:
            if flag:
                current += 1
            else:
                if current > 0:
                    streaks.append(current)
                current = 0
            max_streak = max(max_streak, current)
        if current > 0:
            streaks.append(current)
        streak_rows.append(
            {
                "island": island,
                "last_digit": last_digit,
                "max_streak": int(max_streak),
                "avg_streak": float(sum(streaks) / len(streaks)) if streaks else 0.0,
                "n_xday_appearances": int(len(flags)),
            }
        )

    streak_df = pd.DataFrame(streak_rows)

    dd_group_df = (
        pairs.groupby(["island", "last_digit", "dd_group_transition"], sort=True)
        .agg(
            continuation_hits=("continuation_hit", "sum"),
            continuation_candidates=("prev_top3", "sum"),
            n_pairs=("continuation_hit", "size"),
            mean_gap_days=("gap_days", "mean"),
        )
        .reset_index()
    )
    dd_group_df["continuation_rate"] = dd_group_df.apply(
        lambda row: float(row["continuation_hits"] / row["continuation_candidates"])
        if float(row["continuation_candidates"]) > 0
        else float("nan"),
        axis=1,
    )
    dd_group_df = dd_group_df[dd_group_df["n_pairs"] >= MIN_PAIRS_PER_DIGIT].copy()
    dd_group_df = dd_group_df.drop(columns=["continuation_hits", "continuation_candidates"])

    return cont_records, streak_df, dd_group_df


def _sort_island(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["island_order"] = out["island"].map(ISLAND_ORDER).fillna(999).astype(int)
    out["digit_order"] = pd.to_numeric(out["last_digit"], errors="coerce").fillna(999).astype(int)
    cols = [c for c in ["dd_group_transition", "continuation_rate", "recovery_rate", "max_streak", "avg_streak", "n_pairs"] if c in out.columns]
    return out.sort_values(["island_order", "digit_order", *cols], ascending=[True, True, False, False, False, False][: 2 + len(cols)]).drop(columns=["island_order", "digit_order"])


def _print_report(cont: pd.DataFrame, streak: pd.DataFrame, dd_group_df: pd.DataFrame) -> None:
    if cont.empty:
        print("No qualifying x_day digit pairs.")
        return

    for island in [AT_ISLAND, JUGGLER_ISLAND, VARIETY_ISLAND]:
        island_cont = cont.loc[cont["island"].eq(island)].copy()
        if island_cont.empty:
            continue
        print(f"\n## {island}")
        print("Continuation top")
        print(
            island_cont.sort_values(["continuation_rate", "n_pairs", "last_digit"], ascending=[False, False, True])
            .head(5)
            .to_string(index=False)
        )
        print("Continuation bottom")
        print(
            island_cont.sort_values(["continuation_rate", "n_pairs", "last_digit"], ascending=[True, False, True])
            .head(5)
            .to_string(index=False)
        )
        print("Recovery top")
        print(
            island_cont.sort_values(["recovery_rate", "n_pairs", "last_digit"], ascending=[False, False, True])
            .head(5)
            .to_string(index=False)
        )
        print("Recovery bottom")
        print(
            island_cont.sort_values(["recovery_rate", "n_pairs", "last_digit"], ascending=[True, False, True])
            .head(5)
            .to_string(index=False)
        )
        island_streak = streak.loc[streak["island"].eq(island)].copy()
        if not island_streak.empty:
            print("Streak top")
            print(island_streak.sort_values(["max_streak", "avg_streak", "last_digit"], ascending=[False, False, True]).head(5).to_string(index=False))

        mean_cont = float(island_cont["continuation_rate"].mean()) if not island_cont.empty else 0.0
        mean_rec = float(island_cont["recovery_rate"].mean()) if not island_cont.empty else 0.0
        comment = "固定傾向あり" if mean_cont > 0.50 else ("ローテーション傾向" if mean_cont < 0.15 else "中立")
        print(f"baseline=0.30 continuation_mean={mean_cont:.3f} recovery_mean={mean_rec:.3f} comment={comment}")

        island_dd = dd_group_df.loc[dd_group_df["island"].eq(island)].copy()
        if not island_dd.empty:
            print("DD transition continuation top")
            print(island_dd.sort_values(["continuation_rate", "n_pairs"], ascending=[False, False]).head(5).to_string(index=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mitoya x_day lag-1 cycle analysis.")
    parser.add_argument("--db-path", default="", help="DB path override. Empty uses resolve_db_path.")
    parser.add_argument("--db-glob", default="みとや大森町店.db", help="DB auto-detect glob pattern used when --db-path is empty")
    parser.add_argument("--output-dir", default="results", help="Directory for CSV outputs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(str(args.db_path), pattern=str(args.db_glob))
    raw = _load_rows(db_path)
    cont, streak, dd_group_df = build_xday_lag1_cycle_tables(raw)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cont_path = out_dir / "mitoya_xday_lag1_continuation.csv"
    streak_path = out_dir / "mitoya_xday_lag1_streak.csv"
    dd_group_path = out_dir / "mitoya_xday_lag1_by_dd_group.csv"
    cont.to_csv(cont_path, index=False, encoding="utf-8-sig")
    streak.to_csv(streak_path, index=False, encoding="utf-8-sig")
    dd_group_df.to_csv(dd_group_path, index=False, encoding="utf-8-sig")
    print(cont_path)
    print(streak_path)
    print(dd_group_path)
    _print_report(cont, streak, dd_group_df)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
