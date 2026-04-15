---
source: raw/notes/SPECIFICATION.md
compiled: 2026-04-11
tags:
  - PachinkoAnalyzer
  - 仕様書
  - PHASE2
  - データベース
  - システムアーキテクチャ
---

# PACHINKO-ANALYZER PHASE 2 完全仕様書
## Ver 2.0 | 2026-04-10 | weekday_nth実装完了版

---

## [0] PROJECT STRUCTURE

```
/mnt/project/
├── table_config.py                    # SotT: MACHINE_TYPE_CONFIGS, RANK_HISTORY_COLUMNS
├── db_setup.py                        # DB作成 | 8tables + machine_master
├── json_processor.py                  # JSON読込 & 正規化
├── data_inserter.py                   # INSERT操作（高レベルAPI）
├── database_accessor.py               # DB操作全般（CRUD）
├── database_config.py                 # table_config の re-export
├── summary_calculator.py              # 集計テーブル UPDATE
├── rank_calculator.py                 # ランク・履歴計算
├── date_info_calculator.py            # 日付フラグ計算（weekday_nth実装）
├── incremental_db_updater.py          # 増分更新エンジン
├── batch_incremental_updater.py       # 複数ホール一括処理
└── main_processor.py                  # 実運用エントリーポイント

/mnt/project/db/
└── {hall_name}.db                     # SQLite DB | ホール別

/mnt/project/config/
└── hall_config.json                   # ホール設定 & イベント設定

/mnt/project/data/
├── {hall_name}/
│   ├── {date}_{hall_name}_data.json   # スクレイパー出力
│   └── {hall_name}台位置.csv          # 台配置マスターCSV
└── ...
```

---

## [1] DATABASE SCHEMA

### [1.1] Tables Definition

| # | Table | Role | PK | FK | Rows |
|-|-|-|-|-|-|
| 1 | machine_detailed_results | 個別台実績 | (date, machine_number) | - | ~3M/year |
| 2 | machine_layout | 台配置 | machine_number | - | ~400 |
| 3 | daily_hall_summary | ホール全体集計 | date | - | ~250/year |
| 4 | daily_machine_type_summary | 機種別集計 | (date, machine_name) | - | ~3K/year |
| 5 | last_digit_summary_{all,jug,hana,oki,other} | 末尾別集計 | (date, last_digit) | - | ~50/year×5 |
| 6 | daily_position_summary_{all,jug,hana,oki,other} | 位置別集計 | (date, front_position) | - | ~200/year×5 |
| 7 | daily_island_summary | 島別集計 | (date, island_name) | - | ~100/year |
| 8 | machine_master | 機種マスター | machine_name_normalized | - | ~50 |

### [1.2] Column Groups

#### A. machine_detailed_results (17cols)

```
date(TEXT), machine_name(TEXT), machine_number(INT), 
last_digit(TEXT), is_zorome(BOOL),
machine_rank_in_type(INT),
games_normalized(INT), games_deviation(INT),
diff_coins_normalized(INT),
bb_count(INT), rb_count(INT),
total_probability_{fraction(TEXT), decimal(REAL)},
bb_probability_{fraction(TEXT), decimal(REAL)},
rb_probability_{fraction(TEXT), decimal(REAL)}
```

#### B. daily_hall_summary (20cols)

```
Base Stats (6):
  date(PK), total_machines(INT), total_games(INT),
  total_diff_coins(INT), avg_games_per_machine(INT),
  avg_diff_per_machine(INT)

Date Flags (13):
  day_of_week(TEXT), last_digit(INT), weekday_nth(TEXT),
  is_strong_zorome(BOOL), is_zorome(BOOL),
  is_month_start(BOOL), is_month_end(BOOL),
  is_weekend(BOOL), is_holiday(BOOL),
  hall_anniversary(BOOL), is_x_day(BOOL),
  week_of_month(INT), is_any_event(BOOL)

Aggregated Stats (1):
  win_rate(INT)
```

#### C. daily_machine_type_summary (30+cols)

