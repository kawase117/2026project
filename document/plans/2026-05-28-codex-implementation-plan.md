# Codex 実装プラン — 2026-05-28（ML分析タスク）

## 概要

機械学習・統計分析の強化タスク。3つのスクリプトを独立して実装する。

**プロジェクトルート**: `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project`

---

## Task 1: 台末尾ゾロ目 + 翌日予測統合ワークフロー

**優先度**: 🔴 最高

### 目的

翌日予測（末尾ランキング）に以下を付加した統合出力を生成する：
1. 各末尾の予測スコアと確信度（相対的スコア）
2. 予測で上位の末尾に該当する「台末尾ゾロ目」の機種名・台番号リスト

### 台末尾ゾロ目の定義

台番号の末2桁が同じ数字（11, 22, 33, 44, 55, 66, 77, 88, 99, 100, 110, 200, 211, 222...）
```python
def is_zorome_machine(machine_number: int) -> bool:
    tail2 = abs(int(machine_number)) % 100
    return (tail2 // 10) == (tail2 % 10) and tail2 != 0
```

⚠️ `machine_detailed_results.is_zorome` とは**別物**。
`is_zorome` は「月日ゾロ目（日付の日部分と台末尾が一致）」。
台末尾ゾロ目は「台番号の末2桁が同じ数字」であり、上記の関数で別途計算する。

### 実装ファイル

`ml/last_digit/nextday_zorome_report.py`

### 入力

- `--db-path`: SQLiteDBパス（例: `db/マルハンメガシティ2000-蒲田7.db`）
- `--output-prefix`: 出力先プレフィックス（デフォルト: `db/experiments/nextday_zorome_report`）
- `--top-n`: 表示する末尾の上位件数（デフォルト: 3）

### 処理フロー

```
1. 最新日のmachine_detailed_resultsから全レコードを取得
2. 台末尾ゾロ目の台番号・機種名リストを末尾（0-9）ごとに構築
   - 例: 末尾1 → [(2011, "モンキーターンV"), (2111, "某機種"), ...]
3. 既存の翌日予測スコアを計算
   （tail_ltr_split_rule_nextday_gpu の _predict_for_date を流用）
4. 各末尾の combined_rank と combined_score を計算
5. combined_score を min-max 正規化 → 確信度（0-100%）として表示
   combined_score はランクの平均（小さいほど良い）:
     確信度 = (max_score - score) / (max_score - min_score) * 100
     → Rank 1 が最も高い確信度になる

出力形式（テキスト）:
  翌日予測 (蒲田七, 2026-05-29 水曜日)
  ─────────────────────────────────────────
  Rank 1: 末尾 7  確信度 82%
    台末尾ゾロ目:
      2077 スマスロ某
      2177 A-SLOT+ 某
  
  Rank 2: 末尾 1  確信度 61%
    台末尾ゾロ目:
      2011 モンキーターンV
      2111 某機種
  
  Rank 3: 末尾 5  確信度 53%
    台末尾ゾロ目:
      2055 マジアカード
      2155 ディスクアップ ULTRAREMIX
```

### 出力ファイル

- `{output_prefix}_{日付}.json`
- `{output_prefix}_{日付}.txt`（人間が読む形式）

### 注意事項

- 台末尾ゾロ目リストは「最新日」（= DBの最新 date）から取得する
- `machine_detailed_results` に `day_of_week` カラムは**存在しない**
  → 日付情報が必要な場合は `daily_hall_summary` とJOINする

---

## Task 2: 日曜日「機種一」多台数戦略の統計検証

**優先度**: 🔴 高

### 目的

日曜日「機種一（機種一台に高設定を一台入れる）」戦略において、
台数別（少数機種 vs 多台数機種）の期待差枚・突出台数を集計し、
少ない台数の機種を狙うことが合理的か統計的に確認する。

### 背景と仮説

- 仮説A（少数機種有利）：3台機種 → 確率1/3で高設定 → 安牌
- 仮説B（多台数機種は高設定複数あり）：30台機種でも設定6を複数台入れる場合がある
  → 突出した期待差枚や回転数から高設定を探す
- 既知の事実：**1台機種は設定が入らない**（実績確認済み → 除外する）

### 実装ファイル

`ml/experiments/sunday_machine_analysis.py`

### 入力

- `--db-path`: SQLiteDBパス
- `--output-dir`: 出力ディレクトリ（デフォルト: `db/experiments/sunday_machine_analysis`）
- `--min-records`: 集計に必要な最小レコード数（デフォルト: 20）

### 処理内容

