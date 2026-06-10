#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
データベーステーブル定義（設定駆動版）
"""

import sqlite3
import os
import csv
import sys
from table_config import MACHINE_TYPE_CONFIGS, SUMMARY_TABLE_CONFIGS, get_rank_columns

sys.stdout.reconfigure(encoding='utf-8')

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
    
    # 1. 台配置マスター（フロア座標付き）
    cursor.execute('''
        CREATE TABLE machine_layout (
            machine_number      INTEGER PRIMARY KEY,
            hall_name           TEXT,
            x                   INTEGER,
            y                   INTEGER,
            display_y           INTEGER,
            section             TEXT,
            section_min         INTEGER,
            section_max         INTEGER,
            rank_from_min       INTEGER,
            rank_from_max       INTEGER,
            is_reversed_section INTEGER DEFAULT 0,
            rank_from_aisle     INTEGER,
            physical_corner     INTEGER,
            physical_corner_valid INTEGER DEFAULT 0
        )
    ''')
    print("[OK] machine_layout")
    
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
    print("[OK] machine_detailed_results")
    
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
    print("[OK] daily_machine_type_summary")
    
    # 4. 末尾別集計（6テーブル）
    _create_summary_tables(cursor, 'last_digit_summary', 'last_digit')
    
    # 5. 位置別集計（6テーブル）
    _create_summary_tables(cursor, 'daily_position_summary', 'rank_from_min', is_integer_key=True)
    
    # 6. 島別集計
    rank_columns = get_rank_columns('island_rank')
    rank_columns_sql = ',\n            '.join(rank_columns)
    
    cursor.execute(f'''
        CREATE TABLE daily_island_summary (
            date TEXT,
            section TEXT,
            machine_count INTEGER,
            total_games INTEGER,
            avg_games REAL,
            total_diff_coins INTEGER,
            avg_diff_coins REAL,
            win_rate INTEGER,
            high_profit_rate REAL,
            {rank_columns_sql},
            PRIMARY KEY (date, section)
        )
    ''')
    cursor.execute('CREATE INDEX idx_daily_island_date ON daily_island_summary(date)')
    print("[OK] daily_island_summary")
    
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
    print("[OK] daily_hall_summary")

    # 8. 月次トレンド集計
    _create_monthly_trend_tables(cursor)
    
    conn.commit()
    conn.close()
    
    print(f"\nテーブル作成完了:")
    print(f"  - 基本: 3テーブル")
    print(f"  - 末尾別: 6テーブル (all, jug, hana, oki, bt, other)")
    print(f"  - 位置別: 6テーブル (all, jug, hana, oki, bt, other)")
    print(f"  - 島別: 1テーブル")
    print(f"  - 月次トレンド: 18テーブル (3軸 × 6タイプ)")
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
        print(f"[OK] {table_name}")

def _create_monthly_trend_tables(cursor):
    """月次トレンドテーブルを作成（3軸 × 6機種タイプ = 18テーブル）"""
    axis_configs = [
        {'axis': 'date_digit', 'key_col': 'date_digit INTEGER NOT NULL', 'key_name': 'date_digit'},
        {'axis': 'weekday', 'key_col': 'day_of_week TEXT NOT NULL', 'key_name': 'day_of_week'},
        {'axis': 'machine_digit', 'key_col': 'machine_digit TEXT NOT NULL', 'key_name': 'machine_digit'},
    ]
    type_suffixes = [config['suffix'] for config in MACHINE_TYPE_CONFIGS]

    for axis_cfg in axis_configs:
        axis = axis_cfg['axis']
        key_col = axis_cfg['key_col']
        key_name = axis_cfg['key_name']

        for suffix in type_suffixes:
            table_name = f"monthly_trend_{axis}_{suffix}"
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    year_month               TEXT    NOT NULL,
                    {key_col},
                    sample_count             INTEGER,
                    days_in_month            INTEGER,
                    is_complete              INTEGER DEFAULT 0,
                    avg_diff_per_machine     REAL,
                    median_diff_per_machine  REAL,
                    max_diff_coins           INTEGER,
                    min_diff_coins           INTEGER,
                    total_diff_coins         INTEGER,
                    avg_games_per_machine    REAL,
                    win_rate                 REAL,
                    high_profit_rate         REAL,
                    machine_count            REAL,
                    avg_rank_diff            REAL,
                    avg_rank_games           REAL,
                    avg_rank_efficiency      REAL,
                    times_ranked_1st         INTEGER,
                    times_ranked_top3        INTEGER,
                    PRIMARY KEY (year_month, {key_name})
                )
            ''')
            cursor.execute(
                f'CREATE INDEX IF NOT EXISTS idx_{table_name}_ym ON {table_name}(year_month)'
            )
            print(f"[OK] {table_name}")

    print("月次トレンドテーブル作成完了: 18テーブル")

def _load_reversed_sections(hall_name: str, db_dir: str) -> frozenset:
    """hall_config.json から逆順セクションセットを取得する。

    逆順セクション＝メイン通路側が高番号端のセクション。
    rank_from_max=1 が通路直近の角番台。
    設定がない場合は空セットを返す（後方互換）。
    """
    import json
    from pathlib import Path
    # hall_config.json は db_dir の親か、プロジェクトルートの config/ に置かれている
    candidates = [Path(__file__).resolve().parents[1] / "config" / "hall_config.json"]

    # 後方互換として既存の db_dir ベース探索も残す。
    base_dir = db_dir if db_dir != "." else os.getcwd()
    candidates.extend([
        Path(base_dir) / "config" / "hall_config.json",
        Path(os.path.dirname(base_dir)) / "config" / "hall_config.json",
        Path(base_dir) / ".." / "config" / "hall_config.json",
    ])

    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            for hall in config.get("halls", []):
                if hall.get("hall_name") == hall_name:
                    sections = (
                        hall
                        .get("layout_settings", {})
                        .get("reversed_sections", [])
                    )
                    return frozenset(sections)
        except Exception:
            continue

    print(f"[WARN] hall_config.json が見つかりません: hall_name={hall_name}")
    return frozenset()


def _import_machine_layout(db_path, hall_name, db_dir):
    """フロア座標CSVをmachine_layoutに自動インポート（Heatmap/ディレクトリを検索）。

    hall_config.json の layout_settings.reversed_sections を参照して
    is_reversed_section / rank_from_aisle を自動計算する。
    """
    try:
        base_dir = db_dir if db_dir != "." else os.getcwd()
        heatmap_dir = os.path.join(base_dir, "Heatmap")

        if not os.path.exists(heatmap_dir):
            print(f"[WARN] Heatmapディレクトリ未検出: {heatmap_dir}")
            return

        matched_rows = []
        for fname in os.listdir(heatmap_dir):
            if "floor_coordinates" not in fname or not fname.endswith(".csv"):
                continue
            csv_path = os.path.join(heatmap_dir, fname)
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    for row in csv.DictReader(f):
                        if row.get('hall_name') == hall_name:
                            matched_rows.append(row)
            except Exception:
                continue

        if not matched_rows:
            print(f"[WARN] フロア座標データ未検出: hall_name={hall_name}")
            return

        # hall_config.json から逆順セクションを取得
        reversed_sections = _load_reversed_sections(hall_name, db_dir)
        if reversed_sections:
            print(f"[INFO] 逆順セクション: {sorted(reversed_sections)}")

        def _to_int(val):
            try:
                return int(val) if val not in (None, '') else None
            except ValueError:
                return None

        records = []
        for row in matched_rows:
            try:
                section = row.get('section')
                rank_from_min = _to_int(row.get('rank_from_min'))
                rank_from_max = _to_int(row.get('rank_from_max'))
                is_reversed = 1 if section in reversed_sections else 0
                if rank_from_min is not None and rank_from_max is not None:
                    rank_from_aisle = rank_from_max if is_reversed else rank_from_min
                else:
                    rank_from_aisle = None

                if (
                    rank_from_min is not None and rank_from_min > 0
                    and rank_from_max is not None and rank_from_max > 0
                ):
                    physical_corner = min(rank_from_min, rank_from_max)
                    physical_corner_valid = 1
                else:
                    physical_corner = -1
                    physical_corner_valid = 0

                records.append((
                    int(row['machine_number']),
                    row['hall_name'],
                    _to_int(row.get('X')),
                    _to_int(row.get('Y')),
                    _to_int(row.get('display_y')),
                    section,
                    _to_int(row.get('section_min')),
                    _to_int(row.get('section_max')),
                    rank_from_min,
                    rank_from_max,
                    is_reversed,
                    rank_from_aisle,
                    physical_corner,
                    physical_corner_valid,
                ))
            except (ValueError, KeyError):
                continue

        if records:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT OR REPLACE INTO machine_layout
                (machine_number, hall_name, x, y, display_y,
                 section, section_min, section_max,
                 rank_from_min, rank_from_max,
                 is_reversed_section, rank_from_aisle,
                 physical_corner, physical_corner_valid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', records)
            conn.commit()
            conn.close()
            print(f"[OK] フロア座標データ: {len(records)}台 ({hall_name})")

    except Exception as e:
        print(f"[WARN] フロア座標CSV読み込みエラー: {str(e)}")

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
    print("[OK] machine_master テーブル作成")
    
    # BT機種15個の初期データを登録
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
    
    print(f"[OK] BT機種15個を登録")
    
    conn.commit()
    conn.close()
    
    return db_path

if __name__ == "__main__":
    print("main_processor.pyから実行してください。")
