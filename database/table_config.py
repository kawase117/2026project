#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テーブル設定の一元管理
"""

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

def get_all_summary_tables():
    """すべての集計テーブル名とその設定を取得"""
    tables = []
    
    for config in SUMMARY_TABLE_CONFIGS:
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

def get_rank_columns(rank_prefix):
    """指定されたプレフィックスでランク・履歴カラムを生成"""
    return [col.format(prefix=rank_prefix) for col in RANK_HISTORY_COLUMNS]