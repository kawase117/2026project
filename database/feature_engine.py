#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
特徴量計算統合インターフェース
database_processor と feature_calculator を結合するアダプタ
"""

import pandas as pd
from typing import Optional

# ここで feature_calculator_part1, part2 をインポートできる
# 当面は既存の feature_calculator.py を使用


class FeatureEngineeringPipeline:
    """特徴量エンジニアリングパイプライン"""
    
    def __init__(self, db_path: str, hall_config_path: str):
        """
        Parameters
        ----------
        db_path : str
            SQLiteデータベースのパス
        hall_config_path : str
            hall_config.json のパス
        """
        self.db_path = db_path
        self.hall_config_path = hall_config_path
        
        # 特徴量計算エンジンをここで遅延ロード
        self._feature_calc = None
    
    @property
    def feature_calc(self):
        """特徴量計算エンジン（遅延ロード）"""
        if self._feature_calc is None:
            from feature_calculator import FeatureCalculator
            self._feature_calc = FeatureCalculator(self.db_path, self.hall_config_path)
        return self._feature_calc
    
    def calculate_features_for_date(self, date: str, table_name: str, 
                                   hall_name: str) -> Optional[pd.DataFrame]:
        """
        指定日の指定テーブルに対して特徴量を計算
        
        Parameters
        ----------
        date : str
            計算対象日付（YYYYMMDD）
        table_name : str
            計算対象テーブル
        hall_name : str
            ホール名
        
        Returns
        -------
        pd.DataFrame
            特徴量が計算された DataFrame、計算失敗時は None
        """
        try:
            # テーブルからデータを取得
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            
            # 集計テーブルからデータを取得
            query = f"SELECT * FROM {table_name} WHERE date = ?"
            df_data = pd.read_sql_query(query, conn, params=(date,))
            
            if df_data.empty:
                conn.close()
                return None
            
            # event_calendar を取得
            df_event = pd.read_sql_query("SELECT * FROM event_calendar", conn)
            
            conn.close()
            
            if df_event.empty:
                return df_data  # イベントカレンダーがない場合は何もしない
            
            # テーブル別に特徴量計算
            if table_name == 'daily_hall_summary':
                # グループG（イベント×末尾マッチング）のみ
                df_result = self.feature_calc.calculate_group_g_features(
                    date, df_data, df_event, hall_name
                )
            
            elif 'last_digit_summary' in table_name:
                # グループA（基本統計）+ グループB～F（履歴）+ グループ新規①・③
                df_result = df_data.copy()
                
                # グループA
                df_result = self.feature_calc.calculate_group_a_features(
                    date, df_event, df_result
                )
                
                # グループB～F
                df_result = self.feature_calc.calculate_group_bf_features(
                    date, df_result
                )
                
                # グループ新規①（刻み値）
                df_result = self.feature_calc.calculate_group_new1_features(
                    df_result
                )
                
                # グループ新規③（末尾連続パターン）
                df_result = self.feature_calc.calculate_group_new3_features(
                    date, df_result
                )
            
            elif table_name == 'machine_detailed_results':
                # グループA + グループB～F + グループ新規① + グループ新規②
                df_result = df_data.copy()
                
                # グループA
                df_result = self.feature_calc.calculate_group_a_features(
                    date, df_event, df_result
                )
                
                # グループB～F
                df_result = self.feature_calc.calculate_group_bf_features(
                    date, df_result
                )
                
                # グループ新規①（刻み値）
                df_result = self.feature_calc.calculate_group_new1_features(
                    df_result
                )
                
                # グループ新規②（隣接台パターン）
                df_result = self.feature_calc.calculate_group_new2_features(
                    date, df_result
                )
            
            elif 'daily_machine_type_summary' in table_name or \
                 'daily_position_summary' in table_name or \
                 'daily_island_summary' in table_name:
                # グループA + グループB～F + グループ新規①
                df_result = df_data.copy()
                
                # グループA
                df_result = self.feature_calc.calculate_group_a_features(
                    date, df_event, df_result
                )
                
                # グループB～F
                df_result = self.feature_calc.calculate_group_bf_features(
                    date, df_result
                )
                
                # グループ新規①（刻み値）
                df_result = self.feature_calc.calculate_group_new1_features(
                    df_result
                )
            
            else:
                # 未対応テーブル
                return df_data
            
            return df_result
        
        except Exception as e:
            print(f"⚠️ 特徴量計算エラー ({table_name}, {date}): {str(e)}")
            return None
