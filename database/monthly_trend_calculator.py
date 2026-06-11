#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
月次トレンドテーブルの計算・更新
"""

import calendar
import re
import sqlite3

import pandas as pd

from table_config import MACHINE_TYPE_CONFIGS


MACHINE_SUFFIXES = [config["suffix"] for config in MACHINE_TYPE_CONFIGS]
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# 機種タイプフィルタ（DataFrame のフラグ列で絞り込む）
TYPE_FILTERS = {
    "all": lambda df: df,
    "jug": lambda df: df[df["jug_flag"] == 1],
    "hana": lambda df: df[df["hana_flag"] == 1],
    "oki": lambda df: df[df["oki_flag"] == 1],
    "bt": lambda df: df[df["bt_flag"] == 1],
    "other": lambda df: df[
        (df["jug_flag"] == 0)
        & (df["hana_flag"] == 0)
        & (df["oki_flag"] == 0)
        & (df["bt_flag"] == 0)
    ],
}

# machine_digit テーブル用 SQL WHERE 条件
TYPE_SQL_CONDITIONS = {
    "all": "1=1",
    "jug": "mm.jug_flag = 1",
    "hana": "mm.hana_flag = 1",
    "oki": "mm.oki_flag = 1",
    "bt": "mm.bt_flag = 1",
    "other": "mm.jug_flag = 0 AND mm.hana_flag = 0 AND mm.oki_flag = 0 AND mm.bt_flag = 0",
}


def _assert_safe(name: str) -> None:
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")

UPSERT_COLS = [
    "year_month",
    "sample_count",
    "days_in_month",
    "is_complete",
    "avg_diff_per_machine",
    "median_diff_per_machine",
    "max_diff_coins",
    "min_diff_coins",
    "total_diff_coins",
    "avg_games_per_machine",
    "win_rate",
    "high_profit_rate",
    "machine_count",
    "avg_rank_diff",
    "avg_rank_games",
    "avg_rank_efficiency",
    "times_ranked_1st",
    "times_ranked_top3",
]


class MonthlyTrendCalculator:
    """月次トレンドテーブルの計算・更新クラス"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def update_month(self, date: str):
        """日次処理完了後のエントリーポイント。"""
        year_month = date[:6]
        self._compute_month(year_month)
        self._maybe_complete_prev_month(year_month)

    def _compute_month(self, year_month: str):
        """指定月の全18テーブルを再計算して INSERT OR REPLACE"""
        year = int(year_month[:4])
        month = int(year_month[4:])
        days_in_month = calendar.monthrange(year, month)[1]

        conn = self.get_connection()
        try:
            df_machines, df_hall = self._load_month_data(conn, year_month)

            if not df_machines.empty and not df_hall.empty:
                self._compute_date_digit_tables(
                    conn, year_month, days_in_month, df_machines, df_hall
                )
                self._compute_weekday_tables(
                    conn, year_month, days_in_month, df_machines, df_hall
                )

            self._compute_machine_digit_tables(conn, year_month, days_in_month)
            conn.commit()
        finally:
            conn.close()

    def _load_month_data(self, conn, year_month: str):
        """machine_detailed_results と daily_hall_summary を月分ロード"""
        df_machines = pd.read_sql_query(
            """
            SELECT
                m.date,
                m.machine_name,
                m.last_digit AS machine_digit,
                m.games_normalized,
                m.diff_coins_normalized,
                COALESCE(mm.jug_flag, 0) AS jug_flag,
                COALESCE(mm.hana_flag, 0) AS hana_flag,
                COALESCE(mm.oki_flag, 0) AS oki_flag,
                COALESCE(mm.bt_flag, 0) AS bt_flag
            FROM machine_detailed_results m
            LEFT JOIN machine_master mm
                   ON m.machine_name = mm.machine_name_normalized
            WHERE m.date LIKE ?
            """,
            conn,
            params=(f"{year_month}%",),
        )

        df_hall = pd.read_sql_query(
            """
            SELECT date,
                   last_digit AS date_digit,
                   day_of_week
            FROM daily_hall_summary
            WHERE date LIKE ?
            """,
            conn,
            params=(f"{year_month}%",),
        )

        return df_machines, df_hall

    def _compute_date_digit_tables(self, conn, year_month, days_in_month, df_machines, df_hall):
        df = df_machines.merge(df_hall[["date", "date_digit"]], on="date", how="inner")
        df["date_digit"] = df["date_digit"].astype(int)

        for suffix, filter_fn in TYPE_FILTERS.items():
            df_type = filter_fn(df.copy())
            if df_type.empty:
                continue
            rows = self._aggregate_by_key(df_type, "date_digit", year_month, days_in_month)
            self._upsert_rows(conn, f"monthly_trend_date_digit_{suffix}", "date_digit", rows)

    def _compute_weekday_tables(self, conn, year_month, days_in_month, df_machines, df_hall):
        df = df_machines.merge(df_hall[["date", "day_of_week"]], on="date", how="inner")

        for suffix, filter_fn in TYPE_FILTERS.items():
            df_type = filter_fn(df.copy())
            if df_type.empty:
                continue
            rows = self._aggregate_by_key(df_type, "day_of_week", year_month, days_in_month)
            self._upsert_rows(conn, f"monthly_trend_weekday_{suffix}", "day_of_week", rows)

    def _compute_machine_digit_tables(self, conn, year_month, days_in_month):
        """last_digit_summary_* から月次集計（既存ランク列を活用）"""
        for suffix in MACHINE_SUFFIXES:
            src = f"last_digit_summary_{suffix}"

            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (src,),
            )
            if not cur.fetchone():
                continue

            df = pd.read_sql_query(
                f"""
                SELECT
                    last_digit AS machine_digit,
                    date,
                    avg_diff_coins,
                    avg_games,
                    max_diff_coins,
                    min_diff_coins,
                    total_diff_coins,
                    win_rate,
                    high_profit_rate,
                    machine_count,
                    last_digit_rank_diff AS rank_diff,
                    last_digit_rank_games AS rank_games,
                    last_digit_rank_efficiency AS rank_efficiency
                FROM {src}
                WHERE date LIKE ?
                  AND last_digit NOT IN ('ゾロ目')
                """,
                conn,
                params=(f"{year_month}%",),
            )

            if df.empty:
                continue

            cond = TYPE_SQL_CONDITIONS[suffix]
            df_raw = pd.read_sql_query(
                f"""
                SELECT m.last_digit AS machine_digit, m.diff_coins_normalized
                FROM machine_detailed_results m
                LEFT JOIN machine_master mm
                       ON m.machine_name = mm.machine_name_normalized
                WHERE m.date LIKE ?
                  AND m.last_digit IN ('0','1','2','3','4','5','6','7','8','9')
                  AND {cond}
                """,
                conn,
                params=(f"{year_month}%",),
            )

            result = (
                df.groupby("machine_digit")
                .agg(
                    sample_count=("date", "nunique"),
                    avg_diff_per_machine=("avg_diff_coins", "mean"),
                    avg_games_per_machine=("avg_games", "mean"),
                    win_rate=("win_rate", "mean"),
                    high_profit_rate=("high_profit_rate", "mean"),
                    machine_count=("machine_count", "mean"),
                    avg_rank_diff=("rank_diff", "mean"),
                    avg_rank_games=("rank_games", "mean"),
                    avg_rank_efficiency=("rank_efficiency", "mean"),
                    times_ranked_1st=("rank_diff", lambda x: (x == 1).sum()),
                    times_ranked_top3=("rank_diff", lambda x: (x <= 3).sum()),
                )
                .reset_index()
            )

            raw_agg = (
                df_raw.groupby("machine_digit")["diff_coins_normalized"]
                .agg(["median", "max", "min", "sum"])
                .rename(
                    columns={
                        "median": "median_diff_per_machine",
                        "max": "max_diff_coins",
                        "min": "min_diff_coins",
                        "sum": "total_diff_coins",
                    }
                )
                .reset_index()
            )
            result = result.merge(raw_agg, on="machine_digit", how="left")

            result["year_month"] = year_month
            result["days_in_month"] = days_in_month
            result["is_complete"] = 0

            self._upsert_rows(conn, f"monthly_trend_machine_digit_{suffix}", "machine_digit", result)

    def _aggregate_by_key(self, df, key_col, year_month, days_in_month):
        """date_digit / day_of_week をキーに月次集計する汎用メソッド"""
        df = df.copy()
        df["is_high_profit"] = (
            (df["diff_coins_normalized"] >= 1000)
            & (df["games_normalized"] >= 3000)
        ).astype(int)

        daily = (
            df.groupby(["date", key_col])
            .agg(
                avg_diff=("diff_coins_normalized", "mean"),
                avg_games=("games_normalized", "mean"),
                machine_count_d=("machine_name", "count"),
                win_count=("diff_coins_normalized", lambda x: (x > 0).sum()),
                high_profit_count=("is_high_profit", "sum"),
            )
            .reset_index()
        )

        daily["win_rate"] = daily["win_count"] / daily["machine_count_d"] * 100
        daily["high_profit_rate"] = daily["high_profit_count"] / daily["machine_count_d"] * 100
        daily["efficiency"] = daily["avg_diff"] / daily["avg_games"].replace(0, float("nan"))

        daily["rank_diff"] = (
            daily.groupby("date")["avg_diff"].rank(ascending=False, method="first").astype(int)
        )
        daily["rank_games"] = (
            daily.groupby("date")["avg_games"].rank(ascending=False, method="first").astype(int)
        )
        daily["rank_efficiency"] = (
            daily.groupby("date")["efficiency"].rank(ascending=False, method="first").astype(int)
        )

        raw_agg = (
            df.groupby(key_col)["diff_coins_normalized"]
            .agg(["median", "max", "min", "sum"])
            .rename(
                columns={
                    "median": "median_diff_per_machine",
                    "max": "max_diff_coins",
                    "min": "min_diff_coins",
                    "sum": "total_diff_coins",
                }
            )
        )

        result = (
            daily.groupby(key_col)
            .agg(
                sample_count=("date", "nunique"),
                avg_diff_per_machine=("avg_diff", "mean"),
                avg_games_per_machine=("avg_games", "mean"),
                win_rate=("win_rate", "mean"),
                high_profit_rate=("high_profit_rate", "mean"),
                machine_count=("machine_count_d", "mean"),
                avg_rank_diff=("rank_diff", "mean"),
                avg_rank_games=("rank_games", "mean"),
                avg_rank_efficiency=("rank_efficiency", "mean"),
                times_ranked_1st=("rank_diff", lambda x: (x == 1).sum()),
                times_ranked_top3=("rank_diff", lambda x: (x <= 3).sum()),
            )
            .reset_index()
            .merge(raw_agg, on=key_col, how="left")
        )

        result["year_month"] = year_month
        result["days_in_month"] = days_in_month
        result["is_complete"] = 0
        return result

    def _upsert_rows(self, conn, table_name, key_name, df):
        """DataFrame の行を INSERT OR REPLACE で DB に書き込む"""
        if df.empty:
            return

        _assert_safe(table_name)
        _assert_safe(key_name)

        cols = [key_name] + UPSERT_COLS
        placeholders = ",".join(["?"] * len(cols))
        sql = (
            f"INSERT OR REPLACE INTO {table_name} "
            f"({','.join(cols)}) VALUES ({placeholders})"
        )

        records = [tuple(row.get(c) for c in cols) for _, row in df.iterrows()]
        conn.cursor().executemany(sql, records)

    def _maybe_complete_prev_month(self, current_year_month: str):
        """前月のデータが存在し is_complete=0 なら is_complete=1 にする"""
        prev = self._get_prev_month(current_year_month)

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            for suffix in MACHINE_SUFFIXES:
                for axis in ["date_digit", "weekday", "machine_digit"]:
                    table = f"monthly_trend_{axis}_{suffix}"
                    _assert_safe(table)
                    cur.execute(
                        f"UPDATE {table} SET is_complete = 1 "
                        f"WHERE year_month = ? AND is_complete = 0",
                        (prev,),
                    )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _get_prev_month(year_month: str) -> str:
        if not re.fullmatch(r"\d{6}", year_month):
            raise ValueError(f"Invalid year_month: {year_month!r}")
        year = int(year_month[:4])
        month = int(year_month[4:])
        if month == 1:
            return f"{year - 1}12"
        return f"{year}{month - 1:02d}"
