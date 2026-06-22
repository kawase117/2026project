# database/ — DBモジュール ガイド

## DBスキーマ（主要テーブル）

### machine_detailed_results（メインデータ）
| カラム | 型 | 注意 |
|--------|-----|------|
| date | TEXT | YYYYMMDD形式 |
| machine_number | INTEGER | 台番号 |
| machine_name | TEXT | 機種名 |
| last_digit | **TEXT** | "0"〜"9"（文字列！） |
| is_zorome | **INTEGER** | 0/1（BOOLEAN非対応）。台番号の末尾2桁が同じ場合に 1 |
| games_normalized | INTEGER | 正規化ゲーム数 |
| diff_coins_normalized | INTEGER | 正規化差枚 |

### daily_hall_summary（ホール集計）
| カラム | 型 | 注意 |
|--------|-----|------|
| date | TEXT | YYYYMMDD形式 |
| day_of_week | TEXT | 曜日（日本語） |
| last_digit | INTEGER | 日付末尾（整数！） |
| weekday_nth | TEXT | 第N曜日（"Mon1"など）必ずこのテーブルから取得 |
| win_rate | FLOAT | 勝率（%） |
| avg_games_per_machine | INTEGER | 台平均G数 |
| avg_diff_per_machine | INTEGER | 台平均差枚 |
| is_zorome | INTEGER | 日付の日が 11 または 22 の場合に 1 |

## モジュール構成

| ファイル | 役割 |
|---------|------|
| main_processor.py | 全処理のオーケストレーター |
| data_inserter.py | SQLiteへのデータ投入 |
| date_info_calculator.py | 日付フラグ計算（is_zorome, weekday_nth等） |
| summary_calculator.py | 集計処理 |
| rank_calculator.py | ランク・移動平均計算（ROW_NUMBER()使用） |
| batch_incremental_updater.py | バッチ増分更新 |
| incremental_db_updater.py | 増分DB更新 |
| db_setup.py | テーブル定義・スキーマ |
| table_config.py | テーブル設定 |

## キャッシング

```python
@st.cache_data(ttl=3600)  # 1時間キャッシュ
def load_machine_detailed_results(db_path): ...
def load_daily_hall_summary(db_path): ...
```

## 実装済み改善（2026-04）

- rank_calculator.py：サブクエリ O(n²) → ROW_NUMBER() ウィンドウ関数 O(n)（SQLite 3.25.0以上必須）
- main_processor.py / incremental_db_updater.py：ランク計算と日付フラグ追加を同一 try/except に統合
