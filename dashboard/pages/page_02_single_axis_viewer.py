"""
Page 2: 単一軸ビューア
日別・曜日別・日末日別・第X曜日別・台番号末尾別を1ページで確認する（探索グループ）。

instincts で単一軸は効果なし確定（weekday-digit-nth-single-dim-all-null）のため、
本ページは新たな発見用ではなくデータ目視確認用途。
"""

import streamlit as st

from ..design_system import section_title
from ..utils.filters import apply_sidebar_filters
from ..utils.single_axis_viewer import (
    AXIS_LABELS,
    render_categorical_axis,
    render_daily_trend,
    render_machine_tail,
)


def render():
    """単一軸ビューアのページを描画"""
    section_title(
        "単一軸ビューア",
        "軸を選んでデータを目視確認します（単一軸のシグナルは既存分析でnull確定済み）",
    )

    axis_key = st.selectbox(
        "🔎 軸を選択",
        list(AXIS_LABELS.keys()),
        format_func=lambda key: AXIS_LABELS[key],
    )

    if axis_key == "machine_tail":
        if not st.session_state.db_path:
            st.warning("⚠️ ホールDBが選択されていません")
            return
        render_machine_tail(
            db_path=st.session_state.db_path,
            date_range=st.session_state.date_range,
            min_games=st.session_state.min_games,
            show_low_confidence=st.session_state.show_low_confidence,
            machine_type=st.session_state.machine_type,
        )
        return

    df = st.session_state.df_hall_summary
    if df.empty:
        st.warning("⚠️ データが見つかりません")
        return

    df_filtered = apply_sidebar_filters(
        df,
        date_range=st.session_state.date_range,
        min_games=st.session_state.min_games,
        show_low_confidence=st.session_state.show_low_confidence,
    )

    if df_filtered.empty:
        st.warning("⚠️ フィルタ条件に合致するデータがありません")
        return

    if axis_key == "daily_trend":
        render_daily_trend(df_filtered)
    else:
        render_categorical_axis(df_filtered, axis_key)
