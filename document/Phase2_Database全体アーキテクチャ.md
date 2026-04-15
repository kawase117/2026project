---
source: raw/notes/PHASE_2_DATABASE_ARCHITECTURE.md
compiled: 2026-04-06
tags: [pachinko, database, phase-2, sqlite, architecture]
---

# Phase 2 (Database) 全体アーキテクチャドキュメント

**対象ファイル**: `main_processor.py`, `json_processor.py`, `data_inserter.py`, 他ユーティリティ
**作成日**: 2026-04-06
**目的**: Phase 2 の実装全体を説明

---

## 📋 概要

Phase 2（Database）は、[[Phase1_Scraper実装ドキュメント|Phase 1]] で出力された **JSON ファイルを読み込んで、SQLite データベースに投入し、多層的な集計・計算を行うフェーズ**です。

**入力**: `data/{hall_name}/*.json` （Phase 1 の出力）
**出力**: `db/{hall_name}.db` （SQLite データベース）

---

## 🎯 Phase 2 の目標

1. ✅ JSON 形式の生データを読み込む
2. ✅ 機種名・フラグの正規化・自動判定
3. ✅ SQLite テーブルへの効率的な投入
4. ✅ 多層的な集計（ホール別・機種別・末尾別・位置別・島別）
5. ✅ ランク・履歴情報の自動計算
6. ✅ 日付情報フラグの付加
7. ✅ 新規日付のみを追加する増分更新対応

---

## 🔄 データフロー全体

```
【入力】
data/{hall_name}/{date}_{hall_name}_data.json
（Phase 1 で生成された HTML テーブル抽出データ）

【Phase 2-1: JSON 処理】
json_processor.py
├─ JSON読込・正規化
├─ 機種名の標準化
├─ 機種フラグの自動判定（jug, hana, oki, bt）
├─ 末尾・ゾロ目フラグ計算
└─ データ型変換（文字列 → 数値）

【Phase 2-2: DB投入】
data_inserter.py
├─ machine_detailed_results に個別台データ投入
├─ machine_layout に台配置情報投入
└─ 日付フラグ情報付加（date_info_calculator.py）

【Phase 2-3: 集計・ランク計算】
summary_calculator.py
├─ 日別ホール全体集計（daily_hall_summary）
├─ 機種別日次集計（daily_machine_type_summary）
├─ 末尾別集計（last_digit_summary_*）
├─ 位置別集計（daily_position_summary_*）
└─ 島別集計（daily_island_summary）

rank_calculator.py
├─ 日別順位計算
├─ 移動平均計算（7～35日）
└─ 機種フラグベースの統計

【出力】
db/{hall_name}.db
├─ machine_detailed_results（個別台実績）
├─ machine_layout（台配置マスター）
├─ daily_hall_summary（ホール全体集計）
├─ daily_machine_type_summary（機種別集計）
├─ last_digit_summary_*（末尾別集計）
├─ daily_position_summary_*（位置別集計）
├─ daily_island_summary（島別集計）
├─ event_calendar（イベント情報）
└─ machine_master（機種マスター）
```

---

## 📊 主要な処理モジュール

### 1. JSON処理（json_processor.py）

- JSON ファイルの読み込み
- 機種名の正規化（表記ゆれ統一）
- 機種フラグの自動判定（jug_flag, hana_flag, oki_flag, bt_flag）
- 数値型への変換（文字列 → int/float）

### 2. DB投入（data_inserter.py）

- `machine_detailed_results` テーブルへの投入
- `machine_layout` テーブルへの台配置情報追加
- トランザクション管理（エラー時ロールバック）

### 3. 集計計算（summary_calculator.py）

- ホール別・機種別の基本統計（合計、平均、最大、最小）
- 勝率・効率・高収益台率の計算

### 4. ランク・履歴計算（rank_calculator.py）

- 日別相対順位（1位～n位）
- 移動平均（7日、14日、21日、28日、35日）

### 5. 増分更新（incremental_db_updater.py）

- 既存 DB から最終日付を取得
- JSON ファイルから新規日付のみ抽出
- 新規日付データのみを処理・投入（パフォーマンス向上）

---

## 🗄️ データベーススキーマ

### machine_detailed_results テーブル

個別台の日別実績データ。各台、各日付ごとに 1 行。

| カラム | 型 | 説明 |
|--------|-----|------|
| date | TEXT | 日付（YYYYMMDD） |
| machine_name | TEXT | 機種名（正規化済み） |
| machine_number | INTEGER | 台番号 |
| last_digit | TEXT | 台番号末尾 |
| is_zorome | BOOLEAN | ゾロ目台フラグ |
| games_normalized | INTEGER | ゲーム数 |
| diff_coins_normalized | INTEGER | 差枚 |
| bb_count | INTEGER | BB回数 |
| rb_count | INTEGER | RB回数 |
| total_probability_decimal | REAL | 合成確率 |
| bb_probability_decimal | REAL | BB確率 |
| rb_probability_decimal | REAL | RB確率 |

---

## 💻 使用方法

### 単一ホール処理

```python
python main_processor.py --hall "マルハンメガシティ柏"
```

### 複数ホール一括処理

```python
python batch_incremental_updater.py
```

### 既存 DB のみ削除・リセット

```python
python main_processor.py --reset
```

---

## ✅ Phase 2 での実装完了項目

| 機能 | ファイル | ステータス |
|------|---------|-----------|
| JSON 処理・正規化 | json_processor.py | ✅ 完成 |
| DB 投入・トランザクション | data_inserter.py | ✅ 完成 |
| 基本集計 | summary_calculator.py | ✅ 完成 |
| ランク・履歴計算 | rank_calculator.py | ✅ 完成 |
| 増分更新（単一） | incremental_db_updater.py | ✅ 完成 |
| 増分更新（一括） | batch_incremental_updater.py | ✅ 完成 |
| 日付情報フラグ付加 | date_info_calculator.py | ✅ 完成 |

---

## 🔗 関連文書

- [[Phase1_Scraper実装ドキュメント]] - Phase 1 スクレイパー仕様
- [[Pachinko分析DBスキーマ説明]] - テーブル詳細仕様
- [[未実装タスクリスト]] - 優先タスク一覧

