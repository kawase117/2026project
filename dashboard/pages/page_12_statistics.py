"""
Page 12: 統計情報
詳細統計情報の表示
"""

import streamlit as st
import pandas as pd

from ..design_system import section_title, premium_divider, COLORS


def render():
    """統計情報のページを描画"""
    section_title("統計情報", "詳細な統計情報を表示します")

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

    # 統計量計算
    st.markdown("### 📊 勝率の統計")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("平均", f"{df_filtered['win_rate'].mean():.1f}%")
    with col2:
        st.metric("中央値", f"{df_filtered['win_rate'].median():.1f}%")
    with col3:
        st.metric("標準偏差", f"{df_filtered['win_rate'].std():.1f}%")
    with col4:
        st.metric("最大値", f"{df_filtered['win_rate'].max():.1f}%")

    st.markdown("### 🎲 平均G数の統計")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("平均", f"{int(df_filtered['avg_games_per_machine'].mean()):,}G")
    with col2:
        st.metric("中央値", f"{int(df_filtered['avg_games_per_machine'].median()):,}G")
    with col3:
        st.metric("標準偏差", f"{int(df_filtered['avg_games_per_machine'].std()):,}G")
    with col4:
        st.metric("最大値", f"{int(df_filtered['avg_games_per_machine'].max()):,}G")

    st.markdown("### 💰 平均差枚の統計")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("平均", f"{int(df_filtered['avg_diff_per_machine'].mean()):,}枚")
    with col2:
        st.metric("中央値", f"{int(df_filtered['avg_diff_per_machine'].median()):,}枚")
    with col3:
        st.metric("標準偏差", f"{int(df_filtered['avg_diff_per_machine'].std()):,}枚")
    with col4:
        st.metric("最大値", f"{int(df_filtered['avg_diff_per_machine'].max()):,}枚")

    st.markdown("### 🤖 稼働台数の統計")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("平均", f"{int(df_filtered['total_machines'].mean())}台")
    with col2:
        st.metric("中央値", f"{int(df_filtered['total_machines'].median())}台")
    with col3:
        st.metric("標準偏差", f"{int(df_filtered['total_machines'].std())}台")
    with col4:
        st.metric("最大値", f"{int(df_filtered['total_machines'].max())}台")

    # データ概要
    premium_divider()
    st.markdown("### 📋 データ概要")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("分析期間",
                  f"{df_filtered['date'].min().strftime('%Y-%m-%d')} 〜 {df_filtered['date'].max().strftime('%Y-%m-%d')}")

    with col2:
        st.metric("データ件数", f"{len(df_filtered)}件")

    with col3:
        st.metric("データ範囲", f"{(df_filtered['date'].max() - df_filtered['date'].min()).days}日間")

    # 統計テーブル
    premium_divider()
    st.markdown("### 📊 詳細統計テーブル")

    stats_data = {
        '指標': ['勝率(%)', '平均G数', '平均差枚', '稼働台数'],
        '平均': [
            f"{df_filtered['win_rate'].mean():.1f}",
            f"{int(df_filtered['avg_games_per_machine'].mean())}",
            f"{int(df_filtered['avg_diff_per_machine'].mean())}",
            f"{int(df_filtered['total_machines'].mean())}"
        ],
        '中央値': [
            f"{df_filtered['win_rate'].median():.1f}",
            f"{int(df_filtered['avg_games_per_machine'].median())}",
            f"{int(df_filtered['avg_diff_per_machine'].median())}",
            f"{int(df_filtered['total_machines'].median())}"
        ],
        '標準偏差': [
            f"{df_filtered['win_rate'].std():.1f}",
            f"{int(df_filtered['avg_games_per_machine'].std())}",
            f"{int(df_filtered['avg_diff_per_machine'].std())}",
            f"{int(df_filtered['total_machines'].std())}"
        ],
        '最小値': [
            f"{df_filtered['win_rate'].min():.1f}",
            f"{int(df_filtered['avg_games_per_machine'].min())}",
            f"{int(df_filtered['avg_diff_per_machine'].min())}",
            f"{int(df_filtered['total_machines'].min())}"
        ],
        '最大値': [
            f"{df_filtered['win_rate'].max():.1f}",
            f"{int(df_filtered['avg_games_per_machine'].max())}",
            f"{int(df_filtered['avg_diff_per_machine'].max())}",
            f"{int(df_filtered['total_machines'].max())}"
        ]
    }

    df_stats = pd.DataFrame(stats_data)
    st.dataframe(df_stats, use_container_width=True, hide_index=True)
