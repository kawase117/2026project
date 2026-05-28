# Codex 実装プラン — 2026-05-28（DB・Dashboard拡張タスク）

## 概要

DB集計テーブルの追加と Dashboard の新規ページ追加。
機械学習とは独立したタスク。2つのタスクを独立して実装する。

**プロジェクトルート**: `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project`

---

## Task 4: 2F3F/NA セグメント別特徴量テーブル（蒲田七専用）

**優先度**: 🟠 中高

### 目的

蒲田七の機種を 2F/3F/NA のフロア別セグメントに分類し、
セグメント × 末尾 × 機種別の集計テーブルを作成する。
将来的に機械学習の特徴エンジニアリングへ活用する。

### 前提

- 蒲田七のみ 2F/3F/NA の情報が存在する（他のDBには実装しない）
- `machine_layout` テーブルまたは `machine_master` テーブルにフロア情報が存在する想定

### 実装ファイル

`database/segment_feature_aggregator.py`

### 事前確認が必要な項目（実装前に必ず確認）

```sql
-- machine_layoutの構造確認
PRAGMA table_info(machine_layout);
SELECT * FROM machine_layout LIMIT 5;

-- machine_masterの構造確認
PRAGMA table_info(machine_master);
SELECT * FROM machine_master LIMIT 5;
```
→ フロア（2F/3F/NA）情報がどのカラムに格納されているか確認してから実装すること。

### 処理内容

```python
# 1. machine_layout または machine_master から 2F/3F/NA の情報を取得
# （実際のカラム名は事前確認で決定）

# 2. セグメント別集計テーブルを作成
CREATE TABLE IF NOT EXISTS segment_last_digit_summary AS
SELECT 
    segment,         -- '2F' / '3F' / 'NA'
    last_digit,
    machine_name,
    COUNT(*) as records,
    AVG(diff_coins_normalized) as avg_diff,
    AVG(games_normalized) as avg_games,
    SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
    COUNT(DISTINCT machine_number) as num_machines,
    COUNT(DISTINCT date) as active_days
FROM machine_detailed_results m
JOIN (SELECT machine_name, segment FROM machine_segments_view) s 
  ON m.machine_name = s.machine_name
GROUP BY segment, last_digit, machine_name;

# 3. 全セグメント統合バージョンも作成（結合計算用）
CREATE TABLE IF NOT EXISTS segment_last_digit_summary_all AS
SELECT 
    last_digit,
    machine_name,
    COUNT(*) as records,
    AVG(diff_coins_normalized) as avg_diff,
    AVG(games_normalized) as avg_games,
    SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
    COUNT(DISTINCT machine_number) as num_machines,
    COUNT(DISTINCT date) as active_days
FROM machine_detailed_results
GROUP BY last_digit, machine_name;
```

### 注意

- このスクリプトは **蒲田七DBのみ** に作成する
- 他のDBで誤って実行しないようガード処理を追加：
  ```python
  db_name = Path(db_path).name
  if '蒲田7' not in db_name and '蒲田七' not in db_name:
      print(f"このスクリプトは蒲田七DB専用です。対象外: {db_name}")
      sys.exit(0)
  ```

### 実行コマンド

```bash
venv\Scripts\python.exe -m database.segment_feature_aggregator \
  --db-path "db/マルハンメガシティ2000-蒲田7.db"
```

---

## Task 5: 機種別月別集計テーブル（Dashboard用）

**優先度**: 🟡 中

### 目的

機種別の月別パフォーマンス（期待差枚・勝率・回転数）を集計し、
Dashboard での月別トレンド可視化のデータソースを提供する。

### 実装ファイル（2つ）

1. `database/machine_type_monthly_aggregator.py` — テーブル生成スクリプト
2. `dashboard/pages/page_17_machine_monthly_trend.py` — Dashboard ページ

### DBテーブル作成

```python
# database/machine_type_monthly_aggregator.py

CREATE TABLE IF NOT EXISTS machine_type_monthly_summary AS
SELECT 
    substr(date, 1, 6) as year_month,  -- 'YYYYMM'形式（dateはYYYYMMDD）
    machine_name,
    COUNT(DISTINCT date) as active_days,
    COUNT(DISTINCT machine_number) as num_machines,
    SUM(games_normalized) as total_games,
    AVG(diff_coins_normalized) as avg_diff,
    SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as win_rate,
    MIN(diff_coins_normalized) as min_diff,
    MAX(diff_coins_normalized) as max_diff,
    AVG(games_normalized) as avg_games
FROM machine_detailed_results
GROUP BY year_month, machine_name
ORDER BY year_month, machine_name;
```

### Dashboard ページ仕様

`dashboard/pages/page_17_machine_monthly_trend.py` を新規作成：

```python
# インポートの規約
from ..utils.filters import filter_by_date_range
from ..utils.charts import create_line_chart, create_bar_chart
from ..utils.data_loader import load_machine_type_monthly_summary  # 新規追加が必要

# UI要素
# 1. ドロップダウン: 機種名の複数選択（multiselect）
# 2. 折れ線グラフ（Plotly）: 月別 avg_diff の推移（選択した機種を重ねて表示）
# 3. 棒グラフ: 月別 win_rate の推移
# 4. min_games フィルタ: st.session_state.min_games で total_games をフィルタ
# 5. 空データでも例外を出さない（charts.py の規約に従う）
```

### 注意事項

- `data_loader.py` に `load_machine_type_monthly_summary(db_path)` 関数を追加すること
- `@st.cache_data(ttl=3600)` でキャッシュする
- ページ番号は `page_17` に固定（既存の `config/constants.py` に追記が必要）

### 実行コマンド

```bash
# テーブル生成
venv\Scripts\python.exe -m database.machine_type_monthly_aggregator \
  --db-path "db/マルハンメガシティ2000-蒲田7.db"

# Dashboard 起動（ページ確認）
streamlit run main_app.py
```

---

## 共通実装要件

### コーディング規約

```python
from __future__ import annotations  # 必須（全ファイル先頭）
import argparse
import logging
import sqlite3
from pathlib import Path

# DB接続
conn = sqlite3.connect(str(db_path), check_same_thread=False)
```

### DBスキーマの重要な注意事項

| テーブル | last_digit の型 | day_of_week | 注意 |
|---------|----------------|-------------|------|
| `machine_detailed_results` | TEXT ("0"〜"9") | カラムなし | |
| `daily_hall_summary` | INTEGER (0〜9) | あり ('月'〜'日') | |

- `date` カラムは YYYYMMDD 形式の TEXT
- `substr(date, 1, 6)` で YYYYMM を取得可能

---

*プラン作成日: 2026-05-28*
*担当: kawase117*
