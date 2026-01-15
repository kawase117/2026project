#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設定管理モジュール
hall_config.json と table_config の統合管理
"""

import json
from typing import Dict, List, Optional, Any


class TableConfig:
    """テーブル設定マスター"""
    
    # 機種タイプ別テーブル設定
    MACHINE_TYPE_CONFIGS = [
        {
            'suffix': 'all',
            'name': '全体',
            'condition': '',
        },
        {
            'suffix': 'jug',
            'name': 'ジャグラー',
            'condition': 'AND mm.jug_flag = 1',
        },
        {
            'suffix': 'hana',
            'name': 'ハナハナ',
            'condition': 'AND mm.hana_flag = 1',
        },
        {
            'suffix': 'oki',
            'name': '沖ドキ',
            'condition': 'AND mm.oki_flag = 1',
        },
        {
            'suffix': 'other',
            'name': '非Aタイプ',
            'condition': 'AND mm.jug_flag = 0 AND mm.hana_flag = 0 AND mm.oki_flag = 0',
        }
    ]
    
    # 集計テーブル設定（ランク・履歴カラム用）
    SUMMARY_TABLE_CONFIGS = [
        {
            'base_name': 'daily_machine_type_summary',
            'group_key': 'machine_name',
            'rank_prefix': 'machine_type_rank',
            'variants': [None]  # 単一テーブル
        },
        {
            'base_name': 'last_digit_summary',
            'group_key': 'last_digit',
            'rank_prefix': 'last_digit_rank',
            'variants': ['all', 'jug', 'hana', 'oki', 'other']
        },
        {
            'base_name': 'daily_position_summary',
            'group_key': 'front_position',
            'rank_prefix': 'position_rank',
            'variants': ['all', 'jug', 'hana', 'oki', 'other']
        },
        {
            'base_name': 'daily_island_summary',
            'group_key': 'island_name',
            'rank_prefix': 'island_rank',
            'variants': [None]
        }
    ]
    
    # ランク・履歴カラム定義（全テーブル共通）
    RANK_HISTORY_COLUMNS = [
        "{prefix}_diff INTEGER",
        "{prefix}_games INTEGER",
        "{prefix}_efficiency INTEGER",
        "avg_diff_7d REAL", "avg_diff_14d REAL", "avg_diff_21d REAL",
        "avg_diff_28d REAL", "avg_diff_35d REAL",
        "avg_games_7d REAL", "avg_games_14d REAL", "avg_games_21d REAL",
        "avg_games_28d REAL", "avg_games_35d REAL",
        "avg_efficiency_7d REAL", "avg_efficiency_14d REAL", "avg_efficiency_21d REAL",
        "avg_efficiency_28d REAL", "avg_efficiency_35d REAL",
        "avg_rank_diff_7d REAL", "avg_rank_diff_14d REAL", "avg_rank_diff_21d REAL",
        "avg_rank_diff_28d REAL", "avg_rank_diff_35d REAL"
    ]
    
    @staticmethod
    def get_all_summary_tables() -> List[Dict[str, str]]:
        """すべての集計テーブル名とその設定を取得"""
        tables = []
        
        for config in TableConfig.SUMMARY_TABLE_CONFIGS:
            base = config['base_name']
            variants = config['variants']
            
            if variants == [None]:
                # 単一テーブル
                tables.append({
                    'table_name': base,
                    'group_key': config['group_key'],
                    'rank_prefix': config['rank_prefix']
                })
            else:
                # 複数バリアント
                for variant in variants:
                    tables.append({
                        'table_name': f"{base}_{variant}",
                        'group_key': config['group_key'],
                        'rank_prefix': config['rank_prefix']
                    })
        
        return tables
    
    @staticmethod
    def get_rank_columns(rank_prefix: str) -> List[str]:
        """指定されたプレフィックスでランク・履歴カラムを生成"""
        return [col.format(prefix=rank_prefix) for col in TableConfig.RANK_HISTORY_COLUMNS]
    
    @staticmethod
    def get_machine_type_config(suffix: str) -> Optional[Dict[str, Any]]:
        """機種タイプ設定を取得"""
        for config in TableConfig.MACHINE_TYPE_CONFIGS:
            if config['suffix'] == suffix:
                return config
        return None


class HallConfig:
    """ホール設定管理"""
    
    def __init__(self, config_file: str):
        """
        Parameters
        ----------
        config_file : str
            hall_config.json のパス
        """
        self.config_file = config_file
        self.halls = self._load_halls()
    
    def _load_halls(self) -> Dict[str, Dict[str, Any]]:
        """hall_config.json を読み込み"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # ホール名をキーとした辞書に変換
        halls = {}
        for hall in config.get('halls', []):
            halls[hall['hall_name']] = hall
        
        return halls
    
    def get_hall(self, hall_name: str) -> Optional[Dict[str, Any]]:
        """指定されたホール名の設定を取得"""
        return self.halls.get(hall_name)
    
    def get_active_halls(self) -> List[str]:
        """有効なホール名リストを取得"""
        return [name for name, cfg in self.halls.items() if cfg.get('active', True)]
    
    def get_all_halls(self) -> List[str]:
        """全ホール名リストを取得"""
        return list(self.halls.keys())


class ProjectConfig:
    """プロジェクト全体設定"""
    
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
        self.hall_config = HallConfig(hall_config_path)
        self.table_config = TableConfig()
    
    @property
    def active_halls(self) -> List[str]:
        """有効なホール名リスト"""
        return self.hall_config.get_active_halls()
    
    @property
    def all_summary_tables(self) -> List[Dict[str, str]]:
        """全集計テーブル情報"""
        return self.table_config.get_all_summary_tables()
    
    @property
    def machine_type_configs(self) -> List[Dict[str, Any]]:
        """機種タイプ設定リスト"""
        return self.table_config.MACHINE_TYPE_CONFIGS
