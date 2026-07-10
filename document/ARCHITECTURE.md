# ARCHITECTURE.md
## システムアーキテクチャ

**最終更新**: 2026-07-10（dashboard/ セクションをPhase 1-4再構築後の構成に更新）
**システム**: Pachinko Analyzer v2.0（モジュール化版）
**テクノロジー**: Streamlit + Plotly + SQLite + Pandas

---

## 📐 全体構成図

```
┌─────────────────────────────────────────────────────────────┐
│                       Web ブラウザ                           │
│                    localhost:8501                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐
│    Streamlit UI      │  │   Plotly グラフ       │
│  (Page Navigation)   │  │  (Visualization)     │
│  (Sidebar Filters)   │  │  (Heatmap)           │
│  (Metrics)           │  │  (Subplots)          │
└──────────────────────┘  └──────────────────────┘
          │                         │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   Pandas DataFrame      │
          │ (Aggregation/Filtering) │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │   SQLite DB Connection  │
          │    (Query Execution)    │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │  db/{hall_name}.db      │
          │  (8+ Tables / ホール別) │
          └─────────────────────────┘
```

---

## 🔄 データフロー

### Phase 1 → 2 → 3 全体フロー

```
【Phase 1: Scraper】
ana-slo.com
    ↓ BeautifulSoup HTMLパース
data/{hall_name}/{date}_data.json

【Phase 2: Database】
data/{hall_name}/*.json
    ↓ main_processor.py（オーケストレーター）
    ├─ data_inserter.py       → machine_detailed_results
    ├─ date_info_calculator.py → 日付フラグ付加
    ├─ summary_calculator.py  → daily_hall_summary など
    └─ rank_calculator.py     → 順位・移動平均
db/{hall_name}.db

【Phase 3: Dashboard】
db/{hall_name}.db
    ↓ utils/data_loader.py（@st.cache_data）
    ├─ load_machine_detailed_results()
    ├─ load_daily_hall_summary()
    └─ load_last_digit_summary()
        ↓
dashboard/pages/*.py（描画、詳細は下記モジュール構成を参照）
```

---

## 📦 モジュール構成（現在）

### dashboard/ （2026-07-10 再構築後）

ページ定義は `config/constants.py` の `PAGE_DEFS`（単一の情報源）が持ち、
`main.py` / `main_app.py` の `PAGE_ROUTER` はそのキーに対応するモジュールを
マッピングするだけの薄いエントリーポイント。共通のサイドバー・フィルタ・
ルーティングロジックは `app_shell.py` に集約されている。

```
dashboard/
├── main.py              # PAGE_ROUTER 定義 + app_shell.render_app() 呼び出し（相対import版）
├── app_shell.py          # サイドバー・ホール選択・フィルタ・ルーティングの共通ロジック
├── design_system.py     # カラーパレット・UIコンポーネント
├── config/
│   ├── constants.py      # PAGE_GROUPS / PAGE_DEFS（ページ定義の単一の情報源）
│   └── hall_configs/     # ホール別セグメント定義（フロア/LR/イベント日/冷却帯等）
│       ├── kamata1.yaml
│       └── kamata7.yaml
├── utils/
│   ├── data_loader.py         # DB読み込み関数（キャッシュ付き）
│   ├── theory_engine.py       # ホール非依存のセオリー検証エンジン
│   ├── interaction_analysis.py # 交互作用エクスプローラ用の集計・検定
│   ├── single_axis_viewer.py  # 単一軸ビューアの集計ロジック
│   └── styling.py             # CSSダークテーマ
└── pages/
    ├── page_01_hall_overview.py
    ├── page_02_single_axis_viewer.py      # 旧02,03,05,06,07,09を統合
    ├── page_04_dd_analysis.py
    ├── page_08_individual_machines.py
    ├── page_10_period_top10.py
    ├── page_11_cross_search.py
    ├── page_11b_interaction_explorer.py
    ├── page_11c_axis_screening.py
    ├── page_12_statistics.py
    ├── page_13_hall_selection.py
    ├── page_14_notion_exporter.py
    ├── page_15_backtest_validation.py
    ├── page_16_cross_search_bulk.py
    ├── page_17_heatmap.py
    ├── page_18_daily_report.py
    ├── page_19_daily_report_visual_test.py  # visible=False（devのみ）
    └── page_20_theory_verification.py     # 旧20,21,22を統合、ホール非依存
```

セオリー・クレームの本体は `document/theory_registry/<hall>.yaml`
（`document/<hall>_theory.md` の検証対象インデックス。theory.md 自体は
手動管理を維持し、レジストリからの自動生成はしない）。

