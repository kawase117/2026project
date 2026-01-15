#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
データベース操作モジュール
DB接続・CRUD操作を一元管理
"""

import sqlite3
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime


class DataAccessor:
    """データベース操作の一元管理クラス"""
    
    def __init__(self, db_path: str):
        """
        Parameters
        ----------
        db_path : str
            SQLiteデータベースのパス
        """
        self.db_path = db_path
        self._machine_master_initialized = False
    
    def get_connection(self) -> sqlite3.Connection:
        """DB接続を取得"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ===================================================================
    # 機種マスター操作
    # ===================================================================
    
    def ensure_machine_master_table(self):
        """機種マスターテーブルの存在確認と作成"""
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
        self.ensure_machine_master_table()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'SELECT * FROM machine_master WHERE machine_name_normalized = ?',
                (machine_name,)
            )
            existing = cursor.fetchone()
            
            if existing:
                return dict(existing)
            
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
    
    # ===================================================================
    # データ投入（INSERT/UPSERT）
    # ===================================================================
    
    def insert_machine_detailed_results(self, machine_data_list: List[Dict[str, Any]]) -> int:
        """個別台データをバッチ投入"""
        if not machine_data_list:
            return 0
        
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
            return len(records)
        finally:
            conn.close()
    
    def insert_daily_hall_summary(self, date: str, summary_data: Dict[str, Any]) -> bool:
        """日別全体集計を投入"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO daily_hall_summary (
                    date, total_machines, total_games, total_diff_coins,
                    avg_games_per_machine, avg_diff_per_machine
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                date,
                summary_data['total_machines'],
                summary_data['total_games'],
                summary_data['total_diff_coins'],
                summary_data['avg_games'],
                summary_data['avg_diff']
            ))
            conn.commit()
            return True
        finally:
            conn.close()
    
    # ===================================================================
    # データ更新（UPDATE）
    # ===================================================================
    
    def update_games_deviation(self, date: str, avg_games: int) -> int:
        """回転数偏差を更新"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE machine_detailed_results 
                SET games_deviation = games_normalized - ?
                WHERE date = ?
            ''', (avg_games, date))
            
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
    
    def update_features_for_table(self, table_name: str, date: str, 
                                   updates: Dict[str, Dict[str, Any]]) -> int:
        """
        テーブルの特徴量を更新
        
        Parameters
        ----------
        table_name : str
            更新対象テーブル
        date : str
            更新対象日付
        updates : Dict[str, Dict[str, Any]]
            更新情報 {key_value: {column: value, ...}}
        
        Returns
        -------
        int
            更新行数
        """
        if not updates:
            return 0
        
        conn = self.get_connection()
        cursor = conn.cursor()
        updated = 0
        
        try:
            for key_value, columns in updates.items():
                set_clauses = []
                values = []
                
                for col, val in columns.items():
                    set_clauses.append(f"{col} = ?")
                    values.append(val)
                
                if not set_clauses:
                    continue
                
                # WHERE句を動的に構築
                where_clause, where_values = self._build_where_clause(table_name, date, key_value)
                
                sql = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {where_clause}"
                cursor.execute(sql, values + where_values)
                updated += cursor.rowcount
            
            conn.commit()
            return updated
        finally:
            conn.close()
    
    def add_columns_if_needed(self, table_name: str, columns: List[str]) -> int:
        """
        テーブルに列を追加（既存列はスキップ）
        
        Parameters
        ----------
        table_name : str
            対象テーブル
        columns : List[str]
            追加するカラム定義のリスト
        
        Returns
        -------
        int
            追加されたカラム数
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        added = 0
        
        try:
            # テーブルが存在するか確認
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if not cursor.fetchone():
                return 0
            
            # 各カラムを追加
            for column_def in columns:
                try:
                    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_def}")
                    added += 1
                except sqlite3.OperationalError:
                    pass  # カラムが既に存在
            
            conn.commit()
            return added
        finally:
            conn.close()
    
    # ===================================================================
    # データ取得（SELECT）
    # ===================================================================
    
    def select_summary_data(self, date: str, table_name: str) -> List[Dict[str, Any]]:
        """指定テーブルの指定日のデータを取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"SELECT * FROM {table_name} WHERE date = ?", (date,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def select_daily_summary(self, date: str) -> Optional[Dict[str, Any]]:
        """日別全体集計データを取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM daily_hall_summary WHERE date = ?", (date,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def select_machine_detailed_results(self, date: str) -> List[Dict[str, Any]]:
        """個別台データを取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM machine_detailed_results WHERE date = ?", (date,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def select_past_data(self, date: str, table_name: str, 
                        column: str) -> List[Tuple[str, Any]]:
        """
        指定日付より過去のデータを取得
        
        Parameters
        ----------
        date : str
            基準日付（YYYYMMDD）
        table_name : str
            対象テーブル
        column : str
            取得するカラム
        
        Returns
        -------
        List[Tuple[str, Any]]
            [(date, value), ...] のリスト
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                f"SELECT date, {column} FROM {table_name} WHERE date < ? ORDER BY date DESC",
                (date,)
            )
            return cursor.fetchall()
        finally:
            conn.close()
    
    # ===================================================================
    # ヘルパーメソッド
    # ===================================================================
    
    def _build_where_clause(self, table_name: str, date: str, 
                           key_value: Any) -> Tuple[str, List[Any]]:
        """WHERE句を動的に構築"""
        where_clause = "date = ?"
        where_values = [date]
        
        # テーブル名から主キー名を判定
        if 'last_digit' in table_name:
            where_clause += " AND last_digit = ?"
            where_values.append(key_value)
        elif table_name == 'machine_detailed_results':
            where_clause += " AND machine_number = ?"
            where_values.append(key_value)
        elif table_name == 'daily_machine_type_summary':
            where_clause += " AND machine_name = ?"
            where_values.append(key_value)
        elif 'daily_position' in table_name:
            where_clause += " AND front_position = ?"
            where_values.append(key_value)
        elif table_name == 'daily_island_summary':
            where_clause += " AND island_name = ?"
            where_values.append(key_value)
        
        return where_clause, where_values
    
    def table_exists(self, table_name: str) -> bool:
        """テーブルが存在するか確認"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()
    
    def get_table_record_count(self, table_name: str, date: str) -> int:
        """指定テーブルの指定日レコード数を取得"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name} WHERE date = ?", (date,))
            return cursor.fetchone()[0]
        finally:
            conn.close()