```
Base (3):
  date, machine_name, machine_count

Stats (16):
  total_games(INT), avg_games(REAL),
  max_games(INT), min_games(INT),
  total_diff_coins(INT), avg_diff_coins(REAL),
  max_diff_coins(INT), min_diff_coins(INT),
  total_bb(INT), total_rb(INT),
  avg_bb_per_game(REAL), avg_rb_per_game(REAL),
  win_rate(INT), efficiency(REAL),
  high_profit_rate(REAL)

Flags (2):
  is_over10_machine(BOOL), is_3_machine(BOOL)

Rank + History (22):
  {prefix}_diff(INT), {prefix}_games(INT), {prefix}_efficiency(INT),
  avg_diff_{7d,14d,21d,28d,35d}(REAL),
  avg_games_{7d,14d,21d,28d,35d}(REAL),
  avg_efficiency_{7d,14d,21d,28d,35d}(REAL),
  avg_rank_diff_{7d,14d,21d,28d,35d}(REAL)
```

#### D. Rank + History Template (22cols)

file: table_config.py::RANK_HISTORY_COLUMNS

```python
[
  "{prefix}_diff INTEGER",
  "{prefix}_games INTEGER",
  "{prefix}_efficiency INTEGER",
  "avg_diff_{7d,14d,21d,28d,35d} REAL",
  "avg_games_{7d,14d,21d,28d,35d} REAL",
  "avg_efficiency_{7d,14d,21d,28d,35d} REAL",
  "avg_rank_diff_{7d,14d,21d,28d,35d} REAL"
]
```

Applied to:
- daily_machine_type_summary → prefix='machine_type_rank'
- last_digit_summary_* → prefix='last_digit_rank'
- daily_position_summary_* → prefix='position_rank'
- daily_island_summary → prefix='island_rank'

### [1.3] weekday_nth Format Specification

file: date_info_calculator.py::_get_nth_weekday()

```
Format: '{weekday_abbr}{nth}'
Pattern: [A-Z][a-z][a-z][1-5]
Length: 4 chars fixed

Weekday abbr: Mon, Tue, Wed, Thu, Fri, Sat, Sun
Nth: 1-5 (計算: (day-1)//7 + 1)

Examples:
  2026-04-01 (Wed) → Wed1
  2026-04-08 (Wed) → Wed2
  2026-04-15 (Wed) → Wed3
  2026-05-02 (Sat) → Sat1
  2026-05-30 (Sat) → Sat5
```

Usage (Python):
```python
# Extract weekday: weekday_nth.str[:3]  → 'Mon', 'Wed', etc.
# Extract nth: weekday_nth.str[3]      → '1', '2', etc.
# Filter: df[df['weekday_nth']=='Wed2']
# Groupby: df.groupby(df['weekday_nth'].str[:3])
```

---

## [2] DATA FLOW & PROCESSING PIPELINE

### [2.1] Main Entry Point: main_processor.py

```
main()
  └─ get_hall_folders(data_root)
      └─ [hall_1, hall_2, ...]
  
  for each hall:
    └─ process_single_hall(hall_name, project_root)
        ├─ Phase 1: DB Creation
        │   └─ create_database(hall_name, project_root)
        │       ├─ db_setup.py::create_database()
        │       │   ├─ CREATE 8tables
        │       │   ├─ CREATE machine_master
        │       │   └─ _import_machine_layout()
        │       └─ db_setup.py::create_machine_master_db()
        │
        ├─ Phase 2: JSON Loading & Initialization
        │   ├─ JSONProcessor(hall_name, project_root)
        │   └─ get_json_files()
        │
        ├─ Phase 3: Data Import (DataImporter)
        │   └─ import_all_json_files()
        │       for each json_file:
        │         └─ import_single_json(json_filepath)
        │             ├─ json_processor.load_json_file()
        │             ├─ json_processor.process_all_machine_data_for_day()
        │             │   ├─ MachineCountCalculator.calculate_same_machine_counts()
        │             │   └─ DataNormalizer.normalize_*()
        │             │
        │             ├─ data_inserter.insert_machine_detailed_results()
        │             ├─ data_inserter.calculate_and_insert_daily_summary()
        │             │   ├─ INSERT daily_hall_summary (base stats)
        │             │   └─ data_inserter.update_games_deviation()
        │             │
        │             ├─ summary_calculator.update_machine_type_summary()
        │             ├─ summary_calculator.update_last_digit_summary_by_type()
        │             ├─ summary_calculator.update_position_summary_by_type()
        │             ├─ summary_calculator.update_island_summary()
        │             │
        │             ├─ rank_calculator.calculate_ranks_for_date()
        │             ├─ rank_calculator.calculate_history_for_date()
        │             │
        │             └─ date_info_calculator.update_date_info()
        │                 └─ UPDATE daily_hall_summary SET weekday_nth, is_zorome, ...
        │
        └─ Phase 4: Final History Calculation
            └─ rank_calculator.calculate_history_for_date() (last 10 dates)
```

