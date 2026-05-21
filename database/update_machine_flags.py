#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
既存DBの machine_master フラグを一括再評価するユーティリティ。
_BT_KEYWORDS を追加した後に手動で実行する。

使い方:
    python database/update_machine_flags.py
"""

import sqlite3
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from data_inserter import _BT_KEYWORDS


def _calc_flags(name: str) -> dict:
    return {
        'jug_flag':  1 if 'ジャグラー' in name else 0,
        'hana_flag': 1 if ('ハナハナ' in name or 'スーハナ' in name) else 0,
        'oki_flag':  1 if '沖ドキ' in name else 0,
        'bt_flag':   1 if any(kw in name for kw in _BT_KEYWORDS) else 0,
    }


def update_all(db_dir: str = 'db') -> None:
    dbs = glob.glob(os.path.join(db_dir, '*.db'))
    if not dbs:
        print(f'[WARN] DBが見つかりません: {db_dir}')
        return

    total = 0
    for db_path in sorted(dbs):
        updated = _update_one(db_path)
        total += updated
        if updated:
            print(f'[{os.path.basename(db_path)}] {updated}件更新')
        else:
            print(f'[{os.path.basename(db_path)}] 変更なし')

    print(f'\n合計 {total} 件更新完了')


def _update_one(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    count = 0
    try:
        cur.execute('SELECT machine_name_normalized, jug_flag, hana_flag, oki_flag, bt_flag FROM machine_master')
        rows = cur.fetchall()
        for (name, jug, hana, oki, bt) in rows:
            new = _calc_flags(name)
            if (new['jug_flag'], new['hana_flag'], new['oki_flag'], new['bt_flag']) != (jug, hana, oki, bt):
                cur.execute(
                    'UPDATE machine_master SET jug_flag=?, hana_flag=?, oki_flag=?, bt_flag=? WHERE machine_name_normalized=?',
                    (new['jug_flag'], new['hana_flag'], new['oki_flag'], new['bt_flag'], name)
                )
                count += 1
        conn.commit()
    finally:
        conn.close()
    return count


if __name__ == '__main__':
    db_dir = sys.argv[1] if len(sys.argv) > 1 else 'db'
    update_all(db_dir)
