---
source: raw/notes/MAINTENANCE_MANUAL.md
compiled: 2026-04-11
tags:
  - PachinkoAnalyzer
  - 保守
  - デバッグ
  - PHASE2
  - 開発者向け
---

# PACHINKO-ANALYZER PHASE 2 保守・デバッグマニュアル
## Ver 2.0 | 2026-04-10 | 開発者向け

---

## [1] TROUBLESHOOTING

### [1.1] NameError: name 'os' is not defined

**File**: main_processor.py
**Line**: depends on usage
**Cause**: import os が未定義
**Fix**: 確認済み（行10に import os が存在）

```python
# 確認
grep -n "^import os" main_processor.py
# Expected output: 10:import os
```

### [1.2] ModuleNotFoundError: No module named 'feature_engine'

**Status**: RESOLVED - feature_engine.py は削除済み
**Reason**: 実装不完全（feature_calculator.py が存在しない）

```bash
# 確認
ls -la /mnt/project/feature_engine.py
# Expected: No such file or directory
```

### [1.3] DatabaseError: UNIQUE constraint failed

**Cause**: 同一date+machine_numberで重複INSERT
**Fix**: INSERT OR REPLACE を使用（既に実装済み）

```python
# data_inserter.py:85
INSERT OR REPLACE INTO machine_detailed_results (...)
```

### [1.4] hall_config.json 読込エラー

**Cause**: anniversary_date が不正な形式
**Fix**: MMDD形式で指定（例: '0401'）

```python
# date_info_calculator.py:131
if not (1 <= month <= 12):
    raise ValueError(f"anniversary_date の月が範囲外: {month}")
if not (1 <= day <= 31):
    raise ValueError(f"anniversary_date の日が範囲外: {day}")
```

**Validation**:
```bash
# hall_config.json をバリデート
python3 -c "
import json
with open('config/hall_config.json') as f:
    cfg = json.load(f)
    for hall in cfg['halls']:
        date = hall['event_settings']['anniversary_date']
        month, day = int(date[:2]), int(date[2:])
        assert 1<=month<=12, f'{hall}: month={month}'
        assert 1<=day<=31, f'{hall}: day={day}'
print('✅ Config valid')
"
```

### [1.5] JSON ファイルが見つからない

**Cause**: ホール名の不一致（フォルダ名とJSON内のhall_nameが異なる）
**Fix**: _find_correct_hall_folder() で自動検出（既に実装）

```python
# json_processor.py:193
def _find_correct_hall_folder(self) -> Optional[str]:
    # JSON内のhall_nameと実ディレクトリ名を照合して検出
```

**Debug**:
```bash
# JSONファイルのhall_name確認
python3 -c "
import json, glob
for f in glob.glob('data/*/*.json')[:1]:
    with open(f) as fp:
        data = json.load(fp)
        print(f'File: {f}')
        print(f'hall_name in JSON: {data.get(\"hall_name\")}')
"
```

### [1.6] weekday_nth が INT のまま

**Cause**: db_setup.py が古いバージョン（修正済み）
**Current**: weekday_nth TEXT 型

```python
# db_setup.py:141
weekday_nth TEXT,  # ← TEXT型に変更済み
```

**Migration** (既存DBの場合):
```sql
-- 新しいカラムを追加
ALTER TABLE daily_hall_summary ADD COLUMN weekday_nth_new TEXT;

-- データを変換
UPDATE daily_hall_summary
SET weekday_nth_new = (
  CASE CAST(substr(date, 9, 2) AS INTEGER) % 7
    WHEN 1 THEN 'Mon'
    WHEN 2 THEN 'Tue'
    WHEN 3 THEN 'Wed'
    WHEN 4 THEN 'Thu'
    WHEN 5 THEN 'Fri'
    WHEN 6 THEN 'Sat'
    WHEN 0 THEN 'Sun'
  END
) || CAST((CAST(substr(date, 9, 2) AS INTEGER) - 1) / 7 + 1 AS TEXT)
WHERE weekday_nth_new IS NULL;

-- 古いカラムを削除
ALTER TABLE daily_hall_summary DROP COLUMN weekday_nth;

-- 名前を変更
ALTER TABLE daily_hall_summary RENAME COLUMN weekday_nth_new TO weekday_nth;
```