### [2.2] Incremental Update: incremental_db_updater.py

```
IncrementalDBUpdater(hall_name, db_path=None)
  
  run(verbose=True)
    ├─ get_db_registered_dates()
    │   └─ SELECT DISTINCT date FROM machine_detailed_results
    │
    ├─ get_json_available_dates()
    │   └─ glob: data/{hall_name}/*.json
    │
    ├─ get_new_dates(registered_dates, available_dates)
    │   └─ new_dates = available_dates - registered_dates
    │
    for each new_date in sorted(new_dates):
      └─ process_new_date(date_str)
          ├─ json_processor.process_all_machine_data_for_day()
          ├─ data_inserter.insert_machine_detailed_results()
          ├─ data_inserter.calculate_and_insert_daily_summary()
          ├─ summary_calculator.update_*_summary()
          ├─ rank_calculator.calculate_ranks_for_date()
          ├─ rank_calculator.calculate_history_for_date()
          └─ date_info_calculator.update_date_info()
              └─ UPDATE daily_hall_summary SET weekday_nth, ...
    
    for each processed_date[-7:]:
      └─ rank_calculator.calculate_history_for_date() (再計算)
```

### [2.3] Batch Update: batch_incremental_updater.py

```
load_hall_config(config_path)
  └─ hall_config.json
      └─ filter: hall['active'] == True
      └─ [hall_1, hall_2, ...]

run_batch_update(halls, skip_errors=True)
  for each hall:
    └─ IncrementalDBUpdater(hall_name).run()
        └─ (as [2.2])
```

---

## [3] KEY MODULES & INTERFACES

### [3.1] table_config.py (SotT)

**Role**: 全テーブル設定の一元管理

```python
MACHINE_TYPE_CONFIGS = [
  {suffix: 'all', name: '全体', condition: ''},
  {suffix: 'jug', name: 'ジャグラー', condition: 'AND mm.jug_flag=1'},
  {suffix: 'hana', name: 'ハナハナ', condition: 'AND mm.hana_flag=1'},
  {suffix: 'oki', name: '沖ドキ', condition: 'AND mm.oki_flag=1'},
  {suffix: 'bt', name: 'BT機種', condition: 'AND mm.bt_flag=1'},
  {suffix: 'other', name: '非A&非BT', condition: 'AND mm.jug_flag=0 AND ...'},
]

SUMMARY_TABLE_CONFIGS = [
  {base_name: 'daily_machine_type_summary', group_key: 'machine_name', rank_prefix: 'machine_type_rank', variants: [None]},
  {base_name: 'last_digit_summary', group_key: 'last_digit', rank_prefix: 'last_digit_rank', variants: ['all','jug','hana','oki','other']},
  {base_name: 'daily_position_summary', group_key: 'front_position', rank_prefix: 'position_rank', variants: ['all','jug','hana','oki','other']},
  {base_name: 'daily_island_summary', group_key: 'island_name', rank_prefix: 'island_rank', variants: [None]},
]

RANK_HISTORY_COLUMNS = [
  '{prefix}_diff INTEGER',
  '{prefix}_games INTEGER',
  '{prefix}_efficiency INTEGER',
  'avg_diff_{7d,14d,21d,28d,35d} REAL',
  'avg_games_{7d,14d,21d,28d,35d} REAL',
  'avg_efficiency_{7d,14d,21d,28d,35d} REAL',
  'avg_rank_diff_{7d,14d,21d,28d,35d} REAL',
]

def get_all_summary_tables() → List[Dict[str,str]]
  return [{table_name, group_key, rank_prefix}, ...]

def get_rank_columns(rank_prefix: str) → List[str]
  return [col.format(prefix=rank_prefix) for col in RANK_HISTORY_COLUMNS]
```

