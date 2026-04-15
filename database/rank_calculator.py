#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ランク・履歴計算の統合処理
"""

import sqlite3
from datetime import datetime, timedelta
from table_config import get_all_summary_tables, get_rank_columns

class RankCalculator:
    """ランク・履歴計算クラス"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def calculate_ranks_for_date(self, date: str):
        """指定日の全テーブルのランクを計算（ROW_NUMBER()ウィンドウ関数使用）"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            tables = get_all_summary_tables()

            for table_info in tables:
                table = table_info['table_name']
                key = table_info['group_key']
                prefix = table_info['rank_prefix']

                # テーブル存在確認
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                if not cursor.fetchone():
                    continue

                # ROW_NUMBER()ウィンドウ関数でランクを一括取得（1回のSELECTで3ランク全て）
                rows = cursor.execute(f"""
                    SELECT
                        rowid,
                        ROW_NUMBER() OVER (PARTITION BY date ORDER BY avg_diff_coins DESC)          AS rank_diff,
                        ROW_NUMBER() OVER (PARTITION BY date ORDER BY avg_games DESC)               AS rank_games,
                        ROW_NUMBER() OVER (
                            PARTITION BY date
                            ORDER BY CAST(avg_diff_coins AS REAL) / NULLIF(avg_games, 0) DESC
                        )                                                                           AS rank_efficiency
                    FROM {table}
                    WHERE date = ?
                """, (date,)).fetchall()

                # バッチUPDATE（executemany で一括適用）
                cursor.executemany(
                    f"UPDATE {table} SET {prefix}_diff = ?, {prefix}_games = ?, {prefix}_efficiency = ? WHERE rowid = ?",
                    [(r[1], r[2], r[3], r[0]) for r in rows]
                )

            conn.commit()
        finally:
            conn.close()
    
    def calculate_history_for_date(self, date: str):
        """指定日の履歴平均を計算"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            target_date = datetime.strptime(date, '%Y%m%d')
            tables = get_all_summary_tables()
            
            for period in [7, 14, 21, 28, 35]:
                start = (target_date - timedelta(days=period + 1)).strftime('%Y%m%d')
                end = (target_date - timedelta(days=1)).strftime('%Y%m%d')
                
                for table_info in tables:
                    table = table_info['table_name']
                    key = table_info['group_key']
                    prefix = table_info['rank_prefix']
                    
                    # テーブル存在確認
                    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
                    if not cursor.fetchone():
                        continue
                    
                    cursor.execute(f"""
                        UPDATE {table} SET
                            avg_diff_{period}d = (
                                SELECT CAST(AVG(avg_diff_coins) AS INTEGER)
                                FROM {table} h 
                                WHERE h.{key} = {table}.{key} 
                                AND h.date >= ? AND h.date <= ?
                            ),
                            avg_games_{period}d = (
                                SELECT CAST(AVG(avg_games) AS INTEGER)
                                FROM {table} h 
                                WHERE h.{key} = {table}.{key} 
                                AND h.date >= ? AND h.date <= ?
                            ),
                            avg_efficiency_{period}d = (
                                SELECT AVG(CAST(h.{prefix}_efficiency AS REAL))
                                FROM {table} h 
                                WHERE h.{key} = {table}.{key} 
                                AND h.date >= ? AND h.date <= ?
                            ),
                            avg_rank_diff_{period}d = (
                                SELECT CAST(AVG(CAST(h.{prefix}_diff AS REAL)) AS INTEGER)
                                FROM {table} h 
                                WHERE h.{key} = {table}.{key} 
                                AND h.date >= ? AND h.date <= ?
                            )
                        WHERE date = ?
                    """, (start, end, start, end, start, end, start, end, date))
            
            conn.commit()
        finally:
            conn.close()