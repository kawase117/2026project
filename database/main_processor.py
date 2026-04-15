#!/usr/bin/env python3
"""
パチスロデータ分析プロジェクト - DB構築メインスクリプト（全ホール自動処理版）
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
import os
import time
import glob
from datetime import datetime
from pathlib import Path

from db_setup import create_database
from json_processor import JSONProcessor
from data_inserter import DataInserter
from summary_calculator import SummaryCalculator
from rank_calculator import RankCalculator
from date_info_calculator import DateInfoCalculator

class DataImporter:
    """統合データインポーター"""
    
    def __init__(self, hall_name: str, db_path: str, json_processor: JSONProcessor):
        self.hall_name = hall_name
        self.json_processor = json_processor
        self.data_inserter = DataInserter(db_path)
        self.summary_calc = SummaryCalculator(db_path)
        self.rank_calc = RankCalculator(db_path)
        self.date_info_calc = DateInfoCalculator(hall_name, db_path)
    
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
        
        # 4. ランク・履歴計算 + 日付フラグ追加（原子的に処理）
        try:
            self.rank_calc.calculate_ranks_for_date(date)
            self.rank_calc.calculate_history_for_date(date)
            self.date_info_calc.update_date_info(date)
            print(f"✅ {date}: ランク計算・日付フラグ追加完了")
        except Exception as e:
            print(f"⚠️ {date}: ランク計算・日付フラグ追加スキップ - {str(e)}")
            # 処理継続（次の日付へ）
        
        return date
    
    def import_all_json_files(self):
        """全JSONファイルをバッチ処理"""
        json_files = self.json_processor.get_json_files()
        processed_dates = []
        
        print(f"\n🚀 バッチ処理開始: {len(json_files)} ファイル")
        
        # 日付情報カラムをセットアップ
        try:
            self.date_info_calc.add_date_info_columns()
            print("✓ 日付情報カラムをセットアップ")
        except Exception as e:
            print(f"⚠️ 日付情報セットアップ: {str(e)}")
        
        for i, json_file in enumerate(json_files, 1):
            try:
                date = self.import_single_json(json_file)
                processed_dates.append(date)
                print(f"進捗: {i}/{len(json_files)} ({date})")
            except Exception as e:
                print(f"❌ エラー: {str(e)} ({os.path.basename(json_file)})")
                # 処理継続（次のファイルへ）
        
        # 最終履歴再計算
        if processed_dates:
            print("\n📈 最終履歴処理...")
            try:
                for date in processed_dates[-10:]:
                    self.rank_calc.calculate_history_for_date(date)
                print("✓ 最終処理完了")
            except Exception as e:
                print(f"⚠️ 最終処理エラー: {str(e)}")
        
        print(f"\n✅ 完了: {len(processed_dates)} 日分")
        return processed_dates

def get_hall_folders(data_root: str) -> list:
    """
    data/ フォルダ内の全ホール別フォルダを取得
    
    Returns
    -------
    list
        ホール名リスト
    """
    if not os.path.exists(data_root):
        print(f"❌ data フォルダが見つかりません: {data_root}")
        return []
    
    hall_folders = []
    for folder in os.listdir(data_root):
        folder_path = os.path.join(data_root, folder)
        if os.path.isdir(folder_path):
            # test_full, test_minimal など テストフォルダは除外
            if not folder.startswith('test_'):
                hall_folders.append(folder)
    
    return sorted(hall_folders)

def process_single_hall(hall_name: str, project_root: str) -> bool:
    """
    単一ホール処理
    
    Parameters
    ----------
    hall_name : str
        ホール名
    project_root : str
        プロジェクトルート
    
    Returns
    -------
    bool
        処理成功フラグ
    """
    print(f"\n{'=' * 60}")
    print(f"📍 ホール処理: {hall_name}")
    print(f"{'=' * 60}")
    
    try:
        # Phase 1: DB作成
        print(f"\n📋 Phase 1: データベース作成")
        print("-" * 40)
        start_time = time.time()
        db_path = create_database(hall_name, project_root)
        db_time = time.time() - start_time
        print(f"✅ DB作成完了 ({db_time:.2f}秒)")
        
        # Phase 2: JSON処理準備
        print(f"\n📁 Phase 2: JSON読み込み")
        print("-" * 40)
        processor = JSONProcessor(hall_name, project_root)
        json_files = processor.get_json_files()
        
        if not json_files:
            print(f"⚠️  JSONファイル未検出: {hall_name}")
            return False
        
        print(f"✅ JSONファイル: {len(json_files)}個")
        
        # Phase 3: データ投入
        print(f"\n🚀 Phase 3: データ投入")
        print("-" * 40)
        import_start = time.time()
        importer = DataImporter(hall_name, db_path, processor)
        processed_dates = importer.import_all_json_files()
        import_time = time.time() - import_start
        
        # Phase 4: 結果サマリー
        print(f"\n📊 Phase 4: 結果サマリー")
        print("-" * 40)
        _print_summary(db_path, processed_dates, db_time, import_time)
        
        return True
        
    except Exception as e:
        print(f"\n❌ エラー発生: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """メイン処理 - 全ホール自動処理"""
    print("=" * 60)
    print("パチスロデータ分析 - DB構築（全ホール自動処理版）")
    print("=" * 60)
    
    # プロジェクトルート自動検出
    current_file = Path(__file__).resolve()
    project_root = str(current_file.parent.parent)  # database/ → プロジェクトルート
    
    data_root = os.path.join(project_root, 'data')
    print(f"プロジェクトルート: {project_root}")
    print(f"データフォルダ: {data_root}")
    
    # ホール別フォルダを取得
    hall_folders = get_hall_folders(data_root)
    
    if not hall_folders:
        print(f"❌ ホール別フォルダが見つかりません")
        return False
    
    print(f"\n検出ホール数: {len(hall_folders)}")
    for i, hall in enumerate(hall_folders, 1):
        print(f"  {i}. {hall}")
    
    # 全ホール処理
    print(f"\n{'=' * 60}")
    print(f"🚀 処理開始")
    print(f"{'=' * 60}")
    
    successful_halls = []
    failed_halls = []
    
    for hall_name in hall_folders:
        success = process_single_hall(hall_name, project_root)
        if success:
            successful_halls.append(hall_name)
        else:
            failed_halls.append(hall_name)
    
    # 最終サマリー
    print(f"\n{'=' * 60}")
    print(f"📊 全体完了サマリー")
    print(f"{'=' * 60}")
    print(f"✅ 成功: {len(successful_halls)} ホール")
    for hall in successful_halls:
        print(f"   • {hall}")
    
    if failed_halls:
        print(f"\n❌ 失敗: {len(failed_halls)} ホール")
        for hall in failed_halls:
            print(f"   • {hall}")
    
    return len(failed_halls) == 0

def _print_summary(db_path, processed_dates, db_time, import_time):
    """結果サマリー表示"""
    import sqlite3
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 基本統計
    cursor.execute('SELECT COUNT(*) FROM machine_detailed_results')
    total_machines = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM daily_machine_type_summary')
    machine_types = cursor.fetchone()[0]
    
    cursor.execute('SELECT MIN(date), MAX(date) FROM daily_hall_summary')
    date_range = cursor.fetchone()
    
    cursor.execute('SELECT SUM(total_games), SUM(total_diff_coins) FROM daily_hall_summary')
    totals = cursor.fetchone()
    
    conn.close()
    
    total_time = db_time + import_time
    
    print(f"✅ ホール完了")
    print(f"\n📈 処理結果:")
    print(f"   処理期間: {date_range[0]} ～ {date_range[1]}")
    print(f"   処理日数: {len(processed_dates)} 日")
    print(f"   個別台データ: {total_machines:,} レコード")
    print(f"   機種別集計: {machine_types:,} レコード")
    print(f"   総ゲーム数: {totals[0]:,} G")
    print(f"   総差枚: {totals[1]:+,} 枚")
    print(f"\n⏱️  処理時間:")
    print(f"   DB作成: {db_time:.2f}秒")
    print(f"   データ投入: {import_time:.2f}秒")
    print(f"   合計: {total_time:.2f}秒")
    print(f"\n💾 出力:")
    print(f"   {os.path.abspath(db_path)}")
    print(f"   サイズ: {os.path.getsize(db_path) / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    success = main()
    sys.exit(0 if success else 1)