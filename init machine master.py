#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
machine_master.db に BT機種初期データを登録
"""

import sqlite3
import os

def init_machine_master_with_bt_machines():
    """machine_master.db にBT機種16個を登録"""
    
    db_path = os.path.join("db", "machine_master.db")
    
    if not os.path.exists(db_path):
        print(f"❌ machine_master.db が見つかりません: {db_path}")
        print(f"   先に db_setup.py で create_machine_master_db() を実行してください")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # BT機種16個のデータ
    bt_machines = [
        {
            'name': 'LBパチスロ ヱヴァンゲリヲン ～約束の扉',
            'display_names': 'LBパチスロ ヱヴァンゲリヲン ～約束の扉, LBエヴァ',
            'official_name': 'LBパチスロ ヱヴァンゲリヲン ～約束の扉',
        },
        {
            'name': 'スマスロ サンダーV',
            'display_names': 'スマスロ サンダーV, スマスロサンダー',
            'official_name': 'スマスロ サンダーV',
        },
        {
            'name': 'ニューキングハナハナV',
            'display_names': 'ニューキングハナハナV, キングハナハナ',
            'official_name': 'ニューキングハナハナV',
        },
        {
            'name': 'L不二子BT',
            'display_names': 'L不二子BT, L不二子',
            'official_name': 'L不二子BT',
        },
        {
            'name': 'SHAKE BONUS TRIGGER',
            'display_names': 'SHAKE BONUS TRIGGER, シェイクBT',
            'official_name': 'SHAKE BONUS TRIGGER',
        },
        {
            'name': 'マジカルハロウィン ボーナストリガー',
            'display_names': 'マジカルハロウィン ボーナストリガー, マジカルハロウィンBT',
            'official_name': 'マジカルハロウィン ボーナストリガー',
        },
        {
            'name': 'クレアの秘宝伝 〜はじまりの扉と太陽の石〜 ボーナストリガーver.',
            'display_names': 'クレアの秘宝伝 ボーナストリガー, クレア秘宝伝BT',
            'official_name': 'クレアの秘宝伝 〜はじまりの扉と太陽の石〜 ボーナストリガーver.',
        },
        {
            'name': 'マタドールⅢ',
            'display_names': 'マタドールⅢ, マタドール3',
            'official_name': 'マタドールⅢ',
        },
        {
            'name': 'アレックス ブライト',
            'display_names': 'アレックス ブライト, アレックスブライト',
            'official_name': 'アレックス ブライト',
        },
        {
            'name': 'LBトリプルクラウン',
            'display_names': 'LBトリプルクラウン, LBクラウン',
            'official_name': 'LBトリプルクラウン',
        },
        {
            'name': 'LBジャックポット',
            'display_names': 'LBジャックポット, LBジャック',
            'official_name': 'LBジャックポット',
        },
        {
            'name': 'LBパチスロ1000ちゃんA',
            'display_names': 'LBパチスロ1000ちゃんA, LB千ちゃん',
            'official_name': 'LBパチスロ1000ちゃんA',
        },
        {
            'name': '翔べ！ハーレムエース',
            'display_names': '翔べ！ハーレムエース, ハーレムエース',
            'official_name': '翔べ！ハーレムエース',
        },
        {
            'name': 'LBプレミアムうまい棒',
            'display_names': 'LBプレミアムうまい棒, LBうまい棒',
            'official_name': 'LBプレミアムうまい棒',
        },
        {
            'name': 'スマスロニューパルサーBT',
            'display_names': 'スマスロニューパルサーBT, スマスロパルサー',
            'official_name': 'スマスロニューパルサーBT',
        },
        {
            'name': 'ジャグラーBT',
            'display_names': 'ジャグラーBT, アイムジャグラーBT',
            'official_name': 'ジャグラーBT',
        },
    ]
    
    try:
        inserted = 0
        for machine in bt_machines:
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO machine_master (
                        machine_name_normalized, bt_flag, display_names, official_name
                    ) VALUES (?, ?, ?, ?)
                ''', (
                    machine['name'],
                    1,  # bt_flag
                    machine['display_names'],
                    machine['official_name']
                ))
                inserted += 1
            except Exception as e:
                print(f"⚠️  {machine['name']}: {e}")
        
        conn.commit()
        print(f"✓ BT機種 {inserted} 個を登録しました")
        return True
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        return False
    
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("machine_master.db - BT機種初期データ登録")
    print("=" * 60)
    
    success = init_machine_master_with_bt_machines()
    
    if success:
        print("\n✅ 初期化完了")
    else:
        print("\n❌ 初期化失敗")