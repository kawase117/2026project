"""
Pachinko Analyzer Dashboard - Data Loader
データベースからのデータ読み込み関数（キャッシング対応）
"""

import streamlit as st
import pandas as pd
import sqlite3
from pathlib import Path
from typing import List


# ========================================
# セキュリティ: 許可された属性名のホワイトリスト
# ========================================

# daily_hall_summaryのフィルタ対象カラムのホワイトリスト
# hall_anniversary, is_x_day, week_of_month, is_any_event は
# ホール固有設定または複合フラグのため除外
ALLOWED_ATTRIBUTES = {
    'day_of_week', 'last_digit', 'weekday_nth',
    'is_zorome', 'is_strong_zorome', 'is_month_start',
    'is_month_end', 'is_weekend', 'is_holiday'
}


# ========================================
# Database Connection
# ========================================

@st.cache_resource
def get_db_connection(db_path: str):
    """データベース接続"""
    return sqlite3.connect(db_path)


def get_available_halls(db_dir: Path = Path('./db')) -> List[str]:
    """利用可能なホール一覧を取得"""
    if not db_dir.exists():
        return []
    return [f.stem for f in db_dir.glob('*.db')]


def get_all_hall_paths(db_dir: Path = Path('./db')) -> dict:
    """すべてのホール DB パスをホール名キーで返す"""
    if not db_dir.exists():
        return {}
    return {f.stem: f for f in db_dir.glob('*.db')}


# ========================================
# Data Loading Functions (with caching)
# ========================================

@st.cache_data(ttl=3600)
def load_daily_hall_summary(db_path: str) -> pd.DataFrame:
    """ホール全体の日別集計データを読み込み"""
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM daily_hall_summary ORDER BY date"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        return df
    except Exception as e:
        st.error(f"ホール集計データ読み込みエラー: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_machine_detailed_by_date(db_path: str, date_str: str) -> pd.DataFrame:
    """指定日の個別台データを読み込み"""
    try:
        conn = sqlite3.connect(db_path)
        query = f"""
            SELECT * FROM machine_detailed_results
            WHERE date = '{date_str}'
            ORDER BY diff_coins_normalized DESC
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"個別台データ読み込みエラー: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_last_digit_summary(db_path: str, machine_type: str = 'all') -> pd.DataFrame:
    """末尾別集計データを読み込み"""
    try:
        table_name = f"last_digit_summary_{machine_type}"
        conn = sqlite3.connect(db_path)
        query = f"SELECT * FROM {table_name} ORDER BY date"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        return df
    except Exception as e:
        st.error(f"末尾別集計データ読み込みエラー: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_machine_detailed_results(db_path: str) -> pd.DataFrame:
    """すべての個別台実績データを読み込み"""
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM machine_detailed_results ORDER BY date DESC"
        df = pd.read_sql_query(query, conn)
        conn.close()

        if not df.empty:
            # date を datetime に変換（フィルタリング用）
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        return df
    except Exception as e:
        st.error(f"個別台データ読み込みエラー: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_daily_hall_by_attribute(
    db_path: str,
    attribute: str,
    attribute_value = None
) -> pd.DataFrame:
    """
    日付属性でフィルタされた daily_hall_summary データを取得

    パラメータ:
        db_path: ホール DB のパス
        attribute: フィルタ対象の属性（'day_of_week', 'last_digit', 'is_month_end' など）
        attribute_value: フィルタ値（指定しない場合は全データ）

    戻り値:
        属性別にフィルタされた DataFrame
    """
    if attribute not in ALLOWED_ATTRIBUTES:
        raise ValueError(
            f"許可されていないattribute: '{attribute}'. "
            f"許可値: {sorted(ALLOWED_ATTRIBUTES)}"
        )

    try:
        conn = sqlite3.connect(db_path)

        if attribute_value is not None:
            # 特定の属性値でフィルタ
            query = f"SELECT * FROM daily_hall_summary WHERE {attribute} = ? ORDER BY date"
            df = pd.read_sql_query(query, conn, params=(attribute_value,))
        else:
            # フィルタなし（全期間）
            query = "SELECT * FROM daily_hall_summary ORDER BY date"
            df = pd.read_sql_query(query, conn)

        conn.close()

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        return df
    except Exception as e:
        st.error(f"ホール属性別データ読み込みエラー: {e}")
        return pd.DataFrame()
