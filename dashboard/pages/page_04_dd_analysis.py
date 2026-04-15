"""
Page 4: DD別分析
月内の日付位置別分析
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.filters import apply_sidebar_filters
from ..design_system import section_title, premium_divider, COLORS


def render():
    """DD別分析のページを描画"""
    section_title("DD別分析（月内の日付位置別）", "各月の同じ日付（1日、2日...31日）でのパターンを比較します")

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

    # 日付を抽出
    df_filtered_copy = df_filtered.copy()
    df_filtered_copy['day_of_month'] = df_filtered_copy['date'].dt.day

    # グラフ表示
    col1, col2, col3 = st.columns(3)

    dd_order = sorted(df_filtered_copy['day_of_month'].unique())
    dd_data = df_filtered_copy.groupby('day_of_month')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    dd_data = dd_data.reindex(dd_order)

    with col1:
        fig1 = px.bar(
            x=[f"{d}日" for d in dd_data.index],
            y=dd_data['win_rate'],
            title='📊 DD別勝率',
            labels={'x': '日付', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color=COLORS['secondary_blue'])
        fig1.update_xaxes(tickangle=-45)
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=[f"{d}日" for d in dd_data.index],
            y=dd_data['avg_games_per_machine'],
            title='🎲 DD別平均G数',
            labels={'x': '日付', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color=COLORS['secondary_orange'])
        fig2.update_xaxes(tickangle=-45)
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=[f"{d}日" for d in dd_data.index],
            y=dd_data['avg_diff_per_machine'],
            title='💰 DD別平均差枚',
            labels={'x': '日付', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color=COLORS['secondary_green'])
        fig3.update_xaxes(tickangle=-45)
        st.plotly_chart(fig3, use_container_width=True)

    # テーブル表示
    premium_divider()
    st.markdown("### 📋 DD別詳細統計")

    table_data = []
    for dd in dd_order:
        dd_subset = df_filtered_copy[df_filtered_copy['day_of_month'] == dd]
        if not dd_subset.empty:
            table_data.append({
                '日付': f"{dd}日",
                '平均勝率': float(dd_subset['win_rate'].mean()),
                '平均G数': int(dd_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(dd_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(dd_subset)
            })

    df_dd_display = pd.DataFrame(table_data)

    # 勝率を小数点第1位でフォーマット
    df_dd_display_formatted = df_dd_display.copy()
    df_dd_display_formatted['平均勝率'] = df_dd_display['平均勝率'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(df_dd_display_formatted, use_container_width=True, hide_index=True)