詳細は `document/plans/2026-07-10-dashboard-refactoring-plan.md` を参照。

### database/ （Phase 2）

```
database/
├── main_processor.py          # 全処理のオーケストレーター
├── data_inserter.py           # SQLiteへのデータ投入
├── date_info_calculator.py    # 日付フラグ計算
├── summary_calculator.py      # 集計処理
├── rank_calculator.py         # ランク・移動平均
├── batch_incremental_updater.py  # 複数ホール一括更新
├── incremental_db_updater.py     # 単一ホール増分更新
├── db_setup.py                # テーブル定義・スキーマ
└── table_config.py            # テーブル設定
```

### scraper/ （Phase 1）

```
scraper/
└── anaslo-scraper_multi.py    # マルチホール対応スクレイパー
```

---

## 🗄️ データベーススキーマ（主要テーブル）

詳細は `パチスロ分析データベース スキーマ説明書.md` を参照。

```
db/{hall_name}.db
│
├── machine_detailed_results    ← ダッシュボードのメインデータ
│   ├── date (TEXT: YYYYMMDD)
│   ├── machine_number (INTEGER)
│   ├── machine_name (TEXT)
│   ├── last_digit (TEXT: "0"〜"9")  ← TEXTに注意
│   ├── is_zorome (INTEGER: 0/1)
│   ├── games_normalized (INTEGER)
│   └── diff_coins_normalized (INTEGER)
│
├── daily_hall_summary          ← ホール全体集計
│   ├── date (TEXT: YYYYMMDD)
│   ├── day_of_week (TEXT)
│   ├── last_digit (INTEGER: 0〜9)   ← INTEGERに注意
│   ├── weekday_nth (TEXT: "Mon1"など)
│   ├── win_rate (FLOAT)
│   ├── avg_games_per_machine (INTEGER)
│   ├── avg_diff_per_machine (INTEGER)
│   └── is_zorome (INTEGER: 0/1)
│
├── last_digit_summary_YYYYMMDD ← 末尾別集計（キャッシュ）
├── daily_machine_type_summary  ← 機種別集計
├── machine_layout              ← 台配置マスター
├── machine_master              ← 機種マスター
├── event_calendar              ← イベント情報
└── daily_island_summary        ← 島別集計
```

---

## 🔐 キャッシング戦略

```python
@st.cache_data(ttl=3600)  # 1時間キャッシュ
def load_machine_detailed_results(db_path): ...

@st.cache_data(ttl=3600)
def load_daily_hall_summary(db_path): ...

@st.cache_data(ttl=3600)
def load_last_digit_summary(db_path, date): ...
```

| 処理 | 初回 | キャッシュ有 |
|------|------|------------|
| DB データ取得 | 2〜3秒 | - |
| groupby 集計 | 1〜2秒 | - |
| グラフ描画 | 0.5〜1秒 | - |
| **合計（初回）** | **4〜7秒** | - |
| **合計（キャッシュ）** | - | **0.5〜1秒** |

---

## 🌐 session_state 設計

```python
# main.py で初期化・更新
st.session_state.db_path            # 選択中DB
st.session_state.hall_name          # 選択中ホール名
st.session_state.df_hall_summary    # ホール集計DataFrame
st.session_state.date_range         # 期間フィルタ (tuple)
st.session_state.min_games          # 最小G数（集計前フィルタに使用）
st.session_state.show_low_confidence  # 低信頼度データ表示フラグ
st.session_state.machine_type       # 機種タイプフィルタ
```

---

## 🎨 デザインシステム

```python
# design_system.py
COLORS = {
    'primary': '#0f172a',        # 深紺（背景）
    'accent': '#d4af37',         # 金色（アクセント）
    'secondary_blue': '#3b82f6',
    'secondary_orange': '#f97316',
    'secondary_green': '#10b981',
    'secondary_red': '#ef4444',
}

# コンポーネント関数
section_title(title, subtitle)   # 金色アンダーラインタイトル
premium_divider()                 # グラデーション区切り線
metric_card(label, value, ...)   # ラグジュアリーメトリクスカード
```

---

## 🚀 将来の拡張予定

### 近期
- [ ] Heatmap：台配置×性能ヒートマップをダッシュボードに統合
- [ ] OCR：画像からデータ自動抽出

### Phase 4（機械学習）
- [ ] 設定推定モデル（BB回数から設定を推測）
- [ ] 明日の勝率予測
- [ ] 最適台選択のAI推奨

---

**作成日**: 2026-04-15
**対象**: システム設計の参考資料