---

## [2] DEBUGGING TECHNIQUES

### [2.1] DB 内容確認

```bash
# DB ファイルサイズ
ls -lh db/マルハンメガシティ柏.db

# テーブル一覧
sqlite3 db/マルハンメガシティ柏.db "SELECT name FROM sqlite_master WHERE type='table';"

# machine_detailed_results の行数
sqlite3 db/マルハンメガシティ柏.db "SELECT COUNT(*) FROM machine_detailed_results;"

# 最新日付の確認
sqlite3 db/マルハンメガシティ柏.db "SELECT MAX(date) FROM daily_hall_summary;"

# daily_hall_summary の weekday_nth 確認
sqlite3 db/マルハンメガシティ柏.db "
  SELECT date, day_of_week, weekday_nth, is_zorome, is_any_event 
  FROM daily_hall_summary 
  ORDER BY date DESC 
  LIMIT 10;
"
```

### [2.2] JSON 処理のログ

```python
# json_processor.py で詳細ログを有効化
import logging
logging.basicConfig(level=logging.DEBUG)

processor = JSONProcessor('マルハンメガシティ柏')
processor.get_json_files()
```

### [2.3] 日付フラグの計算確認

```python
from date_info_calculator import DateInfoCalculator

calc = DateInfoCalculator('マルハンメガシティ柏')

# 特定日の計算結果
info = calc.calculate_date_info('20260408')
print(info)
# {
#   date: '20260408',
#   day_of_week: '水',
#   weekday_nth: 'Wed2',  ← 確認
#   is_zorome: 0,
#   is_any_event: 0,
#   ...
# }
```

### [2.4] パフォーマンス測定

```python
import time
from incremental_db_updater import IncrementalDBUpdater

updater = IncrementalDBUpdater('マルハンメガシティ柏')

start = time.time()
result = updater.run()
elapsed = time.time() - start

print(f"処理時間: {elapsed:.2f}秒")
print(f"処理件数: {result['processed']}")
print(f"速度: {result['processed']/elapsed:.0f} records/sec")
```

### [2.5] SQL クエリの手動テスト

```sql
-- weekday_nth の値確認
SELECT DISTINCT weekday_nth 
FROM daily_hall_summary 
WHERE weekday_nth IS NOT NULL 
ORDER BY weekday_nth;

-- 形式確認（'Mon1' 等）
SELECT 
  weekday_nth,
  substr(weekday_nth, 1, 3) AS weekday,
  substr(weekday_nth, 4, 1) AS nth
FROM daily_hall_summary 
LIMIT 10;

-- 曜日別集計
SELECT 
  substr(weekday_nth, 1, 3) AS weekday,
  COUNT(*) AS count,
  AVG(avg_diff_coins) AS avg_diff
FROM daily_hall_summary 
WHERE weekday_nth IS NOT NULL
GROUP BY substr(weekday_nth, 1, 3)
ORDER BY weekday;

-- 第N週別集計
SELECT 
  substr(weekday_nth, 4, 1) AS nth,
  COUNT(*) AS count,
  AVG(avg_diff_coins) AS avg_diff
FROM daily_hall_summary 
WHERE weekday_nth IS NOT NULL
GROUP BY substr(weekday_nth, 4, 1)
ORDER BY nth;
```

---

## [3] MODIFICATION POINTS

### [3.1] 新しい日付フラグを追加する場合

**File**: date_info_calculator.py

