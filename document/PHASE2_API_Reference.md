---
source: raw/notes/API_REFERENCE.md
compiled: 2026-04-11
tags:
  - PachinkoAnalyzer
  - API
  - PHASE2
  - 開発者ガイド
  - DateInfoCalculator
---

# PACHINKO-ANALYZER PHASE 2 - API Reference
## Quick Guide for Developers

---

## TABLE OF CONTENTS
1. [DateInfoCalculator](#dateinfoCalculator)
2. [JSONProcessor](#jsonprocessor)
3. [DataInserter](#datainserter)
4. [SummaryCalculator](#summarycalculator)
5. [RankCalculator](#rankcalculator)
6. [Database Schema](#database-schema)
7. [Examples](#examples)

---

## DateInfoCalculator

**Module**: date_info_calculator.py

### Constructor
```python
from date_info_calculator import DateInfoCalculator

calc = DateInfoCalculator(
    hall_name: str,
    db_path: str = None,      # Default: {project_root}/db/{hall_name}.db
    config_path: str = None    # Default: {project_root}/config/hall_config.json
)
```

### Public Methods

#### calculate_date_info(date_str: str) → dict
```python
info = calc.calculate_date_info('20260408')
# Returns:
# {
#   'date': '20260408',
#   'day_of_week': '水',
#   'last_digit': 8,
#   'weekday_nth': 'Wed2',
#   'is_strong_zorome': 0,
#   'is_zorome': 0,
#   'is_month_start': 0,
#   'is_month_end': 0,
#   'is_weekend': 0,
#   'is_holiday': 0,
#   'hall_anniversary': 0,
#   'is_x_day': 0,
#   'week_of_month': 2,
#   'is_any_event': 0
# }
```

#### add_date_info_columns() → bool
```python
success = calc.add_date_info_columns()
# Adds missing columns to daily_hall_summary
# Types:
#   - TEXT: day_of_week, weekday_nth
#   - INTEGER: last_digit, week_of_month
#   - BOOL: is_*
```

#### update_date_info(date_str: str) → bool
```python
success = calc.update_date_info('20260408')
# Updates daily_hall_summary with date flags
# INSERT if date not exists, UPDATE if exists
```

#### _get_nth_weekday(date_obj: datetime) → str
```python
from datetime import datetime
date_obj = datetime.strptime('20260408', '%Y%m%d')
result = calc._get_nth_weekday(date_obj)
# Returns: 'Wed2'
# Format: {weekday_abbr}{nth}
#   weekday_abbr: Mon, Tue, Wed, Thu, Fri, Sat, Sun
#   nth: 1-5 (calculated as (day-1)//7 + 1)
```

### Private Methods (Utilities)
```python
calc._get_day_of_week(date_obj) → str        # '月'～'日'
calc._get_last_digit(day: int) → int         # 0-9
calc._get_week_of_month(day: int) → int      # 1-5
calc._check_strong_zorome(month, day) → bool # month == day (1-9)
calc._check_zorome(day) → bool               # day in [11, 22]
calc._check_month_start(day) → bool          # day == 1
calc._check_month_end(date_obj) → bool
calc._check_weekend(date_obj) → bool         # weekday >= 5
calc._check_holiday(date_obj) → bool         # jpholiday or fixed holidays
calc._check_x_day(day) → bool                # day in event_digits
calc._check_hall_anniversary(month, day) → bool
```

---

## JSONProcessor

**Module**: json_processor.py

### Constructor
```python
from json_processor import JSONProcessor

processor = JSONProcessor(
    hall_name: str,
    project_root: str = None  # Default: {parent_of_script}/..
)
```

### Public Methods

#### get_json_files() → List[str]
```python
json_files = processor.get_json_files()
# Returns: ['data/hall_name/20260101_hall_name_data.json', ...]
# Auto-detects correct hall folder if needed
```

#### load_json_file(filepath: str) → dict
```python
json_data = processor.load_json_file('data/hall_name/20260101_hall_name_data.json')
# Returns: {'date': '20260101', 'all_data': [...]}
```

#### process_all_machine_data_for_day(date: str, machine_records: List[dict], avg_games: int = None) → List[dict]
```python
machine_data_list = processor.process_all_machine_data_for_day(
    '20260101',
    json_data['all_data'],
    avg_games=250  # Optional
)
# Returns: [
#   {
#     'date': '20260101',
#     'machine_name': 'マイジャグラーV',
#     'machine_number': 1001,
#     'last_digit': '1',
#     'is_zorome': 1,
#     'machine_rank_in_type': 3,
#     'games_normalized': 280,
#     'games_deviation': 30,
#     'diff_coins_normalized': 450,
#     'bb_count': 5,
#     'rb_count': 3,
#     'total_probability_fraction': '1/180.5',
#     'total_probability_decimal': 0.00554,
#     ...
#   },
#   ...
# ]
```

#### process_machine_data(date: str, machine_record: dict, avg_games: int = None) → dict
```python
# Single record processing (called internally)
```

#### get_daily_machine_summary() → dict
```python
summary = processor.get_daily_machine_summary()
# Returns: {'マイジャグラーV': 5, 'ハナハナ': 3, ...}
```

#### get_machine_name_list() → List[str]
```python
names = processor.get_machine_name_list()
# Returns: ['マイジャグラーV', 'ハナハナ', ...]
# Sorted by count (descending)
```

---

## DataInserter

**Module**: data_inserter.py

### Constructor
```python
from data_inserter import DataInserter

inserter = DataInserter(db_path: str)
```

### Public Methods

#### insert_machine_detailed_results(machine_data_list: List[dict]) → None
```python
inserter.insert_machine_detailed_results(machine_data_list)
# Batch INSERT into machine_detailed_results
# Auto-creates machine_master records if needed
```

#### calculate_and_insert_daily_summary(date: str) → int | None
```python
avg_games = inserter.calculate_and_insert_daily_summary('20260101')
# Returns: avg_games (for use in games_deviation calc)
# Inserts into daily_hall_summary (base stats)
# Calculates win_rate automatically
```

#### update_games_deviation(date: str, avg_games: int) → None
```python
inserter.update_games_deviation('20260101', 250)
# Updates machine_detailed_results.games_deviation
```

#### get_or_create_machine_master(machine_name: str) → dict
```python
master = inserter.get_or_create_machine_master('マイジャグラーV')
# Returns: {
#   'machine_name_normalized': 'マイジャグラーV',
#   'jug_flag': 1,
#   'hana_flag': 0,
#   'oki_flag': 0,
#   ...
# }
# Auto-creates if not exists (with simple flag detection)
```

---

## SummaryCalculator

**Module**: summary_calculator.py

### Constructor
```python
from summary_calculator import SummaryCalculator

summary_calc = SummaryCalculator(db_path: str)
```

### Public Methods

#### update_machine_type_summary(date: str) → None
```python
summary_calc.update_machine_type_summary('20260101')
# Updates daily_machine_type_summary
# Groups by machine_name
```

#### update_last_digit_summary_by_type(date: str) → None
```python
summary_calc.update_last_digit_summary_by_type('20260101')
# Updates last_digit_summary_{all,jug,hana,oki,other}
# Groups by last_digit (0-9 + zorome)
```

#### update_position_summary_by_type(date: str) → None
```python
summary_calc.update_position_summary_by_type('20260101')
# Updates daily_position_summary_{all,jug,hana,oki,other}
# Groups by front_position
```

#### update_island_summary(date: str) → None
```python
summary_calc.update_island_summary('20260101')
# Updates daily_island_summary
# Groups by island_name
```

---

## RankCalculator

**Module**: rank_calculator.py

### Constructor
```python
from rank_calculator import RankCalculator

rank_calc = RankCalculator(db_path: str)
```

### Public Methods

#### calculate_ranks_for_date(date: str) → None
```python
rank_calc.calculate_ranks_for_date('20260101')
# Calculates {prefix}_diff, {prefix}_games, {prefix}_efficiency
# For all summary tables
```

#### calculate_history_for_date(date: str) → None
```python
rank_calc.calculate_history_for_date('20260101')
# Calculates moving averages for 7,14,21,28,35 days
# avg_diff_*d, avg_games_*d, avg_efficiency_*d, avg_rank_diff_*d
```

---

## Database Schema

### weekday_nth Format
```
Type: TEXT (fixed 4 chars)
Format: {weekday_abbr}{nth}
  weekday_abbr: Mon, Tue, Wed, Thu, Fri, Sat, Sun
  nth: 1-5 (calculated as (day-1)//7 + 1)

Examples:
  2026-04-01 (Wed, day 1) → Wed1
  2026-04-08 (Wed, day 8) → Wed2
  2026-04-15 (Wed, day 15) → Wed3
  2026-04-30 (Thu, day 30) → Thu5
```

### Date Flags (daily_hall_summary)
```
day_of_week       TEXT   # '月'～'日'
last_digit        INT    # 0-9
weekday_nth       TEXT   # 'Mon1'～'Sun5'
is_strong_zorome  INT    # month == day (1-9月)
is_zorome         INT    # day in [11, 22]
is_month_start    INT    # day == 1
is_month_end      INT    # last day of month
is_weekend        INT    # weekday >= 5 (Sat, Sun)
is_holiday        INT    # jpholiday or fixed holidays
hall_anniversary  INT    # configで指定された周年日
is_x_day          INT    # configで指定されたevent_digits
week_of_month     INT    # 1-5 ((day-1)//7 + 1)
is_any_event      INT    # is_holiday OR is_weekend OR is_x_day
```

### Rank + History Template (22cols)
```
{prefix}_diff                INTEGER  # Rank by avg_diff_coins (ascending)
{prefix}_games               INTEGER  # Rank by avg_games (ascending)
{prefix}_efficiency          INTEGER  # Rank by efficiency (ascending)
avg_diff_7d, 14d, 21d, 28d, 35d    REAL  # Moving average
avg_games_7d, 14d, 21d, 28d, 35d   REAL  # Moving average
avg_efficiency_7d, 14d, 21d, 28d, 35d REAL
avg_rank_diff_7d, 14d, 21d, 28d, 35d REAL
```

---

## Examples

### Example 1: Full Data Processing Pipeline

```python
from main_processor import DataImporter
from json_processor import JSONProcessor

json_filepath = 'data/マルハンメガシティ柏/20260101_マルハンメガシティ柏_data.json'

processor = JSONProcessor('マルハンメガシティ柏')
importer = DataImporter('/path/to/db', processor)

# Process single JSON
date = importer.import_single_json(json_filepath)
print(f"Processed: {date}")
```

### Example 2: Incremental Update

```python
from incremental_db_updater import IncrementalDBUpdater

updater = IncrementalDBUpdater('マルハンメガシティ柏')
result = updater.run(verbose=True)

print(f"Status: {result['status']}")
print(f"Processed: {result['processed']} dates")
print(f"Failed: {result['failed']} dates")
```

### Example 3: Date Flag Analysis

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('db/マルハンメガシティ柏.db')

# 曜日別の平均差枚
weekday_analysis = pd.read_sql("""
    SELECT 
        substr(weekday_nth, 1, 3) AS weekday,
        COUNT(*) AS count,
        ROUND(AVG(avg_diff_coins), 1) AS avg_diff
    FROM daily_hall_summary
    WHERE weekday_nth IS NOT NULL
    GROUP BY substr(weekday_nth, 1, 3)
    ORDER BY weekday
""", conn)

print(weekday_analysis)

# 第N週別の平均差枚
nth_week_analysis = pd.read_sql("""
    SELECT 
        CAST(substr(weekday_nth, 4, 1) AS INTEGER) AS nth,
        COUNT(*) AS count,
        ROUND(AVG(avg_diff_coins), 1) AS avg_diff
    FROM daily_hall_summary
    WHERE weekday_nth IS NOT NULL
    GROUP BY substr(weekday_nth, 4, 1)
    ORDER BY nth
""", conn)

print(nth_week_analysis)

conn.close()
```

### Example 4: weekday_nth Filter

```python
import pandas as pd
import sqlite3

conn = sqlite3.connect('db/マルハンメガシティ柏.db')
df = pd.read_sql("SELECT * FROM daily_hall_summary", conn)

# 第2水曜日のみ
wed2 = df[df['weekday_nth'] == 'Wed2']
print(f"Wed2 平均差枚: {wed2['avg_diff_coins'].mean():.1f}")

# 全ての水曜日
all_wed = df[df['weekday_nth'].str.startswith('Wed')]
print(f"All Wed 平均差枚: {all_wed['avg_diff_coins'].mean():.1f}")

# 第2週全体
week2 = df[df['weekday_nth'].str.endswith('2')]
print(f"Week2 平均差枚: {week2['avg_diff_coins'].mean():.1f}")

conn.close()
```

### Example 5: Cross-tabulation Analysis

```python
import pandas as pd
import sqlite3

conn = sqlite3.connect('db/マルハンメガシティ柏.db')
df = pd.read_sql("SELECT * FROM daily_hall_summary", conn)

# 曜日 × 第N週
pivot = pd.pivot_table(
    df,
    values='avg_diff_coins',
    index=df['weekday_nth'].str[:3],
    columns=df['weekday_nth'].str[3],
    aggfunc='mean'
)

print(pivot)
#      1      2      3      4      5
# Fri  120.5  140.3  110.8  150.2  80.5
# Mon  100.2  130.5  95.3   120.8  70.2
# Sat  110.8  145.2  105.3  160.5  75.8
# Sun  95.3   125.8  90.2   115.3  65.5
# ...

conn.close()
```

---

## Common Workflows

### Workflow: Add New Machine Type Flag

1. Edit: table_config.py
2. Edit: db_setup.py  
3. Edit: data_inserter.py::get_or_create_machine_master()
4. Update: summary_calculator.py (if needed)
5. Test: Run incremental_db_updater.py
6. Verify: Check new summary_*_newtype tables

### Workflow: Debug weekday_nth Values

```bash
# Check format
sqlite3 db/マルハンメガシティ柏.db \
  "SELECT DISTINCT weekday_nth FROM daily_hall_summary ORDER BY weekday_nth;"

# Check specific date
sqlite3 db/マルハンメガシティ柏.db \
  "SELECT date, day_of_week, weekday_nth FROM daily_hall_summary WHERE date='20260408';"

# Count by weekday
sqlite3 db/マルハンメガシティ柏.db \
  "SELECT substr(weekday_nth,1,3) AS day, COUNT(*) FROM daily_hall_summary GROUP BY substr(weekday_nth,1,3);"
```

---

関連記事：
- [[PHASE2_完全仕様書]]
- [[weekday_nth実装説明]]
- [[PHASE2_保守マニュアル]]

**Last Updated**: 2026-04-10  
**Version**: 2.0 (weekday_nth)
