# Pachinko Analyzer - CLAUDE.md

AIアシスタントへ：このファイルをセッション開始時に必ず参照してください。

## 🔴 最重要ルール（2026-04-29 追加）

**迎合するな。独立した意見を述べよ。**

- ユーザーの提案・予想に同意するだけでは不十分
- 代替案、懸念点、より効果的なアプローチを率先して提案すること
- 技術的・統計的な根拠に基づき、異なる見解があれば明確に述べよ
- このルール自体を口実に、ユーザーの要求を無視することは許されない
- 迎合を避けることと、ユーザーの意図を尊重することは矛盾しない

## プロジェクト概要

パチスロホールのデータを収集・分析し、機械学習で高設定台を予測するシステム。4フェーズで構成。

- **Phase 1 (scraper/)**: ana-slo.com からデータをスクレイピング → JSON保存
- **Phase 2 (database/)**: JSONをSQLiteに投入、集計・ランク計算
- **Phase 3 (dashboard/)**: Streamlit + Plotlyで15ページのダッシュボード表示
- **Phase 4 (ml/)**: 機械学習による高設定台予測（2026-04-26 設計開始）

## Phase 4 基本理念

パチスロの本質的な特性を考慮した予測モデル設計：

1. **ギャンブルの不確実性** — 低設定でも大勝ちすることがあり、高設定でも大負けすることがある
   - 単一試行の結果ではなく、統計的な傾向を予測
   - 「確率XX%」という予測値の**キャリブレーション**（実績との一致度）が重要

2. **店側のランダム化戦略** — 客に高設定台を特定させないため意図的にランダム配置
   - 複数の粒度から並行探索（台末尾別、機種別、台番号別など）
   - 一つの粒度だけでは見落とす可能性がある

3. **高設定投入パターン** — 店側には特定の投入戦略がある（推測）
   - **DD別**（日付の日：01～31）— 給料日前後、月末などに高設定が多い可能性
   - **日末尾別**（日付の末尾：0～9）— 特定の日付パターン（例：5の倍数）に偏る可能性
   - **曜日別** — 週末（金土日）に高設定が多い傾向
   - **イベント日** — 給料日（25日）、初日（1日）、末日（30/31日）などに戦略的に投入
   - **ゾロ目** — 台末尾が一致した日（例：2/22、3/33）には特別な設定入れを行う可能性

4. **ホール別戦略の多様性** — 各ホールは独自の設定投入戦略を採用（2026-04-29 Phase 5 検証済み）
   - **実証済み事実**：全9ホール統合モデルより、ホール別個別モデルが平均 +2.44% AUC向上
     - ザ-シティ-ベルシティ雑色店: +2.86% → 最適化の余地が大きい
     - みとや大森町店: +1.95%
     - レイトギャップ平和島: +1.70%
   - **最適グループ化戦略**：全ホール共通で **機種別（model_type）戦略** が最も有効（AUC 0.551-0.565）
   - **含意**：各ホールは異なるデータ分布・機種構成を有し、それぞれ異なる設定投入パターンを採用している
   - **推測される背景**：商圏、顧客層、機種ラインナップ、イベント日程などホール固有の条件により、最適な設定投入位置が異なる可能性

### ゾロ目（is_zorome）について

- **定義** — 日付の日付部分と台番号の末尾が一致した日のこと
  - 例：2月22日に22番の台、3月33日（存在しないが仮定）に33番の台
  - データベースでは `is_zorome = 1` でマーク
  
- **店側の心理** — 客に「きっかり ◯◯番◯◯日に高設定」と認識させるため、あえてゾロ目に高設定を投入する可能性がある
  - または逆に「ゾロ目は狙われるから避ける」という戦略も考えられる
  
