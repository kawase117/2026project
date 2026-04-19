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
from db_setup import create_database


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
        
        # DB チェック＆初期化
        self._ensure_database_initialized()

        # 初期化
        self.json_processor = JSONProcessor(hall_name)
        self.data_inserter = DataInserter(self.db_path)
        self.summary_calc = SummaryCalculator(self.db_path)
        self.rank_calc = RankCalculator(self.db_path)
        self.date_info_calc = DateInfoCalculator(hall_name, self.db_path)
    
    def _ensure_database_initialized(self):
        """DB が存在しない、またはテーブルがない場合は db_setup で初期化"""
        if not self.hall_name:
            return  # hall_name が確定していない場合はスキップ

        needs_init = False

        if not os.path.exists(self.db_path):
            print(f"   DB が存在しないため作成します: {self.db_path}")
            needs_init = True
        else:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='machine_detailed_results'")
                table_exists = cursor.fetchone() is not None
                conn.close()
                if not table_exists:
                    print(f"   テーブルが存在しないため DB を再初期化します")
                    os.remove(self.db_path)
                    needs_init = True
            except Exception as e:
                print(f"   DB チェック失敗: {e}、DB を再初期化します")
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                needs_init = True

        if needs_init:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            created_path = create_database(self.hall_name, project_root)
            print(f"   [OK] DB 作成完了: {created_path}")

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
            print(f"   [WARN] DB日付取得エラー: {e}")
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
            print(f"   [WARN] JSON日付取得エラー: {e}")
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
            print(f"\n   [DATE] {date_str} を処理中...")
            
            # JSON ファイルを取得
            json_files = self.json_processor.get_json_files()
            json_filepath = None
            
            for jf in json_files:
                if date_str in os.path.basename(jf):
                    json_filepath = jf
                    break
            
            if not json_filepath:
                print(f"      [ERROR] JSON ファイルが見つかりません")
                return False
            
            # JSON を読み込み
            with open(json_filepath, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # 日付を検証
            json_date = json_data.get('date')
            if json_date != date_str:
                print(f"      [WARN] JSON内の日付不一致: {date_str} != {json_date}")
                # 日付で強制上書き
                json_data['date'] = date_str
            
            # 個別台データを処理
            machine_records = json_data.get('all_data', [])
            machine_data_list = self.json_processor.process_all_machine_data_for_day(
                date_str, machine_records, None
            )
            
            if not machine_data_list:
                print(f"      [ERROR] 機械データが0件です")
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
                print(f"      [WARN] 集計処理エラー: {e}")
            
            # 4. ランク・履歴計算 + 日付フラグ追加（原子的に処理）
            try:
                self.rank_calc.calculate_ranks_for_date(date_str)
                self.rank_calc.calculate_history_for_date(date_str)
                self.date_info_calc.update_date_info(date_str)
                print(f"      [OK] ランク計算・日付フラグ追加完了")
            except Exception as e:
                print(f"      [WARN] ランク計算・日付フラグ追加スキップ - {str(e)}")
                # 処理継続（次の日付へ）
            
            print(f"      [OK] {date_str} を DB に追加しました")
            return True
            
        except Exception as e:
            print(f"      [ERROR] エラー: {e}")
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
        # Step 1: JSON から利用可能な日付を確認（先に実行して hall_name を確定させる）
        print("[SEARCH] JSON ファイルから利用可能な日付を確認中...")
        available_dates = self.get_json_available_dates()

        # JSONProcessor が hall_name を更新した場合、db_path と各モジュールを再設定
        if self.json_processor.hall_name != self.hall_name:
            old_name = self.hall_name
            self.hall_name = self.json_processor.hall_name
            safe_hall_name = self.hall_name.replace(" ", "_").replace("（", "(").replace("）", ")")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir) if script_dir.endswith(('database', 'scraper')) else script_dir
            db_dir = os.path.join(project_root, "db")
            os.makedirs(db_dir, exist_ok=True)
            self.db_path = os.path.join(db_dir, f"{safe_hall_name}.db")
            self.data_inserter = DataInserter(self.db_path)
            self.summary_calc = SummaryCalculator(self.db_path)
            self.rank_calc = RankCalculator(self.db_path)
            self.date_info_calc = DateInfoCalculator(self.hall_name, self.db_path)
            print(f"   ホール名を '{old_name}' → '{self.hall_name}' に更新しました")

        # DB チェック＆初期化（hall_name 確定後に実行）
        self._ensure_database_initialized()

        print("=" * 70)
        print(f"[REPORT] 増分更新スクリプト - {self.hall_name}")
        print("=" * 70)
        print()

        if available_dates:
            min_date = min(available_dates)
            max_date = max(available_dates)
            print(f"   [OK] {len(available_dates)}件の JSON ファイルを検出")
            print(f"   [DATE] 期間: {min_date} ～ {max_date}")
        else:
            print(f"   [ERROR] JSON ファイルが見つかりません")
            return {
                'status': 'error',
                'message': 'JSON ファイルが見つかりません',
                'new_dates': [],
                'processed': 0,
                'failed': 0
            }

        print()

        # Step 2: DB 登録済み日付を確認（hall_name/db_path 確定後に実行）
        print("[SEARCH] DB 登録済み日付を確認中...")
        registered_dates = self.get_db_registered_dates()

        if registered_dates:
            min_date = min(registered_dates)
            max_date = max(registered_dates)
            print(f"   [OK] {len(registered_dates)}件の日付が登録済み")
            print(f"   [DATE] 期間: {min_date} ～ {max_date}")
        else:
            print(f"   [WARN] DB にデータが登録されていません")
        
        print()
        
        # 新規日付を検出
        new_dates = self.get_new_dates(registered_dates, available_dates)
        
        print("[NOTE] 新規日付の検出:")
        if new_dates:
            print(f"   [NEW] {len(new_dates)}件の新規日付を検出しました")
            print(f"   [DATE] 対象: {new_dates[0]} ～ {new_dates[-1]}")
        else:
            print(f"   [INFO] 新規データはありません（最新の状態です）")
            return {
                'status': 'success',
                'message': '新規データはありません',
                'new_dates': [],
                'processed': 0,
                'failed': 0
            }
        
        print()
        print("=" * 70)
        print(f"[START] 増分更新を開始します")
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
            print("[TREND] 最終履歴処理を実行中...")
            print("=" * 70)
            
            for date_str in processed_dates[-7:]:
                try:
                    self.rank_calc.calculate_history_for_date(date_str)
                    print(f"   [OK] {date_str} の履歴を再計算")
                except Exception as e:
                    print(f"   [WARN] {date_str} 履歴処理エラー: {e}")
        
        # 結果サマリー
        print()
        print("=" * 70)
        print(f"[REPORT] 増分更新完了")
        print("=" * 70)
        print(f"[OK] 正常処理: {processed_count}件")
        print(f"[ERROR] 失敗: {failed_count}件")
        
        if processed_count > 0:
            print(f"\n[DATE] 追加された日付:")
            print(f"   {processed_dates[0]} ～ {processed_dates[-1]}")
            print(f"   合計 {len(processed_dates)}日分")
        
        print()
        print(f"[DB] DB パス: {self.db_path}")
        print(f"[REPORT] DB サイズ: {os.path.getsize(self.db_path) / 1024 / 1024:.2f} MB")
        print("=" * 70)
        
        return {
            'status': 'success' if failed_count == 0 else 'partial',
            'message': f'{processed_count}件を追加、{failed_count}件失敗',
            'new_dates': new_dates,
            'processed': processed_count,
            'failed': failed_count,
            'processed_dates': processed_dates
        }

    @classmethod
    def run_all_halls(cls):
        """複数ホール一括処理：hall_config.json から全ホールを読み込み、JSON 有無で自動認識"""
        config_path = Path(__file__).parent.parent / "config" / "hall_config.json"

        try:
            with open(config_path, encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"[ERROR] hall_config.json の読込失敗: {e}")
            return {}

        print("=" * 70)
        print("複数ホール増分更新を開始します")
        print("=" * 70)
        print()

        results = {}
        success_count = 0
        skipped_count = 0
        error_count = 0

        for i, hall_config in enumerate(config["halls"], 1):
            hall_name = hall_config["hall_name"]
            print(f"[{i}/{len(config['halls'])}] {hall_name}")

            try:
                updater = cls(hall_name)

                # JSON ファイル有無を確認
                json_dates = updater.get_json_available_dates()
                if not json_dates:
                    print(f"     → JSON ファイルなし（スキップ）")
                    results[hall_name] = {"status": "skipped", "message": "JSON ファイルなし"}
                    skipped_count += 1
                    continue

                # 新規日付がある場合のみ処理
                result = updater.run()
                results[hall_name] = result

                if result["status"] == "success":
                    success_count += 1
                else:
                    error_count += 1

            except Exception as e:
                results[hall_name] = {"status": "error", "message": str(e)}
                print(f"     → エラー: {e}")
                error_count += 1

        # 最終サマリー
        print()
        print("=" * 70)
        print("複数ホール更新完了")
        print("=" * 70)
        print(f"成功: {success_count}, スキップ: {skipped_count}, エラー: {error_count}")

        for hall_name, result in results.items():
            status_emoji = "[OK]" if result["status"] == "success" else "[SKIP]" if result["status"] == "skipped" else "[ERROR]"
            print(f"{status_emoji} {hall_name}: {result['message']}")

        print("=" * 70)
        return results


def main():
    """メイン処理"""

    # CLI オプション処理
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        # 複数ホール一括処理
        results = IncrementalDBUpdater.run_all_halls()
        # すべて成功または成功＋スキップなら exit 0
        error_count = sum(1 for r in results.values() if r["status"] == "error")
        return 0 if error_count == 0 else 1

    # 単一ホール処理（既存機能）
    if len(sys.argv) > 1:
        hall_name = sys.argv[1]
    else:
        hall_name = ""

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
