#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
充実したテスト用JSONデータ生成スクリプト
10日分、各日50台のテストデータを生成
"""

import json
import os
from datetime import datetime, timedelta
import random


def create_test_json_data():
    """充実したテスト用JSONデータを生成"""
    
    # テスト用ディレクトリの作成
    test_data_dir = os.path.join(os.getcwd(), "data", "test_full")
    os.makedirs(test_data_dir, exist_ok=True)
    
    # テスト日付（10日分）
    base_date = datetime(2025, 1, 1)
    test_dates = [
        (base_date + timedelta(days=i)).strftime('%Y%m%d')
        for i in range(10)
    ]
    
    # 機種名のリスト（BT機種を含む）
    machine_types = [
        # ジャグラー系（30%）
        ('マイジャグラーV', 'jug'),
        ('アイムジャグラーEX', 'jug'),
        ('ゴーゴージャグラー', 'jug'),
        ('ジャグラーBT', 'bt'),  # BT機種
        
        # ハナハナ系（30%）
        ('ハナハナゴールド', 'hana'),
        ('キングハナハナ', 'hana'),
        ('ニューキングハナハナV', 'bt'),  # BT機種
        ('スーパーハナハナ', 'hana'),
        
        # 沖ドキ系（15%）
        ('沖ドキ', 'oki'),
        ('沖ドキ！LIGHT', 'oki'),
        
        # その他BT機種（10%）
        ('L不二子BT', 'bt'),
        ('スマスロニューパルサーBT', 'bt'),
        
        # 非Aタイプ（15%）
        ('スターギャルズ', 'other'),
        ('ビビッドハーレム', 'other'),
        ('アレックス', 'other'),
        ('グレートキングハナハナ', 'other'),
    ]
    
    # 各日付ごとにJSON を生成
    for date_str in test_dates:
        print(f"生成中: {date_str}")
        
        data = {
            "date": date_str,
            "all_data": []
        }
        
        # 50台分のデータを生成
        for machine_idx in range(50):
            machine_number = 1001 + machine_idx  # 1001-1050
            machine_name, machine_type = random.choice(machine_types)
            
            # 機種タイプによって差枚の分布を変える
            if machine_type in ['jug', 'hana']:
                # ジャグラー・ハナハナ：勝ちやすい傾向（60% プラス）
                is_profitable = random.random() > 0.4
                if is_profitable:
                    diff_coins = random.randint(500, 5000)
                else:
                    diff_coins = -random.randint(100, 3000)
            elif machine_type == 'oki':
                # 沖ドキ：中程度（50% プラス）
                is_profitable = random.random() > 0.5
                if is_profitable:
                    diff_coins = random.randint(300, 4000)
                else:
                    diff_coins = -random.randint(100, 2500)
            elif machine_type == 'bt':
                # BT機種：やや有利（65% プラス）
                is_profitable = random.random() > 0.35
                if is_profitable:
                    diff_coins = random.randint(800, 6000)
                else:
                    diff_coins = -random.randint(100, 2000)
            else:
                # その他：厳しい傾向（40% プラス）
                is_profitable = random.random() > 0.6
                if is_profitable:
                    diff_coins = random.randint(200, 2500)
                else:
                    diff_coins = -random.randint(200, 4000)
            
            # ゲーム数：機種タイプで異なる分布
            if machine_type in ['jug', 'hana']:
                games = random.randint(2000, 6000)
            elif machine_type == 'oki':
                games = random.randint(1500, 5000)
            else:
                games = random.randint(1000, 5500)
            
            machine_data = {
                "台番号": str(machine_number),
                "機種名": machine_name,
                "G数": str(games),
                "差枚": str(diff_coins),
                "BB": str(random.randint(3, 20)),
                "RB": str(random.randint(2, 15)),
                "合成確率": f"1/{random.randint(150, 350)}",
                "BB確率": f"1/{random.randint(250, 450)}",
                "RB確率": f"1/{random.randint(400, 700)}",
            }
            
            data["all_data"].append(machine_data)
        
        # JSONファイルに保存
        filename = f"{date_str}_test_data.json"
        filepath = os.path.join(test_data_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"  ✓ {filename} を生成 ({len(data['all_data'])}台)")
    
    print(f"\n✅ テストデータ生成完了")
    print(f"   保存先: {test_data_dir}")
    print(f"   ファイル数: {len(test_dates)}")
    print(f"   1ファイルあたりの台数: 50台")
    print(f"   合計: {len(test_dates) * 50}台")
    print(f"\n📊 期間: 2025-01-01 ～ 2025-01-10")
    print(f"\n📈 機種分布:")
    print(f"   ジャグラー系: 4機種")
    print(f"   ハナハナ系: 4機種")
    print(f"   沖ドキ系: 2機種")
    print(f"   BT機種: 4機種")
    print(f"   その他: 4機種")
    
    return test_data_dir


if __name__ == "__main__":
    create_test_json_data()