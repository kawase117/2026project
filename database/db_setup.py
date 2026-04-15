#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
データベーステーブル定義（設定駆動版）
"""

import sqlite3
import os
import csv
from table_config import MACHINE_TYPE_CONFIGS, SUMMARY_TABLE_CONFIGS, get_rank_columns

def create_database(hall_name, db_dir="."):
    """データベース作成"""
    safe_hall_name = hall_name.replace(" ", "_").replace("（", "(").replace("）", ")")
    db_filename = f"{safe_hall_name}.db"
    
    # db/ フォルダ直下に配置
    db_folder = os.path.join(db_dir, "db")
    os.makedirs(db_folder, exist_ok=True)
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
    rank_columns = get_rank_columns('machine_type_rank')
    rank_columns_sql = ',\n            '.join(rank_columns)
    
    cursor.execute(f'''
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
            win_rate INTEGER,
            efficiency REAL,
            high_profit_rate REAL,
            is_over10_machine BOOLEAN DEFAULT 0,
            is_3_machine BOOLEAN DEFAULT 0,
            {rank_columns_sql},
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
    rank_columns = get_rank_columns('island_rank')
    rank_columns_sql = ',\n            '.join(rank_columns)
    
    cursor.execute(f'''
        CREATE TABLE daily_island_summary (
            date TEXT,
            island_name TEXT,
            machine_count INTEGER,
            total_games INTEGER,
            avg_games REAL,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            win_rate INTEGER,
            high_profit_rate REAL,
            {rank_columns_sql},
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
            avg_diff_per_machine INTEGER,
            win_rate INTEGER,
            
            -- 日付情報カラム（date_info_calculator.py で追加）
            day_of_week TEXT,
            last_digit INTEGER,
            weekday_nth TEXT,
            is_strong_zorome INTEGER DEFAULT 0,
            is_zorome INTEGER DEFAULT 0,
            is_month_start INTEGER DEFAULT 0,
            is_month_end INTEGER DEFAULT 0,
            is_weekend INTEGER DEFAULT 0,
            is_holiday INTEGER DEFAULT 0,
            hall_anniversary INTEGER DEFAULT 0,
            is_x_day INTEGER DEFAULT 0,
            week_of_month INTEGER,
            is_any_event INTEGER DEFAULT 0
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
    print(f"  - ランク・履歴カラム: 全集計テーブルに統合完了")
    
    # 台配置CSV自動インポート
    _import_machine_layout(db_path, hall_name, db_dir)
    
    return db_path

def _create_summary_tables(cursor, base_name, key_column, is_integer_key=False):
    """集計テーブルを設定駆動で作成（ランク・履歴カラム含む）"""
    key_type = 'INTEGER' if is_integer_key else 'TEXT'
    
    # テーブルの rank_prefix を特定
    rank_prefix = None
    for summary_config in SUMMARY_TABLE_CONFIGS:
        if summary_config['base_name'] == base_name:
            rank_prefix = summary_config['rank_prefix']
            break
    
    if not rank_prefix:
        rank_prefix = base_name.replace('daily_', '').replace('_summary', '')
    
    for config in MACHINE_TYPE_CONFIGS:
        suffix = config['suffix']
        table_name = f"{base_name}_{suffix}"
        
        rank_columns = get_rank_columns(rank_prefix)
        rank_columns_sql = ',\n                '.join(rank_columns)
        
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
                win_rate INTEGER,
                high_profit_rate REAL,
                {rank_columns_sql},
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

def create_machine_master_db(db_dir="."):
    """machine_master.db を新規作成（複数ホール間共有マスターDB）"""
    db_folder = os.path.join(db_dir, "db")
    os.makedirs(db_folder, exist_ok=True)
    
    db_path = os.path.join(db_folder, "machine_master.db")
    
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"既存 machine_master.db 削除: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print(f"machine_master.db 作成: {db_path}")
    
    # machine_master テーブル定義
    cursor.execute('''
        CREATE TABLE machine_master (
            machine_name_normalized TEXT PRIMARY KEY,
            
            -- 機種分類フラグ
            jug_flag BOOLEAN DEFAULT 0,
            hana_flag BOOLEAN DEFAULT 0,
            oki_flag BOOLEAN DEFAULT 0,
            bt_flag BOOLEAN DEFAULT 0,
            
            -- 表記・名称
            display_names TEXT,
            official_name TEXT,
            
            -- ペイアウト情報
            payout_setting1 REAL,
            payout_setting2 REAL,
            payout_setting3 REAL,
            payout_setting4 REAL,
            payout_setting5 REAL,
            payout_setting6 REAL,
            
            -- タイムスタンプ
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("✓ machine_master テーブル作成")
    
    # BT機種16個の初期データを登録
    bt_machines = [
        ('__LBパチスロ ヱヴァンゲリヲン ～約束の扉__', '__LBパチスロ ヱヴァンゲリヲン ～約束の扉__'),
        ('スマスロ サンダーV', 'スマスロ サンダーV'),
        ('ニューキングハナハナV', 'ニューキングハナハナV'),
        ('L不二子BT', 'L不二子BT'),
        ('SHAKE BONUS TRIGGER', 'SHAKE BONUS TRIGGER'),
        ('マジカルハロウィン ボーナストリガー', 'マジカルハロウィン ボーナストリガー'),
        ('クレアの秘宝伝 〜はじまりの扉と太陽の石〜 ボーナストリガーver.', 'クレアの秘宝伝 ボーナストリガー'),
        ('マタドールⅢ', 'マタドールⅢ'),
        ('アレックス ブライト', 'アレックス ブライト'),
        ('LBトリプルクラウン', 'LBトリプルクラウン'),
        ('LBジャックポット', 'LBジャックポット'),
        ('LBパチスロ1000ちゃんA', 'LBパチスロ1000ちゃんA'),
        ('翔べ！ハーレムエース', '翔べ！ハーレムエース'),
        ('LBプレミアムうまい棒', 'LBプレミアムうまい棒'),
        ('スマスロニューパルサーBT', 'スマスロニューパルサーBT'),
    ]
    
    for machine_name, official_name in bt_machines:
        cursor.execute('''
            INSERT INTO machine_master (
                machine_name_normalized, bt_flag, official_name
            ) VALUES (?, 1, ?)
        ''', (machine_name, official_name))
    
    print(f"✓ BT機種16個を登録")
    
    conn.commit()
    conn.close()
    
    return db_path

if __name__ == "__main__":
    print("main_processor.pyから実行してください。")