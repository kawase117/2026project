#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
é›†è¨ˆå‡¦ç†ã®çµ±åˆã‚¯ãƒ©ã‚¹
"""

import sqlite3
from table_config import MACHINE_TYPE_CONFIGS

class SummaryCalculator:
    """å„ç¨®é›†è¨ˆå‡¦ç†ã‚’çµ±åˆ"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def update_machine_type_summary(self, date: str):
        """æ©Ÿç¨®åˆ¥ã‚µãƒžãƒªãƒ¼æ›´æ–°"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM daily_machine_type_summary WHERE date = ?', (date,))
            
            cursor.execute('''
                INSERT INTO daily_machine_type_summary (
                    date, machine_name, machine_count, total_games, avg_games,
                    max_games, min_games, total_diff_coins, avg_diff_coins,
                    max_diff_coins, min_diff_coins, total_bb, total_rb,
                    avg_bb_per_game, avg_rb_per_game, win_rate, efficiency, high_profit_rate,
                    is_over10_machine, is_3_machine
                )
                SELECT 
                    m.date, m.machine_name, COUNT(*),
                    SUM(m.games_normalized), ROUND(AVG(m.games_normalized), 1),
                    MAX(m.games_normalized), MIN(m.games_normalized),
                    SUM(m.diff_coins_normalized), ROUND(AVG(m.diff_coins_normalized), 1),
                    MAX(m.diff_coins_normalized), MIN(m.diff_coins_normalized),
                    SUM(m.bb_count), SUM(m.rb_count),
                    CASE WHEN SUM(m.games_normalized) > 0 
                        THEN ROUND(CAST(SUM(m.bb_count) AS REAL) / SUM(m.games_normalized), 6) END,
                    CASE WHEN SUM(m.games_normalized) > 0 
                        THEN ROUND(CAST(SUM(m.rb_count) AS REAL) / SUM(m.games_normalized), 6) END,
                    CAST(ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) AS INTEGER),
                    CASE WHEN SUM(m.games_normalized) > 0 
                        THEN ROUND(CAST(SUM(m.diff_coins_normalized) AS REAL) / SUM(m.games_normalized), 4) END,
                    ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1),
                    CASE WHEN COUNT(*) >= 10 THEN 1 ELSE 0 END,
                    CASE WHEN COUNT(*) = 3 THEN 1 ELSE 0 END
                FROM machine_detailed_results m
                WHERE m.date = ?
                GROUP BY m.date, m.machine_name
            ''', (date,))
            
            conn.commit()
            print(f"âœ“ æ©Ÿç¨®åˆ¥ã‚µãƒžãƒªãƒ¼: {cursor.rowcount}æ©Ÿç¨® ({date})")
        finally:
            conn.close()
    
    def update_last_digit_summary_by_type(self, date: str):
        """æœ«å°¾åˆ¥é›†è¨ˆã‚’æ©Ÿç¨®ã‚¿ã‚¤ãƒ—åˆ¥ã«æ›´æ–°"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            for config in MACHINE_TYPE_CONFIGS:
                table = f"last_digit_summary_{config['suffix']}"
                condition = config['condition']
                
                cursor.execute(f'DELETE FROM {table} WHERE date = ?', (date,))
                
                # åŸºæœ¬æœ«å°¾(0-9)
                cursor.execute(f'''
                    INSERT INTO {table} (
                        date, last_digit, machine_count, total_games, avg_games,
                        max_games, min_games, total_diff_coins, avg_diff_coins,
                        max_diff_coins, min_diff_coins, win_rate, high_profit_rate
                    )
                    SELECT 
                        m.date, m.last_digit, COUNT(*),
                        SUM(m.games_normalized), ROUND(AVG(m.games_normalized), 2),
                        MAX(m.games_normalized), MIN(m.games_normalized),
                        SUM(m.diff_coins_normalized), ROUND(AVG(m.diff_coins_normalized), 2),
                        MAX(m.diff_coins_normalized), MIN(m.diff_coins_normalized),
                        CAST(ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) AS INTEGER),
                        ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                    FROM machine_detailed_results m
                    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
                    WHERE m.date = ? {condition}
                    GROUP BY m.date, m.last_digit
                ''', (date,))
                
                # ã‚¾ãƒ­ç›®
                cursor.execute(f'''
                    INSERT INTO {table} (
                        date, last_digit, machine_count, total_games, avg_games,
                        max_games, min_games, total_diff_coins, avg_diff_coins,
                        max_diff_coins, min_diff_coins, win_rate, high_profit_rate
                    )
                    SELECT 
                        m.date, 'ã‚¾ãƒ­ç›®', COUNT(*),
                        SUM(m.games_normalized), ROUND(AVG(m.games_normalized), 2),
                        MAX(m.games_normalized), MIN(m.games_normalized),
                        SUM(m.diff_coins_normalized), ROUND(AVG(m.diff_coins_normalized), 2),
                        MAX(m.diff_coins_normalized), MIN(m.diff_coins_normalized),
                        CAST(ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) AS INTEGER),
                        ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                    FROM machine_detailed_results m
                    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
                    WHERE m.date = ? AND m.is_zorome = 1 {condition}
                    HAVING COUNT(*) > 0
                ''', (date,))
            
            conn.commit()
            print(f"âœ“ æœ«å°¾åˆ¥é›†è¨ˆå®Œäº† ({date})")
        finally:
            conn.close()
    
    def update_position_summary_by_type(self, date: str):
        """ä½ç½®åˆ¥é›†è¨ˆã‚’æ©Ÿç¨®ã‚¿ã‚¤ãƒ—åˆ¥ã«æ›´æ–°"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            for config in MACHINE_TYPE_CONFIGS:
                table = f"daily_position_summary_{config['suffix']}"
                condition = config['condition']
                
                cursor.execute(f'DELETE FROM {table} WHERE date = ?', (date,))
                
                cursor.execute(f'''
                    INSERT INTO {table} (
                        date, front_position, machine_count, total_games, avg_games,
                        max_games, min_games, total_diff_coins, avg_diff_coins,
                        max_diff_coins, min_diff_coins, win_rate, high_profit_rate
                    )
                    SELECT 
                        m.date, ml.front_position, COUNT(*),
                        SUM(m.games_normalized), ROUND(AVG(m.games_normalized), 1),
                        MAX(m.games_normalized), MIN(m.games_normalized),
                        SUM(m.diff_coins_normalized), ROUND(AVG(m.diff_coins_normalized), 1),
                        MAX(m.diff_coins_normalized), MIN(m.diff_coins_normalized),
                        CAST(ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) AS INTEGER),
                        ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                    FROM machine_detailed_results m
                    LEFT JOIN machine_layout ml ON m.machine_number = ml.machine_number
                    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
                    WHERE m.date = ? AND ml.front_position IS NOT NULL {condition}
                    GROUP BY m.date, ml.front_position
                ''', (date,))
            
            conn.commit()
            print(f"âœ“ ä½ç½®åˆ¥é›†è¨ˆå®Œäº† ({date})")
        finally:
            conn.close()
    
    def update_island_summary(self, date: str):
        """å³¶åˆ¥é›†è¨ˆã‚’æ›´æ–°"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM daily_island_summary WHERE date = ?', (date,))
            
            cursor.execute('''
                INSERT INTO daily_island_summary (
                    date, island_name, machine_count, total_games, avg_games,
                    total_diff_coins, avg_diff_coins, win_rate, high_profit_rate
                )
                SELECT 
                    m.date, ml.island_name, COUNT(*),
                    SUM(m.games_normalized), ROUND(AVG(m.games_normalized), 1),
                    SUM(m.diff_coins_normalized), ROUND(AVG(m.diff_coins_normalized), 1),
                    CAST(ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) AS INTEGER),
                    ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                FROM machine_detailed_results m
                LEFT JOIN machine_layout ml ON m.machine_number = ml.machine_number
                WHERE m.date = ? AND ml.island_name IS NOT NULL
                GROUP BY m.date, ml.island_name
            ''', (date,))
            
            conn.commit()
            print(f"âœ“ å³¶åˆ¥é›†è¨ˆ: {cursor.rowcount}å³¶ ({date})")
        finally:
            conn.close()