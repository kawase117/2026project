#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
データベーステーブル定義（設定駆動版）
"""

import sqlite3
import os
import csv
from table_config import MACHINE_TYPE_CONFIGS

def create_database(hall_name, db_dir="."):
    """データベース作成（ホール別 DB を db フォルダ直下に配置）"""
    # db フォルダを確保（なければ作成）
    db_folder = os.path.join(db_dir, "db")
    os.makedirs(db_folder, exist_ok=True)
    
    # ホール名をファイル名として使用（スペースなど危険な文字のみ処理）
    safe_hall_name = hall_name.replace(" ", "_").replace("（", "(").replace("）", ")")
    db_filename = f"{safe_hall_name}.db"
    db_path = os.path.join(db_folder, db_filename)
    
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"既存DB削除: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"データベース作成: {db_path}")
    
    # 1. 台配置マスター
    cursor.execute('''
        CREATE TABLE machine_layout (
            machine_number INTEGER PRIMARY KEY,
            front_position INTEGER,
            back_position INTEGER,
            island_name TEXT
        )
    ''')
    print("✓ machine_layout")
    
    # 2. 個別台データ
    cursor.execute('''
        CREATE TABLE machine_detailed_results (
            date TEXT,
            machine_name TEXT,
            machine_number INTEGER,
            last_digit TEXT,
            is_zorome BOOLEAN,
            machine_rank_in_type INTEGER,
            games_normalized INTEGER,
            diff_coins_normalized INTEGER,
            games_deviation INTEGER,
            bb_count INTEGER,
            rb_count INTEGER,
            total_probability_fraction TEXT,
            total_probability_decimal REAL,
            bb_probability_fraction TEXT,
            bb_probability_decimal REAL,
            rb_probability_fraction TEXT, 
            rb_probability_decimal REAL,
            PRIMARY KEY (date, machine_number)
        )
    ''')
    print("✓ machine_detailed_results")
    
    # 3. 機種別サマリー
    cursor.execute('''
        CREATE TABLE daily_machine_type_summary (
            date TEXT,
            machine_name TEXT,
            machine_count INTEGER NOT NULL,
            total_games INTEGER,
            avg_games REAL,
            max_games INTEGER,
            min_games INTEGER,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            max_diff_coins INTEGER,
            min_diff_coins INTEGER,
            total_bb INTEGER,
            total_rb INTEGER,
            avg_bb_per_game REAL,
            avg_rb_per_game REAL,
            win_rate REAL,
            efficiency REAL,
            high_profit_rate REAL,
            is_over10_machine BOOLEAN DEFAULT 0,
            is_3_machine BOOLEAN DEFAULT 0,
            PRIMARY KEY (date, machine_name)
        )
    ''')
    cursor.execute('CREATE INDEX idx_daily_machine_type_date ON daily_machine_type_summary(date)')
    print("✓ daily_machine_type_summary")
    
    # 4. 末尾別集計（5テーブル）
    _create_summary_tables(cursor, 'last_digit_summary', 'last_digit')
    
    # 5. 位置別集計（5テーブル）
    _create_summary_tables(cursor, 'daily_position_summary', 'front_position', is_integer_key=True)
    
    # 6. 島別集計
    cursor.execute('''
        CREATE TABLE daily_island_summary (
            date TEXT,
            island_name TEXT,
            machine_count INTEGER,
            total_games INTEGER,
            avg_games REAL,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            win_rate REAL,
            high_profit_rate REAL,
            PRIMARY KEY (date, island_name)
        )
    ''')
    cursor.execute('CREATE INDEX idx_daily_island_date ON daily_island_summary(date)')
    print("✓ daily_island_summary")
    
    # 7. 日別全体集計
    cursor.execute('''
        CREATE TABLE daily_hall_summary (
            date TEXT PRIMARY KEY,
            total_machines INTEGER,
            total_games INTEGER,
            total_diff_coins INTEGER,
            avg_games_per_machine INTEGER,
            avg_diff_per_machine INTEGER
        )
    ''')
    print("✓ daily_hall_summary")
    
    conn.commit()
    conn.close()
    
    print(f"\nテーブル作成完了:")
    print(f"  - 基本: 3テーブル")
    print(f"  - 末尾別: 5テーブル (all, jug, hana, oki, other)")
    print(f"  - 位置別: 5テーブル (all, jug, hana, oki, other)")
    print(f"  - 島別: 1テーブル")
    
    # 台配置CSV自動インポート
    _import_machine_layout(db_path, hall_name, db_dir)
    
    return db_path

def _create_summary_tables(cursor, base_name, key_column, is_integer_key=False):
    """集計テーブルを設定駆動で作成"""
    key_type = 'INTEGER' if is_integer_key else 'TEXT'
    
    for config in MACHINE_TYPE_CONFIGS:
        suffix = config['suffix']
        table_name = f"{base_name}_{suffix}"
        
        cursor.execute(f'''
            CREATE TABLE {table_name} (
                date TEXT,
                {key_column} {key_type},
                machine_count INTEGER,
                total_games INTEGER,
                avg_games REAL,
                max_games INTEGER,
                min_games INTEGER,
                total_diff_coins INTEGER,
                avg_diff_coins REAL,
                max_diff_coins INTEGER,
                min_diff_coins INTEGER,
                win_rate REAL,
                high_profit_rate REAL,
                PRIMARY KEY (date, {key_column})
            )
        ''')
        cursor.execute(f'CREATE INDEX idx_{table_name}_date ON {table_name}(date)')
        cursor.execute(f'CREATE INDEX idx_{table_name}_key ON {table_name}({key_column})')
        print(f"✓ {table_name}")

def _import_machine_layout(db_path, hall_name, db_dir):
    """台配置CSVを自動インポート"""
    try:
        csv_filename = f"{hall_name}台位置.csv"
        base_dir = db_dir if db_dir != "." else os.getcwd()
        csv_dir = os.path.join(base_dir, "scraped_data", hall_name)
        csv_path = os.path.join(csv_dir, csv_filename)
        
        if not os.path.exists(csv_path):
            print(f"⚠️ 台配置CSV未検出: {csv_filename}")
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            csv_reader = csv.DictReader(f)
            records = []
            
            for row in csv_reader:
                try:
                    records.append((
                        int(row['台番号']),
                        int(row['前角']),
                        int(row['後角']),
                        row['列名'].strip()
                    ))
                except (ValueError, KeyError):
                    continue
        
        if records:
            cursor.executemany('''
                INSERT OR REPLACE INTO machine_layout 
                (machine_number, front_position, back_position, island_name)
                VALUES (?, ?, ?, ?)
            ''', records)
            conn.commit()
            print(f"✓ 台配置データ: {len(records)}台 ({csv_filename})")
        
        conn.close()
        
    except Exception as e:
        print(f"⚠️ 台配置CSV読み込みエラー: {str(e)}")

if __name__ == "__main__":
    print("main_processor.pyから実行してください。")