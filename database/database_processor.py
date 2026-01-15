#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
統合データ処理パイプライン
JSON読み込みからDB更新まで一連の処理を管理
"""

import os
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from database_config import ProjectConfig, TableConfig
from database_accessor import DataAccessor
from json_processor import JSONProcessor


class SummaryProcessor:
    """集計処理（summary_calculator + rank_calculator を統合）"""
    
    def __init__(self, db_accessor: DataAccessor, config: ProjectConfig):
        self.db = db_accessor
        self.config = config
    
    def process_date(self, date: str):
        """指定日の全集計を処理"""
        # 1. 機種別集計
        self._update_machine_type_summary(date)
        # 2. 末尾別集計
        self._update_last_digit_summary(date)
        # 3. 位置別集計
        self._update_position_summary(date)
        # 4. 島別集計
        self._update_island_summary(date)
        # 5. ランク計算
        self._calculate_ranks(date)
        # 6. 履歴計算
        self._calculate_history(date)
    
    def _update_machine_type_summary(self, date: str):
        """機種別サマリー更新"""
        conn = self.db.get_connection()
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
                    ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1),
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
            print(f"✓ 機種別サマリー: {cursor.rowcount}機種 ({date})")
        finally:
            conn.close()
    
    def _update_last_digit_summary(self, date: str):
        """末尾別サマリー更新"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for config in self.config.machine_type_configs:
                table = f"last_digit_summary_{config['suffix']}"
                condition = config['condition']
                
                cursor.execute(f'DELETE FROM {table} WHERE date = ?', (date,))
                
                # 基本末尾(0-9)
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
                        ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1),
                        ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                    FROM machine_detailed_results m
                    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
                    WHERE m.date = ? {condition}
                    GROUP BY m.date, m.last_digit
                ''', (date,))
                
                # ゾロ目
                cursor.execute(f'''
                    INSERT INTO {table} (
                        date, last_digit, machine_count, total_games, avg_games,
                        max_games, min_games, total_diff_coins, avg_diff_coins,
                        max_diff_coins, min_diff_coins, win_rate, high_profit_rate
                    )
                    SELECT 
                        m.date, 'ゾロ目', COUNT(*),
                        SUM(m.games_normalized), ROUND(AVG(m.games_normalized), 2),
                        MAX(m.games_normalized), MIN(m.games_normalized),
                        SUM(m.diff_coins_normalized), ROUND(AVG(m.diff_coins_normalized), 2),
                        MAX(m.diff_coins_normalized), MIN(m.diff_coins_normalized),
                        ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1),
                        ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                    FROM machine_detailed_results m
                    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
                    WHERE m.date = ? AND m.is_zorome = 1 {condition}
                    HAVING COUNT(*) > 0
                ''', (date,))
            
            conn.commit()
            print(f"✓ 末尾別サマリー完了 ({date})")
        finally:
            conn.close()
    
    def _update_position_summary(self, date: str):
        """位置別サマリー更新"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for config in self.config.machine_type_configs:
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
                        ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1),
                        ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                    FROM machine_detailed_results m
                    LEFT JOIN machine_layout ml ON m.machine_number = ml.machine_number
                    LEFT JOIN machine_master mm ON m.machine_name = mm.machine_name_normalized
                    WHERE m.date = ? AND ml.front_position IS NOT NULL {condition}
                    GROUP BY m.date, ml.front_position
                ''', (date,))
            
            conn.commit()
            print(f"✓ 位置別サマリー完了 ({date})")
        finally:
            conn.close()
    
    def _update_island_summary(self, date: str):
        """島別サマリー更新"""
        conn = self.db.get_connection()
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
                    ROUND(SUM(CASE WHEN m.diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1),
                    ROUND(SUM(CASE WHEN m.games_normalized >= 3000 AND m.diff_coins_normalized >= 1000 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1)
                FROM machine_detailed_results m
                LEFT JOIN machine_layout ml ON m.machine_number = ml.machine_number
                WHERE m.date = ? AND ml.island_name IS NOT NULL
                GROUP BY m.date, ml.island_name
            ''', (date,))
            
            conn.commit()
            print(f"✓ 島別サマリー: {cursor.rowcount}島 ({date})")
        finally:
            conn.close()
    
    def _calculate_ranks(self, date: str):
        """ランク計算"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            for table_info in self.config.all_summary_tables:
                table = table_info['table_name']
                prefix = table_info['rank_prefix']
                
                if not self.db.table_exists(table):
                    continue
                
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
            print(f"✓ ランク計算完了 ({date})")
        finally:
            conn.close()
    
    def _calculate_history(self, date: str):
        """履歴計算"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            target_date = datetime.strptime(date, '%Y%m%d')
            
            for period in [7, 14, 21, 28, 35]:
                start = (target_date - timedelta(days=period + 1)).strftime('%Y%m%d')
                end = (target_date - timedelta(days=1)).strftime('%Y%m%d')
                
                for table_info in self.config.all_summary_tables:
                    table = table_info['table_name']
                    key = table_info['group_key']
                    prefix = table_info['rank_prefix']
                    
                    if not self.db.table_exists(table):
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
            print(f"✓ 履歴計算完了 ({date})")
        finally:
            conn.close()


class DataPipeline:
    """統合データ処理パイプライン"""
    
    def __init__(self, db_path: str, hall_config_path: str, json_processor: JSONProcessor):
        """
        Parameters
        ----------
        db_path : str
            SQLiteデータベースのパス
        hall_config_path : str
            hall_config.json のパス
        json_processor : JSONProcessor
            JSON処理エンジン
        """
        self.config = ProjectConfig(db_path, hall_config_path)
        self.db = DataAccessor(db_path)
        self.summary = SummaryProcessor(self.db, self.config)
        self.json_processor = json_processor
        
        self._setup_done = False
    
    def _ensure_setup(self):
        """初期化処理（ランク・履歴カラム追加）"""
        if self._setup_done:
            return
        
        for table_info in self.config.all_summary_tables:
            table_name = table_info['table_name']
            rank_prefix = table_info['rank_prefix']
            
            if not self.db.table_exists(table_name):
                continue
            
            columns = TableConfig.get_rank_columns(rank_prefix)
            added = self.db.add_columns_if_needed(table_name, columns)
            if added > 0:
                print(f"  + {table_name}: {added}カラム追加")
        
        self._setup_done = True
    
    def process_single_date(self, json_filepath: str) -> Optional[str]:
        """
        単一JSONファイルを処理
        
        Parameters
        ----------
        json_filepath : str
            JSON ファイルパス
        
        Returns
        -------
        str
            処理された日付（YYYYMMDD）、エラー時は None
        """
        print(f"\n処理中: {os.path.basename(json_filepath)}")
        
        self._ensure_setup()
        
        try:
            # 1. JSONロード
            json_data = self.json_processor.load_json_file(json_filepath)
            date = json_data.get("date")
            if not date:
                raise ValueError(f"日付情報なし: {json_filepath}")
            
            # 2. 個別台データ処理
            machine_records = json_data.get("all_data", [])
            machine_data_list = self.json_processor.process_all_machine_data_for_day(
                date, machine_records, None
            )
            
            # 3. 個別台データ投入
            inserted = self.db.insert_machine_detailed_results(machine_data_list)
            print(f"✓ 個別台データ {inserted} 件投入")
            
            # 4. 日別全体集計
            avg_games = self._calculate_and_insert_daily_summary(date)
            if avg_games:
                updated = self.db.update_games_deviation(date, avg_games)
                print(f"✓ 回転数偏差更新: {updated}台 (平均{avg_games}G)")
            
            # 5. 各種集計・ランク・履歴
            self.summary.process_date(date)
            
            return date
        
        except Exception as e:
            print(f"❌ エラー: {str(e)}")
            raise
    
    def process_all_dates(self) -> List[str]:
        """全JSONファイルをバッチ処理"""
        json_files = self.json_processor.get_json_files()
        processed_dates = []
        
        print(f"\n🚀 バッチ処理開始: {len(json_files)} ファイル")
        
        for i, json_file in enumerate(json_files, 1):
            try:
                date = self.process_single_date(json_file)
                if date:
                    processed_dates.append(date)
                    print(f"進捗: {i}/{len(json_files)} ({date})")
            except Exception as e:
                print(f"❌ {os.path.basename(json_file)}: {str(e)}")
                raise
        
        print(f"\n✅ 完了: {len(processed_dates)} 日分")
        return processed_dates
    
    def _calculate_and_insert_daily_summary(self, date: str) -> Optional[int]:
        """日別全体集計を計算して投入"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_machines,
                    SUM(games_normalized) as total_games,
                    SUM(diff_coins_normalized) as total_diff_coins,
                    CAST(AVG(CAST(games_normalized AS REAL)) AS INTEGER) as avg_games,
                    CAST(AVG(CAST(diff_coins_normalized AS REAL)) AS INTEGER) as avg_diff
                FROM machine_detailed_results
                WHERE date = ?
            ''', (date,))
            
            result = cursor.fetchone()
            
            if result and result[0] > 0:
                total_machines, total_games, total_diff_coins, avg_games, avg_diff = result
                
                summary_data = {
                    'total_machines': total_machines,
                    'total_games': total_games,
                    'total_diff_coins': total_diff_coins,
                    'avg_games': avg_games,
                    'avg_diff': avg_diff
                }
                
                if self.db.insert_daily_hall_summary(date, summary_data):
                    print(f"✓ 日別全体集計 ({date}): 台数={total_machines}, 平均={avg_games}G")
                    return avg_games
        finally:
            conn.close()
        
        return None
