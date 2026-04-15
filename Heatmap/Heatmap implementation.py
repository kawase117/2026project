"""
ホール配置図ヒートマップ実装スクリプト
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta
import sqlite3
import os
from pathlib import Path

# ==========================================
# ファイルパス設定
# ==========================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COORDS_FILE = os.path.join(SCRIPT_DIR, '2F_floor_coordinates.csv')

# DBパスを設定（あなたの環境に合わせて修正）
# 【ここを修正してください】
DB_PATH = r'C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田1.db'
# または具体的に
# DB_PATH = r'C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田1.db'

# ファイルの存在確認
if not os.path.exists(COORDS_FILE):
    st.error(f"❌ 座標ファイルが見つかりません: {COORDS_FILE}")
    st.stop()

if not os.path.exists(DB_PATH):
    st.error(f"❌ DBファイルが見つかりません: {DB_PATH}")
    st.stop()

# ==========================================
# Page: ヒートマップ（機械の配置図）
# ==========================================

st.markdown("## 🗺️ ホール配置図ヒートマップ")
st.markdown("台番号の配置と性能を可視化します")

# 1. 座標情報を読み込み
coords_df = pd.read_csv(COORDS_FILE)
coords_df['machine_number'] = coords_df['machine_number'].astype(int)

# 2. DBから性能データを取得
try:
    all_machines = pd.read_sql_query(
        "SELECT * FROM machine_detailed_results ORDER BY date DESC",
        sqlite3.connect(DB_PATH)
    )
except Exception as e:
    st.error(f"❌ DBエラー: {e}")
    st.stop()

if all_machines.empty:
    st.warning("⚠️ 個別台データが見つかりません")
else:
    # 日付フィルタ
    date_range = st.date_input(
        "分析期間",
        value=(datetime.now() - timedelta(days=30), datetime.now()),
        key="heatmap_date_range"
    )
    
    all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
    
    all_machines_filtered = all_machines[
        (all_machines['date'] >= pd.Timestamp(date_range[0])) &
        (all_machines['date'] <= pd.Timestamp(date_range[1]))
    ]
    
    if all_machines_filtered.empty:
        st.warning("⚠️ 指定期間にデータがありません")
    else:
        # 性能指標を選択
        metric = st.radio(
            "表示する指標",
            ["勝率(%)", "平均差枚", "平均G数"],
            key="heatmap_metric"
        )
        
        # 台番号ごとの統計を計算
        machine_stats = all_machines_filtered.groupby('machine_number').agg({
            'diff_coins_normalized': ['mean', lambda x: (x > 0).sum() / len(x) * 100],
            'games_normalized': 'mean'
        }).round(2)
        
        machine_stats.columns = ['avg_diff', 'win_rate', 'avg_games']
        machine_stats = machine_stats.reset_index()
        
        # 座標情報とマージ
        heatmap_data = coords_df.merge(
            machine_stats,
            on='machine_number',
            how='left'
        )
        
        # 選択された指標のマッピング
        if metric == "勝率(%)":
            metric_col = 'win_rate'
            metric_label = '勝率(%)'
            colorscale = 'RdYlGn'
            min_val = 0
            max_val = 100
        elif metric == "平均差枚":
            metric_col = 'avg_diff'
            metric_label = '平均差枚'
            colorscale = 'RdYlGn'
            min_val = heatmap_data[metric_col].min()
            max_val = heatmap_data[metric_col].max()
        else:  # 平均G数
            metric_col = 'avg_games'
            metric_label = '平均G数'
            colorscale = 'Blues'
            min_val = heatmap_data[metric_col].min()
            max_val = heatmap_data[metric_col].max()
        
        # ヒートマップ用の行列を作成
        max_x = int(heatmap_data['X'].max())
        max_y = int(heatmap_data['Y'].max())
        
        heatmap_matrix = np.full((max_y, max_x), np.nan)
        machine_matrix = np.full((max_y, max_x), '', dtype=object)
        
        for _, row in heatmap_data.iterrows():
            x_idx = int(row['X']) - 1
            y_idx = int(row['Y']) - 1
            
            if not pd.isna(row[metric_col]):
                heatmap_matrix[y_idx, x_idx] = row[metric_col]
            
            machine_matrix[y_idx, x_idx] = str(int(row['machine_number']))
        
        # Plotlyヒートマップを作成
        fig = go.Figure(data=go.Heatmap(
            z=heatmap_matrix,  # ← 元のまま（逆順にしない）
            x=list(range(max_x, 0, -1)),
            y=list(range(max_y, 0, -1)),  
            colorscale=colorscale,
            customdata=machine_matrix,
            hovertemplate='<b>台番号: %{customdata}</b><br>' +
                        f'{metric_label}: %{{z:.1f}}<br>' +
                        '位置: X=%{x}, Y=%{y}<extra></extra>',
            zmin=min_val,
            zmax=max_val
        ))
        
        fig.update_layout(
            title=f'ホール配置図 - {metric_label}',
            xaxis_title='X座標（左→右）',
            yaxis_title='Y座標（下→上）',
            height=800,  # 高さを増やす
            hovermode='closest',
            yaxis=dict(autorange='reversed')
        )

        # 正方形セルにする
        fig.update_yaxes(scaleanchor="x", scaleratio=1)
        fig.update_xaxes(scaleanchor="y", scaleratio=1)
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 統計サマリー
        st.markdown("---")
        st.markdown("### 📊 統計サマリー")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "平均勝率",
                f"{machine_stats['win_rate'].mean():.1f}%"
            )
        
        with col2:
            st.metric(
                "平均差枚",
                f"{machine_stats['avg_diff'].mean():.0f}枚"
            )
        
        with col3:
            st.metric(
                "最高勝率",
                f"{machine_stats['win_rate'].max():.1f}%"
            )
        
        with col4:
            st.metric(
                "最高差枚",
                f"{machine_stats['avg_diff'].max():.0f}枚"
            )
        
        # TOP 10表示
        st.markdown("---")
        st.markdown("### 🏆 勝率TOP 10")
        
        top_10 = machine_stats.nlargest(10, 'win_rate')[['machine_number', 'win_rate', 'avg_diff', 'avg_games']]
        top_10.columns = ['台番号', '勝率(%)', '平均差枚', '平均G数']
        
        st.dataframe(top_10, use_container_width=True, hide_index=True)