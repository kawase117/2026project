"""
Page 7: 第X曜日別分析
各月の第N曜日パターン分析
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.filters import apply_sidebar_filters
from ..design_system import section_title, premium_divider, COLORS


def render():
    """第X曜日別分析のページを描画"""
    section_title("第X曜日別分析", "各月の第N曜日（例：第1月曜日、第2金曜日）のパターンを分析します")

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

    # weekday_nth 列を使用
    if 'weekday_nth' not in df_filtered.columns:
        st.warning("⚠️ weekday_nth データが利用できません")
        return

    df_weekday_nth = df_filtered.groupby('weekday_nth').agg({
        'win_rate': ['mean', 'std'],
        'avg_games_per_machine': ['mean', 'std'],
        'avg_diff_per_machine': ['mean', 'std'],
        'total_machines': 'mean'
    }).round(2)

    # グラフ表示（全パターン表示）
    weekday_nth_order = sorted(df_filtered['weekday_nth'].unique())
    weekday_nth_data = df_filtered.groupby('weekday_nth')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    weekday_nth_data = weekday_nth_data.reindex(weekday_nth_order)

    # 3つのグラフを縦並びで表示
    st.markdown("### 📊 第X曜日別勝率")
    fig1 = px.bar(
        x=weekday_nth_data.index.astype(str),
        y=weekday_nth_data['win_rate'],
        title='',
        labels={'x': '第X曜日', 'y': '勝率(%)'},
        height=400
    )
    fig1.update_traces(marker_color=COLORS['secondary_blue'])
    fig1.update_xaxes(tickangle=-45)
    st.plotly_chart(fig1, use_container_width=True)

    st.markdown("### 🎲 第X曜日別平均G数")
    fig2 = px.bar(
        x=weekday_nth_data.index.astype(str),
        y=weekday_nth_data['avg_games_per_machine'],
        title='',
        labels={'x': '第X曜日', 'y': '平均G数'},
        height=400
    )
    fig2.update_traces(marker_color=COLORS['secondary_orange'])
    fig2.update_xaxes(tickangle=-45)
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("### 💰 第X曜日別平均差枚")
    fig3 = px.bar(
        x=weekday_nth_data.index.astype(str),
        y=weekday_nth_data['avg_diff_per_machine'],
        title='',
        labels={'x': '第X曜日', 'y': '平均差枚'},
        height=400
    )
    fig3.update_traces(marker_color=COLORS['secondary_green'])
    fig3.update_xaxes(tickangle=-45)
    st.plotly_chart(fig3, use_container_width=True)

    # テーブル表示
    premium_divider()
    st.markdown("### 📋 第X曜日別詳細統計")

    table_data = []
    for nth in weekday_nth_order:
        nth_subset = df_filtered[df_filtered['weekday_nth'] == nth]
        if not nth_subset.empty:
            table_data.append({
                '第X曜日': nth,
                '平均勝率': float(nth_subset['win_rate'].mean()),
                '平均G数': int(nth_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(nth_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(nth_subset)
            })

    df_nth_display = pd.DataFrame(table_data)

    # 勝率を小数点第1位でフォーマット
    df_nth_display_formatted = df_nth_display.copy()
    df_nth_display_formatted['平均勝率'] = df_nth_display['平均勝率'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(df_nth_display_formatted, use_container_width=True, hide_index=True)
