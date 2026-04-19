#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基本的なデータINSERT処理
"""

import sqlite3
from typing import List, Dict, Any
from datetime import datetime

class DataInserter:
    """基本的なデータ投入クラス"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._machine_master_initialized = False
    
    def get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def _ensure_machine_master_table(self):
        """機種マスターテーブルの存在確認"""
        if self._machine_master_initialized:
            return
            
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS machine_master (
                    machine_name_normalized TEXT PRIMARY KEY,
                    jug_flag BOOLEAN,
                    hana_flag BOOLEAN,
                    oki_flag BOOLEAN,
                    bt_flag BOOLEAN DEFAULT 0,
                    display_names TEXT,
                    official_name TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            ''')
            conn.commit()
            self._machine_master_initialized = True
        finally:
            conn.close()
    
    def get_or_create_machine_master(self, machine_name: str) -> Dict[str, Any]:
        """機種マスター情報を取得または作成"""
        self._ensure_machine_master_table()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT * FROM machine_master WHERE machine_name_normalized = ?',
                (machine_name,)
            )
            existing = cursor.fetchone()
            
            if existing:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, existing))
            
            # 新規機種の場合、機種名から分類
            jug_flag = 1 if 'ジャグラー' in machine_name else 0
            hana_flag = 1 if 'ハナハナ' in machine_name else 0
            oki_flag = 1 if '沖ドキ' in machine_name else 0
            
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
                INSERT INTO machine_master (
                    machine_name_normalized, jug_flag, hana_flag, oki_flag,
                    display_names, official_name, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (machine_name, jug_flag, hana_flag, oki_flag, 
                  machine_name, machine_name, now, now))
            
            conn.commit()
            
            return {
                'machine_name_normalized': machine_name,
                'jug_flag': jug_flag,
                'hana_flag': hana_flag,
                'oki_flag': oki_flag
            }
        finally:
            conn.close()
    
    def insert_machine_detailed_results(self, machine_data_list: List[Dict[str, Any]]):
        """個別台データをバッチ投入"""
        if not machine_data_list:
            return
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            insert_sql = '''
                INSERT OR REPLACE INTO machine_detailed_results (
                    date, machine_name, machine_number, last_digit, is_zorome,
                    machine_rank_in_type, games_normalized, diff_coins_normalized,
                    games_deviation, bb_count, rb_count,
                    total_probability_fraction, total_probability_decimal,
                    bb_probability_fraction, bb_probability_decimal,
                    rb_probability_fraction, rb_probability_decimal
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            
            records = []
            for data in machine_data_list:
                self.get_or_create_machine_master(data["machine_name"])
                
                record = (
                    data["date"], data["machine_name"], data["machine_number"],
                    data["last_digit"], data["is_zorome"], data["machine_rank_in_type"],
                    data["games_normalized"], data["diff_coins_normalized"],
                    data["games_deviation"], data["bb_count"], data["rb_count"],
                    data["total_probability_fraction"], data["total_probability_decimal"],
                    data["bb_probability_fraction"], data["bb_probability_decimal"],
                    data["rb_probability_fraction"], data["rb_probability_decimal"]
                )
                records.append(record)
            
            cursor.executemany(insert_sql, records)
            conn.commit()
            print(f"[OK] 個別台データ {len(records)} 件投入")
            
        finally:
            conn.close()
    
    def update_games_deviation(self, date: str, avg_games_per_machine: int):
        """回転数偏差を更新"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE machine_detailed_results 
                SET games_deviation = games_normalized - ?
                WHERE date = ?
            ''', (avg_games_per_machine, date))
            
            conn.commit()
            print(f"[OK] 回転数偏差更新: {cursor.rowcount}台 (平均{avg_games_per_machine}G)")
        finally:
            conn.close()
    
    def calculate_and_insert_daily_summary(self, date: str):
        """日別全体集計を計算して投入（win_rate を含む）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_machines,
                    SUM(games_normalized) as total_games,
                    SUM(diff_coins_normalized) as total_diff_coins,
                    CAST(AVG(CAST(games_normalized AS REAL)) AS INTEGER) as avg_games,
                    CAST(AVG(CAST(diff_coins_normalized AS REAL)) AS INTEGER) as avg_diff,
                    SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END) as win_count
                FROM machine_detailed_results
                WHERE date = ?
            ''', (date,))
            
            result = cursor.fetchone()
            
            if result and result[0] > 0:
                total_machines, total_games, total_diff_coins, avg_games, avg_diff, win_count = result
                win_rate = int(round(win_count * 100.0 / total_machines, 0))
                
                cursor.execute('''
                    INSERT OR REPLACE INTO daily_hall_summary (
                        date, total_machines, total_games, total_diff_coins,
                        avg_games_per_machine, avg_diff_per_machine, win_rate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (date, total_machines, total_games, total_diff_coins, avg_games, avg_diff, win_rate))
                
                conn.commit()
                print(f"[OK] 日別全体集計 ({date}): 台数={total_machines}, 平均={avg_games}G, 勝率={win_rate}%")
                return avg_games
        finally:
            conn.close()
        
        return None