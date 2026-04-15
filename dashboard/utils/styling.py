"""
Pachinko Analyzer Dashboard - Styling
ダークテーマ設定とStreamlitカスタマイズ
"""

import streamlit as st


def configure_page():
    """ページ設定を適用"""
    st.set_page_config(
        page_title="Pachinko Analyzer Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )


def apply_dark_theme():
    """ダークテーマを適用"""
    st.markdown("""
    <style>
        /* ダークテーマ全体設定 */
        [data-testid="stSidebar"] {
            background-color: #1e1e1e;
        }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
            color: #ffffff;
        }
        [data-testid="stSidebar"] label {
            color: #ffffff !important;
            font-weight: 600;
        }
        /* メインコンテンツエリア */
        [data-testid="stAppViewContainer"] {
            background-color: #0e1117;
            color: #c9d1d9;
        }
        .metric-container {
            background-color: #1f2937;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #1f77b4;
        }
        .header-style {
            color: #58a6ff;
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 20px;
        }
        .subheader-style {
            color: #8b949e;
            font-size: 16px;
            margin-top: 15px;
            margin-bottom: 10px;
        }
    </style>
    """, unsafe_allow_html=True)
