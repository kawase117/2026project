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


def generate_validation_table(
    df_test: pd.DataFrame,
    training_stats: Dict,
    pattern_name: str,
    group_cols: list,
    train_data: pd.DataFrame
) -> pd.DataFrame:
    """
    検証テーブル生成（左：過去 | 中央：4月毎日 | 右：集計）
    """
    # 検証指標計算
    rankings = compute_top_percentile_rankings(training_stats)
    validation_df = compute_validation_metrics(
        df_test, rankings, pattern_name, group_cols
    )

    # 訓練データの過去統計を追加（左側）
    train_agg = train_data.groupby(group_cols, as_index=False).agg({
        'diff_coins_normalized': 'mean',
        'games_normalized': 'mean'
    })

    # 結合
    result = validation_df.copy()

    # 過去のランク情報を左側に追加
    training_stats_df = training_stats[pattern_name].copy()
    training_stats_df = training_stats_df.rename(columns={
        'diff_coins_normalized_mean': '過去差枚',
        'games_normalized_mean': '過去G数',
        'win_rate': '過去勝率',
        'diff_coins_normalized_count': '出現回数'
    })

    # マージ
    merge_cols = group_cols
    result = result.merge(training_stats_df[merge_cols + ['過去勝率', '過去差枚', '過去G数', '出現回数']],
                          on=merge_cols, how='left')

    # 右側の集計（TOP20%維持率など）を計算
    test_dates = sorted([c for c in result.columns if c.startswith('d_')])

    def calc_top20_ratio(row):
        count = sum(1 for d in test_dates if row.get(d) and row[d].get('rank20') == '✓')
        return f"{count}/{len(test_dates)}" if test_dates else "N/A"

    def calc_top10_ratio(row):
        count = sum(1 for d in test_dates if row.get(d) and row[d].get('rank10') == '✓')
        return f"{count}/{len(test_dates)}" if test_dates else "N/A"

    def calc_profit_ratio(row):
        count = sum(1 for d in test_dates if row.get(d) and row[d].get('profit') == '✓')
        return f"{count}/{len(test_dates)}" if test_dates else "N/A"

    result['TOP20%維持率'] = result.apply(calc_top20_ratio, axis=1)
    result['TOP10%維持率'] = result.apply(calc_top10_ratio, axis=1)
    result['利益性維持率'] = result.apply(calc_profit_ratio, axis=1)

    # カラム順序整理（左 | 中央日付 | 右集計）
    left_cols = group_cols + ['過去勝率', '過去差枚', '過去G数', '出現回数']
    right_cols = ['TOP20%維持率', 'TOP10%維持率', '利益性維持率']
    middle_cols = test_dates

    final_cols = left_cols + middle_cols + right_cols
    result = result[[c for c in final_cols if c in result.columns]]

    return result


def render_validation_table(
    df_test: pd.DataFrame,
    training_stats: Dict,
    pattern_name: str,
    group_cols: list,
    train_data: pd.DataFrame
):
    """
    検証テーブルをStreamlitで表示（ソート・フィルタ付き）
    """
    table_df = generate_validation_table(df_test, training_stats, pattern_name, group_cols, train_data)

    st.markdown(f"### テーブル: {pattern_name}")

    # ソートオプション
    sort_col = st.selectbox(
        f"ソート対象（{pattern_name}）",
        options=table_df.columns,
        key=f"sort_{pattern_name}",
        index=0
    )

    # フィルタオプション（信頼度による絞込）
    if 'TOP20%維持率' in table_df.columns:
        min_ratio = st.slider(
            f"最小TOP20%維持率（{pattern_name}）",
            min_value=0,
            max_value=20,
            value=5,
            step=1,
            key=f"filter_{pattern_name}"
        )
        # フィルタ適用
        table_df = table_df[
            table_df['TOP20%維持率'].str.extract(r'(\d+)', expand=False).astype(int) >= min_ratio
        ]

    # ソート適用
    table_df = table_df.sort_values(by=sort_col, ascending=False, key=abs)

    # 表示（スクロール可能）
    st.dataframe(table_df, use_container_width=True)


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

    # 3つのDD別パターンを表示
    patterns = [
        ('dd_tail', ['dd', 'last_digit'], 'DD × 台末尾'),
        ('dd_machine', ['dd', 'machine_number'], 'DD × 台番号'),
        ('dd_type', ['dd', 'machine_name'], 'DD × 機種'),
        # ('weekday_tail', ['weekday', 'last_digit'], '曜日 × 台末尾'),  # Task 8で実装
        # ('weekday_machine', ['weekday', 'machine_number'], '曜日 × 台番号'),
        # ('weekday_type', ['weekday', 'machine_name'], '曜日 × 機種'),
    ]

    for pattern_name, group_cols, display_name in patterns:
        st.markdown("---")
        st.subheader(f"📈 {display_name} 分析")

        col1, col2 = st.columns(2)

        with col1:
            render_confidence_ranking_chart(rankings, pattern_name)
        with col2:
            render_metrics_distribution_chart(training_stats, pattern_name)

        render_heatmap_chart(training_stats, pattern_name)

        render_validation_table(df_all, training_stats, pattern_name, group_cols, df_all)
