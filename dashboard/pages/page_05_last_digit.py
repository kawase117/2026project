"""
Page 5: 末尾別分析
台番号末尾ごとの性能パターン
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.data_loader import load_last_digit_summary, load_machine_detailed_results
from ..utils.filters import apply_sidebar_filters, filter_by_date_range
from ..design_system import section_title, premium_divider, COLORS


def render():
    """末尾別分析のページを描画"""
    section_title("末尾別分析", "台番号末尾ごとの性能パターンを分析します")

    machine_type = st.session_state.machine_type

    df_last_digit = load_last_digit_summary(str(st.session_state.db_path), machine_type)

    if df_last_digit.empty:
        st.warning(f"末尾別データが利用できません（機種: {machine_type}）")
        return

    df_last_digit_filtered = apply_sidebar_filters(
        df_last_digit,
        date_range=st.session_state.date_range,
        min_games=st.session_state.min_games,
        show_low_confidence=st.session_state.show_low_confidence,
        games_column='avg_games',
    )

    if df_last_digit_filtered.empty:
        st.warning("⚠️ フィルタ条件に合致するデータがありません")
        return

    # 末尾ごとの平均値
    df_ld_summary = df_last_digit_filtered.groupby('last_digit').agg({
        'win_rate': 'mean',
        'avg_games': 'mean',
        'avg_diff_coins': 'mean',
        'machine_count': 'mean'
    }).round(2).sort_index()

    col1, col2, col3 = st.columns(3)

    with col1:
        fig1 = px.bar(
            x=df_ld_summary.index.astype(str),
            y=df_ld_summary['win_rate'],
            title='📊 末尾別勝率',
            labels={'x': '末尾', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color=COLORS['secondary_blue'])
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=df_ld_summary.index.astype(str),
            y=df_ld_summary['avg_games'],
            title='🎲 末尾別平均G数',
            labels={'x': '末尾', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color=COLORS['secondary_orange'])
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=df_ld_summary.index.astype(str),
            y=df_ld_summary['avg_diff_coins'],
            title='💰 末尾別平均差枚',
            labels={'x': '末尾', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color=COLORS['secondary_green'])
        st.plotly_chart(fig3, use_container_width=True)

    # テーブル表示
    premium_divider()
    st.markdown("### 📋 末尾別詳細統計")

    table_data = []
    for digit in sorted(df_ld_summary.index):
        row = df_ld_summary.loc[digit]
        table_data.append({
            '末尾': str(digit),
            '平均勝率': float(row['win_rate']),
            '平均G数': int(row['avg_games']),
            '平均差枚': int(row['avg_diff_coins']),
            '平均台数': int(row['machine_count'])
        })

    # ゾロ目の集計（個別台データから）
    # ゾロ目は台数が少ないため min_games フィルタを適用しない（日付範囲のみ適用）
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))
    if not all_machines.empty:
        all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
        all_machines_date_filtered = filter_by_date_range(all_machines, st.session_state.date_range)
        zorome_machines = all_machines_date_filtered[all_machines_date_filtered['is_zorome'] == 1]
        if not zorome_machines.empty:
            zorome_win_rate = (zorome_machines['diff_coins_normalized'] > 0).sum() / len(zorome_machines) * 100
            table_data.append({
                '末尾': 'ゾロ目',
                '平均勝率': float(zorome_win_rate),
                '平均G数': int(zorome_machines['games_normalized'].mean()),
                '平均差枚': int(zorome_machines['diff_coins_normalized'].mean()),
                '平均台数': len(zorome_machines['machine_number'].unique())
            })

    df_ld_display = pd.DataFrame(table_data)

    # 勝率を小数点第1位でフォーマット
    df_ld_display_formatted = df_ld_display.copy()
    df_ld_display_formatted['平均勝率'] = df_ld_display['平均勝率'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(df_ld_display_formatted, use_container_width=True, hide_index=True)
