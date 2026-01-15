#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
パチスロデータ分析 - DB構築（複数ホール対応版）
database フォルダ内で実行
hall_config.json から有効なホール名を自動取得
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
import time

# 同じ database フォルダ内のファイルをインポート
from db_setup import create_database
from json_processor import JSONProcessor
from database_processor import DataPipeline


# ===================================================================
# パス定義
# ===================================================================

PROJECT_ROOT = Path(__file__).parent.parent  # database/ から親へ → プロジェクトルート
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DB_DIR = PROJECT_ROOT / "db"
HALL_CONFIG_PATH = str(CONFIG_DIR / "hall_config.json")


def get_database_path(hall_name: str) -> str:
    """
    ホール別 DB パスを取得・DB フォルダを確保
    
    Parameters
    ----------
    hall_name : str
        ホール名
    
    Returns
    -------
    str
        db/{hall_name}.db のパス
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return str(DB_DIR / f"{hall_name}.db")


# ===================================================================
# ホール設定の読み込み
# ===================================================================

def load_hall_config() -> dict:
    """hall_config.json を読み込み"""
    with open(HALL_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_active_halls() -> list:
    """
    hall_config.json から有効なホール名を取得
    
    Returns
    -------
    list
        有効なホール名のリスト
    """
    config = load_hall_config()
    return [h['hall_name'] for h in config.get('halls', []) 
            if h.get('active', True)]


def ensure_data_directory(hall_name: str) -> Path:
    """
    ホール別データディレクトリを作成・取得
    
    Parameters
    ----------
    hall_name : str
        ホール名
    
    Returns
    -------
    Path
        data/{hall_name}/ のパス
    """
    hall_data_dir = DATA_DIR / hall_name
    hall_data_dir.mkdir(parents=True, exist_ok=True)
    return hall_data_dir


# ===================================================================
# メイン処理
# ===================================================================

def process_hall(hall_name: str) -> bool:
    """
    ホール別の処理を実行
    
    Parameters
    ----------
    hall_name : str
        ホール名
    
    Returns
    -------
    bool
        処理成功フラグ
    """
    print(f"\n{'=' * 60}")
    print(f"📍 ホール処理: {hall_name}")
    print(f"{'=' * 60}")
    
    try:
        # ホール別データディレクトリを確保
        hall_data_dir = ensure_data_directory(hall_name)
        print(f"データディレクトリ: {hall_data_dir}")
        
        # Phase 1: DB作成
        print(f"\n📋 Phase 1: データベース作成")
        print("-" * 40)
        start_time = time.time()
        db_path = create_database(hall_name, str(PROJECT_ROOT))
        db_time = time.time() - start_time
        print(f"✅ DB作成完了: {db_path}")
        print(f"   処理時間: {db_time:.2f}秒")
        
        # Phase 2: JSON処理準備
        print(f"\n📁 Phase 2: JSON読み込み")
        print("-" * 40)
        processor = JSONProcessor(hall_name)
        json_files = processor.get_json_files()
        
        if not json_files:
            print(f"⚠️  JSON ファイルが見つかりません: {hall_name}")
            print(f"   期待場所: {hall_data_dir}/")
            return False
        
        print(f"✅ JSON ファイル検出: {len(json_files)} 個")
        # json_files は str のリストなので Path に変換
        first_date = Path(json_files[0]).stem
        last_date = Path(json_files[-1]).stem
        print(f"   期間: {first_date} ～ {last_date}")
        
        # Phase 3: データ投入・処理
        print(f"\n⚙️  Phase 3: データ投入・処理")
        print("-" * 40)
        start_time = time.time()
        pipeline = DataPipeline(db_path, HALL_CONFIG_PATH, processor)
        processed_dates = pipeline.process_all_dates()
        import_time = time.time() - start_time
        
        if not processed_dates:
            print(f"❌ データ処理に失敗しました")
            return False
        
        print(f"✅ データ投入完了: {len(processed_dates)} 日分")
        print(f"   処理時間: {import_time:.2f}秒")
        
        # Phase 4: 結果サマリー
        print(f"\n📊 Phase 4: 処理結果")
        print("-" * 40)
        _print_summary(db_path, processed_dates, db_time, import_time)
        
        return True
        
    except Exception as e:
        print(f"\n❌ エラー発生: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def _print_summary(db_path, processed_dates, db_time, import_time):
    """結果サマリー表示"""
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
    
    print(f"✅ ホール処理完了")
    print(f"\n📈 処理結果:")
    print(f"   処理期間: {date_range[0]} ～ {date_range[1]}")
    print(f"   処理日数: {len(processed_dates)} 日")
    print(f"   個別台データ: {total_machines:,} レコード")
    print(f"   機種別集計: {machine_types:,} レコード")
    if totals[0]:
        print(f"   総ゲーム数: {totals[0]:,} G")
        print(f"   総差枚: {totals[1]:+,} 枚")
    print(f"\n⏱️  処理時間:")
    print(f"   DB作成: {db_time:.2f}秒")
    print(f"   データ投入: {import_time:.2f}秒")
    print(f"   合計: {total_time:.2f}秒")


# ===================================================================
# メイン実行
# ===================================================================

def main():
    """メイン処理"""
    print("\n" + "=" * 60)
    print("🎯 パチスロデータ分析システム - DB構築")
    print("=" * 60)
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"プロジェクト: {PROJECT_ROOT}")
    
    try:
        # ホール設定の読み込み
        print(f"\n📋 ホール設定読み込み...")
        active_halls = get_active_halls()
        print(f"✅ 有効ホール数: {len(active_halls)}")
        
        if not active_halls:
            print("❌ 有効なホールがありません。hall_config.json を確認してください。")
            return
        
        # 全ホール処理
        print(f"\n{'=' * 60}")
        print(f"📊 全ホール処理開始")
        print(f"{'=' * 60}")
        
        start_time = time.time()
        success_count = 0
        
        for i, hall_name in enumerate(active_halls, 1):
            print(f"\n[{i}/{len(active_halls)}] {hall_name}")
            if process_hall(hall_name):
                success_count += 1
        
        # 全体サマリー
        total_time = time.time() - start_time
        print(f"\n{'=' * 60}")
        print(f"✅ 全処理完了")
        print(f"{'=' * 60}")
        print(f"成功: {success_count}/{len(active_halls)} ホール")
        print(f"処理時間: {total_time:.2f}秒 ({total_time/60:.1f}分)")
        print(f"\n📁 DB 出力先: {DB_DIR}")
        
    except Exception as e:
        print(f"\n❌ 致命的エラー: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()