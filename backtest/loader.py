"""データ読み込みモジュール"""

import sqlite3
import pandas as pd
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=8)
def load_machine_data(db_path: str) -> pd.DataFrame:
    """
    DBからmachine_detailed_resultsを読み込み、分析用に加工

    同一 db_path への複数呼び出しはメモリキャッシュされる（maxsize=8）

    Args:
        db_path: SQLiteデータベースパス

    Returns:
        DataFrame with columns: date, dd, weekday, machine_number, machine_name, last_digit, diff_coins_normalized, games_normalized
    """
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_number, machine_name, last_digit, diff_coins_normalized, games_normalized FROM machine_detailed_results",
        conn
    )
    conn.close()

    # 日付変換・dd・曜日の追加
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['dd'] = df['date'].dt.day  # 月内日付（1-31）
    df['weekday'] = df['date'].dt.day_name()  # 曜日（Monday など）

    return df.sort_values('date').reset_index(drop=True)
