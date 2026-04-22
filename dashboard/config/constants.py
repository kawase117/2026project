"""
Pachinko Analyzer Dashboard - Constants
定数・設定値の一元管理
"""

# ========================================
# ページ定義
# ========================================

PAGES = [
    {"icon": "🏠", "title": "ホール全体", "key": "hall_overview"},
    {"icon": "📅", "title": "日別分析", "key": "daily_analysis"},
    {"icon": "📆", "title": "曜日別分析", "key": "weekday_analysis"},
    {"icon": "📆", "title": "DD別分析", "key": "dd_analysis"},
    {"icon": "📊", "title": "末尾別分析", "key": "last_digit"},
    {"icon": "📊", "title": "日末日別分析", "key": "day_last_digit"},
    {"icon": "📋", "title": "第X曜日別分析", "key": "nth_weekday"},
    {"icon": "💻", "title": "個別台分析", "key": "individual_machines"},
    {"icon": "🎯", "title": "台番号末尾別分析", "key": "machine_tail"},
    {"icon": "⭐", "title": "期間TOP10分析", "key": "period_top10"},
    {"icon": "🔀", "title": "クロス検索分析", "key": "cross_search"},
    {"icon": "ℹ️", "title": "統計情報", "key": "statistics"},
    {"icon": "🏪", "title": "ホール選択支援", "key": "hall_selection"},
    {"icon": "📌", "title": "Notion へ保存", "key": "notion_exporter"},
    {"icon": "📊", "title": "バックテスト検証", "key": "backtest_validation"},
]

# ========================================
# ページレジストリ
# ========================================

PAGE_REGISTRY = {
    1: {
        "name": "ホール全体",
        "file": "page_01_hall_overview",
        "icon": "🏠"
    },
    2: {
        "name": "日別分析",
        "file": "page_02_daily_analysis",
        "icon": "📅"
    },
    3: {
        "name": "曜日別分析",
        "file": "page_03_weekday_analysis",
        "icon": "📆"
    },
    4: {
        "name": "DD別分析",
        "file": "page_04_dd_analysis",
        "icon": "📆"
    },
    5: {
        "name": "末尾別分析",
        "file": "page_05_last_digit",
        "icon": "📊"
    },
    6: {
        "name": "日末日別分析",
        "file": "page_06_day_last_digit",
        "icon": "📊"
    },
    7: {
        "name": "第X曜日別分析",
        "file": "page_07_nth_weekday",
        "icon": "📋"
    },
    8: {
        "name": "個別台分析",
        "file": "page_08_individual_machines",
        "icon": "💻"
    },
    9: {
        "name": "台番号末尾別分析",
        "file": "page_09_machine_tail",
        "icon": "🎯"
    },
    10: {
        "name": "期間TOP10分析",
        "file": "page_10_period_top10",
        "icon": "⭐"
    },
    11: {
        "name": "クロス検索分析",
        "file": "page_11_cross_search",
        "icon": "🔀"
    },
    12: {
        "name": "統計情報",
        "file": "page_12_statistics",
        "icon": "ℹ️"
    },
    13: {
        "name": "ホール選択支援",
        "file": "page_13_hall_selection",
        "icon": "🏪"
    },
    14: {
        "name": "Notion Exporter",
        "file": "page_14_notion_exporter",
        "icon": "📌"
    },
    15: {
        "name": "バックテスト検証",
        "file": "page_15_backtest_validation",
        "icon": "📊"
    }
}

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
