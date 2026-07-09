"""ダッシュボードの共通シェル（サイドバー・フィルタ・ルーティング）。

main.py（相対インポート）と main_app.py（絶対インポート、CLAUDE.md 記載の
兼用エントリーポイント）はインポートスタイルのみが異なる双子ページのため、
共通ロジックはここに集約し、両者は PAGE_ROUTER の組み立てだけを担う。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

import pandas as pd
import streamlit as st

from .config.constants import FOOTER_TEXT, MACHINE_TYPES, PAGE_DEFS, PAGE_GROUPS, TRUST_LEVEL_INFO
from .utils.data_loader import get_available_halls, load_daily_hall_summary
from .utils.styling import apply_dark_theme, configure_page

VISIBLE_PAGE_DEFS = [page for page in PAGE_DEFS if page.get("visible", True)]


def _init_session_state() -> None:
    if "db_path" not in st.session_state:
        st.session_state.db_path = None
    if "hall_name" not in st.session_state:
        st.session_state.hall_name = None
    if "df_hall_summary" not in st.session_state:
        st.session_state.df_hall_summary = None
    if "page_key" not in st.session_state:
        st.session_state.page_key = VISIBLE_PAGE_DEFS[0]["key"]
    if "date_range" not in st.session_state:
        st.session_state.date_range = (pd.to_datetime("2026-01-01"), pd.to_datetime("2026-12-31"))
    if "min_games" not in st.session_state:
        st.session_state.min_games = 1000
    if "show_low_confidence" not in st.session_state:
        st.session_state.show_low_confidence = False
    if "machine_type" not in st.session_state:
        st.session_state.machine_type = "all"


def _render_hall_selector() -> None:
    db_dir = Path("./db")
    available_halls = get_available_halls(db_dir)

    if not available_halls:
        st.sidebar.error("❌ db/ ディレクトリにデータベースがありません")
        st.stop()

    selected_hall = st.sidebar.selectbox(
        "📍 ホールを選択",
        available_halls,
        index=0
        if not st.session_state.hall_name
        else available_halls.index(st.session_state.hall_name)
        if st.session_state.hall_name in available_halls
        else 0,
    )
    st.session_state.hall_name = selected_hall
    st.session_state.db_path = db_dir / f"{selected_hall}.db"

    if st.session_state.db_path:
        st.session_state.df_hall_summary = load_daily_hall_summary(str(st.session_state.db_path))


def _render_navigation() -> None:
    group_labels = {group["key"]: group["label"] for group in PAGE_GROUPS}
    group_keys = [group["key"] for group in PAGE_GROUPS]

    current_def = next(
        (page for page in VISIBLE_PAGE_DEFS if page["key"] == st.session_state.page_key),
        VISIBLE_PAGE_DEFS[0],
    )
    current_group = current_def["group"]

    selected_group = st.sidebar.selectbox(
        "🗂️ 分類",
        group_keys,
        format_func=lambda key: group_labels[key],
        index=group_keys.index(current_group),
    )

    group_pages = [page for page in VISIBLE_PAGE_DEFS if page["group"] == selected_group]
    page_titles = [page["icon"] + " " + page["title"] for page in group_pages]
    default_idx = next(
        (i for i, page in enumerate(group_pages) if page["key"] == st.session_state.page_key),
        0,
    )

    page_idx = st.sidebar.radio(
        "📊 分析ページ",
        range(len(page_titles)),
        format_func=lambda i: page_titles[i],
        index=default_idx,
    )
    st.session_state.page_key = group_pages[page_idx]["key"]


def _render_filters() -> None:
    st.sidebar.markdown("### 🎛️ フィルタ設定")

    df = st.session_state.df_hall_summary
    if df is None or df.empty:
        return

    min_date = df["date"].min().date()
    max_date = df["date"].max().date()
    default_start = pd.to_datetime("2026-01-01").date()
    default_end = max_date

    date_range_tuple = st.sidebar.slider(
        "📅 期間選択",
        min_value=min_date,
        max_value=max_date,
        value=(default_start, default_end),
        format="YYYY-MM-DD",
    )
    st.session_state.date_range = (
        pd.to_datetime(date_range_tuple[0]),
        pd.to_datetime(date_range_tuple[1]),
    )

    st.session_state.min_games = st.sidebar.slider(
        "🎲 最小G数（信頼性フィルタ）",
        min_value=0,
        max_value=int(df["avg_games_per_machine"].max()),
        value=1000,
        step=100,
    )

    st.session_state.show_low_confidence = st.sidebar.checkbox(
        "参考値を表示（低信頼度）",
        value=False,
        help="G数が少ないデータも表示",
    )

    st.session_state.machine_type = st.sidebar.selectbox(
        "🎰 機種タイプ",
        MACHINE_TYPES,
        help="末尾別分析で使用",
    )


def render_app(page_router: Dict[str, Callable[[], None]]) -> None:
    """ダッシュボードのメインシェルを描画する。

    main.py / main_app.py はインポートスタイルの違いのみを吸収し、
    組み立てた page_router をここに渡すだけでよい。
    """
    configure_page()
    apply_dark_theme()

    _init_session_state()

    st.sidebar.markdown("### 🎮 Pachinko Analyzer")
    st.sidebar.markdown("---")

    _render_hall_selector()

    st.sidebar.markdown("---")

    _render_navigation()

    st.sidebar.markdown("---")

    _render_filters()

    st.sidebar.markdown("---")
    st.sidebar.markdown(TRUST_LEVEL_INFO)

    try:
        page_key = st.session_state.page_key
        if page_key in page_router:
            page_router[page_key]()
        else:
            st.error(f"ページ '{page_key}' が見つかりません")
    except Exception as e:
        st.error(f"ページ読み込みエラー: {e}")
        st.info("このエラーが続く場合は、以下のコマンドで起動してください:\nstreamlit run main_app.py")

    st.markdown("---")
    st.markdown(
        f"""
<div style="text-align: center; color: #888; font-size: 12px;">
    {FOOTER_TEXT}
</div>
""",
        unsafe_allow_html=True,
    )
