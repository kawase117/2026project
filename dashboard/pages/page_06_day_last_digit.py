"""
Page 6: 日末日別分析
日付の末尾数字ごとの性能パターン
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..design_system import section_title, premium_divider, COLORS


def render():
    """日末日別分析のページを描画"""
    section_title("日末日別分析", "日付の末尾数字ごとの性能パターンを分析します")

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

    # 末尾別集計
    df_filtered_copy = df_filtered.copy()
    df_filtered_copy['day_last_digit'] = df_filtered_copy['date'].dt.strftime('%d').str[-1].astype(int)

    # グラフ表示
    col1, col2, col3 = st.columns(3)

    digit_order = sorted(df_filtered_copy['day_last_digit'].unique())
    digit_data = df_filtered_copy.groupby('day_last_digit')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    digit_data = digit_data.reindex(digit_order)

    with col1:
        fig1 = px.bar(
            x=digit_data.index.astype(str),
            y=digit_data['win_rate'],
            title='📊 末尾別勝率',
            labels={'x': '日付末尾', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color=COLORS['secondary_blue'])
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=digit_data.index.astype(str),
            y=digit_data['avg_games_per_machine'],
            title='🎲 末尾別平均G数',
            labels={'x': '日付末尾', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color=COLORS['secondary_orange'])
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=digit_data.index.astype(str),
            y=digit_data['avg_diff_per_machine'],
            title='💰 末尾別平均差枚',
            labels={'x': '日付末尾', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color=COLORS['secondary_green'])
        st.plotly_chart(fig3, use_container_width=True)

    # テーブル表示
    premium_divider()
    st.markdown("### 📋 日末尾別詳細統計")

    table_data = []
    for digit in digit_order:
        digit_subset = df_filtered_copy[df_filtered_copy['day_last_digit'] == digit]
        if not digit_subset.empty:
            table_data.append({
                '末尾': digit,
                '平均勝率': float(digit_subset['win_rate'].mean()),
                '平均G数': int(digit_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(digit_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(digit_subset)
            })

    df_dd_display = pd.DataFrame(table_data)

    # 勝率を小数点第1位でフォーマット
    df_dd_display_formatted = df_dd_display.copy()
    df_dd_display_formatted['平均勝率'] = df_dd_display['平均勝率'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(df_dd_display_formatted, use_container_width=True, hide_index=True)
