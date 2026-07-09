"""
Pachinko Analyzer Dashboard - Constants
定数・設定値の一元管理
"""

# ========================================
# ページグループ（サイドバーナビの分類）
# ========================================

PAGE_GROUPS = [
    {"key": "explore", "label": "📊 探索（発見）"},
    {"key": "theory", "label": "🔬 セオリー検証"},
    {"key": "ops", "label": "📝 運用"},
    {"key": "admin", "label": "ℹ️ 管理"},
]

# ========================================
# ページ定義（単一の情報源）
# main.py / main_app.py の PAGE_ROUTER はこのリストのキーに対応するモジュールをマッピングする。
# visible=False のページはサイドバーに表示されない（テストページ等）。
# ========================================

PAGE_DEFS = [
    {"key": "hall_overview", "title": "ホール全体", "icon": "🏠", "group": "admin"},
    {"key": "single_axis_viewer", "title": "単一軸ビューア", "icon": "📈", "group": "explore"},
    {"key": "dd_analysis", "title": "DD別分析", "icon": "📆", "group": "explore"},
    {"key": "individual_machines", "title": "個別台分析", "icon": "💻", "group": "explore"},
    {"key": "period_top10", "title": "期間TOP10分析", "icon": "⭐", "group": "explore"},
    {"key": "cross_search", "title": "クロス検索分析", "icon": "🔀", "group": "explore"},
    {"key": "cross_search_bulk", "title": "クロス検索一括", "icon": "📑", "group": "explore"},
    {"key": "heatmap", "title": "Heatmap", "icon": "H", "group": "explore"},
    {"key": "kamata7_theory", "title": "Kamata7 Theory", "icon": "K7", "group": "theory"},
    {"key": "kamata7_event_checks", "title": "Kamata7 Event Checks", "icon": "K7", "group": "theory"},
    {"key": "kamata7_segments", "title": "Kamata7 Segments", "icon": "K7", "group": "theory"},
    {"key": "daily_report", "title": "前日レポート", "icon": "📝", "group": "ops"},
    {"key": "hall_selection", "title": "ホール選択支援", "icon": "🏪", "group": "ops"},
    {"key": "backtest_validation", "title": "バックテスト検証", "icon": "📊", "group": "ops"},
    {"key": "notion_exporter", "title": "Notion へ保存", "icon": "📌", "group": "ops"},
    {"key": "statistics", "title": "統計情報", "icon": "ℹ️", "group": "admin"},
    {
        "key": "daily_report_visual_test",
        "title": "前日レポート Visual Test",
        "icon": "🧪",
        "group": "admin",
        "visible": False,
    },
]

# ========================================
# デフォルト値
# ========================================

DEFAULT_MIN_GAMES = 1000
DEFAULT_MIN_SAMPLE_SIZE = 5
DEFAULT_DB_DIR = './db'
DEFAULT_START_DATE = '2026-01-01'

# ========================================
# 機種タイプ
# ========================================

MACHINE_TYPES = ["all", "jug", "hana", "oki", "other"]

# ========================================
# UI テキスト
# ========================================

TRUST_LEVEL_INFO = """
**ℹ️ 信頼性基準**
- G数 ≥ 1000G: ✅ 高信頼
- G数 < 1000G: ⚠️ 参考値
- サンプル数 ≥ 5台: ✅ 統計的有意
"""

FOOTER_TEXT = """
Pachinko Analyzer Dashboard | Phase 3 Data Exploration
信頼性基準: G数 ≥ 1000G, サンプル数 ≥ 5
"""
