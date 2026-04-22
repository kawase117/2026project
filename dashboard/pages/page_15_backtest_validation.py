# dashboard/pages/page_15_backtest_validation.py

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
import sys
from typing import Dict

# 相対インポート
from ..utils.data_loader import load_machine_detailed_results
from ..utils.backtest_helpers import (
    compute_training_stats,
    compute_top_percentile_rankings,
    compute_validation_metrics
)
from ..utils.charts import create_bar_chart


# データロード関数
@st.cache_data(ttl=3600)
def load_all_data(db_path):
    return load_machine_detailed_results(db_path)


def render_confidence_ranking_chart(rankings: Dict, pattern_name: str):
    """信頼度ランキングTOP10（勝率/差枚/G数別）"""
    if pattern_name not in rankings or len(rankings[pattern_name]) == 0:
        st.warning(f"パターン {pattern_name} のデータがありません")
        return

    metrics = ['win_rate', 'avg_diff', 'avg_games']
    data = []

    for metric in metrics:
        if metric not in rankings[pattern_name]:
            continue

        ranking_info = rankings[pattern_name][metric]
        threshold20 = ranking_info.get('threshold20', 0)
        count = len(ranking_info.get('top20', set()))

        data.append({
            'metric': f"{metric}",
            'count': count,
            'threshold': threshold20
        })

    if not data:
        st.info("有効なランキングデータがありません")
        return

    df_chart = pd.DataFrame(data)
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df_chart['metric'],
        y=df_chart['count'],
        text=df_chart['count'],
        textposition='auto',
        marker_color=['#1f77b4', '#ff7f0e', '#2ca02c']
    ))

    fig.update_layout(
        title=f"信頼度ランキングTOP10 ({pattern_name})",
        xaxis_title="指標",
        yaxis_title="TOP20%に入るパターン数",
        height=400,
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)


def render_metrics_distribution_chart(stats_dict: Dict[str, pd.DataFrame], pattern_name: str):
    """指標の分布（全パターンの平均）"""
    if pattern_name not in stats_dict:
        st.warning(f"パターン {pattern_name} のデータがありません")
        return

    df = stats_dict[pattern_name]

    fig = go.Figure()

    # 勝率の平均
    if 'win_rate' in df.columns:
        avg_wr = df['win_rate'].mean()
        fig.add_trace(go.Bar(name='勝率(%)', x=['勝率'], y=[avg_wr]))

    # 平均差枚の平均（正規化）
    if 'diff_coins_normalized_mean' in df.columns:
        avg_diff = df['diff_coins_normalized_mean'].mean()
        fig.add_trace(go.Bar(name='差枚(平均)', x=['差枚'], y=[avg_diff]))

    # 平均G数の平均（正規化）
    if 'games_normalized_mean' in df.columns:
        avg_games = df['games_normalized_mean'].mean()
        fig.add_trace(go.Bar(name='G数(平均)', x=['G数'], y=[avg_games]))

    fig.update_layout(
        title=f"指標の分布 ({pattern_name})",
        barmode='group',
        height=400,
        xaxis_title="指標",
        yaxis_title="値"
    )

    st.plotly_chart(fig, use_container_width=True)


def render_heatmap_chart(stats_dict: Dict[str, pd.DataFrame], pattern_name: str):
    """ヒートマップ（DD×台末尾の信頼度など）"""
    if pattern_name not in stats_dict:
        st.warning(f"パターン {pattern_name} のデータがありません")
        return

    df = stats_dict[pattern_name]

    # pattern_name から軸を判定
    if 'dd_tail' in pattern_name:
        x_col, y_col = 0, 1  # (dd, last_digit)
    elif 'dd_machine' in pattern_name:
        x_col, y_col = 0, 1  # (dd, machine_number)
    elif 'dd_type' in pattern_name:
        x_col, y_col = 0, 1  # (dd, machine_name)
    else:
        st.info("ヒートマップ非対応のパターンです")
        return

    # ピボットテーブル作成
    pivot = df.pivot_table(
        values='win_rate',
        index=df.columns[y_col],
        columns=df.columns[x_col],
        aggfunc='mean'
    )

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale='RdYlGn',
        zmid=50
    ))

    fig.update_layout(
        title=f"ヒートマップ信頼度 ({pattern_name})",
        xaxis_title=df.columns[x_col],
        yaxis_title=df.columns[y_col],
        height=500
    )

    st.plotly_chart(fig, use_container_width=True)


def render():
    """バックテスト検証ページを描画"""
    # ページタイトルと説明
    st.title("📊 バックテスト検証 (2026-01～03 → 2026-04)")
    st.write("過去3ヶ月のランキングが4月で再現するか検証します。ホール別・複数パターン分析。")

    # セッション状態からホール選択を取得
    if 'hall_name' not in st.session_state or 'db_path' not in st.session_state:
        st.error("ホールを選択してください（サイドバー）")
        st.stop()

    db_path = st.session_state.db_path

    # データロード
    df_all = load_all_data(db_path)

    st.write(f"**選択ホール:** {st.session_state.hall_name}")
    st.write(f"**データ件数:** {len(df_all):,}")

    # 訓練統計計算
    training_stats = compute_training_stats(df_all, "20260101", "20260331")
    rankings = compute_top_percentile_rankings(training_stats)

    st.success("✓ 訓練データ読込完了（1月～3月）")

    st.markdown("---")

    # 3つのパターンを表示
    patterns_dd = [
        ('dd_tail', 'DD × 台末尾'),
        ('dd_machine', 'DD × 台番号'),
        ('dd_type', 'DD × 機種'),
    ]

    for pattern_name, display_name in patterns_dd:
        st.markdown("---")
        st.subheader(f"📈 {display_name} 分析")

        col1, col2 = st.columns(2)

        with col1:
            render_confidence_ranking_chart(rankings, pattern_name)
        with col2:
            render_metrics_distribution_chart(training_stats, pattern_name)

        render_heatmap_chart(training_stats, pattern_name)
