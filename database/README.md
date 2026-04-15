# database/ - Phase 2 データベース処理

Phase 1（scraper）が出力したJSONをSQLiteに投入し、集計・ランク計算を行うモジュール群。

## データフロー

```
data/{hall_name}/*.json   ← Phase 1 の出力
        ↓
  main_processor.py       ← オーケストレーター
        ↓
  data_inserter.py        ← machine_detailed_results に投入
  date_info_calculator.py ← 日付フラグ付加
        ↓
  summary_calculator.py   ← daily_hall_summary など集計
  rank_calculator.py      ← 日別順位・移動平均
        ↓
db/{hall_name}.db         ← 出力先
```

## 各モジュールの役割

| ファイル | 役割 |
|---------|------|
| `main_processor.py` | 全処理のオーケストレーター。ホール指定で一括実行 |
| `data_inserter.py` | JSONデータをSQLiteに投入。重複チェック付き |
| `date_info_calculator.py` | 曜日・第X曜日・ゾロ目・月初末フラグを計算 |
| `summary_calculator.py` | daily_hall_summary / last_digit_summary など集計 |
| `rank_calculator.py` | 日別順位・移動平均（7〜35日）を計算 |
| `batch_incremental_updater.py` | 複数ホールの増分更新をバッチ実行 |
| `incremental_db_updater.py` | 単一ホールの増分更新 |
| `db_setup.py` | テーブル定義・スキーマ・初期化 |
| `table_config.py` | テーブル設定・カラム定義 |

## 出力テーブル一覧

| テーブル | 説明 |
|---------|------|
| `machine_detailed_results` | 台別の日次実績（ダッシュボードのメインデータ） |
| `machine_layout` | 台配置マスター（島・行・列） |
| `daily_hall_summary` | ホール全体の日次集計（勝率・平均G数・平均差枚） |
| `daily_machine_type_summary` | 機種タイプ別の日次集計 |
| `last_digit_summary_YYYYMMDD` | 末尾別集計（日付ごとのキャッシュテーブル） |
| `daily_position_summary_*` | 位置別集計 |
| `daily_island_summary` | 島別集計 |
| `machine_master` | 機種マスター |
| `event_calendar` | イベント情報 |

## 注意事項

- `last_digit`：machine_detailed_resultsではTEXT型（"0"〜"9"）
- `is_zorome`：INTEGER（0/1）。SQLiteはBOOLEAN非対応
- `weekday_nth`：daily_hall_summaryに格納。個別台テーブルにはない
- 増分更新：既存日付のデータはスキップ（重複しない）
