#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複数ホール一括増分更新スクリプト
すべてのアクティブなホールを順番に処理
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

from incremental_db_updater import IncrementalDBUpdater


def load_hall_config(config_path: str = None) -> list:
    """
    hall_config.json からホール設定を読み込み
    
    Args:
        config_path: config ファイルパス（省略時は自動検出）
    
    Returns:
        アクティブなホール設定のリスト
    """
    try:
        # config パスの決定
        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(script_dir) if script_dir.endswith(('database', 'scraper')) else script_dir
            config_path = os.path.join(project_root, "config", "hall_config.json")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        active_halls = [hall for hall in config['halls'] if hall.get('active', True)]
        
        if not active_halls:
            print("❌ アクティブなホール設定が見つかりません")
            return []
        
        print(f"✅ {len(active_halls)}個のホール設定を読み込みました")
        return active_halls
        
    except FileNotFoundError:
        print(f"❌ hall_config.json が見つかりません: {config_path}")
        return []
    except json.JSONDecodeError:
        print(f"❌ hall_config.json の形式が不正です")
        return []
    except Exception as e:
        print(f"❌ 設定読み込みエラー: {e}")
        return []


def run_batch_update(halls: list, skip_errors: bool = True) -> dict:
    """
    複数ホールを順番に処理
    
    Args:
        halls: ホール設定のリスト
        skip_errors: エラー時にスキップするか
    
    Returns:
        処理結果の辞書
    """
    
    results = {
        'total_halls': len(halls),
        'successful_halls': 0,
        'partial_halls': 0,
        'error_halls': 0,
        'total_processed': 0,
        'total_failed': 0,
        'hall_results': {}
    }
    
    print("=" * 80)
    print(f"🚀 複数ホール一括増分更新を開始します")
    print("=" * 80)
    print(f"📊 対象ホール数: {len(halls)}")
    print()
    
    for i, hall in enumerate(halls, 1):
        hall_name = hall['hall_name']
        
        print(f"\n{'=' * 80}")
        print(f"🏢 [{i}/{len(halls)}] {hall_name}")
        print(f"{'=' * 80}")
        print()
        
        try:
            # 増分更新を実行
            updater = IncrementalDBUpdater(hall_name)
            result = updater.run(verbose=True)
            
            # 結果を記録
            results['hall_results'][hall_name] = result
            results['total_processed'] += result.get('processed', 0)
            results['total_failed'] += result.get('failed', 0)
            
            if result['status'] == 'success':
                results['successful_halls'] += 1
            elif result['status'] == 'partial':
                results['partial_halls'] += 1
            else:
                results['error_halls'] += 1
            
            # エラー時の処理
            if result['status'] == 'error' and not skip_errors:
                print(f"\n❌ エラーが発生したため、処理を中断します")
                print(f"   メッセージ: {result.get('message', 'Unknown error')}")
                break
            
            # ホール間の待機
            if i < len(halls):
                print()
                print("⏳ 次のホールの処理に進みます...")
        
        except Exception as e:
            print(f"❌ エラー: {e}")
            results['error_halls'] += 1
            results['hall_results'][hall_name] = {
                'status': 'error',
                'message': str(e)
            }
            
            if not skip_errors:
                break
    
    return results


def print_batch_summary(results: dict):
    """
    一括処理の結果サマリーを表示
    
    Args:
        results: 処理結果の辞書
    """
    
    print()
    print("=" * 80)
    print(f"📊 一括処理完了")
    print("=" * 80)
    print()
    
    print("🎯 全体統計:")
    print(f"   📝 対象ホール: {results['total_halls']}個")
    print(f"   ✅ 成功: {results['successful_halls']}個")
    print(f"   ⚠️ 部分成功: {results['partial_halls']}個")
    print(f"   ❌ エラー: {results['error_halls']}個")
    print()
    
    print("📈 データ処理統計:")
    print(f"   ✅ 総追加件数: {results['total_processed']}件")
    print(f"   ❌ 総失敗件数: {results['total_failed']}件")
    print()
    
    # ホール別結果
    print("🏢 ホール別結果:")
    print()
    
    for hall_name, result in results['hall_results'].items():
        status_icon = "✅" if result['status'] == 'success' else "⚠️" if result['status'] == 'partial' else "❌"
        
        if result['status'] in ['success', 'partial']:
            processed = result.get('processed', 0)
            failed = result.get('failed', 0)
            message = f"追加: {processed}件, 失敗: {failed}件"
        else:
            message = result.get('message', 'Unknown error')
        
        print(f"   {status_icon} {hall_name}")
        print(f"      {message}")
    
    print()
    print("=" * 80)
    print(f"⏰ 完了時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)


def main():
    """メイン処理"""
    
    # hall_config.json を読み込み
    print("=" * 80)
    print(f"📊 複数ホール一括増分更新スクリプト")
    print("=" * 80)
    print()
    
    print("🔍 ホール設定を読み込み中...")
    halls = load_hall_config()
    
    if not halls:
        print()
        print("❌ ホール設定が見つかりません")
        return 1
    
    print()
    
    # 一括更新を実行
    results = run_batch_update(halls, skip_errors=True)
    
    # 結果を表示
    print_batch_summary(results)
    
    # 終了コード
    if results['error_halls'] == 0 and results['total_failed'] == 0:
        return 0
    else:
        return 1


if __name__ == "__main__":
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    exit_code = main()
    sys.exit(exit_code)