```python
# 1. メソッドを追加
def _check_my_event(self, date_obj) -> bool:
    """新しいイベント判定"""
    # 実装...
    return result

# 2. calculate_date_info() に追加
info = {
    # ...
    'my_event': 1 if self._check_my_event(date_obj) else 0,
}

# 3. add_date_info_columns() に追加
columns_to_add = [
    # ...
    'my_event',  # ← 追加
]

# 4. update_date_info() の SQL に追加
update_sql = """
  UPDATE daily_hall_summary
  SET ... my_event = ?,
  WHERE date = ?
"""

cursor.execute(update_sql, (..., my_event_value, date_str))
```

**Verification**:
```bash
# カラムが追加されたか確認
sqlite3 db/マルハンメガシティ柏.db ".schema daily_hall_summary" | grep my_event
```

### [3.2] 新しい集計テーブルを追加する場合

**File**: table_config.py

```python
# SUMMARY_TABLE_CONFIGS に追加
{
    'base_name': 'my_summary',
    'group_key': 'my_key',
    'rank_prefix': 'my_rank',
    'variants': ['all', 'jug', 'hana'],
}
```

**File**: db_setup.py

```python
# CREATE TABLE を追加
cursor.execute('''
    CREATE TABLE my_summary_all (
        date TEXT,
        my_key TEXT,
        machine_count INTEGER,
        total_games INTEGER,
        ...
        {rank_columns_sql},
        PRIMARY KEY (date, my_key)
    )
''')
```

**File**: summary_calculator.py

```python
# update_* メソッドを追加
def update_my_summary(self, date: str):
    """my_summary を更新"""
    cursor.execute('DELETE FROM my_summary_all WHERE date = ?', (date,))
    cursor.execute('''
        INSERT INTO my_summary_all (...)
        SELECT ... FROM machine_detailed_results
        WHERE date = ?
        GROUP BY my_key
    ''', (date,))
    conn.commit()

# main_processor.py と incremental_db_updater.py で呼び出し
self.summary_calc.update_my_summary(date)
```

### [3.3] 機種フラグを追加する場合

**File**: table_config.py

```python
MACHINE_TYPE_CONFIGS に追加:
{
    'suffix': 'mytype',
    'name': 'マイタイプ',
    'condition': 'AND mm.mytype_flag = 1',
}
```

**File**: db_setup.py

```python
# machine_master に カラムを追加
cursor.execute('''
    CREATE TABLE machine_master (
        ...
        mytype_flag BOOLEAN DEFAULT 0,
        ...
    )
''')
```

**File**: data_inserter.py

```python
# get_or_create_machine_master() で判定ロジックを追加
mytype_flag = 1 if 'マイタイプ' in machine_name else 0

cursor.execute('''
    INSERT INTO machine_master (..., mytype_flag, ...)
    VALUES (..., ?, ...)
''', (..., mytype_flag, ...))
```

---

## [4] CODE REVIEW CHECKLIST

新しいコードの追加時：

- [ ] 構文チェック: `python3 -m py_compile file.py`
- [ ] import の確認: 循環依存がない
- [ ] DB transaction: try-except-finally で確実にclose
- [ ] SQL injection: すべて `?` パラメータを使用
- [ ] エラーハンドリング: 予想可能なエラーをキャッチ
- [ ] ログ出力: 重要な処理は print(...) で記録
- [ ] テスト: 実際のデータで動作確認
- [ ] ドキュメント: 本仕様書とこのマニュアルを更新

---

## [5] REGRESSION TEST CASES

修正後に実行すべきテスト：

