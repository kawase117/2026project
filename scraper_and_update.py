#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複数ホール増分更新スクリプト
スクレイパー実行後、各ホール別に incremental_db_updater で DB を更新
"""

import sys
from pathlib import Path
from database.incremental_db_updater import IncrementalDBUpdater
import json

def main():
    # hall_config.json から全ホール読込
    config_path = Path(__file__).parent / "config" / "hall_config.json"

    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception as e:
        print(f"❌ hall_config.json の読込エラー: {e}")
        sys.exit(1)

    print("=" * 60)
    print("複数ホール増分更新開始")
    print("=" * 60)

    results = {}
    for hall_config in config["halls"]:
        hall_name = hall_config["hall_name"]
        print(f"\n▶ {hall_name} を処理中...")

        try:
            updater = IncrementalDBUpdater(hall_name)
            result = updater.run()
            results[hall_name] = result
            print(f"  ✅ {result['message']}")
        except Exception as e:
            results[hall_name] = {"status": "error", "message": str(e)}
            print(f"  ❌ エラー: {e}")

    # サマリー
    print("\n" + "=" * 60)
    print("処理完了サマリー")
    print("=" * 60)

    success_count = 0
    partial_count = 0
    error_count = 0

    for hall_name, result in results.items():
        if result["status"] == "success":
            status_emoji = "✅"
            success_count += 1
        elif result["status"] == "partial":
            status_emoji = "⚠️"
            partial_count += 1
        else:
            status_emoji = "❌"
            error_count += 1

        print(f"{status_emoji} {hall_name}: {result['message']}")

    print("\n" + "-" * 60)
    print(f"成功: {success_count}, 部分成功: {partial_count}, エラー: {error_count}")
    print("=" * 60)

    return 0 if error_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
