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
| `sync_new_machine_master.py` | アナスロDBの新機種を検出し、一撃で確認できた行を正本CSVへ追加して分類を同期 |
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

## 新機種マスターの同期

`batch_incremental_updater.py` と `main_processor.py` は全ホールの取込後に一度だけ、`incremental_db_updater.py` の単独CLIは対象ホールの取込後に新機種を照合する。アナスロ側の機種名と一撃の正式名称が一致し、導入日から60日以内にDBへ初出し、メーカー・機種区分・設定1/6の出玉率が確認できた場合だけ `document/machine_master_research/machine_master.csv` に追加する。既存行のスペックは変更しない。追加後、DBの未分類行へ機種区分を同期する。

候補が曖昧、未掲載、または検索できない機種は `scratch/machine_master_new_machine_review.json` に残し、次回のバッチで再試行する。検索は1回60秒を上限とし、DB取込自体は継続する。自動照合には通信可能な環境が必要。

確認だけ行う場合：

```powershell
venv\Scripts\python.exe database\sync_new_machine_master.py
```

確認済みの機種を反映する場合：

```powershell
venv\Scripts\python.exe database\sync_new_machine_master.py --apply
```