```python
# test_weekday_nth_format.py
import unittest
from date_info_calculator import DateInfoCalculator
from datetime import datetime

class TestWeekdayNth(unittest.TestCase):
    
    def test_format(self):
        """weekday_nth の形式確認"""
        calc = DateInfoCalculator('test_hall', ':memory:')
        
        test_cases = [
            ('20260401', 'Wed1'),  # 2026-04-01 = 水曜、第1週
            ('20260408', 'Wed2'),  # 2026-04-08 = 水曜、第2週
            ('20260415', 'Wed3'),  # 2026-04-15 = 水曜、第3週
            ('20260502', 'Fri1'),  # 2026-05-02 = 金曜、第1週
            ('20260530', 'Sat5'),  # 2026-05-30 = 土曜、第5週
        ]
        
        for date_str, expected in test_cases:
            result = calc._get_nth_weekday(datetime.strptime(date_str, '%Y%m%d'))
            self.assertEqual(result, expected, f"{date_str} failed")
    
    def test_string_operations(self):
        """weekday_nth の文字列操作確認"""
        wnth = 'Wed2'
        
        self.assertEqual(wnth[:3], 'Wed')
        self.assertEqual(wnth[3:], '2')
        self.assertTrue(wnth.startswith('Wed'))
        self.assertTrue(wnth.endswith('2'))

if __name__ == '__main__':
    unittest.main()
```

実行:
```bash
python3 test_weekday_nth_format.py
# OK: 全テストがPASSすることを確認
```

---

## [6] DEPLOYMENT CHECKLIST

新バージョンを本番環境にデプロイする際：

### Phase A: Pre-deployment
- [ ] 全ファイルの構文チェック完了
- [ ] ローカルテストで機能確認
- [ ] SPECIFICATION.md と本マニュアルを更新
- [ ] Git に commit & push

### Phase B: Deployment
- [ ] バックアップ: `cp db/*.db db_backup/`
- [ ] 新コードをデプロイ
- [ ] 小規模ホールで試験実行
- [ ] エラーログを確認

### Phase C: Post-deployment
- [ ] すべてのホールで incremental_db_updater.py を実行
- [ ] DB の weekday_nth カラムを確認
- [ ] rank_calculator の計算が正常に完了したか確認
- [ ] パフォーマンス（処理時間）が大幅に低下していないか確認

---

## [7] DEPENDENCY GRAPH

```
main_processor.py
  ├─ db_setup.py
  ├─ json_processor.py
  │   └─ table_config.py (SotT)
  ├─ data_inserter.py
  ├─ summary_calculator.py
  │   └─ table_config.py
  ├─ rank_calculator.py
  │   └─ table_config.py
  └─ date_info_calculator.py
      └─ jpholiday (optional)

incremental_db_updater.py
  ├─ json_processor.py
  ├─ data_inserter.py
  ├─ summary_calculator.py
  ├─ rank_calculator.py
  └─ date_info_calculator.py

batch_incremental_updater.py
  └─ incremental_db_updater.py
```

**Circular Dependency**: なし ✅

---

## [8] CONFIGURATION REFERENCE

### [8.1] environment 変数（未実装、将来用）

```bash
export PACHINKO_PROJECT_ROOT=/path/to/project
export PACHINKO_DB_DIR=$PACHINKO_PROJECT_ROOT/db
export PACHINKO_DATA_DIR=$PACHINKO_PROJECT_ROOT/data
export PACHINKO_CONFIG=$PACHINKO_PROJECT_ROOT/config/hall_config.json
```

### [8.2] logging 設定（未実装、将来用）

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('pachinko.log'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)
```

---

## [9] QUICK REFERENCE

```bash
# 全ホール増分更新
python3 batch_incremental_updater.py

# 単一ホール増分更新
python3 incremental_db_updater.py "マルハンメガシティ柏"

# DB リセット & 再構築（全ホール）
python3 main_processor.py

# 特定ホールのデータ確認
sqlite3 db/マルハンメガシティ柏.db \
  "SELECT date, day_of_week, weekday_nth FROM daily_hall_summary LIMIT 5;"

# weekday_nth の値確認
sqlite3 db/マルハンメガシティ柏.db \
  "SELECT DISTINCT weekday_nth FROM daily_hall_summary ORDER BY weekday_nth;"
```

---

関連記事：
- [[PHASE2_完全仕様書]]
- [[PHASE2_API_Reference]]
- [[weekday_nth実装説明]]

**Last Updated**: 2026-04-10  
**Maintainer**: Development Team  
**Status**: ACTIVE
