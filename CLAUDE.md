# Pachinko Analyzer - CLAUDE.md

AIアシスタントへ：このファイルをセッション開始時に必ず参照してください。

## プロジェクト概要

パチスロホールのデータを収集・分析するダッシュボードシステム。3フェーズで構成。

- **Phase 1 (scraper/)**: ana-slo.com からデータをスクレイピング → JSON保存
- **Phase 2 (database/)**: JSONをSQLiteに投入、集計・ランク計算
- **Phase 3 (dashboard/)**: Streamlit + Plotlyで15ページのダッシュボード表示

## 現在のディレクトリ構造（最新版）

```
2026project/
├── CLAUDE.md                    ← このファイル
├── main_app.py                  ← 起動エントリーポイント（絶対インポート）
├── dashboard/                   ← Phase 3 ダッシュボード（モジュール化）
│   ├── main.py                  ← ダッシュボード本体（サイドバー・ルーティング）
│   ├── design_system.py         ← デザインシステム（色・コンポーネント）
│   ├── config/constants.py      ← 定数・ページ定義
│   ├── utils/data_loader.py     ← データ読み込み関数（キャッシュ付き）
│   ├── utils/filters.py         ← 共通フィルタリング関数（全ページで使用）
│   ├── utils/charts.py          ← 共通グラフ生成関数
│   ├── utils/styling.py         ← CSSダークテーマ設定
│   └── pages/
│       ├── page_01_hall_overview.py     ← ホール全体 時系列推移
│       ├── page_02_daily_analysis.py    ← 日別分析
│       ├── page_03_weekday_analysis.py  ← 曜日別分析
│       ├── page_04_dd_analysis.py       ← DD別分析（月内日付）
│       ├── page_05_last_digit.py        ← 台番号末尾別
│       ├── page_06_day_last_digit.py    ← 日末尾別
│       ├── page_07_nth_weekday.py       ← 第X曜日別
│       ├── page_08_individual_machines.py ← 個別台分析
│       ├── page_09_machine_tail.py      ← 台番号末尾別（期間集計）
│       ├── page_10_period_top10.py      ← 期間TOP10
│       ├── page_11_cross_search.py      ← クロス検索分析（7属性）
│       ├── page_12_statistics.py        ← 統計情報
│       ├── page_13_hall_selection.py    ← 複数ホール選択支援
│       ├── page_14_notion_exporter.py   ← Notion連携
│       └── page_15_backtest_validation.py ← バックテスト検証（新規）
├── database/                    ← Phase 2 DBモジュール群
│   ├── main_processor.py        ← 全処理のオーケストレーター
│   ├── data_inserter.py         ← SQLiteへのデータ投入
│   ├── date_info_calculator.py  ← 日付フラグ計算
│   ├── summary_calculator.py    ← 集計処理
│   ├── rank_calculator.py       ← ランク・移動平均計算
│   ├── batch_incremental_updater.py ← バッチ増分更新
│   ├── incremental_db_updater.py    ← 増分DB更新
│   ├── db_setup.py              ← テーブル定義・スキーマ
│   └── table_config.py          ← テーブル設定
├── scraper/
│   └── anaslo-scraper_multi.py  ← ana-slo.comスクレイパー（マルチホール対応）
├── config/
│   └── hall_config.json         ← ホール設定（URL・名前マッピング）
├── db/                          ← SQLiteデータベース（gitignore）
│   └── {ホール名}.db
├── data/                        ← スクレイピングJSON（gitignore）
├── Heatmap/                     ← ヒートマップ実装（開発中）
├── ocr/                         ← OCR関連（開発中）
├── test/                        ← ユニットテスト
│   ├── test_filters.py          ← filters.py テスト（9件）
│   └── test_charts.py           ← charts.py テスト（6件）
└── document/                    ← 設計ドキュメント群
```

## 起動方法

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
streamlit run main_app.py
```

## 技術スタック

- **Streamlit** 1.56.0 - Web UI
- **Plotly** 6.7.0 - グラフ・ヒートマップ
- **Pandas** 3.0.2 - データ処理
- **SQLite** (stdlib) - データベース
- **BeautifulSoup** - HTMLパース（Phase 1）

## サイドバーのsession_state

| キー | 型 | 説明 |
|------|-----|------|
| `db_path` | Path | 選択中のDBファイルパス |
| `hall_name` | str | 選択中のホール名 |
| `df_hall_summary` | DataFrame | ホール集計データ（キャッシュ） |
| `date_range` | tuple(datetime, datetime) | 期間フィルタ |
| `min_games` | int | 最小G数（信頼性フィルタ） |
| `show_low_confidence` | bool | 低G数データも表示するか |
| `machine_type` | str | 機種タイプフィルタ |

## DBスキーマ（主要テーブル）

### machine_detailed_results（メインデータ）
| カラム | 型 | 注意 |
|--------|-----|------|
| date | TEXT | YYYYMMDD形式 |
| machine_number | INTEGER | 台番号 |
| machine_name | TEXT | 機種名 |
| last_digit | **TEXT** | "0"〜"9"（文字列！） |
| is_zorome | **INTEGER** | 0/1（BOOLEAN非対応） |
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
| is_zorome | INTEGER | ゾロ目フラグ（0/1） |

## 共通ユーティリティ（2026-04 追加）

### utils/filters.py — フィルタリング関数

全ページで使用する共通フィルタ。直接インライン実装してはいけない。

```python
from ..utils.filters import apply_sidebar_filters, apply_machine_filters, filter_by_date_range

