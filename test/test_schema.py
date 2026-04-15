#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
簡易テスト用メインスクリプト
テストデータで DB を構築し、カラムが正しく作られているか確認
"""

import sys
import os
import time
import sqlite3
from datetime import datetime
from pathlib import Path

# ============================================================================
# パス設定（Windows環境対応）
# ============================================================================
# test/test_schema.py → test/ → 2026project/ → database/
# 全てのモジュール（db_setup.py等）は database/ フォルダ内
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent  # test/ → 2026project/
database_dir = project_root / 'database'   # 2026project/database/

# database/ フォルダをパスに追加
if str(database_dir) not in sys.path:
    sys.path.insert(0, str(database_dir))

# ============================================================================
# ここからインポート（全モジュール）
# ============================================================================

from db_setup import create_database, create_machine_master_db
from json_processor import JSONProcessor
from data_inserter import DataInserter
from summary_calculator import SummaryCalculator
from rank_calculator import RankCalculator

# 以下は既存コードのまま

class TestDataImporter:
    """テスト用データインポーター"""
    
    def __init__(self, db_path: str, json_processor: JSONProcessor):
        self.json_processor = json_processor
        self.data_inserter = DataInserter(db_path)
        self.summary_calc = SummaryCalculator(db_path)
        self.rank_calc = RankCalculator(db_path)
    
    def import_single_json(self, json_filepath: str) -> str:
        """単一JSONファイルを処理"""
        print(f"\n処理中: {os.path.basename(json_filepath)}")
        
        # JSONロード
        json_data = self.json_processor.load_json_file(json_filepath)
        date = json_data.get("date")
        if not date:
            raise ValueError(f"日付情報なし: {json_filepath}")
        
        # 個別台データ処理
        machine_records = json_data.get("all_data", [])
        machine_data_list = self.json_processor.process_all_machine_data_for_day(
            date, machine_records, None
        )
        
        # 1. 個別台データ投入
        self.data_inserter.insert_machine_detailed_results(machine_data_list)
        
        # 2. 日別全体集計
        avg_games = self.data_inserter.calculate_and_insert_daily_summary(date)
        if avg_games:
            self.data_inserter.update_games_deviation(date, avg_games)
        
        # 3. 各種集計
        self.summary_calc.update_machine_type_summary(date)
        self.summary_calc.update_last_digit_summary_by_type(date)
        self.summary_calc.update_position_summary_by_type(date)
        self.summary_calc.update_island_summary(date)
        
        # 4. ランク・履歴計算
        try:
            self.rank_calc.calculate_ranks_for_date(date)
            self.rank_calc.calculate_history_for_date(date)
            print(f"✓ ランク・履歴完了 ({date})")
        except Exception as e:
            print(f"⚠️ ランク計算スキップ: {str(e)}")
        
        return date
    
    def import_all_json_files(self):
        """全JSONファイルをバッチ処理"""
        json_files = self.json_processor.get_json_files()
        processed_dates = []
        
        print(f"\n🚀 バッチ処理開始: {len(json_files)} ファイル")
        
        for i, json_file in enumerate(json_files, 1):
            try:
                date = self.import_single_json(json_file)
                processed_dates.append(date)
                print(f"進捗: {i}/{len(json_files)} ({date})")
            except Exception as e:
                print(f"❌ エラー: {str(e)}")
                raise
        
        print(f"\n✅ 完了: {len(processed_dates)} 日分")
        return processed_dates


def verify_table_schema(db_path: str):
    """テーブルスキーマの確認"""
    print("\n" + "=" * 60)
    print("📊 テーブルスキーマ検証")
    print("=" * 60)
    
    # machine_master.db の確認
    master_db_path = os.path.join(os.path.dirname(db_path), "machine_master.db")
    if os.path.exists(master_db_path):
        print("\n✓ machine_master.db")
        master_conn = sqlite3.connect(master_db_path)
        master_cursor = master_conn.cursor()
        
        master_cursor.execute("PRAGMA table_info(machine_master)")
        columns = {row[1]: row[2] for row in master_cursor.fetchall()}
        
        required_master_columns = ['machine_name_normalized', 'bt_flag', 'display_names', 'official_name']
        for col in required_master_columns:
            if col in columns:
                print(f"  ✓ {col:30s} ({columns[col]})")
            else:
                print(f"  ❌ {col:30s} (未検出)")
        
        master_conn.close()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 確認するテーブルと必須カラム
    tables_to_check = {
        'daily_hall_summary': ['date', 'total_machines', 'total_games', 'total_diff_coins', 'win_rate'],
        'daily_machine_type_summary': ['date', 'machine_name', 'win_rate', 'machine_type_rank_diff', 'avg_diff_7d'],
        'last_digit_summary_all': ['date', 'last_digit', 'win_rate', 'last_digit_rank_diff', 'avg_diff_7d'],
        'daily_position_summary_all': ['date', 'front_position', 'win_rate', 'position_rank_diff', 'avg_diff_7d'],
        'daily_island_summary': ['date', 'island_name', 'win_rate', 'island_rank_diff', 'avg_diff_7d'],
    }
    
    all_valid = True
    
    for table_name, required_columns in tables_to_check.items():
        # テーブル存在確認
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
        exists = cursor.fetchone() is not None
        
        if not exists:
            print(f"\n❌ テーブル未検出: {table_name}")
            all_valid = False
            continue
        
        # カラム確認
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        print(f"\n✓ {table_name}")
        missing = []
        for col in required_columns:
            if col in columns:
                print(f"  ✓ {col:30s} ({columns[col]})")
            else:
                print(f"  ❌ {col:30s} (未検出)")
                missing.append(col)
                all_valid = False
        
        if missing:
            print(f"     ⚠️  未検出カラム: {', '.join(missing)}")
    
    conn.close()
    
    print("\n" + "-" * 60)
    if all_valid:
        print("✅ 全カラムが正しく作成されました")
    else:
        print("❌ いくつかのカラムが未検出です")
    print("-" * 60)
    
    return all_valid


def verify_data_integrity(db_path: str):
    """データの整合性確認"""
    print("\n" + "=" * 60)
    print("📈 データ整合性検証")
    print("=" * 60)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # daily_hall_summary の win_rate 確認
    cursor.execute("SELECT date, total_machines, win_rate FROM daily_hall_summary ORDER BY date")
    rows = cursor.fetchall()
    
    print(f"\n✓ daily_hall_summary (win_rate の値)")
    for date, total_machines, win_rate in rows:
        print(f"  {date}: 稼働台数={total_machines:3d}, 勝率={win_rate:3d}%")
        
        # win_rate は 0-100 の範囲内であるか確認
        if not (0 <= win_rate <= 100):
            print(f"     ⚠️  警告: win_rate が範囲外です: {win_rate}")
    
    # daily_machine_type_summary の データサンプル
    cursor.execute("""
        SELECT date, machine_name, win_rate, machine_type_rank_diff, avg_diff_7d
        FROM daily_machine_type_summary
        LIMIT 5
    """)
    rows = cursor.fetchall()
    
    print(f"\n✓ daily_machine_type_summary (サンプル)")
    for date, machine_name, win_rate, rank, avg_diff in rows:
        print(f"  {date} {machine_name:15s}: 勝率={win_rate:3d}%, ランク={rank}, 平均={avg_diff}")
    
    conn.close()
    
    print("\n" + "-" * 60)
    print("✅ データ整合性確認完了")
    print("-" * 60)


def main():
    """メイン処理"""
    print("=" * 60)
    print("パチスロデータ分析 - 簡易テスト実行")
    print("=" * 60)
    
    # テスト用ホール名と設定
    HALL_NAME = "テストホール"
    BASE_DIR = os.getcwd()
    
    print(f"ホール名: {HALL_NAME}")
    print(f"ディレクトリ: {BASE_DIR}")
    
    try:
        # Phase 0: machine_master.db 作成
        print(f"\n📋 Phase 0: machine_master.db 作成")
        print("-" * 40)
        start_time = time.time()
        master_db_path = create_machine_master_db(BASE_DIR)
        
        # BT機種初期データ登録
        import sqlite3
        master_conn = sqlite3.connect(master_db_path)
        master_cursor = master_conn.cursor()
        
        bt_machines = [
            ('L不二子BT', 1, 'L不二子BT, L不二子', 'L不二子BT'),
            ('スマスロニューパルサーBT', 1, 'スマスロニューパルサーBT', 'スマスロニューパルサー'),
            ('LBトリプルクラウン', 1, 'LBトリプルクラウン', 'LBトリプルクラウン'),
        ]
        
        for machine in bt_machines:
            master_cursor.execute('''
                INSERT OR REPLACE INTO machine_master (
                    machine_name_normalized, bt_flag, display_names, official_name
                ) VALUES (?, ?, ?, ?)
            ''', machine)
        
        master_conn.commit()
        master_conn.close()
        master_time = time.time() - start_time
        print(f"✅ machine_master.db 作成完了 ({master_time:.2f}秒)")
        
        # Phase 1: DB作成
        print(f"\n📋 Phase 1: データベース作成")
        print("-" * 40)
        start_time = time.time()
        db_path = create_database(HALL_NAME, BASE_DIR)
        db_time = time.time() - start_time
        print(f"✅ DB作成完了 ({db_time:.2f}秒)")
        
        # Phase 2: JSON処理準備（テストデータ用）
        print(f"\n📁 Phase 2: テストデータ読み込み")
        print("-" * 40)
        processor = JSONProcessor(HALL_NAME)
        
        # テストデータディレクトリを指定
        test_data_dir = os.path.join(BASE_DIR, "data", "test_full")
        if not os.path.exists(test_data_dir):
            print(f"⚠️  test_full が見つかりません。test_minimal を使用します")
            test_data_dir = os.path.join(BASE_DIR, "data", "test_minimal")
        
        # JSONファイルを手動で収集（通常の json_processor は別パスを参照）
        json_files = sorted([
            os.path.join(test_data_dir, f) 
            for f in os.listdir(test_data_dir) 
            if f.endswith('.json')
        ])
        
        print(f"✅ テストJSONファイル: {len(json_files)}個")
        
        # Phase 3: データ投入
        print(f"\n🚀 Phase 3: テストデータ投入")
        print("-" * 40)
        import_start = time.time()
        importer = TestDataImporter(db_path, processor)
        
        processed_dates = []
        for json_file in json_files:
            try:
                date = importer.import_single_json(json_file)
                processed_dates.append(date)
            except Exception as e:
                print(f"❌ エラー: {str(e)}")
                raise
        
        import_time = time.time() - import_start
        
        # Phase 4: スキーマ検証
        print(f"\n🔍 Phase 4: スキーマ検証")
        print("-" * 40)
        schema_valid = verify_table_schema(db_path)
        
        # Phase 5: データ整合性検証
        print(f"\n✔️  Phase 5: データ整合性検証")
        print("-" * 40)
        verify_data_integrity(db_path)
        
        # Phase 6: 結果サマリー
        print(f"\n📊 Phase 6: 結果サマリー")
        print("=" * 60)
        
        total_time = db_time + import_time
        
        print(f"✅ テスト完了")
        print(f"\n📈 処理結果:")
        print(f"   処理日数: {len(processed_dates)} 日")
        print(f"   処理期間: {processed_dates[0]} ～ {processed_dates[-1]}")
        print(f"   1日あたりの台数: 10台")
        print(f"   合計: {len(processed_dates) * 10}台")
        
        print(f"\n⏱️  処理時間:")
        print(f"   DB作成: {db_time:.2f}秒")
        print(f"   データ投入: {import_time:.2f}秒")
        print(f"   合計: {total_time:.2f}秒")
        
        print(f"\n💾 出力:")
        print(f"   {os.path.abspath(db_path)}")
        print(f"   サイズ: {os.path.getsize(db_path) / 1024:.2f} KB")
        
        print(f"\n🎯 検証結果: {'✅ 成功' if schema_valid else '❌ 失敗'}")
        print("=" * 60)
        
        return schema_valid
        
    except Exception as e:
        print(f"\n❌ エラー発生: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    success = main()
    sys.exit(0 if success else 1)