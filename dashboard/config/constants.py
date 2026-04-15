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
    {"icon": "📊", "title": "日末日別分析", "key": "day_last_digit"},
    {"icon": "📋", "title": "第X曜日別分析", "key": "nth_weekday"},
    {"icon": "💻", "title": "個別台分析", "key": "individual_machines"},
    {"icon": "🎯", "title": "台番号末尾別分析", "key": "machine_tail"},
    {"icon": "⭐", "title": "期間TOP10分析", "key": "period_top10"},
    {"icon": "🔀", "title": "クロス検索分析", "key": "cross_search"},
    {"icon": "ℹ️", "title": "統計情報", "key": "statistics"},
    {"icon": "🏪", "title": "ホール選択支援", "key": "hall_selection"},
]

# ========================================
# 配色設定
# ========================================

COLORS = {
    'primary': '#1f77b4',      # 勝率（青）
    'secondary': '#ff7f0e',    # G数（オレンジ）
    'tertiary': '#2ca02c'      # 差枚（緑）
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
