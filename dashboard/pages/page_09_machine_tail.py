"""
Page 9: 台番号末尾別分析
末尾別の期間集計＋ゾロ目分析（機種タイプ対応）
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.data_loader import load_machine_detailed_results, load_last_digit_summary


def render():
    """台番号末尾別分析のページを描画"""
    st.markdown("## 台番号末尾別分析")
    st.markdown("台番号の末尾（0-9）ごと、ゾロ目（同じ数字が複数）の性能を、指定期間で集計して分析します")

    date_range = st.session_state.date_range
    min_games = st.session_state.min_games
    machine_type = st.session_state.machine_type

    # 機種タイプの末尾別集計データを取得
    df_last_digit = load_last_digit_summary(str(st.session_state.db_path), machine_type)

    if df_last_digit.empty:
        st.warning(f"⚠️ 末尾別データが利用できません（機種: {machine_type}）")
        return

    # 日付でフィルタ
    df_last_digit_filtered = df_last_digit[
        (df_last_digit['date'] >= date_range[0]) &
        (df_last_digit['date'] <= date_range[1])
    ]

    if not st.session_state.show_low_confidence:
        df_last_digit_filtered = df_last_digit_filtered[df_last_digit_filtered['avg_games'] >= min_games]

    if df_last_digit_filtered.empty:
        st.warning("⚠️ フィルタ条件に合致するデータがありません")
        return

    # 末尾ごとの平均値
    tail_summary = df_last_digit_filtered.groupby('last_digit').agg({
        'win_rate': 'mean',
        'avg_games': 'mean',
        'avg_diff_coins': 'mean',
        'machine_count': 'mean'
    }).round(2).sort_index()

    # 期間内のすべての個別台データを集計（ゾロ目用）
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

    # ゾロ目用のコピー
    df_machines = all_machines_filtered.copy()

    # グラフ表示
    col1, col2, col3 = st.columns(3)

    tail_order = sorted(tail_summary.index)

    with col1:
        fig1 = px.bar(
            x=tail_order,
            y=[tail_summary.loc[t, 'avg_games'] for t in tail_order],
            title='🎲 末尾別平均G数',
            labels={'x': '台番号末尾', 'y': '平均G数'}
        )
        fig1.update_traces(marker_color='#ff7f0e')
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=tail_order,
            y=[tail_summary.loc[t, 'avg_diff_coins'] for t in tail_order],
            title='💰 末尾別平均差枚',
            labels={'x': '台番号末尾', 'y': '平均差枚'}
        )
        fig2.update_traces(marker_color='#2ca02c')
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=tail_order,
            y=[tail_summary.loc[t, 'machine_count'] for t in tail_order],
            title='🤖 末尾別台数',
            labels={'x': '台番号末尾', 'y': '台数'}
        )
        fig3.update_traces(marker_color='#d62728')
        st.plotly_chart(fig3, use_container_width=True)

    # テーブル表示
    st.markdown("---")
    st.markdown("### 📋 台番号末尾別詳細統計")

    table_data = []

    # 末尾0-9の集計
    for tail in tail_order:
        row = tail_summary.loc[tail]
        table_data.append({
            '末尾': int(tail),
            '勝率': float(row['win_rate']),
            '平均G数': int(row['avg_games']),
            '平均差枚': int(row['avg_diff_coins']),
            '台数': int(row['machine_count'])
        })

    # ゾロ目（is_zorome=1）の集計（個別台データから）
    if 'is_zorome' in df_machines.columns:
        zorome_machines = df_machines[df_machines['is_zorome'] == 1]
        if not zorome_machines.empty:
            zorome_avg_games = zorome_machines['games_normalized'].mean()
            # min_games フィルタを適用（show_low_confidence が False の場合）
            if st.session_state.show_low_confidence or zorome_avg_games >= min_games:
                zorome_win_rate = (zorome_machines['diff_coins_normalized'] > 0).sum() / len(zorome_machines) * 100
                # ゾロ目台数を重複排除で計算（unique な machine_number の数）
                zorome_count = len(zorome_machines['machine_number'].unique())
                table_data.append({
                    '末尾': 'ゾロ目',
                    '勝率': float(zorome_win_rate),
                    '平均G数': int(zorome_avg_games),
                    '平均差枚': int(zorome_machines['diff_coins_normalized'].mean()),
                    '台数': zorome_count
                })

    df_tail_display = pd.DataFrame(table_data)

    # 勝率を小数点第1位でフォーマット
    df_tail_display_formatted = df_tail_display.copy()
    df_tail_display_formatted['勝率'] = df_tail_display['勝率'].apply(lambda x: f"{x:.1f}%")

    st.dataframe(df_tail_display_formatted, use_container_width=True, hide_index=True)
