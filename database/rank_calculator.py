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
        """指定日の全テーブルのランクを計算"""
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
                
                # ランク計算（効率的なサブクエリ方式）
                cursor.execute(f"""
                    UPDATE {table} SET
                        {prefix}_diff = (
                            SELECT COUNT(*) + 1 
                            FROM {table} t2 
                            WHERE t2.date = ? AND t2.avg_diff_coins > {table}.avg_diff_coins
                        ),
                        {prefix}_games = (
                            SELECT COUNT(*) + 1 
                            FROM {table} t2 
                            WHERE t2.date = ? AND t2.avg_games > {table}.avg_games
                        ),
                        {prefix}_efficiency = (
                            SELECT COUNT(*) + 1 
                            FROM {table} t2 
                            WHERE t2.date = ? 
                            AND CAST(t2.avg_diff_coins AS REAL) / NULLIF(t2.avg_games, 0) 
                                > CAST({table}.avg_diff_coins AS REAL) / NULLIF({table}.avg_games, 0)
                        )
                    WHERE date = ?
                """, (date, date, date, date))
            
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