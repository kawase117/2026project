"""
Page 3: 曜日別分析
曜日ごとの平均値を比較
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.filters import apply_sidebar_filters
from ..design_system import section_title, premium_divider, COLORS


def render():
    """曜日別分析のページを描画"""
    section_title("曜日別分析", "曜日ごとの平均値を比較して、パターンを検出します")

    # session_state からフィルタ情報を取得
    df = st.session_state.df_hall_summary

    if df.empty:
        st.warning("⚠️ データが見つかりません")
        return

    # フィルタリング
    df_filtered = apply_sidebar_filters(
        df,
        date_range=st.session_state.date_range,
        min_games=st.session_state.min_games,
        show_low_confidence=st.session_state.show_low_confidence,
    )

    if df_filtered.empty:
        st.warning("⚠️ フィルタ条件に合致するデータがありません")
        return

    # 曜日別集計
    dow_mapping = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}
    df_filtered_copy = df_filtered.copy()
    df_filtered_copy['day_name'] = df_filtered_copy['date'].dt.dayofweek.map(dow_mapping)

    # グラフ表示
    col1, col2, col3 = st.columns(3)

    dow_order = ['月', '火', '水', '木', '金', '土', '日']
    dow_data = df_filtered_copy.groupby('day_name')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    dow_data = dow_data.reindex(dow_order)

    with col1:
        fig1 = px.bar(
            x=dow_data.index,
            y=dow_data['win_rate'],
            title='📊 曜日別勝率',
            labels={'x': '曜日', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color=COLORS['secondary_blue'])
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=dow_data.index,
            y=dow_data['avg_games_per_machine'],
            title='🎲 曜日別平均G数',
            labels={'x': '曜日', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color=COLORS['secondary_orange'])
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=dow_data.index,
            y=dow_data['avg_diff_per_machine'],
            title='💰 曜日別平均差枚',
            labels={'x': '曜日', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color=COLORS['secondary_green'])
        st.plotly_chart(fig3, use_container_width=True)

    # テーブル表示
    premium_divider()
    st.markdown("### 📋 曜日別詳細統計")

    summary_data = []
    for dow in dow_order:
        dow_subset = df_filtered_copy[df_filtered_copy['day_name'] == dow]
        if not dow_subset.empty:
            summary_data.append({
                '曜日': dow,
                '平均勝率': float(dow_subset['win_rate'].mean()),
                '平均G数': int(dow_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(dow_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(dow_subset)
            })

    df_dow_display = pd.DataFrame(summary_data)

    # 勝率を小数点第1位でフォーマット
    df_dow_display_formatted = df_dow_display.copy()
    df_dow_display_formatted['平均勝率'] = df_dow_display['平均勝率'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(df_dow_display_formatted, use_container_width=True, hide_index=True)