```python
# 1. 日曜日のデータ取得（daily_hall_summaryとJOINが必須）
df_sunday = pd.read_sql("""
    SELECT m.machine_name, m.machine_number, m.diff_coins_normalized,
           m.games_normalized, m.last_digit
    FROM machine_detailed_results m
    JOIN daily_hall_summary d ON m.date = d.date
    WHERE d.day_of_week = '日'
""", conn)

# 2. 機種別集計
machine_stats = df_sunday.groupby('machine_name').agg(
    num_machines=('machine_number', 'nunique'),
    avg_diff=('diff_coins_normalized', 'mean'),
    std_diff=('diff_coins_normalized', 'std'),
    total_records=('diff_coins_normalized', 'count'),
    win_rate=('diff_coins_normalized', lambda x: (x > 0).mean()),
)
# min-records フィルタを適用

# 3. 突出台の計算（高設定候補率）
# 各機種内で「avg_diff + 1σ を超えたレコードの割合」

# 4. 台数カテゴリに分類（num_machinesで）
# 1台: 除外（設定なし既知）
# 2-5台: 少数（安牌候補）
# 6-15台: 中程度
# 16-50台: 多台数
# 50台超: 超多台数

# 5. カテゴリ別の平均値と95%信頼区間（ブートストラップ可）

# 6. 相関分析
# num_machines vs avg_diff の Pearson + Spearman
```

### 出力

```
=== 日曜日 機種別台数と期待差枚の関係 ===

台数カテゴリ別集計:
カテゴリ    機種数  avg_diff  win_rate  突出台率（高設定候補率）
1台         XX     除外      ---       ---
2-5台       XX     +XXX      XX.X%     XX.X%
6-15台      XX     +XXX      XX.X%     XX.X%
16-50台     XX     +XXX      XX.X%     XX.X%
50台超      XX     +XXX      XX.X%     XX.X%

台数との相関:
  Pearson: XXX (p=XXX)
  Spearman: XXX (p=XXX)
  → 「多台数ほど期待差枚が低い」傾向があるか確認

上位機種（avg_diff 高い順, min-recordsフィルタ済み）:
  機種名, 台数, avg_diff, win_rate, 突出台率
  ...（上位15件）
```

- 出力: `{output_dir}/sunday_machine_analysis.csv` および `.json`

---

## Task 3: 「兆候機種」相関分析（モンターン・北斗）

**優先度**: 🔴 高

### 目的

「モンキーターンV または スマスロ北斗の拳が兆候を示す日 → 他の同じ末尾の機種も強いか」
を全日で検証する。水曜日に限定せず全曜日で分析し、曜日別にも分解する。

### 実装ファイル

`ml/experiments/signal_machine_correlation_analysis.py`

### 入力

- `--db-path`: SQLiteDBパス
- `--output-dir`: 出力ディレクトリ
- `--diff-threshold`: 差枚による信号閾値（デフォルト: `200`）
- `--rb-threshold`: RB確率による信号閾値（デフォルト: `0.003333`、= 1/300）

### 信号機種名の取得方法（⚠️ 重要）

**ハードコードしないこと。** DBから正確な機種名を取得して使用する。

```python
# DBから信号機種名を動的取得
cursor = conn.cursor()

# スマスロ北斗の拳（「北斗の拳 転生の章2」は別機種のため除外）
# 「スマスロ北斗」で前方一致検索することで転生の章2を除外する
cursor.execute(
    "SELECT DISTINCT machine_name FROM machine_detailed_results "
    "WHERE machine_name LIKE 'スマスロ北斗%'"
)
hokuto_names = [r[0] for r in cursor.fetchall()]  # → ['スマスロ北斗の拳']

# モンキーターン
cursor.execute(
    "SELECT DISTINCT machine_name FROM machine_detailed_results "
    "WHERE machine_name LIKE 'モンキーターン%'"
)
monkey_names = [r[0] for r in cursor.fetchall()]  # → ['モンキーターンV']

SIGNAL_MACHINES = hokuto_names + monkey_names
# 必ず実行時にログ出力: f"信号機種: {SIGNAL_MACHINES}"
```

⚠️ `LIKE '%北斗%'` で検索すると「北斗の拳 転生の章2」も含まれてしまう。
必ず `LIKE 'スマスロ北斗%'` で前方一致を使用すること。

### 信号条件（2条件の OR）

