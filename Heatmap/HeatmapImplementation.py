"""
ホール配置図ヒートマップ - 蒲田七 2F版 v1.0
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta
import sqlite3
import os

# ==========================================
# ファイルパス設定
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COORDS_FILE = os.path.join(SCRIPT_DIR, '2F_floor_coordinates_kamata7.csv')
DB_PATH = r'C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田7.db'

if not os.path.exists(COORDS_FILE):
    st.error(f"❌ 座標ファイルが見つかりません: {COORDS_FILE}")
    st.stop()
if not os.path.exists(DB_PATH):
    st.error(f"❌ DBファイルが見つかりません: {DB_PATH}")
    st.stop()

# ==========================================
# Page: ヒートマップ（蒲田七 2F）
# ==========================================
st.markdown("## 🗺️ ホール配置図ヒートマップ（蒲田七 2F）")
st.markdown("台番号の配置と性能を可視化します")

coords_df = pd.read_csv(COORDS_FILE)
coords_df['machine_number'] = coords_df['machine_number'].astype(int)

try:
    conn = sqlite3.connect(DB_PATH)
    all_machines = pd.read_sql_query(
        "SELECT * FROM machine_detailed_results ORDER BY date DESC", conn
    )
    conn.close()
except Exception as e:
    st.error(f"❌ DBエラー: {e}")
    st.stop()

if all_machines.empty:
    st.warning("⚠️ 個別台データが見つかりません")
    st.stop()

# 日付フィルタ
col_l, col_r = st.columns([2, 1])
with col_l:
    date_range = st.date_input(
        "分析期間",
        value=(datetime(2026, 1, 1).date(), datetime.now().date()),
        key="heatmap7_date_range"
    )
with col_r:
    metric = st.radio(
        "表示指標",
        ["勝率(%)", "平均差枚", "平均G数"],
        key="heatmap7_metric",
        horizontal=False
    )

all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
filtered = all_machines[
    (all_machines['date'] >= pd.Timestamp(date_range[0])) &
    (all_machines['date'] <= pd.Timestamp(date_range[1]))
]

if filtered.empty:
    st.warning("⚠️ 指定期間にデータがありません")
    st.stop()

# 台番号ごとの統計
machine_stats = filtered.groupby('machine_number').agg(
    avg_diff=('diff_coins_normalized', 'mean'),
    win_rate=('diff_coins_normalized', lambda x: (x > 0).sum() / len(x) * 100),
    avg_games=('games_normalized', 'mean')
).round(2).reset_index()

# 座標とマージ
heatmap_data = coords_df.merge(machine_stats, on='machine_number', how='left')

# 指標設定
if metric == "勝率(%)":
    metric_col, metric_label = 'win_rate', '勝率(%)'
    colorscale = 'RdYlGn'
    zmin, zmax = 0, 100
    fmt = '{:.1f}%'
elif metric == "平均差枚":
    metric_col, metric_label = 'avg_diff', '平均差枚(枚)'
    colorscale = 'RdYlGn'
    zmin = heatmap_data[metric_col].min()
    zmax = heatmap_data[metric_col].max()
    fmt = '{:.0f}枚'
else:
    metric_col, metric_label = 'avg_games', '平均G数(G)'
    colorscale = 'Blues'
    zmin = heatmap_data[metric_col].min()
    zmax = heatmap_data[metric_col].max()
    fmt = '{:.0f}G'

# グリッド行列を作成
max_x = int(heatmap_data['X'].max())
max_y = int(heatmap_data['Y'].max())
z_mat    = np.full((max_y, max_x), np.nan)
mn_mat   = np.full((max_y, max_x), '', dtype=object)
val_mat  = np.full((max_y, max_x), '', dtype=object)

for _, row in heatmap_data.iterrows():
    xi = int(row['X']) - 1
    yi = int(row['Y']) - 1
    mn_mat[yi, xi] = str(int(row['machine_number']))
    if not pd.isna(row[metric_col]):
        z_mat[yi, xi] = row[metric_col]
        val_mat[yi, xi] = fmt.format(row[metric_col])

# 動的高さ
height = max(600, max_y * 22 + 200)

fig = go.Figure(data=go.Heatmap(
    z=z_mat,
    x=list(range(1, max_x + 1)),
    y=list(range(1, max_y + 1)),
    colorscale=colorscale,
    customdata=np.stack([mn_mat, val_mat], axis=-1),
    hovertemplate='<b>台番号: %{customdata[0]}</b><br>'
                  + f'{metric_label}: %{{customdata[1]}}<br>'
                  + 'X=%{x}, Y=%{y}<extra></extra>',
    zmin=zmin,
    zmax=zmax,
    xgap=0.5,
    ygap=0.5,
))

fig.update_traces(colorbar=dict(
    title=dict(text=metric_label, side="right"),
    thickness=18,
    len=0.7
))

fig.update_layout(
    title=dict(
        text=f'蒲田七 2F 配置図 - {metric_label}',
        x=0.5, xanchor='center',
        font=dict(size=18)
    ),
    height=height,
    hovermode='closest',
    yaxis=dict(autorange='reversed', side='left',
               showgrid=True, gridwidth=0.5,
               gridcolor='rgba(200,200,200,0.2)'),
    xaxis=dict(showgrid=True, gridwidth=0.5,
               gridcolor='rgba(200,200,200,0.2)'),
    font=dict(family='Arial, sans-serif', size=11, color='black'),
    margin=dict(l=60, r=110, t=80, b=60),
    plot_bgcolor='white',
    paper_bgcolor='white'
)
fig.update_yaxes(scaleanchor="x", scaleratio=1)
fig.update_xaxes(scaleanchor="y", scaleratio=1)

st.plotly_chart(fig, use_container_width=True)

# 統計サマリー
st.markdown("---")
st.markdown("### 📊 統計サマリー")
c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.metric("分析台数", f"{len(machine_stats)}台")
with c2: st.metric("平均勝率", f"{machine_stats['win_rate'].mean():.1f}%")
with c3: st.metric("平均差枚", f"{machine_stats['avg_diff'].mean():.0f}枚")
with c4: st.metric("最高勝率", f"{machine_stats['win_rate'].max():.1f}%")
with c5: st.metric("最高差枚", f"{machine_stats['avg_diff'].max():.0f}枚")

# TOP 10 タブ
st.markdown("---")
st.markdown("### 🏆 性能 TOP 10")
tab1, tab2, tab3 = st.tabs(["勝率 TOP10", "差枚 TOP10", "G数 TOP10"])

def top_table(col, label):
    df = machine_stats.nlargest(10, col)[['machine_number', 'win_rate', 'avg_diff', 'avg_games']].copy()
    df.columns = ['台番号', '勝率(%)', '平均差枚', '平均G数']
    df.insert(0, '順位', range(1, len(df) + 1))
    st.dataframe(df, use_container_width=True, hide_index=True)

with tab1: top_table('win_rate', '勝率')
with tab2: top_table('avg_diff', '差枚')
with tab3: top_table('avg_games', 'G数')