### [3.2] date_info_calculator.py

**Role**: 日付フラグ計算 & DB更新（weekday_nth含む）

```python
class DateInfoCalculator:
  
  __init__(hall_name: str, db_path: str = None, config_path: str = None)
    ├─ self.hall_name
    ├─ self.db_path
    ├─ self.config_path
    └─ self.hall_config = _load_hall_config()
  
  _load_hall_config() → dict
    ├─ hall_config.json読込
    └─ {event_digits: [], anniversary_date: ''}
  
  _get_day_of_week(date_obj) → str
    return weekday_names[date_obj.weekday()]  # 月火水木金土日
  
  _get_nth_weekday(date_obj) → str
    ├─ weekday_abbr = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    ├─ weekday_num = date_obj.weekday()  # 0-6
    ├─ nth = (date_obj.day - 1) // 7 + 1  # 1-5
    └─ return f"{weekday_abbr[weekday_num]}{nth}"  # 'Wed2'等
  
  _get_last_digit(day: int) → int
    return day % 10  # 0-9
  
  _check_strong_zorome(month, day) → bool
    return month == day and month <= 12
  
  _check_zorome(day) → bool
    return day in [11, 22]
  
  _check_month_start(day) → bool
    return day == 1
  
  _check_month_end(date_obj) → bool
    return date_obj.day == calendar.monthrange(...)[1]
  
  _check_weekend(date_obj) → bool
    return date_obj.weekday() >= 5
  
  _check_holiday(date_obj) → bool
    try: jpholiday.is_holiday(date_obj.date())
    except: (固定祝日判定)
  
  _check_x_day(day) → bool
    return day in self.hall_config['event_digits']
  
  _check_hall_anniversary(month, day) → bool
    anniversary_date = self.hall_config['anniversary_date']  # MMDD
    return month == int(anniversary_date[:2]) and day == int(anniversary_date[2:])
  
  _get_week_of_month(day) → int
    return (day - 1) // 7 + 1  # 1-5
  
  calculate_date_info(date_str: str) → dict
    ├─ date_obj = datetime.strptime(date_str, '%Y%m%d')
    ├─ 各フラグを計算
    └─ return {
         date, day_of_week, last_digit, weekday_nth,
         is_strong_zorome, is_zorome, is_month_start, is_month_end,
         is_weekend, is_holiday, hall_anniversary, is_x_day,
         week_of_month, is_any_event
       }
  
  add_date_info_columns() → bool
    ├─ daily_hall_summary の現在のカラムを確認
    ├─ 不足カラムを ALTER TABLE で追加
    │   ├─ TEXT: day_of_week, weekday_nth
    │   ├─ INTEGER: last_digit, week_of_month
    │   └─ BOOL: is_*
    └─ commit
  
  update_date_info(date_str: str) → bool
    ├─ date_info = calculate_date_info(date_str)
    ├─ IF EXISTS:
    │   UPDATE daily_hall_summary SET {...} WHERE date=?
    └─ ELSE:
        INSERT INTO daily_hall_summary (...) VALUES (...)
```

**Integration points**:
- main_processor.py::DataImporter.__init__
- incremental_db_updater.py::IncrementalDBUpdater.__init__
- Both call: add_date_info_columns() (初期化)
- Both call: update_date_info(date_str) (各日付後)

---

## [4] CONFIGURATION FILES

### [4.1] hall_config.json Structure

