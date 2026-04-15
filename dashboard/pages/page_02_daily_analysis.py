"""
Page 2: 日別分析
毎日の3指標の詳細な推移を表示
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..design_system import section_title, premium_divider, COLORS


def render():
    """日別分析のページを描画"""
    section_title("日別分析", "毎日の3指標の詳細な推移を表示します")

    # session_state からフィルタ情報を取得
    df = st.session_state.df_hall_summary
    date_range = st.session_state.date_range
    min_games = st.session_state.min_games

    if df.empty:
        st.warning("⚠️ データが見つかりません")
        return

    # フィルタリング
    df_filtered = df[
        (df['date'] >= date_range[0]) &
        (df['date'] <= date_range[1])
    ]

    if not st.session_state.show_low_confidence:
        df_filtered = df_filtered[df_filtered['avg_games_per_machine'] >= min_games]

    if df_filtered.empty:
        st.warning("⚠️ フィルタ条件に合致するデータがありません")
        return

    col1, col2 = st.columns(2)

    with col1:
        # 勝率の日別推移
        fig_win = px.line(
            df_filtered,
            x='date',
            y='win_rate',
            title='📊 勝率の推移',
            markers=True,
            labels={'date': '日付', 'win_rate': '勝率(%)'}
        )
        fig_win.update_traces(line_color=COLORS['secondary_blue'], marker_size=6)
        fig_win.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_win, use_container_width=True)

    with col2:
        # G数の日別推移
        fig_games = px.line(
            df_filtered,
            x='date',
            y='avg_games_per_machine',
            title='🎲 平均G数の推移',
            markers=True,
            labels={'date': '日付', 'avg_games_per_machine': '平均G数'}
        )
        fig_games.update_traces(line_color=COLORS['secondary_orange'], marker_size=6)
        fig_games.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_games, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        # 差枚の日別推移
        fig_diff = px.line(
            df_filtered,
            x='date',
            y='avg_diff_per_machine',
            title='💰 平均差枚の推移',
            markers=True,
            labels={'date': '日付', 'avg_diff_per_machine': '平均差枚'}
        )
        fig_diff.update_traces(line_color=COLORS['secondary_green'], marker_size=6)
        fig_diff.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_diff, use_container_width=True)

    with col4:
        # 稼働台数の推移
        fig_machines = px.bar(
            df_filtered,
            x='date',
            y='total_machines',
            title='🤖 稼働台数の推移',
            labels={'date': '日付', 'total_machines': '稼働台数'}
        )
        fig_machines.update_traces(marker_color=COLORS['secondary_red'])
        fig_machines.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_machines, use_container_width=True)

    # 統計情報
    premium_divider()
    st.markdown("### 📊 統計情報")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("平均勝率", f"{df_filtered['win_rate'].mean():.1f}%")
        st.metric("勝率 (最高)", f"{df_filtered['win_rate'].max():.1f}%")
        st.metric("勝率 (最低)", f"{df_filtered['win_rate'].min():.1f}%")

    with col2:
        st.metric("平均G数", f"{int(df_filtered['avg_games_per_machine'].mean()):,}G")
        st.metric("G数 (最高)", f"{int(df_filtered['avg_games_per_machine'].max()):,}G")
        st.metric("G数 (最低)", f"{int(df_filtered['avg_games_per_machine'].min()):,}G")

    with col3:
        st.metric("平均差枚", f"{int(df_filtered['avg_diff_per_machine'].mean()):,}枚")
        st.metric("差枚 (最高)", f"{int(df_filtered['avg_diff_per_machine'].max()):,}枚")
        st.metric("差枚 (最低)", f"{int(df_filtered['avg_diff_per_machine'].min()):,}枚")
