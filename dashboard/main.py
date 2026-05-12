"""
Pachinko Analyzer - Dashboard Main
パチスロ分析ダッシュボード メインアプリケーション
python -m streamlit run main_app.py
"""

import streamlit as st
import pandas as pd
from pathlib import Path

from .config.constants import PAGES, TRUST_LEVEL_INFO, FOOTER_TEXT
from .utils.styling import configure_page, apply_dark_theme
from .utils.data_loader import get_available_halls, load_daily_hall_summary

# Import page modules
from .pages import (
    page_01_hall_overview,
    page_02_daily_analysis,
    page_03_weekday_analysis,
    page_04_dd_analysis,
    page_05_last_digit,
    page_06_day_last_digit,
    page_07_nth_weekday,
    page_08_individual_machines,
    page_09_machine_tail,
    page_10_period_top10,
    page_11_cross_search,
    page_12_statistics,
    page_13_hall_selection,
    page_14_notion_exporter,
    page_15_backtest_validation,
    page_16_cross_search_bulk,
)

# ページキーと関数のマッピング
PAGE_ROUTER = {
    "hall_overview": page_01_hall_overview.render,
    "daily_analysis": page_02_daily_analysis.render,
    "weekday_analysis": page_03_weekday_analysis.render,
    "dd_analysis": page_04_dd_analysis.render,
    "last_digit": page_05_last_digit.render,
    "day_last_digit": page_06_day_last_digit.render,
    "nth_weekday": page_07_nth_weekday.render,
    "individual_machines": page_08_individual_machines.render,
    "machine_tail": page_09_machine_tail.render,
    "period_top10": page_10_period_top10.render,
    "cross_search": page_11_cross_search.render,
    "cross_search_bulk": page_16_cross_search_bulk.render,
    "statistics": page_12_statistics.render,
    "hall_selection": page_13_hall_selection.render,
    "notion_exporter": page_14_notion_exporter.render,
    "backtest_validation": page_15_backtest_validation.render,
}


# ========================================
# Page Configuration
# ========================================

configure_page()
apply_dark_theme()


# ========================================
# Session State Initialization
# ========================================

if 'db_path' not in st.session_state:
    st.session_state.db_path = None
if 'hall_name' not in st.session_state:
    st.session_state.hall_name = None
if 'df_hall_summary' not in st.session_state:
    st.session_state.df_hall_summary = None
if 'page_key' not in st.session_state:
    st.session_state.page_key = PAGES[0]["key"]
if 'date_range' not in st.session_state:
    st.session_state.date_range = (pd.to_datetime('2026-01-01'), pd.to_datetime('2026-12-31'))
if 'min_games' not in st.session_state:
    st.session_state.min_games = 1000
if 'show_low_confidence' not in st.session_state:
    st.session_state.show_low_confidence = False
if 'machine_type' not in st.session_state:
    st.session_state.machine_type = 'all'


# ========================================
# Sidebar Configuration
# ========================================

st.sidebar.markdown("### 🎮 Pachinko Analyzer")
st.sidebar.markdown("---")

# ホール選択
db_dir = Path('./db')
available_halls = get_available_halls(db_dir)

if available_halls:
    selected_hall = st.sidebar.selectbox(
        "📍 ホールを選択",
        available_halls,
        index=0 if not st.session_state.hall_name else available_halls.index(st.session_state.hall_name) if st.session_state.hall_name in available_halls else 0
    )
    st.session_state.hall_name = selected_hall
    st.session_state.db_path = db_dir / f"{selected_hall}.db"
else:
    st.sidebar.error("❌ db/ ディレクトリにデータベースがありません")
    st.stop()

# データ読み込み
if st.session_state.db_path:
    st.session_state.df_hall_summary = load_daily_hall_summary(str(st.session_state.db_path))

st.sidebar.markdown("---")

# 分析ページ選択
page_titles = [p["icon"] + " " + p["title"] for p in PAGES]
page_idx = st.sidebar.radio(
    "📊 分析ページ",
    range(len(page_titles)),
    format_func=lambda i: page_titles[i],
    index=next((i for i, p in enumerate(PAGES) if p["key"] == st.session_state.page_key), 0)
)
st.session_state.page_key = PAGES[page_idx]["key"]

st.sidebar.markdown("---")

# フィルタ設定
st.sidebar.markdown("### 🎛️ フィルタ設定")

df = st.session_state.df_hall_summary

if not df.empty:
    # 日付範囲選択
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()
    default_start = pd.to_datetime('2026-01-01').date()
    default_end = max_date

    date_range_tuple = st.sidebar.slider(
        "📅 期間選択",
        min_value=min_date,
        max_value=max_date,
        value=(default_start, default_end),
        format="YYYY-MM-DD"
    )

    st.session_state.date_range = (
        pd.to_datetime(date_range_tuple[0]),
        pd.to_datetime(date_range_tuple[1])
    )

    # 信頼性フィルタ
    st.session_state.min_games = st.sidebar.slider(
        "🎲 最小G数（信頼性フィルタ）",
        min_value=0,
        max_value=int(df['avg_games_per_machine'].max()),
        value=1000,
        step=100
    )

    st.session_state.show_low_confidence = st.sidebar.checkbox(
        "参考値を表示（低信頼度）",
        value=False,
        help="G数が少ないデータも表示"
    )

    # 機種フィルタ
    st.session_state.machine_type = st.sidebar.selectbox(
        "🎰 機種タイプ",
        ["all", "jug", "hana", "oki", "other"],
        help="末尾別分析で使用"
    )

st.sidebar.markdown("---")
st.sidebar.markdown(TRUST_LEVEL_INFO)


# ========================================
# Page Routing
# ========================================

try:
    page_key = st.session_state.page_key
    if page_key in PAGE_ROUTER:
        PAGE_ROUTER[page_key]()
    else:
        st.error(f"ページ '{page_key}' が見つかりません")
except Exception as e:
    st.error(f"ページ読み込みエラー: {e}")
    st.info("このエラーが続く場合は、以下のコマンドで起動してください:\nstreamlit run dashboard/main.py")


# ========================================
# Footer
# ========================================

st.markdown("---")
st.markdown(f"""
<div style="text-align: center; color: #888; font-size: 12px;">
    {FOOTER_TEXT}
</div>
""", unsafe_allow_html=True)
