"""
Pachinko Analyzer Dashboard - Data Loader
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st


ALLOWED_ATTRIBUTES = {
    "day_of_week",
    "last_digit",
    "weekday_nth",
    "is_zorome",
    "is_strong_zorome",
    "is_month_start",
    "is_month_end",
    "is_weekend",
    "is_holiday",
}

VALID_MACHINE_TYPES = frozenset({"all", "jug", "hana", "oki", "other"})


@st.cache_resource
def get_db_connection(db_path: str):
    """Return a SQLite connection."""
    return sqlite3.connect(db_path)


def get_available_halls(db_dir: Path = Path("./db")) -> List[str]:
    """Return available hall names from the db directory."""
    if not db_dir.exists():
        return []
    return [f.stem for f in db_dir.glob("*.db")]


def get_all_hall_paths(db_dir: Path = Path("./db")) -> dict:
    """Return a mapping of hall name to DB path."""
    if not db_dir.exists():
        return {}
    return {f.stem: f for f in db_dir.glob("*.db")}


@st.cache_data(ttl=3600)
def load_daily_hall_summary(db_path: str) -> pd.DataFrame:
    """Load daily_hall_summary."""
    try:
        with sqlite3.connect(db_path) as conn:
            query = "SELECT * FROM daily_hall_summary ORDER BY date"
            df = pd.read_sql_query(query, conn)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

        return df
    except Exception as e:
        st.error(f"繝帙・繝ｫ髮・ｨ医ョ繝ｼ繧ｿ隱ｭ縺ｿ霎ｼ縺ｿ繧ｨ繝ｩ繝ｼ: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_machine_detailed_by_date(db_path: str, date_str: str) -> pd.DataFrame:
    """Load machine_detailed_results for a single date."""
    try:
        with sqlite3.connect(db_path) as conn:
            query = """
                SELECT * FROM machine_detailed_results
                WHERE date = ?
                ORDER BY diff_coins_normalized DESC
            """
            df = pd.read_sql_query(query, conn, params=(date_str,))
        return df
    except Exception as e:
        st.error(f"蛟句挨蜿ｰ繝・・繧ｿ隱ｭ縺ｿ霎ｼ縺ｿ繧ｨ繝ｩ繝ｼ: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_last_digit_summary(db_path: str, machine_type: str = "all") -> pd.DataFrame:
    """Load last digit summary."""
    if machine_type not in VALID_MACHINE_TYPES:
        raise ValueError(
            f"辟｡蜉ｹ縺ｪ machine_type: {machine_type!r}. 險ｱ蜿ｯ蛟､: {sorted(VALID_MACHINE_TYPES)}"
        )
    try:
        table_name = f"last_digit_summary_{machine_type}"
        with sqlite3.connect(db_path) as conn:
            query = f"SELECT * FROM {table_name} ORDER BY date"
            df = pd.read_sql_query(query, conn)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

        return df
    except Exception as e:
        st.error(f"譛ｫ蟆ｾ蛻･髮・ｨ医ョ繝ｼ繧ｿ隱ｭ縺ｿ霎ｼ縺ｿ繧ｨ繝ｩ繝ｼ: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_machine_detailed_results(db_path: str) -> pd.DataFrame:
    """Load all machine_detailed_results rows."""
    try:
        with sqlite3.connect(db_path) as conn:
            query = "SELECT * FROM machine_detailed_results ORDER BY date DESC"
            df = pd.read_sql_query(query, conn)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

        return df
    except Exception as e:
        st.error(f"蛟句挨蜿ｰ繝・・繧ｿ隱ｭ縺ｿ霎ｼ縺ｿ繧ｨ繝ｩ繝ｼ: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_daily_hall_by_attribute(
    db_path: str,
    attribute: str,
    attribute_value=None,
) -> pd.DataFrame:
    """Load daily_hall_summary filtered by attribute."""
    if attribute not in ALLOWED_ATTRIBUTES:
        raise ValueError(
            f"險ｱ蜿ｯ縺輔ｌ縺ｦ縺・↑縺・ttribute: '{attribute}'. "
            f"險ｱ蜿ｯ蛟､: {sorted(ALLOWED_ATTRIBUTES)}"
        )

    try:
        with sqlite3.connect(db_path) as conn:
            if attribute_value is not None:
                query = f"SELECT * FROM daily_hall_summary WHERE {attribute} = ? ORDER BY date"
                df = pd.read_sql_query(query, conn, params=(attribute_value,))
            else:
                query = "SELECT * FROM daily_hall_summary ORDER BY date"
                df = pd.read_sql_query(query, conn)

        if not df.empty:
            df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

        return df
    except Exception as e:
        st.error(f"繝帙・繝ｫ螻樊ｧ蛻･繝・・繧ｿ隱ｭ縺ｿ霎ｼ縺ｿ繧ｨ繝ｩ繝ｼ: {e}")
        return pd.DataFrame()
