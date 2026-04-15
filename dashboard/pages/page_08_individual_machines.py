"""
Page 8: 個別台分析
全期間TOP10の表示
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.data_loader import load_machine_detailed_results
from ..utils.filters import filter_by_date_range
from ..design_system import section_title, premium_divider, COLORS


def render():
    """個別台分析のページを描画"""
    section_title("個別台分析（全期間TOP10）", "指定期間における個別台の成績TOP10を表示します")

    # 期間内のすべての個別台データを集計
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))

    if all_machines.empty:
        st.warning("⚠️ 個別台データが見つかりません")
        return

    # 日付でフィルタ
    all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
    all_machines_filtered = filter_by_date_range(all_machines, st.session_state.date_range)

    if all_machines_filtered.empty:
        st.warning("⚠️ 指定期間にデータがありません")
        return

    # 台ごとに集計（すべての機種を表示）
    machine_summary = all_machines_filtered.groupby('machine_number').agg({
        'games_normalized': 'sum',
        'diff_coins_normalized': ['sum', 'mean', 'count'],
    }).round(2)

    machine_summary.columns = ['total_games', 'total_diff', 'avg_diff', 'play_days']
    machine_summary = machine_summary.reset_index()

    # min_games フィルタを適用
    if not st.session_state.show_low_confidence:
        machine_summary = machine_summary[machine_summary['total_games'] >= st.session_state.min_games]

    # すべての機種を取得（→ で連結）
    all_machine_names = all_machines_filtered.sort_values('date').groupby('machine_number')['machine_name'].apply(
        lambda x: ' → '.join(x.unique())
    )
    machine_summary['machine_name'] = machine_summary['machine_number'].map(all_machine_names)

    # 差枚でソート
    machine_summary_diff = machine_summary.nlargest(10, 'total_diff')
    machine_summary_games = machine_summary.nlargest(10, 'total_games')
    machine_summary_efficiency = machine_summary.nlargest(10, 'avg_diff')

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 💰 差枚TOP10")
        display_data = []
        for idx, row in machine_summary_diff.iterrows():
            display_data.append({
                '順位': len(display_data) + 1,
                '台番号': int(row['machine_number']),
                '機種': row['machine_name'],
                '差枚': int(row['total_diff']),
                'G数': int(row['total_games'])
            })
        df_diff_display = pd.DataFrame(display_data)
        st.dataframe(df_diff_display, use_container_width=True, hide_index=True)

    with col2:
        st.markdown("### 🎲 G数TOP10")
        display_data = []
        for idx, row in machine_summary_games.iterrows():
            display_data.append({
                '順位': len(display_data) + 1,
                '台番号': int(row['machine_number']),
                '機種': row['machine_name'],
                'G数': int(row['total_games']),
                '差枚': int(row['total_diff'])
            })
        df_games_display = pd.DataFrame(display_data)
        st.dataframe(df_games_display, use_container_width=True, hide_index=True)

    with col3:
        st.markdown("### 📊 平均差枚TOP10")
        display_data = []
        for idx, row in machine_summary_efficiency.iterrows():
            display_data.append({
                '順位': len(display_data) + 1,
                '台番号': int(row['machine_number']),
                '機種': row['machine_name'],
                '平均差枚': int(row['avg_diff']),
                '稼働日数': int(row['play_days'])
            })
        df_efficiency_display = pd.DataFrame(display_data)
        st.dataframe(df_efficiency_display, use_container_width=True, hide_index=True)

    # グラフ表示
    col1, col2 = st.columns(2)

    with col1:
        fig = px.bar(
            machine_summary_diff.head(10),
            x='machine_number',
            y='total_diff',
            color='machine_name',
            title='差枚TOP10',
            labels={'machine_number': '台番号', 'total_diff': '差枚'},
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = px.scatter(
            machine_summary,
            x='total_games',
            y='total_diff',
            color='machine_name',
            size='play_days',
            title='G数 vs 差枚',
            labels={'total_games': 'G数', 'total_diff': '差枚'},
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)

    # 全表示テーブル
    premium_divider()
    st.markdown("### 📋 全台詳細統計")

    all_display_data = []
    machine_summary_sorted = machine_summary.sort_values('avg_diff', ascending=False)
    for idx, row in machine_summary_sorted.iterrows():
        all_display_data.append({
            '台番号': int(row['machine_number']),
            '機種': row['machine_name'],
            '平均差枚': int(row['avg_diff']),
            '差枚': int(row['total_diff']),
            'G数': int(row['total_games']),
            '稼働日数': int(row['play_days'])
        })

    df_all_display = pd.DataFrame(all_display_data)
    st.dataframe(df_all_display, use_container_width=True, hide_index=True)
