#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
増分更新スクリプト - 新規日付のJSONデータのみをDBに追加
新規JSONファイルを検出して、DB未登録の日付データのみ処理
"""

import os
import sys
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

# モジュールのインポート
from json_processor import JSONProcessor
from data_inserter import DataInserter
from summary_calculator import SummaryCalculator
from rank_calculator import RankCalculator
from date_info_calculator import DateInfoCalculator


class IncrementalDBUpdater:
    """増分更新クラス"""
    
    def __init__(self, hall_name: str, db_path: str = None):
        """
        初期化
        
        Args:
            hall_name: ホール名
            db_path: DBファイルパス（省略時はデフォルトから生成）
        """
        self.hall_name = hall_name
        
        # DBパスの決定
        if db_path is None:
            # 相対パス対応：プロジェクトルートの db フォルダから取得
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir) if script_dir.endswith(('database', 'scraper')) else script_dir
            db_dir = os.path.join(project_root, "db")
            os.makedirs(db_dir, exist_ok=True)
            safe_hall_name = hall_name.replace(" ", "_").replace("（", "(").replace("）", ")")
            self.db_path = os.path.join(db_dir, f"{safe_hall_name}.db")
        else:
            self.db_path = db_path
        
        # 初期化
        self.json_processor = JSONProcessor(hall_name)
        self.data_inserter = DataInserter(self.db_path)
        self.summary_calc = SummaryCalculator(self.db_path)
        self.rank_calc = RankCalculator(self.db_path)
        self.date_info_calc = DateInfoCalculator(hall_name, self.db_path)
    
    def get_db_registered_dates(self) -> set:
        """
        DB に登録済みの日付を取得
        
        Returns:
            登録済み日付の set（例：{'20250101', '20250102', ...}）
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # machine_detailed_results テーブルから日付を抽出
            cursor.execute('SELECT DISTINCT date FROM machine_detailed_results ORDER BY date')
            registered_dates = set(row[0] for row in cursor.fetchall())
            
            conn.close()
            return registered_dates
            
        except Exception as e:
            print(f"   ⚠️ DB日付取得エラー: {e}")
            return set()
    
    def get_json_available_dates(self) -> set:
        """
        JSON ファイルで利用可能な日付を取得
        
        Returns:
            利用可能日付の set（ファイル名から抽出）
        """
        try:
            json_files = self.json_processor.get_json_files()
            available_dates = set()
            
            for json_file in json_files:
                # ファイル名から日付を抽出（YYYYMMDD_*.json パターン）
                filename = os.path.basename(json_file)
                date_part = filename.split('_')[0]
                
                # 日付形式の検証（8文字の数字）
                if len(date_part) == 8 and date_part.isdigit():
                    available_dates.add(date_part)
            
            return available_dates
            
        except Exception as e:
            print(f"   ⚠️ JSON日付取得エラー: {e}")
            return set()
    
    def get_new_dates(self, registered_dates: set, available_dates: set) -> list:
        """
        新規日付（DBに登録されていない日付）を取得
        
        Returns:
            新規日付のリスト（昇順）
        """
        new_dates = available_dates - registered_dates
        return sorted(list(new_dates))
    
    def process_new_date(self, date_str: str) -> bool:
        """
        単一の日付データを処理して DB に追加
        
        Args:
            date_str: 日付（YYYYMMDD）
        
        Returns:
            成功時 True
        """
        try:
            print(f"\n   📅 {date_str} を処理中...")
            
            # JSON ファイルを取得
            json_files = self.json_processor.get_json_files()
            json_filepath = None
            
            for jf in json_files:
                if date_str in os.path.basename(jf):
                    json_filepath = jf
                    break
            
            if not json_filepath:
                print(f"      ❌ JSON ファイルが見つかりません")
                return False
            
            # JSON を読み込み
            with open(json_filepath, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # 日付を検証
            json_date = json_data.get('date')
            if json_date != date_str:
                print(f"      ⚠️ JSON内の日付不一致: {date_str} != {json_date}")
                # 日付で強制上書き
                json_data['date'] = date_str
            
            # 個別台データを処理
            machine_records = json_data.get('all_data', [])
            machine_data_list = self.json_processor.process_all_machine_data_for_day(
                date_str, machine_records, None
            )
            
            if not machine_data_list:
                print(f"      ❌ 機械データが0件です")
                return False
            
            # 1. 個別台データ投入
            self.data_inserter.insert_machine_detailed_results(machine_data_list)
            
            # 2. 日別全体集計
            avg_games = self.data_inserter.calculate_and_insert_daily_summary(date_str)
            if avg_games:
                self.data_inserter.update_games_deviation(date_str, avg_games)
            
            # 3. 各種集計
            try:
                self.summary_calc.update_machine_type_summary(date_str)
                self.summary_calc.update_last_digit_summary_by_type(date_str)
                self.summary_calc.update_position_summary_by_type(date_str)
                self.summary_calc.update_island_summary(date_str)
            except Exception as e:
                print(f"      ⚠️ 集計処理エラー: {e}")
            
            # 4. ランク・履歴計算
            try:
                self.rank_calc.calculate_ranks_for_date(date_str)
                self.rank_calc.calculate_history_for_date(date_str)
            except Exception as e:
                print(f"      ⚠️ ランク計算エラー: {e}")
            
            # 5. 日付フラグ追加 ← **新規**
            try:
                self.date_info_calc.update_date_info(date_str)
            except Exception as e:
                print(f"      ⚠️ 日付フラグエラー: {e}")
            
            print(f"      ✅ {date_str} を DB に追加しました")
            return True
            
        except Exception as e:
            print(f"      ❌ エラー: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run(self, verbose: bool = True) -> dict:
        """
        増分更新を実行
        
        Args:
            verbose: 詳細出力を表示するか
        
        Returns:
            結果情報の辞書
        """
        print("=" * 70)
        print(f"📊 増分更新スクリプト - {self.hall_name}")
        print("=" * 70)
        print()
        
        # 登録済み日付を取得
        print("🔍 DB 登録済み日付を確認中...")
        registered_dates = self.get_db_registered_dates()
        
        if registered_dates:
            min_date = min(registered_dates)
            max_date = max(registered_dates)
            print(f"   ✅ {len(registered_dates)}件の日付が登録済み")
            print(f"   📅 期間: {min_date} ～ {max_date}")
        else:
            print(f"   ⚠️ DB にデータが登録されていません")
        
        print()
        
        # 利用可能な日付を取得
        print("🔍 JSON ファイルから利用可能な日付を確認中...")
        available_dates = self.get_json_available_dates()
        
        if available_dates:
            min_date = min(available_dates)
            max_date = max(available_dates)
            print(f"   ✅ {len(available_dates)}件の JSON ファイルを検出")
            print(f"   📅 期間: {min_date} ～ {max_date}")
        else:
            print(f"   ❌ JSON ファイルが見つかりません")
            return {
                'status': 'error',
                'message': 'JSON ファイルが見つかりません',
                'new_dates': [],
                'processed': 0,
                'failed': 0
            }
        
        print()
        
        # 新規日付を検出
        new_dates = self.get_new_dates(registered_dates, available_dates)
        
        print("📝 新規日付の検出:")
        if new_dates:
            print(f"   🆕 {len(new_dates)}件の新規日付を検出しました")
            print(f"   📅 対象: {new_dates[0]} ～ {new_dates[-1]}")
        else:
            print(f"   ℹ️ 新規データはありません（最新の状態です）")
            return {
                'status': 'success',
                'message': '新規データはありません',
                'new_dates': [],
                'processed': 0,
                'failed': 0
            }
        
        print()
        print("=" * 70)
        print(f"🚀 増分更新を開始します")
        print("=" * 70)
        print()
        
        # 新規日付を処理
        processed_count = 0
        failed_count = 0
        processed_dates = []
        
        for i, date_str in enumerate(new_dates, 1):
            print(f"[{i}/{len(new_dates)}]", end=" ")
            
            if self.process_new_date(date_str):
                processed_count += 1
                processed_dates.append(date_str)
            else:
                failed_count += 1
        
        # 最終履歴再計算（直近7日分）
        if processed_dates:
            print()
            print("=" * 70)
            print("📈 最終履歴処理を実行中...")
            print("=" * 70)
            
            for date_str in processed_dates[-7:]:
                try:
                    self.rank_calc.calculate_history_for_date(date_str)
                    print(f"   ✅ {date_str} の履歴を再計算")
                except Exception as e:
                    print(f"   ⚠️ {date_str} 履歴処理エラー: {e}")
        
        # 結果サマリー
        print()
        print("=" * 70)
        print(f"📊 増分更新完了")
        print("=" * 70)
        print(f"✅ 正常処理: {processed_count}件")
        print(f"❌ 失敗: {failed_count}件")
        
        if processed_count > 0:
            print(f"\n📅 追加された日付:")
            print(f"   {processed_dates[0]} ～ {processed_dates[-1]}")
            print(f"   合計 {len(processed_dates)}日分")
        
        print()
        print(f"💾 DB パス: {self.db_path}")
        print(f"📊 DB サイズ: {os.path.getsize(self.db_path) / 1024 / 1024:.2f} MB")
        print("=" * 70)
        
        return {
            'status': 'success' if failed_count == 0 else 'partial',
            'message': f'{processed_count}件を追加、{failed_count}件失敗',
            'new_dates': new_dates,
            'processed': processed_count,
            'failed': failed_count,
            'processed_dates': processed_dates
        }


def main():
    """メイン処理"""
    
    # ホール名を指定（CLI引数で変更可能）
    if len(sys.argv) > 1:
        hall_name = sys.argv[1]
    else:
        hall_name = "マルハンメガシティ柏"
    
    # DBパスを指定（CLI引数で変更可能）
    db_path = None
    if len(sys.argv) > 2:
        db_path = sys.argv[2]
    
    # 増分更新を実行
    updater = IncrementalDBUpdater(hall_name, db_path)
    result = updater.run()
    
    # 終了コード
    return 0 if result['status'] == 'success' else 1


if __name__ == "__main__":
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    exit_code = main()
    sys.exit(exit_code)
