"""
Page 1: ホール全体
ホール全体の傾向分析
"""

import streamlit as st
import pandas as pd
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from ..utils.data_loader import load_daily_hall_summary
from ..design_system import metric_card, section_title, premium_divider, COLORS


def render():
    """ホール全体のページを描画"""
    section_title("ホール全体の傾向", "最新データの概要と主要指標の推移を表示します")

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

    # 最新日付のデータ
    latest_date = df_filtered['date'].max()
    latest_data = df_filtered[df_filtered['date'] == latest_date].iloc[0]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        metric_card(
            "勝率",
            f"{latest_data['win_rate']:.1f}%",
            icon="📊"
        )

    with col2:
        metric_card(
            "平均G数",
            f"{int(latest_data['avg_games_per_machine']):,}G",
            icon="🎲"
        )

    with col3:
        metric_card(
            "平均差枚",
            f"{int(latest_data['avg_diff_per_machine']):,}枚",
            icon="💰"
        )

    with col4:
        metric_card(
            "稼働台数",
            f"{int(latest_data['total_machines'])}台",
            icon="🤖"
        )

    premium_divider()

    # 3指標の時系列グラフ
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        subplot_titles=("勝率", "平均G数", "平均差枚"),
        vertical_spacing=0.1
    )

    # 第1行: 勝率
    fig.add_trace(
        go.Scatter(
            x=df_filtered['date'],
            y=df_filtered['win_rate'],
            name='勝率 (%)',
            line=dict(color=COLORS['secondary_blue'], width=2)
        ),
        row=1, col=1
    )

    # 第2行: G数
    fig.add_trace(
        go.Scatter(
            x=df_filtered['date'],
            y=df_filtered['avg_games_per_machine'],
            name='平均G数',
            line=dict(color=COLORS['secondary_orange'], width=2)
        ),
        row=2, col=1
    )

    # 第3行: 差枚
    fig.add_trace(
        go.Scatter(
            x=df_filtered['date'],
            y=df_filtered['avg_diff_per_machine'],
            name='平均差枚',
            line=dict(color=COLORS['secondary_green'], width=2)
        ),
        row=3, col=1
    )

    fig.update_yaxes(title_text="勝率(%)", row=1, col=1)
    fig.update_yaxes(title_text="平均G数", row=2, col=1)
    fig.update_yaxes(title_text="平均差枚", row=3, col=1)
    fig.update_xaxes(title_text="日付", row=3, col=1)

    fig.update_layout(title_text="📈 3指標の時系列推移", height=700)

    st.plotly_chart(fig, use_container_width=True)

    # 最新データテーブル
    st.markdown("### 📋 最新30日間のサマリー")
    display_cols = ['date', 'win_rate', 'avg_games_per_machine', 'avg_diff_per_machine', 'total_machines']
    display_df = df_filtered[display_cols].copy()
    display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
    display_df.columns = ['日付', '勝率(%)', '平均G数', '平均差枚', '稼働台数']

    # 勝率をフォーマット
    display_df_formatted = display_df.copy()
    display_df_formatted['勝率(%)'] = display_df_formatted['勝率(%)'].astype(float).apply(lambda x: f"{x:.1f}%")
    display_df_formatted = display_df_formatted.drop('勝率(%)', axis=1)
    display_df_formatted.insert(1, '勝率(%)', display_df['勝率(%)'].astype(float).apply(lambda x: f"{x:.1f}%"))

    st.dataframe(display_df_formatted.iloc[::-1], use_container_width=True, height=400, hide_index=True)