```json
{
  "halls": [
    {
      "hall_name": "マルハンメガシティ柏",
      "active": true,
      "event_settings": {
        "event_digits": [7, 17, 27],
        "anniversary_date": "0401"
      }
    },
    ...
  ]
}
```

**Usage**:
- date_info_calculator.py で anniversary_date & event_digits を読込
- is_x_day, hall_anniversary フラグを計算

---

## [5] DATA VALIDATION & ERROR HANDLING

### [5.1] date_info_calculator.py::_validate_config()

```
Validate:
  ├─ anniversary_date format (MMDD, 0101-1231)
  ├─ event_digits values (1-31)
  └─ raise ValueError if invalid
```

### [5.2] json_processor.py Error Handling

```
Per machine record:
  try:
    process_machine_data()
  except ValueError:
    print(⚠️ warning)
    continue  # スキップして続行
```

### [5.3] DB Transaction Management

```
data_inserter.py, summary_calculator.py:
  try:
    cursor.execute(...)
    conn.commit()
  except Exception:
    conn.rollback()
    raise
  finally:
    conn.close()
```

---

## [6] PERFORMANCE CHARACTERISTICS

### [6.1] Time Complexity

| Operation | Input | Output | Time |
|-|-|-|-|
| JSON処理（1日） | 400machines | 400records | O(n) |
| 機種別集計 | 400mach | 50types | O(n) |
| ランク計算 | 250types | ranks | O(n²) |
| 履歴計算（35d） | 250types×5periods | history | O(n²) |
| 日付フラグ | 1date | 13flags | O(1) |

### [6.2] Space Complexity

| Table | Rows/year | Size | Index |
|-|-|-|-|
| machine_detailed_results | 3M | ~500MB | date, machine_number |
| daily_hall_summary | 250 | <1MB | date |
| daily_machine_type_summary | 12.5K | ~30MB | date, machine_name |
| last_digit_summary_* | 2.5K | ~5MB | date, {last_digit, suffix} |
| **TOTAL** | - | ~600MB | - |

### [6.3] Optimization Tips

```
1. Index戦略:
   CREATE INDEX idx_machine_detailed_date ON machine_detailed_results(date);
   CREATE INDEX idx_summary_date ON daily_machine_type_summary(date);

2. Batch処理:
   executemany() で複数レコード一括INSERT
   
3. 履歴計算:
   calculate_history_for_date() は [7,14,21,28,35]d を一度に処理
   再計算は最新7日分のみ

4. weekday_nth インデックス:
   CREATE INDEX idx_weekday_nth ON daily_hall_summary(weekday_nth);
```

---

## [7] INTEGRATION CHECKLIST

- [x] nth_weekday (INT) → weekday_nth (TEXT) 変更完了
- [x] date_info_calculator.py: _get_nth_weekday() メソッド実装
- [x] db_setup.py: weekday_nth TEXT カラム定義
- [x] main_processor.py: DateInfoCalculator 統合
- [x] incremental_db_updater.py: DateInfoCalculator 統合
- [x] batch_incremental_updater.py: 自動統合
- [x] 構文チェック: 全ファイル成功
- [x] テストケース: weekday_nth 値確認成功

---

## [8] KNOWN LIMITATIONS & FUTURE WORK

### Limitations
- jpholiday ライブラリが未インストール環境では固定祝日のみ
- machine_master は手動で機種フラグを設定する必要がある（自動判定は簡易版）
- テーブル構造は固定（カラム追加には ALTER TABLE が必要）

### Future Enhancements
- [ ] 機種分類の自動学習モデル
- [ ] リアルタイム集計（ストリーミング）
- [ ] 複数DB統合ビュー
- [ ] 設定パターンマッチング機械学習
- [ ] Web UI for データ閲覧・分析

---

関連記事：
- [[PHASE2_API_Reference]]
- [[weekday_nth実装説明]]
- [[PHASE2_保守マニュアル]]

**Created**: 2026-04-10  
**Version**: 2.0 (weekday_nth実装)  
**Status**: PRODUCTION-READY
