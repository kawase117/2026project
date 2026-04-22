"""
Pachinko Analyzer - Dashboard Main (兼用エントリーポイント)
パチスロ分析ダッシュボード メインアプリケーション
"""

import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ========================================
# Load environment variables
# ========================================

load_dotenv()

# ========================================
# Import from local modules
# ========================================

from dashboard.config.constants import PAGES, TRUST_LEVEL_INFO, FOOTER_TEXT
from dashboard.utils.styling import configure_page, apply_dark_theme
from dashboard.utils.data_loader import get_available_halls, load_daily_hall_summary

# Import page modules
from dashboard.pages import (
    page_01_hall_overview,
    page_02_daily_analysis,
    page_03_weekday_analysis,
    page_04_dd_analysis,
    page_06_day_last_digit,
    page_07_nth_weekday,
    page_08_individual_machines,
    page_09_machine_tail,
    page_10_period_top10,
    page_11_cross_search,
    page_12_statistics,
    page_13_hall_selection,
    page_14_notion_exporter,
)


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
page_selection = st.sidebar.radio(
    "📊 分析ページ",
    page_titles,
    index=0
)

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
        help="G数が少ないデータも表示\n\n⚠️ チェック時：最小G数フィルタが無視される\nチェック外：最小G数フィルタが有効になる"
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

# ページ選択に基づいてページ関数を実行
try:
    if "🏠" in page_selection:
        page_01_hall_overview.render()
    elif "📅" in page_selection and "DD" not in page_selection:
        page_02_daily_analysis.render()
    elif "曜日別" in page_selection:
        page_03_weekday_analysis.render()
    elif "DD別" in page_selection:
        page_04_dd_analysis.render()
    elif "日末日別" in page_selection:
        page_06_day_last_digit.render()
    elif "第X曜日" in page_selection:
        page_07_nth_weekday.render()
    elif "個別台" in page_selection:
        page_08_individual_machines.render()
    elif "台番号末尾" in page_selection:
        page_09_machine_tail.render()
    elif "期間TOP10" in page_selection:
        page_10_period_top10.render()
    elif "クロス検索" in page_selection:
        page_11_cross_search.render()
    elif "統計情報" in page_selection:
        page_12_statistics.render()
    elif "ホール選択支援" in page_selection:
        page_13_hall_selection.render()
    elif "Notion へ保存" in page_selection:
        page_14_notion_exporter.render()
except Exception as e:
    st.error(f"ページ読み込みエラー: {e}")
    st.info("このエラーが続く場合は、以下のコマンドで起動してください:\nstreamlit run main_app.py")


# ========================================
# Footer
# ========================================

st.markdown("---")
st.markdown(f"""
<div style="text-align: center; color: #888; font-size: 12px;">
    {FOOTER_TEXT}
</div>
""", unsafe_allow_html=True)