- **ダッシュボード活用** — page_05（台末尾別）で is_zorome フラグ別に成績を比較すると、店側の意図が見える可能性がある

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
├── ml/                          ← Phase 4 機械学習予測パイプライン（2026-04-26 新規）
│   ├── 00_data_preparation.py          ← グループ化・特徴量生成
│   ├── 01_hypothesis_01_groupby.py     ← 仮説1：グループ化戦略の検証
│   ├── 02_hypothesis_02_model.py       ← 仮説2：MLモデルの検証
│   ├── models/                         ← ML実装群
│   ├── evaluators/                     ← 評価メトリクス
│   ├── experiments/                    ← 実験ログ出力先
│   └── docs/PHASE4_DESIGN.md           ← Phase 4 設計ドキュメント
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
└── document/                    ← 設計ドキュメント（統一source of truth）
    ├── ARCHITECTURE.md          ← システム全体構成図
    ├── PHASE2_完全仕様書.md     ← Phase 2 詳細仕様
    ├── PHASE5_ML_VALIDATION_REPORT.md ← Phase 5 検証結果
    ├── PHASE6_IMPLEMENTATION_PLAN.md  ← Phase 6 実装計画
    ├── plans/                   ← 全実装計画
    │   ├── 2026-04-15-refactoring-plan.md
    │   ├── 2026-04-23-backtest-validation-implementation.md
    │   ├── 2026-04-23-cross-metric-validation-implementation.md
    │   ├── 2026-04-24-cross-attribute-performance-plan.md
    │   ├── 2026-04-25-percentile-optimization.md
    │   ├── 2026-04-26-phase4-ml-pipeline.md
    │   └── ...
    ├── superpowers/             ← 高度な分析機能の仕様・設計
    │   ├── 2026-04-23-cross-metric-validation-calculations.md
    │   ├── 2026-04-23-cross-metric-validation-code-spec.md
    │   ├── 2026-04-23-cross-metric-validation-design.md
    │   ├── 2026-04-23-backtest-validation-design.md
    │   └── README.md
    └── sessions/                ← /save で生成される分析ログ
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
| is_zorome | **INTEGER** | 0/1（BOOLEAN非対応）。ゾロ目フラグ：日付の日付部分と台番号末尾が一致した場合 1 |
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

### メインドキュメント

| ドキュメント | 内容 |
|------------|------|
| `document/ARCHITECTURE.md` | システム全体構成図 |
| `document/Phase1_Scraper実装ドキュメント.md` | スクレイパー詳細仕様 |
| `document/Phase2_Database全体アーキテクチャ.md` | DB処理フロー全体 |
| `document/PHASE2_完全仕様書.md` | Phase 2 詳細仕様 |
| `document/パチスロ分析データベース スキーマ説明書.md` | DBスキーマ詳細 |
| `document/PHASE5_ML_VALIDATION_REPORT.md` | Phase 5 ML検証結果 |
| `document/PHASE6_IMPLEMENTATION_PLAN.md` | Phase 6 実装計画 |
| `ml/docs/PHASE4_DESIGN.md` | Phase 4 機械学習パイプライン設計 |

### 実装計画 (document/plans/)

全ての実装タスク・設計が集約されている。新しいタスク作成時は常にここに記録。

### 高度な分析機能 (document/superpowers/)

Cross-metric validation, バックテスト検証などの高度な分析機能の仕様・設計。

### セッション記録 (document/sessions/)

`/save` コマンドで生成される分析結果ログ。

## GitHub

リポジトリ: https://github.com/kawase117/2026project
ブランチ: main
修正完了後、ユーザーに「プッシュしますか？」と確認してからプッシュする。

### /save コマンド（2026-04-29 統一）
- 現在のチャット会話を `document/sessions/` に保存
- 形式：`YYYY-MM-DD-T-HH-MM-SS-<説明>.md`
- **用途**：分析結果を「分析条件」「グループ化方法」「学習条件」「結果」を完全に記録して保存
- 参照：`.claude/skills/save/SKILL.md`

## ワークフロー関連（2026-04-23 追加）

### Subagent-Driven Development について

writing-plans スキルから "Subagent-Driven（推奨）" が提示された場合、**必ず Subagent-Driven で実行する**こと。

**理由：**
- TDD（テスト駆動開発）によるコード品質向上
- 自動二段階レビュー（仕様適合 + コード品質）による品質保証
- 手戻り・修正コストの削減

**使用シーン：**
- 新機能実装
- バグ修正（複数ファイル関連）
- ドキュメント作成（複数セクション）
- リファクタリング