```python
# 各信号機種について、以下の2つの基準で「兆候あり」と判定する
#
# 条件A: 差枚による信号
#   その日の信号機種の avg(diff_coins_normalized) > diff_threshold
#
# 条件B: RB確率による信号
#   その日の信号機種の avg(rb_probability_decimal) < rb_threshold (= 1/300 = 0.003333)
#
# 信号フラグ = 条件A OR 条件B
# ※ 条件A・Bそれぞれ単独でも集計して結果を出力すること
```

### 処理内容

```python
# 1. 全日について信号機種の日別集計
signal_daily = df[df['machine_name'].isin(SIGNAL_MACHINES)].groupby('date').agg(
    avg_diff=('diff_coins_normalized', 'mean'),
    avg_rb_prob=('rb_probability_decimal', 'mean'),  # RB確率
)

# 2. 信号フラグを算出（2条件OR）
signal_daily['signal_diff'] = signal_daily['avg_diff'] > diff_threshold
signal_daily['signal_rb'] = signal_daily['avg_rb_prob'] < rb_threshold
signal_daily['signal'] = signal_daily['signal_diff'] | signal_daily['signal_rb']

# 信号のあった日の「信号機種の last_digit」を取得
# → 「その日の信号機種が属している末尾」を特定

# 3. 信号あり日の同末尾他機種の avg_diff を集計
# 比較: 信号あり日 vs 信号なし日（同末尾・他機種）

# 4. 統計検定（Mann-Whitney U 検定）
from scipy.stats import mannwhitneyu

# 5. 曜日別の分解（daily_hall_summaryとJOIN）

# 6. フェイク末尾の検証
# 信号末尾 vs 非信号末尾の avg_diff を比較
# 差がなければ「フェイクの可能性あり」
```

### 出力

```
=== 兆候機種（モンキーターンV・スマスロ北斗の拳）の相関分析 ===

対象機種: ['モンキーターンV', 'スマスロ北斗の拳']

全日集計:
  信号あり日数（差枚）: XX  信号あり日数（RB確率）: XX  信号あり日数（合計OR）: XX
  信号なし日数: XX
  
  [差枚信号のみ]
  信号あり → 同末尾他機種 avg_diff: +XXX ± XXX
  信号なし → 同末尾他機種 avg_diff: +XXX ± XXX
  差: +XXX (p=XXX, Mann-Whitney U)
  
  [RB確率信号のみ]
  信号あり → 同末尾他機種 avg_diff: +XXX ± XXX
  差: +XXX (p=XXX, Mann-Whitney U)
  
  [両信号OR]
  差: +XXX (p=XXX, Mann-Whitney U)

曜日別（OR信号）:
  水曜日: あり(N=XX) avg=+XXX vs なし avg=+XXX  p=XXX
  日曜日: あり(N=XX) avg=+XXX vs なし avg=+XXX  p=XXX
  （全曜日を表示）

フェイク末尾の確認:
  信号末尾 avg_diff: +XXX
  非信号末尾 avg_diff: +XXX
  → 信号末尾が有意に高ければ「フェイクではない」証拠
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
import pandas as pd
import numpy as np
from scipy.stats import mannwhitneyu

# ロギング設定
from ml.last_digit.utils import configure_logging

# DB接続
conn = sqlite3.connect(str(db_path), check_same_thread=False)
```

### DBスキーマの重要な注意事項

| テーブル | last_digit の型 | day_of_week | 注意 |
|---------|----------------|-------------|------|
| `machine_detailed_results` | TEXT ("0"〜"9") | カラムなし | JOINが必要 |
| `daily_hall_summary` | INTEGER (0〜9) | あり ('月'〜'日') | |

- `machine_detailed_results` に `day_of_week` は**存在しない**
  → `daily_hall_summary` と `date` でJOINする
- `is_zorome` は「月日ゾロ目」（DBの定義）。台末尾ゾロ目とは別物。
- `rb_probability_decimal` カラムは `machine_detailed_results` に存在する

### 実行コマンド例

```bash
# プロジェクトルートから実行
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project

# Task 1
venv\Scripts\python.exe -m ml.last_digit.nextday_zorome_report \
  --db-path "db/マルハンメガシティ2000-蒲田7.db" --top-n 3

# Task 2
venv\Scripts\python.exe -m ml.experiments.sunday_machine_analysis \
  --db-path "db/マルハンメガシティ2000-蒲田7.db" \
  --output-dir "db/experiments/sunday_machine_analysis"

# Task 3
venv\Scripts\python.exe -m ml.experiments.signal_machine_correlation_analysis \
  --db-path "db/マルハンメガシティ2000-蒲田7.db" \
  --output-dir "db/experiments/signal_machine_correlation"
```

---

*プラン作成日: 2026-05-28*
*担当: kawase117*
