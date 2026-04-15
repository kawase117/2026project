# dashboard/ - Phase 3 ダッシュボード

Streamlit + Plotlyによる12ページのパチスロ分析ダッシュボード。

## 起動

```bash
# プロジェクトルートから
streamlit run main_app.py
```

## ファイル構成

| ファイル | 役割 |
|---------|------|
| `main.py` | サイドバー・ルーティング・session_state管理 |
| `design_system.py` | カラーパレット・UIコンポーネント関数 |
| `config/constants.py` | ページ定義リスト・定数 |
| `utils/data_loader.py` | DB読み込み関数（@st.cache_data付き） |
| `utils/styling.py` | CSSダークテーマ適用 |

## ページ一覧

| ページ | ファイル | データソース |
|-------|---------|-------------|
| 🏠 ホール全体 | page_01 | daily_hall_summary |
| 📅 日別分析 | page_02 | daily_hall_summary |
| 📆 曜日別分析 | page_03 | daily_hall_summary |
| 📆 DD別分析 | page_04 | daily_hall_summary |
| 🔢 末尾別分析 | page_05 | machine_detailed_results |
| 📊 日末日別分析 | page_06 | daily_hall_summary |
| 📋 第X曜日別分析 | page_07 | daily_hall_summary |
| 💻 個別台分析 | page_08 | machine_detailed_results |
| 🎯 台番号末尾別分析 | page_09 | machine_detailed_results |
| ⭐ 期間TOP10 | page_10 | machine_detailed_results |
| 🔀 クロス検索分析 | page_11 | machine_detailed_results |
| ℹ️ 統計情報 | page_12 | machine_detailed_results |
| 🏪 ホール選択支援 | page_13 | daily_hall_summary (複数ホール) |

## デザインシステム

```python
from dashboard.design_system import section_title, premium_divider, COLORS, metric_card

# カラーパレット
COLORS = {
    'primary': '#0f172a',        # 深紺（背景）
    'accent': '#d4af37',         # 金色（アクセント）
    'secondary_blue': '#3b82f6',
    'secondary_orange': '#f97316',
    'secondary_green': '#10b981',
    'secondary_red': '#ef4444',
}
```

## min_games フィルタの仕様

- **適用タイミング**：グループ化集計の**前**に個別台レベルで適用
- **条件**：`games_normalized >= min_games`
- **show_low_confidence=True**のとき：フィルタをスキップして全台を集計

```python
# 正しい実装（page_11など）
if not st.session_state.show_low_confidence:
    df = df[df['games_normalized'] >= min_games]
# ← この後にgroupbyで集計
```
