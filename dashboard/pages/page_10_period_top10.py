"""
Page 10: 期間TOP10分析
指定期間トータルのTOP10
"""

import streamlit as st
import pandas as pd

from ..utils.data_loader import load_machine_detailed_results


def render():
    """期間TOP10分析のページを描画"""
    st.markdown("## 期間TOP10分析")
    st.markdown("指定期間トータルの差枚・勝率・G数でTOP10を表示します")

    date_range = st.session_state.date_range
    min_games = st.session_state.min_games

    # 期間内のすべての個別台データを集計
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))

    if all_machines.empty:
        st.warning("⚠️ 個別台データが見つかりません")
        return

    # 日付でフィルタ
    all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
    all_machines_filtered = all_machines[
        (all_machines['date'] >= date_range[0]) &
        (all_machines['date'] <= date_range[1])
    ]

    if all_machines_filtered.empty:
        st.warning("⚠️ 指定期間にデータがありません")
        return

    # 台ごとに集計
    machine_summary = all_machines_filtered.groupby(['machine_number', 'machine_name']).agg({
        'games_normalized': 'sum',
        'diff_coins_normalized': ['sum', 'mean', 'count'],
    }).round(2)

    machine_summary.columns = ['total_games', 'total_diff', 'avg_diff', 'play_days']
    machine_summary = machine_summary.reset_index()

    # min_games フィルタを適用
    if not st.session_state.show_low_confidence:
        machine_summary = machine_summary[machine_summary['total_games'] >= min_games]

    # 差枚でソート
    machine_summary_diff = machine_summary.nlargest(10, 'total_diff')
    machine_summary_games = machine_summary.nlargest(10, 'total_games')
    machine_summary_win = machine_summary.nlargest(10, 'avg_diff')

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
        for idx, row in machine_summary_win.iterrows():
            display_data.append({
                '順位': len(display_data) + 1,
                '台番号': int(row['machine_number']),
                '機種': row['machine_name'],
                '平均差枚': int(row['avg_diff']),
                '稼働日数': int(row['play_days'])
            })
        df_win_display = pd.DataFrame(display_data)
        st.dataframe(df_win_display, use_container_width=True, hide_index=True)

    # 全表示テーブル
    st.markdown("---")
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