# ホール集計データ用（daily_hall_summary系）
df_filtered = apply_sidebar_filters(
    df,
    date_range=st.session_state.date_range,
    min_games=st.session_state.min_games,
    show_low_confidence=st.session_state.show_low_confidence,
    games_column='avg_games_per_machine',  # デフォルト値
)

# 個別台データ用（machine_detailed_results）※集計前に行レベルで適用
df_filtered = apply_machine_filters(
    df,
    date_range=st.session_state.date_range,
    min_games=st.session_state.min_games,
    show_low_confidence=st.session_state.show_low_confidence,
    games_column='games_normalized',  # デフォルト値
)

# page_08/10 のように集計後に total_games で絞る場合は filter_by_date_range のみ使用
df = filter_by_date_range(df, st.session_state.date_range)
# 集計後: df_summary[df_summary['total_games'] >= st.session_state.min_games]
```

**末尾別ページ（page_05, page_09）の games_column**：`avg_games`（`last_digit_summary` のカラム名）

### utils/charts.py — グラフ生成関数

```python
from ..utils.charts import create_bar_chart, create_line_chart, create_scatter_chart

fig = create_bar_chart(df, x='col_x', y='col_y', title='タイトル', height=400)
fig = create_line_chart(df, x='col_x', y='col_y', title='タイトル')
fig = create_scatter_chart(df, x='col_x', y='col_y', size='col_size', title='タイトル')
# 空DataFrameでも例外を出さない（空のFigureを返す）
```

## 重要な注意事項

1. **last_digit型の違い**：`machine_detailed_results`はTEXT、`daily_hall_summary`はINTEGER
2. **weekday_nth**：必ず`daily_hall_summary`から取得（個別台テーブルにはない）
3. **Plotly複合軸**：`make_subplots()`方式を使用（Plotly 6.7.0対応）
4. **インポート**：`main_app.py`は絶対インポート、`dashboard/main.py`は相対インポート
5. **min_gamesフィルタ**：集計**前**に個別台レベルで適用（`games_normalized >= min_games`）
6. **フィルタは必ず utils/filters.py を使うこと**：各ページにインライン実装しない
7. **SQLインジェクション対策**：`load_daily_hall_by_attribute` の `attribute` 引数は `ALLOWED_ATTRIBUTES` ホワイトリストで検証済み

## キャッシング

```python
@st.cache_data(ttl=3600)  # 1時間キャッシュ
def load_machine_detailed_results(db_path): ...
def load_daily_hall_summary(db_path): ...
```

## テスト実行

```bash
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m pytest test/ -v
# test_filters.py: 9件、test_charts.py: 6件（計15件）
```

## database/ 側の改善点（2026-04 実施済み）

- **rank_calculator.py**：サブクエリ O(n²) → `ROW_NUMBER()` ウィンドウ関数 O(n)（SQLite 3.25.0以上必須、現環境 3.50.4）
- **main_processor.py / incremental_db_updater.py**：ランク計算と日付フラグ追加を同一 try/except に統合（部分成功による不整合を防止）

## ドキュメント参照先

| ドキュメント | 内容 |
|------------|------|
| `document/Phase1_Scraper実装ドキュメント.md` | スクレイパー詳細仕様 |
| `document/Phase2_Database全体アーキテクチャ.md` | DB処理フロー全体 |
| `document/PHASE2_完全仕様書.md` | Phase 2 詳細仕様 |
| `document/ARCHITECTURE.md` | システム全体構成図 |
| `document/パチスロ分析データベース スキーマ説明書.md` | DBスキーマ詳細 |
| `document/plans/2026-04-15-refactoring-plan.md` | 2026-04 リファクタリング計画・変更記録 |

## GitHub

リポジトリ: https://github.com/kawase117/2026project
ブランチ: main
修正完了後、ユーザーに「プッシュしますか？」と確認してからプッシュする。

### /save コマンド
- 現在のチャット会話を docs/ に保存
- 形式：raw/sessions/YYYY-MM-DD-T-HH-MM-SS-<説明>.md
- frontmatter: compiled: false, type: session
