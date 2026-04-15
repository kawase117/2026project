"""
Pachinko Analyzer - Dashboard Module
パチスロ分析システムのメインダッシュボード
Streamlit ベースの対話的ダッシュボード
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta
import numpy as np
from typing import Tuple, Dict, List
import warnings
warnings.filterwarnings('ignore')

# ========================================
# Page Configuration
# ========================================

st.set_page_config(
    page_title="Pachinko Analyzer Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========================================
# CSS Styling (ダークテーマ用)
# ========================================

st.markdown("""
<style>
    /* ダークテーマ全体設定 */
    [data-testid="stSidebar"] {
        background-color: #1e1e1e;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {
        color: #ffffff;
    }
    [data-testid="stSidebar"] label {
        color: #ffffff !important;
        font-weight: 600;
    }
    /* メインコンテンツエリア */
    [data-testid="stAppViewContainer"] {
        background-color: #0e1117;
        color: #c9d1d9;
    }
    .metric-container {
        background-color: #1f2937;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #1f77b4;
    }
    .header-style {
        color: #58a6ff;
        font-size: 24px;
        font-weight: bold;
        margin-bottom: 20px;
    }
    .subheader-style {
        color: #8b949e;
        font-size: 16px;
        margin-top: 15px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ========================================
# Session State Initialization
# ========================================

if 'db_path' not in st.session_state:
    st.session_state.db_path = None
if 'hall_name' not in st.session_state:
    st.session_state.hall_name = None
if 'df_hall_summary' not in st.session_state:
    st.session_state.df_hall_summary = None

# ========================================
# Utility Functions
# ========================================

@st.cache_resource
def get_db_connection(db_path: str):
    """データベース接続"""
    return sqlite3.connect(db_path)

def get_available_halls(db_dir: Path = Path('./db')) -> List[str]:
    """利用可能なホール一覧を取得"""
    if not db_dir.exists():
        return []
    return [f.stem for f in db_dir.glob('*.db')]

@st.cache_data(ttl=3600)
def load_daily_hall_summary(db_path: str) -> pd.DataFrame:
    """ホール全体集計データを読み込み（キャッシング対応 - 1時間で自動更新）"""
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM daily_hall_summary ORDER BY date DESC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            st.warning("データが見つかりません")
            return pd.DataFrame()
        
        # データ型変換
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        return df.sort_values('date')
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame()

def load_machine_detailed_by_date(db_path: str, date_str: str) -> pd.DataFrame:
    """指定日の個別台データを読み込み"""
    try:
        conn = sqlite3.connect(db_path)
        query = """
            SELECT 
                date, machine_number, machine_name, last_digit,
                games_normalized as games,
                diff_coins_normalized as diff_coins,
                is_zorome
            FROM machine_detailed_results
            WHERE date = ?
            ORDER BY diff_coins DESC
        """
        df = pd.read_sql_query(query, conn, params=(date_str,))
        conn.close()
        return df
    except Exception as e:
        st.error(f"個別台データ読み込みエラー: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_last_digit_summary(db_path: str, machine_type: str = 'all') -> pd.DataFrame:
    """末尾別集計データを読み込み（キャッシング対応 - 1時間で自動更新）"""
    try:
        conn = sqlite3.connect(db_path)
        table_name = f"last_digit_summary_{machine_type}"
        query = f"SELECT * FROM {table_name} ORDER BY date DESC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            st.warning(f"末尾別データなし（{machine_type}）")
            return pd.DataFrame()
        
        df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        return df.sort_values('date')
    except Exception as e:
        st.warning(f"末尾別データ読み込みエラー（{machine_type}）: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_machine_detailed_results(db_path: str) -> pd.DataFrame:
    """
    すべての個別台実績データを読み込み（キャッシング対応 - 1時間で自動更新）
    
    Returns
    -------
    pd.DataFrame
        個別台実績データ
    """
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM machine_detailed_results ORDER BY date DESC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        
        return df
    except Exception as e:
        st.error(f"個別台データ読み込みエラー: {e}")
        return pd.DataFrame()

# ========================================
# Sidebar Configuration
# ========================================

st.sidebar.markdown("### 🎮 Pachinko Analyzer")
st.sidebar.markdown("---")

# ホール選択
db_dir = Path('./db')
available_halls = get_available_halls(db_dir)

if available_halls:
    selected_hall = st.sidebar.selectbox(
        "📍 ホールを選択",
        available_halls,
        index=0 if not st.session_state.hall_name else available_halls.index(st.session_state.hall_name)
    )
    st.session_state.hall_name = selected_hall
    st.session_state.db_path = db_dir / f"{selected_hall}.db"
else:
    st.sidebar.error("❌ db/ ディレクトリにデータベースがありません")
    st.stop()

# データ読み込み
if st.session_state.db_path:
    st.session_state.df_hall_summary = load_daily_hall_summary(str(st.session_state.db_path))

st.sidebar.markdown("---")

# 分析ページ選択
analysis_page = st.sidebar.radio(
    "📊 分析ページ",
    ["🏠 ホール全体", "📅 日別分析", "📆 曜日別分析", "📆 DD別分析", "🔢 末尾別分析", "📊 日末日別分析", "📋 第X曜日別分析", "💻 個別台分析", "🎯 台番号末尾別分析", "⭐ 期間TOP10分析", "🔀 クロス検索分析", "🔗 複合分析（DD別・曜日別）", "ℹ️ 統計情報"],
    index=0
)

st.sidebar.markdown("---")

# フィルタ設定
st.sidebar.markdown("### 🎛️ フィルタ設定")

df = st.session_state.df_hall_summary

if not df.empty:
    # pandas.Timestamp を datetime.date に変換（Streamlit 1.56.0対応）
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()
    default_start = pd.to_datetime('2026-01-01').date()
    default_end = df['date'].max().date()
    
    date_range_tuple = st.sidebar.slider(
        "📅 期間選択",
        min_value=min_date,
        max_value=max_date,
        value=(default_start, default_end),
        format="YYYY-MM-DD"
    )
    
    # 結果を pd.Timestamp に戻す
    date_range = (
        pd.to_datetime(date_range_tuple[0]),
        pd.to_datetime(date_range_tuple[1])
    )
    
    # 信頼性フィルタ
    min_games = st.sidebar.slider(
        "🎲 最小G数（信頼性フィルタ）",
        min_value=0,
        max_value=int(df['avg_games_per_machine'].max()),
        value=1000,
        step=100
    )
    
    show_low_confidence = st.sidebar.checkbox(
        "参考値を表示（低信頼度）",
        value=False,
        help="G数が少ないデータも表示"
    )
    
    # 機種フィルタ（末尾別分析用）
    machine_type = st.sidebar.selectbox(
        "🎰 機種タイプ",
        ["all", "jug", "hana", "oki", "other"],
        help="末尾別分析で使用"
    )

st.sidebar.markdown("---")
st.sidebar.markdown("**ℹ️ 信頼性基準**")
st.sidebar.markdown("- G数 ≥ 1000G: ✅ 高信頼")
st.sidebar.markdown("- G数 < 1000G: ⚠️ 参考値")
st.sidebar.markdown("- サンプル数 ≥ 5台: ✅ 統計的有意")

# ========================================
# Main Content
# ========================================

st.title("🎮 Pachinko Analyzer Dashboard")
st.markdown(f"**ホール**: {st.session_state.hall_name} | **更新日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
st.markdown("---")

if df.empty:
    st.error("❌ データが利用できません")
    st.stop()

# フィルタリング
df_filtered = df[
    (df['date'] >= date_range[0]) & 
    (df['date'] <= date_range[1])
].copy()

if df_filtered.empty:
    st.warning("⚠️ 指定期間にデータがありません")
    st.stop()

# ========================================
# Page 1: ホール全体
# ========================================

if analysis_page == "🏠 ホール全体":
    st.markdown("## ホール全体の傾向")
    st.markdown("最新データの概要と主要指標の推移を表示します")
    
    # 最新日付のデータ
    latest_date = df_filtered['date'].max()
    latest_data = df_filtered[df_filtered['date'] == latest_date].iloc[0]
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "📊 勝率",
            f"{latest_data['win_rate']:.1f}%",
            delta=f"{latest_data['win_rate'] - df_filtered['win_rate'].iloc[-10:].mean():.1f}%",
            delta_color="off"
        )
    
    with col2:
        st.metric(
            "🎲 平均G数",
            f"{int(latest_data['avg_games_per_machine']):,}G",
            delta=f"{int(latest_data['avg_games_per_machine'] - df_filtered['avg_games_per_machine'].iloc[-10:].mean())}G",
            delta_color="off"
        )
    
    with col3:
        st.metric(
            "💰 平均差枚",
            f"{int(latest_data['avg_diff_per_machine']):,}枚",
            delta=f"{int(latest_data['avg_diff_per_machine'] - df_filtered['avg_diff_per_machine'].iloc[-10:].mean())}枚",
            delta_color="off"
        )
    
    with col4:
        st.metric(
            "🤖 稼働台数",
            f"{int(latest_data['total_machines'])}台",
            delta=None
        )
    
    st.markdown("---")
    
    # 3指標の時系列グラフ（Plotly 6.7.0完全対応 - 最小限設定）
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
            line=dict(color='#1f77b4', width=2)
        ),
        row=1, col=1
    )
    
    # 第2行: G数
    fig.add_trace(
        go.Scatter(
            x=df_filtered['date'],
            y=df_filtered['avg_games_per_machine'],
            name='平均G数',
            line=dict(color='#ff7f0e', width=2)
        ),
        row=2, col=1
    )
    
    # 第3行: 差枚
    fig.add_trace(
        go.Scatter(
            x=df_filtered['date'],
            y=df_filtered['avg_diff_per_machine'],
            name='平均差枚',
            line=dict(color='#2ca02c', width=2)
        ),
        row=3, col=1
    )
    
    fig.update_yaxes(title_text="勝率(%)", row=1, col=1)
    fig.update_yaxes(title_text="平均G数", row=2, col=1)
    fig.update_yaxes(title_text="平均差枚", row=3, col=1)
    fig.update_xaxes(title_text="日付", row=3, col=1)
    
    # シンプルなlayout設定
    fig.update_layout(title_text="📈 3指標の時系列推移", height=700)
    
    st.plotly_chart(fig, use_container_width=True)
    
    # 最新データテーブル
    st.markdown("### 📋 最新30日間のサマリー")
    display_cols = ['date', 'win_rate', 'avg_games_per_machine', 'avg_diff_per_machine', 'total_machines']
    display_df = df_filtered[display_cols].copy()
    display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
    display_df.columns = ['日付', '勝率(%)', '平均G数', '平均差枚', '稼働台数']
    
    st.dataframe(display_df.iloc[::-1], use_container_width=True, height=400)

# ========================================
# Page 2: 日別分析
# ========================================

elif analysis_page == "📅 日別分析":
    st.markdown("## 日別分析")
    st.markdown("毎日の3指標の詳細な推移を表示します")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # 勝率の日別推移
        fig_win = px.line(
            df_filtered,
            x='date',
            y='win_rate',
            title='📊 勝率の推移',
            markers=True,
            labels={'date': '日付', 'win_rate': '勝率(%)'}
        )
        fig_win.update_traces(line_color='#1f77b4', marker_size=6)
        fig_win.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_win, use_container_width=True)
    
    with col2:
        # G数の日別推移
        fig_games = px.line(
            df_filtered,
            x='date',
            y='avg_games_per_machine',
            title='🎲 平均G数の推移',
            markers=True,
            labels={'date': '日付', 'avg_games_per_machine': '平均G数'}
        )
        fig_games.update_traces(line_color='#ff7f0e', marker_size=6)
        fig_games.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_games, use_container_width=True)
    
    col3, col4 = st.columns(2)
    
    with col3:
        # 差枚の日別推移
        fig_diff = px.line(
            df_filtered,
            x='date',
            y='avg_diff_per_machine',
            title='💰 平均差枚の推移',
            markers=True,
            labels={'date': '日付', 'avg_diff_per_machine': '平均差枚'}
        )
        fig_diff.update_traces(line_color='#2ca02c', marker_size=6)
        fig_diff.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_diff, use_container_width=True)
    
    with col4:
        # 稼働台数の推移
        fig_machines = px.bar(
            df_filtered,
            x='date',
            y='total_machines',
            title='🤖 稼働台数の推移',
            labels={'date': '日付', 'total_machines': '稼働台数'}
        )
        fig_machines.update_traces(marker_color='#d62728')
        fig_machines.update_layout(height=400, hovermode='x unified')
        st.plotly_chart(fig_machines, use_container_width=True)
    
    # 統計情報
    st.markdown("---")
    st.markdown("### 📊 統計情報")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("平均勝率", f"{df_filtered['win_rate'].mean():.1f}%")
        st.metric("勝率 (最高)", f"{df_filtered['win_rate'].max():.1f}%")
        st.metric("勝率 (最低)", f"{df_filtered['win_rate'].min():.1f}%")
    
    with col2:
        st.metric("平均G数", f"{int(df_filtered['avg_games_per_machine'].mean()):,}G")
        st.metric("G数 (最高)", f"{int(df_filtered['avg_games_per_machine'].max()):,}G")
        st.metric("G数 (最低)", f"{int(df_filtered['avg_games_per_machine'].min()):,}G")
    
    with col3:
        st.metric("平均差枚", f"{int(df_filtered['avg_diff_per_machine'].mean()):,}枚")
        st.metric("差枚 (最高)", f"{int(df_filtered['avg_diff_per_machine'].max()):,}枚")
        st.metric("差枚 (最低)", f"{int(df_filtered['avg_diff_per_machine'].min()):,}枚")

# ========================================
# Page 3: 曜日別分析
# ========================================

elif analysis_page == "📆 曜日別分析":
    st.markdown("## 曜日別分析")
    st.markdown("曜日ごとの平均値を比較して、パターンを検出します")
    
    # 曜日別集計
    dow_mapping = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}
    df_filtered['day_name'] = df_filtered['date'].dt.dayofweek.map(dow_mapping)
    
    df_dow = df_filtered.groupby('day_name').agg({
        'win_rate': ['mean', 'std'],
        'avg_games_per_machine': ['mean', 'std'],
        'avg_diff_per_machine': ['mean', 'std'],
        'total_machines': 'mean'
    }).round(2)
    
    # グラフ表示
    col1, col2, col3 = st.columns(3)
    
    dow_order = ['月', '火', '水', '木', '金', '土', '日']
    dow_data = df_filtered.groupby('day_name')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    dow_data = dow_data.reindex(dow_order)
    
    with col1:
        fig1 = px.bar(
            x=dow_data.index,
            y=dow_data['win_rate'],
            title='📊 曜日別勝率',
            labels={'x': '曜日', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color='#1f77b4')
        st.plotly_chart(fig1, use_container_width=True)
    
    with col2:
        fig2 = px.bar(
            x=dow_data.index,
            y=dow_data['avg_games_per_machine'],
            title='🎲 曜日別平均G数',
            labels={'x': '曜日', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color='#ff7f0e')
        st.plotly_chart(fig2, use_container_width=True)
    
    with col3:
        fig3 = px.bar(
            x=dow_data.index,
            y=dow_data['avg_diff_per_machine'],
            title='💰 曜日別平均差枚',
            labels={'x': '曜日', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color='#2ca02c')
        st.plotly_chart(fig3, use_container_width=True)
    
    # テーブル表示
    st.markdown("---")
    st.markdown("### 📋 曜日別詳細統計")
    
    summary_data = []
    for dow in dow_order:
        dow_subset = df_filtered[df_filtered['day_name'] == dow]
        if not dow_subset.empty:
            summary_data.append({
                '曜日': dow,
                '平均勝率': float(dow_subset['win_rate'].mean()),
                '平均G数': int(dow_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(dow_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(dow_subset)
            })
    
    df_dow_display = pd.DataFrame(summary_data)
    
    # 勝率を小数点第1位でフォーマット
    df_dow_display_formatted = df_dow_display.copy()
    df_dow_display_formatted['平均勝率'] = df_dow_display['平均勝率'].apply(lambda x: f"{x:.1f}%")
    
    st.dataframe(df_dow_display_formatted, use_container_width=True, hide_index=True)
    
    # 全表示テーブル
    st.markdown("---")
    st.markdown("### 📋 曜日別全詳細統計")
    st.dataframe(df_dow_display_formatted, use_container_width=True, hide_index=True)

# ========================================
# Page 3-B: DD別分析（月内の日付位置別）
# ========================================

elif analysis_page == "📆 DD別分析":
    st.markdown("## DD別分析（月内の日付位置別）")
    st.markdown("各月の同じ日付（1日、2日...31日）でのパターンを比較します")
    
    # 日付を抽出
    df_filtered_copy = df_filtered.copy()
    df_filtered_copy['day_of_month'] = df_filtered_copy['date'].dt.day
    
    df_dd = df_filtered_copy.groupby('day_of_month').agg({
        'win_rate': ['mean', 'std', 'count'],
        'avg_games_per_machine': 'mean',
        'avg_diff_per_machine': 'mean',
        'total_machines': 'mean'
    }).round(2)
    
    # グラフ表示
    col1, col2, col3 = st.columns(3)
    
    dd_order = sorted(df_filtered_copy['day_of_month'].unique())
    dd_data = df_filtered_copy.groupby('day_of_month')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    dd_data = dd_data.reindex(dd_order)
    
    with col1:
        fig1 = px.bar(
            x=dd_data.index.astype(str) + "日",
            y=dd_data['win_rate'],
            title='📊 DD別勝率',
            labels={'x': '日付', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color='#1f77b4')
        fig1.update_xaxes(tickangle=-45)
        st.plotly_chart(fig1, use_container_width=True)
    
    with col2:
        fig2 = px.bar(
            x=dd_data.index.astype(str) + "日",
            y=dd_data['avg_games_per_machine'],
            title='🎲 DD別平均G数',
            labels={'x': '日付', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color='#ff7f0e')
        fig2.update_xaxes(tickangle=-45)
        st.plotly_chart(fig2, use_container_width=True)
    
    with col3:
        fig3 = px.bar(
            x=dd_data.index.astype(str) + "日",
            y=dd_data['avg_diff_per_machine'],
            title='💰 DD別平均差枚',
            labels={'x': '日付', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color='#2ca02c')
        fig3.update_xaxes(tickangle=-45)
        st.plotly_chart(fig3, use_container_width=True)
    
    # テーブル表示
    st.markdown("---")
    st.markdown("### 📋 DD別詳細統計")
    
    table_data = []
    for dd in dd_order:
        dd_subset = df_filtered_copy[df_filtered_copy['day_of_month'] == dd]
        if not dd_subset.empty:
            table_data.append({
                '日付': f"{dd}日",
                '平均勝率': float(dd_subset['win_rate'].mean()),
                '平均G数': int(dd_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(dd_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(dd_subset)
            })
    
    df_dd_display = pd.DataFrame(table_data)
    
    # 勝率を小数点第1位でフォーマット
    df_dd_display_formatted = df_dd_display.copy()
    df_dd_display_formatted['平均勝率'] = df_dd_display['平均勝率'].apply(lambda x: f"{x:.1f}%")
    
    st.dataframe(df_dd_display_formatted, use_container_width=True, hide_index=True)
    
    # 全表示テーブル
    st.markdown("---")
    st.markdown("### 📋 DD別全詳細統計")
    st.dataframe(df_dd_display_formatted, use_container_width=True, hide_index=True)

# ========================================
# Page 4: 末尾別分析
# ========================================

elif analysis_page == "🔢 末尾別分析":
    st.markdown("## 末尾別分析")
    st.markdown("台番号末尾ごとの性能パターンを分析します")
    
    df_last_digit = load_last_digit_summary(str(st.session_state.db_path), machine_type)
    
    if df_last_digit.empty:
        st.warning(f"末尾別データが利用できません（機種: {machine_type}）")
    else:
        df_last_digit_filtered = df_last_digit[
            (df_last_digit['date'] >= date_range[0]) & 
            (df_last_digit['date'] <= date_range[1])
        ]
        
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
            fig1.update_traces(marker_color='#1f77b4')
            st.plotly_chart(fig1, use_container_width=True)
        
        with col2:
            fig2 = px.bar(
                x=df_ld_summary.index.astype(str),
                y=df_ld_summary['avg_games'],
                title='🎲 末尾別平均G数',
                labels={'x': '末尾', 'y': '平均G数'}
            )
            fig2.update_traces(marker_color='#ff7f0e')
            st.plotly_chart(fig2, use_container_width=True)
        
        with col3:
            fig3 = px.bar(
                x=df_ld_summary.index.astype(str),
                y=df_ld_summary['avg_diff_coins'],
                title='💰 末尾別平均差枚',
                labels={'x': '末尾', 'y': '平均差枚'}
            )
            fig3.update_traces(marker_color='#2ca02c')
            st.plotly_chart(fig3, use_container_width=True)
        
    # テーブル表示
    st.markdown("---")
    st.markdown("### 📋 末尾別詳細統計")
    
    table_data = []
    for digit in sorted(df_ld_summary.index):
        # DB テーブルからゾロ目を除外（個別に計算するため）
        if digit == 'ゾロ目':
            continue
        
        row = df_ld_summary.loc[digit]
        table_data.append({
            '末尾': str(digit),
            '平均勝率': float(row['win_rate']),
            '平均G数': int(row['avg_games']),
            '平均差枚': int(row['avg_diff_coins']),
            '平均台数': int(row['machine_count'])
        })
    
    # ゾロ目（is_zorome=1）の集計（個別台データから）
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))
    if not all_machines.empty:
        all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
        zorome_machines = all_machines[
            (all_machines['date'] >= date_range[0]) & 
            (all_machines['date'] <= date_range[1]) &
            (all_machines['is_zorome'] == 1)
        ]
        if not zorome_machines.empty:
            zorome_win_rate = (zorome_machines['diff_coins_normalized'] > 0).sum() / len(zorome_machines) * 100
            # ゾロ目台数を重複排除で計算（unique な machine_number の数）
            zorome_count = len(zorome_machines['machine_number'].unique())
            table_data.append({
                '末尾': 'ゾロ目',
                '平均勝率': float(zorome_win_rate),
                '平均G数': int(zorome_machines['games_normalized'].mean()),
                '平均差枚': int(zorome_machines['diff_coins_normalized'].mean()),
                '平均台数': zorome_count
            })
    
    df_ld_display = pd.DataFrame(table_data)
    
    # 勝率を小数点第1位でフォーマット
    df_ld_display_formatted = df_ld_display.copy()
    df_ld_display_formatted['平均勝率'] = df_ld_display['平均勝率'].apply(lambda x: f"{x:.1f}%")
    
    st.dataframe(df_ld_display_formatted, use_container_width=True, hide_index=True)
    
    # 全表示テーブル
    st.markdown("---")
    st.markdown("### 📋 末尾別全詳細統計")
    st.dataframe(df_ld_display_formatted, use_container_width=True, hide_index=True)

# ========================================
# Page 5: 日末日別分析
# ========================================

elif analysis_page == "📊 日末日別分析":
    st.markdown("## 日末日別分析")
    st.markdown("日付の末尾数字ごとの性能パターンを分析します")
    
    # 末尾別集計
    df_filtered['day_last_digit'] = df_filtered['date'].dt.strftime('%d').str[-1].astype(int)
    
    df_day_digit = df_filtered.groupby('day_last_digit').agg({
        'win_rate': ['mean', 'std'],
        'avg_games_per_machine': ['mean', 'std'],
        'avg_diff_per_machine': ['mean', 'std'],
        'total_machines': 'mean'
    }).round(2)
    
    # グラフ表示
    col1, col2, col3 = st.columns(3)
    
    digit_order = sorted(df_filtered['day_last_digit'].unique())
    digit_data = df_filtered.groupby('day_last_digit')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
    digit_data = digit_data.reindex(digit_order)
    
    with col1:
        fig1 = px.bar(
            x=digit_data.index.astype(str),
            y=digit_data['win_rate'],
            title='📊 末尾別勝率',
            labels={'x': '日付末尾', 'y': '勝率(%)'}
        )
        fig1.update_traces(marker_color='#1f77b4')
        st.plotly_chart(fig1, use_container_width=True)
    
    with col2:
        fig2 = px.bar(
            x=digit_data.index.astype(str),
            y=digit_data['avg_games_per_machine'],
            title='🎲 末尾別平均G数',
            labels={'x': '日付末尾', 'y': '平均G数'}
        )
        fig2.update_traces(marker_color='#ff7f0e')
        st.plotly_chart(fig2, use_container_width=True)
    
    with col3:
        fig3 = px.bar(
            x=digit_data.index.astype(str),
            y=digit_data['avg_diff_per_machine'],
            title='💰 末尾別平均差枚',
            labels={'x': '日付末尾', 'y': '平均差枚'}
        )
        fig3.update_traces(marker_color='#2ca02c')
        st.plotly_chart(fig3, use_container_width=True)
    
    # テーブル表示
    st.markdown("---")
    st.markdown("### 📋 日末尾別詳細統計")
    
    table_data = []
    for digit in digit_order:
        digit_subset = df_filtered[df_filtered['day_last_digit'] == digit]
        if not digit_subset.empty:
            table_data.append({
                '末尾': digit,
                '平均勝率': float(digit_subset['win_rate'].mean()),
                '平均G数': int(digit_subset['avg_games_per_machine'].mean()),
                '平均差枚': int(digit_subset['avg_diff_per_machine'].mean()),
                'サンプル数': len(digit_subset)
            })
    
    df_dd_display = pd.DataFrame(table_data)
    
    # 勝率を小数点第1位でフォーマット
    df_dd_display_formatted = df_dd_display.copy()
    df_dd_display_formatted['平均勝率'] = df_dd_display['平均勝率'].apply(lambda x: f"{x:.1f}%")
    
    st.dataframe(df_dd_display_formatted, use_container_width=True, hide_index=True)
    
    # 全表示テーブル
    st.markdown("---")
    st.markdown("### 📋 日末尾別全詳細統計")
    st.dataframe(df_dd_display_formatted, use_container_width=True, hide_index=True)

# ========================================
# Page 6: 第X曜日別分析
# ========================================

elif analysis_page == "📋 第X曜日別分析":
    st.markdown("## 第X曜日別分析")
    st.markdown("各月の第N曜日（例：第1月曜日、第2金曜日）のパターンを分析します")
    
    # weekday_nth 列を使用
    if 'weekday_nth' in df_filtered.columns:
        df_weekday_nth = df_filtered.groupby('weekday_nth').agg({
            'win_rate': ['mean', 'std'],
            'avg_games_per_machine': ['mean', 'std'],
            'avg_diff_per_machine': ['mean', 'std'],
            'total_machines': 'mean'
        }).round(2)
        
        # グラフ表示（全パターン表示）
        weekday_nth_order = sorted(df_filtered['weekday_nth'].unique())
        weekday_nth_data = df_filtered.groupby('weekday_nth')[['win_rate', 'avg_games_per_machine', 'avg_diff_per_machine']].mean()
        weekday_nth_data = weekday_nth_data.reindex(weekday_nth_order)
        
        # 3つのグラフを縦並びで表示（見やすくするため）
        st.markdown("### 📊 第X曜日別勝率")
        fig1 = px.bar(
            x=weekday_nth_data.index.astype(str),
            y=weekday_nth_data['win_rate'],
            title='',
            labels={'x': '第X曜日', 'y': '勝率(%)'},
            height=400
        )
        fig1.update_traces(marker_color='#1f77b4')
        fig1.update_xaxes(tickangle=-45)
        st.plotly_chart(fig1, use_container_width=True)
        
        st.markdown("### 🎲 第X曜日別平均G数")
        fig2 = px.bar(
            x=weekday_nth_data.index.astype(str),
            y=weekday_nth_data['avg_games_per_machine'],
            title='',
            labels={'x': '第X曜日', 'y': '平均G数'},
            height=400
        )
        fig2.update_traces(marker_color='#ff7f0e')
        fig2.update_xaxes(tickangle=-45)
        st.plotly_chart(fig2, use_container_width=True)
        
        st.markdown("### 💰 第X曜日別平均差枚")
        fig3 = px.bar(
            x=weekday_nth_data.index.astype(str),
            y=weekday_nth_data['avg_diff_per_machine'],
            title='',
            labels={'x': '第X曜日', 'y': '平均差枚'},
            height=400
        )
        fig3.update_traces(marker_color='#2ca02c')
        fig3.update_xaxes(tickangle=-45)
        st.plotly_chart(fig3, use_container_width=True)
        
        # テーブル表示
        st.markdown("---")
        st.markdown("### 📋 第X曜日別詳細統計")
        
        table_data = []
        for nth in weekday_nth_order:
            nth_subset = df_filtered[df_filtered['weekday_nth'] == nth]
            if not nth_subset.empty:
                table_data.append({
                    '第X曜日': nth,
                    '平均勝率': float(nth_subset['win_rate'].mean()),
                    '平均G数': int(nth_subset['avg_games_per_machine'].mean()),
                    '平均差枚': int(nth_subset['avg_diff_per_machine'].mean()),
                    'サンプル数': len(nth_subset)
                })
        
        df_nth_display = pd.DataFrame(table_data)
        
        # 勝率を小数点第1位でフォーマット
        df_nth_display_formatted = df_nth_display.copy()
        df_nth_display_formatted['平均勝率'] = df_nth_display['平均勝率'].apply(lambda x: f"{x:.1f}%")
        
        st.dataframe(df_nth_display_formatted, use_container_width=True, hide_index=True)
        
        # 全表示テーブル
        st.markdown("---")
        st.markdown("### 📋 第X曜日別全詳細統計")
        st.dataframe(df_nth_display_formatted, use_container_width=True, hide_index=True)
    else:
        st.warning("⚠️ weekday_nth データが利用できません")

# ========================================
# Page 7: 個別台分析
# ========================================

elif analysis_page == "💻 個別台分析":
    st.markdown("## 個別台分析（全期間TOP10）")
    st.markdown("指定期間における個別台の成績TOP10を表示します")
    
    # 期間内のすべての個別台データを集計
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))
    
    if all_machines.empty:
        st.warning("⚠️ 個別台データが見つかりません")
    else:
        # 日付でフィルタ
        all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
        all_machines_filtered = all_machines[
            (all_machines['date'] >= date_range[0]) & 
            (all_machines['date'] <= date_range[1])
        ]
        
        if all_machines_filtered.empty:
            st.warning("⚠️ 指定期間にデータがありません")
        else:
            # 台ごとに集計（すべての機種を表示）
            machine_summary = all_machines_filtered.groupby('machine_number').agg({
                'games_normalized': 'sum',
                'diff_coins_normalized': ['sum', 'mean', 'count'],
            }).round(2)
            
            machine_summary.columns = ['total_games', 'total_diff', 'avg_diff', 'play_days']
            machine_summary = machine_summary.reset_index()
            
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
            
            # 全表示テーブル
            st.markdown("---")
            st.markdown("### 📋 全台詳細統計")
            
            all_display_data = []
            machine_summary_sorted = machine_summary.sort_values('total_diff', ascending=False)
            for idx, row in machine_summary_sorted.iterrows():
                all_display_data.append({
                    '台番号': int(row['machine_number']),
                    '機種': row['machine_name'],
                    '差枚': int(row['total_diff']),
                    '平均差枚': int(row['avg_diff']),
                    'G数': int(row['total_games']),
                    '稼働日数': int(row['play_days'])
                })
            
            df_all_display = pd.DataFrame(all_display_data)
            st.dataframe(df_all_display, use_container_width=True, hide_index=True)
            
            # 全表示テーブル
            st.markdown("---")
            st.markdown("### 📋 全台詳細統計")
            
            all_display_data = []
            machine_summary_all = machine_summary.sort_values('avg_diff', ascending=False)
            for idx, row in machine_summary_all.iterrows():
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

# ========================================
# Page 8: 台番号末尾別分析
# ========================================

elif analysis_page == "🎯 台番号末尾別分析":
    st.markdown("## 台番号末尾別分析")
    st.markdown("台番号の末尾（0-9）ごとの性能を、指定期間で集計して分析します")
    
    # 期間内のすべての個別台データを集計
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))
    
    if all_machines.empty:
        st.warning("⚠️ 個別台データが見つかりません")
    else:
        # 日付でフィルタ
        all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
        all_machines_filtered = all_machines[
            (all_machines['date'] >= date_range[0]) & 
            (all_machines['date'] <= date_range[1])
        ]
        
        if all_machines_filtered.empty:
            st.warning("⚠️ 指定期間にデータがありません")
        else:
            # 末尾でグループ化
            all_machines_filtered['tail_digit'] = all_machines_filtered['machine_number'] % 10
            
            df_machines = all_machines_filtered.copy()
            
            # グラフ表示
            col1, col2, col3 = st.columns(3)
            
            tail_data = df_machines.groupby('tail_digit').agg({
                'games_normalized': 'mean',
                'diff_coins_normalized': ['mean', 'count']
            }).round(2)
            
            tail_order = sorted(df_machines['tail_digit'].unique())
            
            with col1:
                fig1 = px.bar(
                    x=tail_order,
                    y=[tail_data.loc[t, ('games_normalized', 'mean')] for t in tail_order],
                    title='🎲 末尾別平均G数',
                    labels={'x': '台番号末尾', 'y': '平均G数'}
                )
                fig1.update_traces(marker_color='#ff7f0e')
                st.plotly_chart(fig1, use_container_width=True)
            
            with col2:
                fig2 = px.bar(
                    x=tail_order,
                    y=[tail_data.loc[t, ('diff_coins_normalized', 'mean')] for t in tail_order],
                    title='💰 末尾別平均差枚',
                    labels={'x': '台番号末尾', 'y': '平均差枚'}
                )
                fig2.update_traces(marker_color='#2ca02c')
                st.plotly_chart(fig2, use_container_width=True)
            
            with col3:
                fig3 = px.bar(
                    x=tail_order,
                    y=[tail_data.loc[t, ('diff_coins_normalized', 'count')] for t in tail_order],
                    title='🤖 末尾別台数',
                    labels={'x': '台番号末尾', 'y': '台数'}
                )
                fig3.update_traces(marker_color='#d62728')
                st.plotly_chart(fig3, use_container_width=True)
            
            # テーブル表示
            st.markdown("---")
            st.markdown("### 📋 台番号末尾別詳細統計")
            
            table_data = []
            for tail in tail_order:
                tail_subset = df_machines[df_machines['tail_digit'] == tail]
                winning = (tail_subset['diff_coins_normalized'] > 0).sum()
                win_rate = (winning / len(tail_subset) * 100) if len(tail_subset) > 0 else 0
                table_data.append({
                    '末尾': int(tail),
                    '勝率': float(win_rate),
                    '平均G数': int(tail_subset['games_normalized'].mean()),
                    '平均差枚': int(tail_subset['diff_coins_normalized'].mean()),
                    '台数': len(tail_subset)
                })
            
            df_tail_display = pd.DataFrame(table_data)
            
            # 勝率を小数点第1位でフォーマット
            df_tail_display_formatted = df_tail_display.copy()
            df_tail_display_formatted['勝率'] = df_tail_display['勝率'].apply(lambda x: f"{x:.1f}%")
            
            st.dataframe(df_tail_display_formatted, use_container_width=True, hide_index=True)
            
            # 全表示テーブル
            st.markdown("---")
            st.markdown("### 📋 台番号末尾別全詳細統計")
            st.dataframe(df_tail_display_formatted, use_container_width=True, hide_index=True)

# ========================================
# Page 9: 期間TOP10分析
# ========================================

elif analysis_page == "⭐ 期間TOP10分析":
    st.markdown("## 期間TOP10分析")
    st.markdown("指定期間トータルの差枚・勝率・G数でTOP10を表示します")
    
    # 期間内のすべての個別台データを集計
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))
    
    if all_machines.empty:
        st.warning("⚠️ 個別台データが見つかりません")
    else:
        # 日付でフィルタ
        all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
        all_machines_filtered = all_machines[
            (all_machines['date'] >= date_range[0]) & 
            (all_machines['date'] <= date_range[1])
        ]
        
        if all_machines_filtered.empty:
            st.warning("⚠️ 指定期間にデータがありません")
        else:
            # 台ごとに集計
            machine_summary = all_machines_filtered.groupby(['machine_number', 'machine_name']).agg({
                'games_normalized': 'sum',
                'diff_coins_normalized': ['sum', 'mean', 'count'],
            }).round(2)
            
            machine_summary.columns = ['total_games', 'total_diff', 'avg_diff', 'play_days']
            machine_summary = machine_summary.reset_index()
            machine_summary['win_rate'] = (machine_summary['total_diff'] > 0).astype(int) * 100
            
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

# ========================================
# Page 11: クロス検索分析
# ========================================

elif analysis_page == "🔀 クロス検索分析":
    st.markdown("## クロス検索分析")
    st.markdown("複数の属性を組み合わせてフィルタリング・分析します")
    
    # 属性選択
    col1, col2 = st.columns(2)
    
    with col1:
        attr1 = st.selectbox(
            "第1属性を選択",
            ["台番号末尾", "日末尾", "DD別", "曜日", "第X曜日", "機種別", "台番号別"],
            key="cross_attr1"
        )
    
    with col2:
        attr2 = st.selectbox(
            "第2属性を選択",
            ["台番号末尾", "日末尾", "DD別", "曜日", "第X曜日", "機種別", "台番号別"],
            key="cross_attr2"
        )
    
    if attr1 == attr2:
        st.warning("⚠️ 異なる属性を選択してください")
    else:
        # 期間内のすべての個別台データを集計
        all_machines = load_machine_detailed_results(str(st.session_state.db_path))
        
        if all_machines.empty:
            st.warning("⚠️ 個別台データが見つかりません")
        else:
            # 日付でフィルタ
            all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
            all_machines_filtered = all_machines[
                (all_machines['date'] >= date_range[0]) & 
                (all_machines['date'] <= date_range[1])
            ]
            
            if all_machines_filtered.empty:
                st.warning("⚠️ 指定期間にデータがありません")
            else:
                # 属性列を追加
                df_cross = all_machines_filtered.copy()
                
                # 属性マッピング
                def get_attr_value(df, attr):
                    if attr == '台番号末尾':
                        return df['machine_number'] % 10
                    elif attr == '日末尾':
                        return df['date'].dt.strftime('%d').str[-1].astype(int)
                    elif attr == 'DD別':
                        return df['date'].dt.day
                    elif attr == '曜日':
                        return df['date'].dt.day_name()
                    elif attr == '第X曜日':
                        # 日付から計算
                        dates = df['date'].unique()
                        weekday_nth_map = {}
                        for d in dates:
                            dow = d.strftime('%a')
                            day = d.day
                            week_of_month = (day - 1) // 7 + 1
                            dow_map = {'Mon': 'Mon', 'Tue': 'Tue', 'Wed': 'Wed', 
                                      'Thu': 'Thu', 'Fri': 'Fri', 'Sat': 'Sat', 'Sun': 'Sun'}
                            weekday_nth_map[d.date()] = f"{dow_map[dow]}{week_of_month}"
                        return df['date'].dt.date.map(weekday_nth_map)
                    elif attr == '機種別':
                        return df['machine_name']
                    elif attr == '台番号別':
                        return df['machine_number'].astype(str)
                
                df_cross['attr1'] = get_attr_value(df_cross, attr1)
                df_cross['attr2'] = get_attr_value(df_cross, attr2)
                
                # クロス集計（勝率を含む）
                def agg_win_rate(x):
                    return (x > 0).sum() / len(x) * 100
                
                cross_summary = df_cross.groupby(['attr1', 'attr2']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_summary.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_summary = cross_summary.reset_index()
                cross_summary = cross_summary.sort_values('total_diff', ascending=False)
                
                # グラフ表示
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### 📊 クロス集計グラフ（差枚）")
                    fig = px.bar(
                        cross_summary.head(20),
                        x='attr1',
                        y='total_diff',
                        color='attr2',
                        title='',
                        labels={'attr1': attr1, 'attr2': attr2, 'total_diff': '差枚'},
                        height=500
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("### 🎲 クロス集計グラフ（G数 vs 差枚）")
                    fig = px.scatter(
                        cross_summary.head(20),
                        x='total_diff',
                        y='avg_games',
                        color='attr2',
                        size='count',
                        title='',
                        labels={'total_diff': '差枚', 'avg_games': '平均G数', 'attr2': attr2},
                        height=500
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                # テーブル表示
                st.markdown("---")
                st.markdown("### 📋 クロス検索結果（TOP20）")
                
                # フィルタ機能を追加
                st.markdown("**フィルタ機能:**")
                filter_col1, filter_col2 = st.columns(2)
                
                with filter_col1:
                    attr1_filter = st.multiselect(
                        f"{attr1}で絞り込み（複数選択可）",
                        sorted([str(x) for x in cross_summary['attr1'].unique()]),
                        key="cross_filter_attr1"
                    )
                
                with filter_col2:
                    attr2_filter = st.multiselect(
                        f"{attr2}で絞り込み（複数選択可）",
                        sorted([str(x) for x in cross_summary['attr2'].unique()]),
                        key="cross_filter_attr2"
                    )
                
                # フィルタを適用
                cross_filtered = cross_summary.copy()
                if attr1_filter:
                    cross_filtered = cross_filtered[cross_filtered['attr1'].astype(str).isin(attr1_filter)]
                if attr2_filter:
                    cross_filtered = cross_filtered[cross_filtered['attr2'].astype(str).isin(attr2_filter)]
                
                # フィルタ後のTOP20を表示
                display_data = []
                for idx, row in cross_filtered.head(20).iterrows():
                    display_data.append({
                        '順位': len(display_data) + 1,
                        attr1: str(row['attr1']),
                        attr2: str(row['attr2']),
                        '勝率': f"{row['win_rate']:.1f}%",
                        '合計差枚': int(row['total_diff']),
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '台数': int(row['count'])
                    })
                
                df_cross_display = pd.DataFrame(display_data)
                if df_cross_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_cross_display, use_container_width=True, hide_index=True)
                
                # 全表示テーブル
                st.markdown("---")
                st.markdown("### 📋 クロス検索結果（全データ）")
                
                # フィルタ後の全データを表示
                all_display_data = []
                for idx, row in cross_filtered.iterrows():
                    all_display_data.append({
                        attr1: str(row['attr1']),
                        attr2: str(row['attr2']),
                        '勝率': f"{row['win_rate']:.1f}%",
                        '合計差枚': int(row['total_diff']),
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '台数': int(row['count'])
                    })
                
                df_cross_all_display = pd.DataFrame(all_display_data)
                if df_cross_all_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_cross_all_display, use_container_width=True, hide_index=True)
                
                # サマリー表示（フィルタ後）
                st.markdown("---")
                st.markdown("### 📊 クロス分析サマリー")
                
                if not cross_filtered.empty:
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric(f"{attr1}パターン数", len(cross_filtered['attr1'].unique()))
                    
                    with col2:
                        st.metric(f"{attr2}パターン数", len(cross_filtered['attr2'].unique()))
                    
                    with col3:
                        st.metric("平均勝率", f"{cross_filtered['win_rate'].mean():.1f}%")
                    
                    with col4:
                        st.metric("平均差枚", f"{cross_filtered['avg_diff'].mean():.1f}枚")
                else:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")

# ========================================
# Page 12: 複合分析（DD別・曜日別）
# ========================================


elif analysis_page == "🔗 複合分析（DD別・曜日別）":
    st.markdown("## 複合分析（DD別・曜日別）")
    st.markdown("複数の属性を組み合わせた6つの分析をタブで表示します（タブを切り替えて確認）")
    
    # 期間の長さをチェック
    days_range = (date_range[1] - date_range[0]).days
    if days_range > 90:
        st.warning(f"⚠️ 期間が長い（{days_range}日）ため、処理に時間がかかる可能性があります。\n推奨期間: 30～60日。")
    
    # 期間内のすべての個別台データを集計
    all_machines = load_machine_detailed_results(str(st.session_state.db_path))
    
    if all_machines.empty:
        st.warning("⚠️ 個別台データが見つかりません")
    else:
        # 日付でフィルタ
        all_machines_filtered = all_machines[
            (all_machines['date'] >= date_range[0]) & 
            (all_machines['date'] <= date_range[1])
        ]
        
        if all_machines_filtered.empty:
            st.warning("⚠️ 指定期間にデータがありません")
        else:
            # 属性値を事前計算
            df_combined = all_machines_filtered.copy()
            df_combined['tail_digit'] = df_combined['machine_number'] % 10
            df_combined['day_of_month'] = df_combined['date'].dt.day
            
            dow_mapping = {0: '月', 1: '火', 2: '水', 3: '木', 4: '金', 5: '土', 6: '日'}
            df_combined['day_name'] = df_combined['date'].dt.dayofweek.map(dow_mapping)
            
            # 勝率計算用関数
            def agg_win_rate(x):
                return (x > 0).sum() / len(x) * 100
            
            # ================================================
            # タブで6つのパターンを表示
            # ================================================
            tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
                '📊 DD別×末尾別',
                '📊 DD別×機種別',
                '📊 DD別×台番号別',
                '📊 曜日別×末尾別',
                '📊 曜日別×機種別',
                '📊 曜日別×台番号別'
            ])
            
            # ================================================
            # Tab 1: DD別×台番号末尾別
            # ================================================
            with tab1:
                st.markdown("### 📊 DD別×台番号末尾別")
                
                cross_dd_tail = df_combined.groupby(['day_of_month', 'tail_digit']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_dd_tail.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_dd_tail = cross_dd_tail.reset_index()
                
                # ゾロ目データを別途計算して追加
                zorome_data = df_combined[df_combined['is_zorome'] == 1].groupby('day_of_month').agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                if not zorome_data.empty:
                    zorome_data.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                    zorome_data = zorome_data.reset_index()
                    zorome_data['tail_digit'] = 'ゾロ目'
                    cross_dd_tail = pd.concat([cross_dd_tail, zorome_data], ignore_index=True)
                
                cross_dd_tail = cross_dd_tail.sort_values('total_diff', ascending=False)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.bar(
                        cross_dd_tail.head(20),
                        x='day_of_month',
                        y='total_diff',
                        color='tail_digit',
                        title='DD別×末尾別 - 差枚TOP20',
                        labels={'day_of_month': 'DD', 'tail_digit': '末尾', 'total_diff': '差枚'},
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("**統計サマリー**")
                    st.write(f"- 総組み合わせ数: {len(cross_dd_tail)}")
                    st.write(f"- 平均差枚: {cross_dd_tail['avg_diff'].mean():.1f}枚")
                    st.write(f"- 平均勝率: {cross_dd_tail['win_rate'].mean():.1f}%")
                    st.write(f"- 最高勝率: {cross_dd_tail['win_rate'].max():.1f}%（DD:{cross_dd_tail.loc[cross_dd_tail['win_rate'].idxmax(), 'day_of_month']:.0f}, 末尾:{cross_dd_tail.loc[cross_dd_tail['win_rate'].idxmax(), 'tail_digit']}）")
                
                # テーブル表示
                st.markdown("**フィルタ機能:**")
                filter_dd_col1, filter_dd_col2 = st.columns(2)
                
                with filter_dd_col1:
                    dd_filter = st.multiselect(
                        "DD別で絞り込み（複数選択可）",
                        sorted([int(x) for x in cross_dd_tail['day_of_month'].unique()]),
                        key="composite_dd_tail_dd"
                    )
                
                with filter_dd_col2:
                    # ゾロ目オプションを含めたフィルタ
                    tail_options = sorted([int(x) for x in cross_dd_tail[cross_dd_tail['tail_digit'] != 'ゾロ目']['tail_digit'].unique()])
                    tail_options_display = tail_options + ['ゾロ目']
                    tail_filter = st.multiselect(
                        "末尾で絞り込み（複数選択可）",
                        tail_options_display,
                        key="composite_dd_tail_tail"
                    )
                
                # フィルタを適用
                cross_dd_tail_filtered = cross_dd_tail.copy()
                if dd_filter:
                    cross_dd_tail_filtered = cross_dd_tail_filtered[cross_dd_tail_filtered['day_of_month'].isin(dd_filter)]
                if tail_filter:
                    cross_dd_tail_filtered = cross_dd_tail_filtered[
                        cross_dd_tail_filtered['tail_digit'].isin([str(x) if x != 'ゾロ目' else x for x in tail_filter])
                    ]
                
                # フィルタ後のデータを表示
                display_data = []
                for idx, row in cross_dd_tail_filtered.head(15).iterrows():
                    tail_val = row['tail_digit']
                    if tail_val == 'ゾロ目':
                        tail_display = 'ゾロ目'
                    else:
                        tail_display = int(tail_val)
                    
                    display_data.append({
                        'DD': int(row['day_of_month']),
                        '末尾': tail_display,
                        '勝率': f"{row['win_rate']:.1f}%",
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '台数': int(row['count'])
                    })
                df_display = pd.DataFrame(display_data)
                if df_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ================================================
            # Tab 2: DD別×機種別
            # ================================================
            with tab2:
                st.markdown("### 📊 DD別×機種別")
                
                cross_dd_machine = df_combined.groupby(['day_of_month', 'machine_name']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_dd_machine.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_dd_machine = cross_dd_machine.reset_index()
                cross_dd_machine = cross_dd_machine.sort_values('total_diff', ascending=False)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.bar(
                        cross_dd_machine.head(20),
                        x='day_of_month',
                        y='total_diff',
                        color='machine_name',
                        title='DD別×機種別 - 差枚TOP20',
                        labels={'day_of_month': 'DD', 'machine_name': '機種', 'total_diff': '差枚'},
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("**統計サマリー**")
                    st.write(f"- 総組み合わせ数: {len(cross_dd_machine)}")
                    st.write(f"- 平均差枚: {cross_dd_machine['avg_diff'].mean():.1f}枚")
                    st.write(f"- 平均勝率: {cross_dd_machine['win_rate'].mean():.1f}%")
                    st.write(f"- 最高勝率: {cross_dd_machine['win_rate'].max():.1f}%")
                
                # テーブル表示
                st.markdown("**フィルタ機能:**")
                filter_dd_col1, filter_dd_col2 = st.columns(2)
                
                with filter_dd_col1:
                    dd_filter_machine = st.multiselect(
                        "DD別で絞り込み（複数選択可）",
                        sorted([int(x) for x in cross_dd_machine['day_of_month'].unique()]),
                        key="composite_dd_machine_dd"
                    )
                
                with filter_dd_col2:
                    machine_filter = st.multiselect(
                        "機種で絞り込み（複数選択可）",
                        sorted([str(x) for x in cross_dd_machine['machine_name'].unique()]),
                        key="composite_dd_machine_machine"
                    )
                
                # フィルタを適用
                cross_dd_machine_filtered = cross_dd_machine.copy()
                if dd_filter_machine:
                    cross_dd_machine_filtered = cross_dd_machine_filtered[cross_dd_machine_filtered['day_of_month'].isin(dd_filter_machine)]
                if machine_filter:
                    cross_dd_machine_filtered = cross_dd_machine_filtered[cross_dd_machine_filtered['machine_name'].isin(machine_filter)]
                
                # フィルタ後のデータを表示
                display_data = []
                for idx, row in cross_dd_machine_filtered.head(15).iterrows():
                    display_data.append({
                        'DD': int(row['day_of_month']),
                        '機種': row['machine_name'],
                        '勝率': f"{row['win_rate']:.1f}%",
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '台数': int(row['count'])
                    })
                df_display = pd.DataFrame(display_data)
                if df_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ================================================
            # Tab 3: DD別×台番号別
            # ================================================
            with tab3:
                st.markdown("### 📊 DD別×台番号別")
                
                cross_dd_number = df_combined.groupby(['day_of_month', 'machine_number']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_dd_number.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_dd_number = cross_dd_number.reset_index()
                cross_dd_number = cross_dd_number.sort_values('total_diff', ascending=False)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.scatter(
                        cross_dd_number.head(30),
                        x='day_of_month',
                        y='avg_diff',
                        size='count',
                        color='win_rate',
                        title='DD別×台番号別 - 差枚分布',
                        labels={'day_of_month': 'DD', 'avg_diff': '平均差枚', 'count': '台数', 'win_rate': '勝率(%)'},
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("**統計サマリー**")
                    st.write(f"- 総組み合わせ数: {len(cross_dd_number)}")
                    st.write(f"- 平均差枚: {cross_dd_number['avg_diff'].mean():.1f}枚")
                    st.write(f"- 平均勝率: {cross_dd_number['win_rate'].mean():.1f}%")
                    st.write(f"- 最高勝率: {cross_dd_number['win_rate'].max():.1f}%")
                
                # テーブル表示
                st.markdown("**フィルタ機能:**")
                filter_dd_col1, filter_dd_col2 = st.columns(2)
                
                with filter_dd_col1:
                    dd_filter_number = st.multiselect(
                        "DD別で絞り込み（複数選択可）",
                        sorted([int(x) for x in cross_dd_number['day_of_month'].unique()]),
                        key="composite_dd_number_dd"
                    )
                
                with filter_dd_col2:
                    number_filter = st.multiselect(
                        "台番号で絞り込み（複数選択可）",
                        sorted([int(x) for x in cross_dd_number['machine_number'].unique()]),
                        key="composite_dd_number_machine"
                    )
                
                # フィルタを適用
                cross_dd_number_filtered = cross_dd_number.copy()
                if dd_filter_number:
                    cross_dd_number_filtered = cross_dd_number_filtered[cross_dd_number_filtered['day_of_month'].isin(dd_filter_number)]
                if number_filter:
                    cross_dd_number_filtered = cross_dd_number_filtered[cross_dd_number_filtered['machine_number'].isin(number_filter)]
                
                # フィルタ後のデータを表示
                all_machine_names = all_machines_filtered.sort_values('date').groupby('machine_number')['machine_name'].apply(
                    lambda x: ' → '.join(x.unique())
                )
                
                display_data = []
                for idx, row in cross_dd_number_filtered.head(15).iterrows():
                    machine_num = int(row['machine_number'])
                    machine_name = all_machine_names.get(machine_num, '不明')
                    display_data.append({
                        'DD': int(row['day_of_month']),
                        '台番号': machine_num,
                        '機種': machine_name,
                        '勝率': f"{row['win_rate']:.1f}%",
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '稼働日数': int(row['count'])
                    })
                df_display = pd.DataFrame(display_data)
                if df_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ================================================
            # Tab 4: 曜日別×台番号末尾別
            # ================================================
            with tab4:
                st.markdown("### 📊 曜日別×台番号末尾別")
                
                cross_dow_tail = df_combined.groupby(['day_name', 'tail_digit']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_dow_tail.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_dow_tail = cross_dow_tail.reset_index()
                
                # ゾロ目データを別途計算して追加
                zorome_data_dow = df_combined[df_combined['is_zorome'] == 1].groupby('day_name').agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                if not zorome_data_dow.empty:
                    zorome_data_dow.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                    zorome_data_dow = zorome_data_dow.reset_index()
                    zorome_data_dow['tail_digit'] = 'ゾロ目'
                    cross_dow_tail = pd.concat([cross_dow_tail, zorome_data_dow], ignore_index=True)
                
                # 曜日順にソート
                dow_order = ['月', '火', '水', '木', '金', '土', '日']
                cross_dow_tail['day_name'] = pd.Categorical(cross_dow_tail['day_name'], categories=dow_order, ordered=True)
                cross_dow_tail = cross_dow_tail.sort_values('day_name')
                cross_dow_tail = cross_dow_tail.sort_values('total_diff', ascending=False, kind='stable')
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.bar(
                        cross_dow_tail.head(20),
                        x='day_name',
                        y='total_diff',
                        color='tail_digit',
                        title='曜日別×末尾別 - 差枚TOP20',
                        labels={'day_name': '曜日', 'tail_digit': '末尾', 'total_diff': '差枚'},
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("**統計サマリー**")
                    st.write(f"- 総組み合わせ数: {len(cross_dow_tail)}")
                    st.write(f"- 平均差枚: {cross_dow_tail['avg_diff'].mean():.1f}枚")
                    st.write(f"- 平均勝率: {cross_dow_tail['win_rate'].mean():.1f}%")
                    st.write(f"- 最高勝率: {cross_dow_tail['win_rate'].max():.1f}%")
                
                # テーブル表示
                st.markdown("**フィルタ機能:**")
                filter_dow_col1, filter_dow_col2 = st.columns(2)
                
                with filter_dow_col1:
                    dow_filter = st.multiselect(
                        "曜日で絞り込み（複数選択可）",
                        dow_order,
                        key="composite_dow_tail_dow"
                    )
                
                with filter_dow_col2:
                    # ゾロ目オプションを含めたフィルタ
                    tail_options_dow = sorted([int(x) for x in cross_dow_tail[cross_dow_tail['tail_digit'] != 'ゾロ目']['tail_digit'].unique()])
                    tail_options_dow_display = tail_options_dow + ['ゾロ目']
                    tail_filter_dow = st.multiselect(
                        "末尾で絞り込み（複数選択可）",
                        tail_options_dow_display,
                        key="composite_dow_tail_tail"
                    )
                
                # フィルタを適用
                cross_dow_tail_filtered = cross_dow_tail.copy()
                if dow_filter:
                    cross_dow_tail_filtered = cross_dow_tail_filtered[cross_dow_tail_filtered['day_name'].isin(dow_filter)]
                if tail_filter_dow:
                    cross_dow_tail_filtered = cross_dow_tail_filtered[
                        cross_dow_tail_filtered['tail_digit'].isin([str(x) if x != 'ゾロ目' else x for x in tail_filter_dow])
                    ]
                
                # フィルタ後のデータを表示
                display_data = []
                for idx, row in cross_dow_tail_filtered.head(15).iterrows():
                    tail_val = row['tail_digit']
                    if tail_val == 'ゾロ目':
                        tail_display = 'ゾロ目'
                    else:
                        tail_display = int(tail_val)
                    
                    display_data.append({
                        '曜日': row['day_name'],
                        '末尾': tail_display,
                        '勝率': f"{row['win_rate']:.1f}%",
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '台数': int(row['count'])
                    })
                df_display = pd.DataFrame(display_data)
                if df_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ================================================
            # Tab 5: 曜日別×機種別
            # ================================================
            with tab5:
                st.markdown("### 📊 曜日別×機種別")
                
                cross_dow_machine = df_combined.groupby(['day_name', 'machine_name']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_dow_machine.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_dow_machine = cross_dow_machine.reset_index()
                cross_dow_machine = cross_dow_machine.sort_values('total_diff', ascending=False)
                
                # 曜日順にソート
                cross_dow_machine['day_name'] = pd.Categorical(cross_dow_machine['day_name'], categories=dow_order, ordered=True)
                cross_dow_machine = cross_dow_machine.sort_values('day_name')
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.bar(
                        cross_dow_machine.head(20),
                        x='day_name',
                        y='total_diff',
                        color='machine_name',
                        title='曜日別×機種別 - 差枚TOP20',
                        labels={'day_name': '曜日', 'machine_name': '機種', 'total_diff': '差枚'},
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("**統計サマリー**")
                    st.write(f"- 総組み合わせ数: {len(cross_dow_machine)}")
                    st.write(f"- 平均差枚: {cross_dow_machine['avg_diff'].mean():.1f}枚")
                    st.write(f"- 平均勝率: {cross_dow_machine['win_rate'].mean():.1f}%")
                    st.write(f"- 最高勝率: {cross_dow_machine['win_rate'].max():.1f}%")
                
                # テーブル表示
                st.markdown("**フィルタ機能:**")
                filter_dow_col1, filter_dow_col2 = st.columns(2)
                
                with filter_dow_col1:
                    dow_filter_machine = st.multiselect(
                        "曜日で絞り込み（複数選択可）",
                        dow_order,
                        key="composite_dow_machine_dow"
                    )
                
                with filter_dow_col2:
                    machine_filter_dow = st.multiselect(
                        "機種で絞り込み（複数選択可）",
                        sorted([str(x) for x in cross_dow_machine['machine_name'].unique()]),
                        key="composite_dow_machine_machine"
                    )
                
                # フィルタを適用
                cross_dow_machine_filtered = cross_dow_machine.copy()
                if dow_filter_machine:
                    cross_dow_machine_filtered = cross_dow_machine_filtered[cross_dow_machine_filtered['day_name'].isin(dow_filter_machine)]
                if machine_filter_dow:
                    cross_dow_machine_filtered = cross_dow_machine_filtered[cross_dow_machine_filtered['machine_name'].isin(machine_filter_dow)]
                
                # フィルタ後のデータを表示
                display_data = []
                for idx, row in cross_dow_machine_filtered.head(15).iterrows():
                    display_data.append({
                        '曜日': row['day_name'],
                        '機種': row['machine_name'],
                        '勝率': f"{row['win_rate']:.1f}%",
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '台数': int(row['count'])
                    })
                df_display = pd.DataFrame(display_data)
                if df_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ================================================
            # Tab 6: 曜日別×台番号別
            # ================================================
            with tab6:
                st.markdown("### 📊 曜日別×台番号別")
                
                cross_dow_number = df_combined.groupby(['day_name', 'machine_number']).agg({
                    'diff_coins_normalized': ['sum', 'mean', agg_win_rate, 'count'],
                    'games_normalized': 'mean'
                }).round(2)
                
                cross_dow_number.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
                cross_dow_number = cross_dow_number.reset_index()
                cross_dow_number = cross_dow_number.sort_values('total_diff', ascending=False)
                
                # 曜日順にソート
                cross_dow_number['day_name'] = pd.Categorical(cross_dow_number['day_name'], categories=dow_order, ordered=True)
                cross_dow_number = cross_dow_number.sort_values('day_name')
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.scatter(
                        cross_dow_number.head(30),
                        x='day_name',
                        y='avg_diff',
                        size='count',
                        color='win_rate',
                        title='曜日別×台番号別 - 差枚分布',
                        labels={'day_name': '曜日', 'avg_diff': '平均差枚', 'count': '台数', 'win_rate': '勝率(%)'},
                        height=400
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.markdown("**統計サマリー**")
                    st.write(f"- 総組み合わせ数: {len(cross_dow_number)}")
                    st.write(f"- 平均差枚: {cross_dow_number['avg_diff'].mean():.1f}枚")
                    st.write(f"- 平均勝率: {cross_dow_number['win_rate'].mean():.1f}%")
                    st.write(f"- 最高勝率: {cross_dow_number['win_rate'].max():.1f}%")
                
                # テーブル表示
                st.markdown("**フィルタ機能:**")
                filter_dow_col1, filter_dow_col2 = st.columns(2)
                
                with filter_dow_col1:
                    dow_filter_number = st.multiselect(
                        "曜日で絞り込み（複数選択可）",
                        dow_order,
                        key="composite_dow_number_dow"
                    )
                
                with filter_dow_col2:
                    number_filter_dow = st.multiselect(
                        "台番号で絞り込み（複数選択可）",
                        sorted([int(x) for x in cross_dow_number['machine_number'].unique()]),
                        key="composite_dow_number_machine"
                    )
                
                # フィルタを適用
                cross_dow_number_filtered = cross_dow_number.copy()
                if dow_filter_number:
                    cross_dow_number_filtered = cross_dow_number_filtered[cross_dow_number_filtered['day_name'].isin(dow_filter_number)]
                if number_filter_dow:
                    cross_dow_number_filtered = cross_dow_number_filtered[cross_dow_number_filtered['machine_number'].isin(number_filter_dow)]
                
                # フィルタ後のデータを表示
                display_data = []
                for idx, row in cross_dow_number_filtered.head(15).iterrows():
                    machine_num = int(row['machine_number'])
                    machine_name = all_machine_names.get(machine_num, '不明')
                    display_data.append({
                        '曜日': row['day_name'],
                        '台番号': machine_num,
                        '機種': machine_name,
                        '勝率': f"{row['win_rate']:.1f}%",
                        '平均差枚': int(row['avg_diff']),
                        '平均G数': int(row['avg_games']),
                        '稼働日数': int(row['count'])
                    })
                df_display = pd.DataFrame(display_data)
                if df_display.empty:
                    st.warning("⚠️ フィルタ条件に該当するデータがありません")
                else:
                    st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            # ================================================
            # 全体サマリー
            # ================================================
            st.markdown("---")
            st.markdown("## 📊 複合分析の全体サマリー")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("DD別パターン数", len(df_combined['day_of_month'].unique()))
                st.metric("曜日パターン数", len(df_combined['day_name'].unique()))
            
            with col2:
                st.metric("末尾パターン数", len(df_combined['tail_digit'].unique()))
                st.metric("機種パターン数", len(df_combined['machine_name'].unique()))
            
            with col3:
                st.metric("台番号数", len(df_combined['machine_number'].unique()))
                st.metric("総データ件数", len(df_combined))
            
            st.markdown("---")
            st.markdown("### 💡 分析のコツ")
            st.write("""
            - **タブの活用**: 6つの異なる視点から分析可能。複数のタブを比較して仮説を検証
            - **高勝率の組み合わせ**: TOP15テーブルの上位を注目。設定投入パターンの検出に有効
            - **高差枚の組み合わせ**: 絶対値の大きい組み合わせは、台数が多いこともあるため、平均差枚も確認推奨
            - **複数パターンの交差検証**: 同じ現象が異なるパターン（DD別×末尾別と曜日別×末尾別など）で確認できると信頼度UP
            - **期間の長さ**: 30日以上推奨。短すぎるとノイズが多く、長すぎるとパフォーマンス低下
            - **季節性の確認**: 同じDD（例：毎月25日）を複数ヶ月かけて集計すると、パターンの再現性がわかる
            """)



elif analysis_page == "ℹ️ 統計情報":
    st.markdown("## 統計情報")
    st.markdown("分析データの詳細な統計情報を表示します")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📊 勝率の統計")
        stats_win = {
            '平均': f"{df_filtered['win_rate'].mean():.2f}%",
            '中央値': f"{df_filtered['win_rate'].median():.2f}%",
            '標準偏差': f"{df_filtered['win_rate'].std():.2f}%",
            '最大値': f"{df_filtered['win_rate'].max():.2f}%",
            '最小値': f"{df_filtered['win_rate'].min():.2f}%",
            'Q1': f"{df_filtered['win_rate'].quantile(0.25):.2f}%",
            'Q3': f"{df_filtered['win_rate'].quantile(0.75):.2f}%"
        }
        for key, val in stats_win.items():
            st.write(f"**{key}**: {val}")
    
    with col2:
        st.markdown("### 🎲 G数の統計")
        stats_games = {
            '平均': f"{df_filtered['avg_games_per_machine'].mean():,.0f}G",
            '中央値': f"{df_filtered['avg_games_per_machine'].median():,.0f}G",
            '標準偏差': f"{df_filtered['avg_games_per_machine'].std():,.0f}G",
            '最大値': f"{df_filtered['avg_games_per_machine'].max():,.0f}G",
            '最小値': f"{df_filtered['avg_games_per_machine'].min():,.0f}G",
            'Q1': f"{df_filtered['avg_games_per_machine'].quantile(0.25):,.0f}G",
            'Q3': f"{df_filtered['avg_games_per_machine'].quantile(0.75):,.0f}G"
        }
        for key, val in stats_games.items():
            st.write(f"**{key}**: {val}")
    
    col3, col4 = st.columns(2)
    
    with col3:
        st.markdown("### 💰 差枚の統計")
        stats_diff = {
            '平均': f"{df_filtered['avg_diff_per_machine'].mean():,.0f}枚",
            '中央値': f"{df_filtered['avg_diff_per_machine'].median():,.0f}枚",
            '標準偏差': f"{df_filtered['avg_diff_per_machine'].std():,.0f}枚",
            '最大値': f"{df_filtered['avg_diff_per_machine'].max():,.0f}枚",
            '最小値': f"{df_filtered['avg_diff_per_machine'].min():,.0f}枚",
            'Q1': f"{df_filtered['avg_diff_per_machine'].quantile(0.25):,.0f}枚",
            'Q3': f"{df_filtered['avg_diff_per_machine'].quantile(0.75):,.0f}枚"
        }
        for key, val in stats_diff.items():
            st.write(f"**{key}**: {val}")
    
    with col4:
        st.markdown("### 🤖 稼働台数の統計")
        stats_machines = {
            '平均': f"{df_filtered['total_machines'].mean():,.0f}台",
            '中央値': f"{df_filtered['total_machines'].median():,.0f}台",
            '標準偏差': f"{df_filtered['total_machines'].std():,.0f}台",
            '最大値': f"{df_filtered['total_machines'].max():,.0f}台",
            '最小値': f"{df_filtered['total_machines'].min():,.0f}台"
        }
        for key, val in stats_machines.items():
            st.write(f"**{key}**: {val}")
    
    # データ概要
    st.markdown("---")
    st.markdown("### 📋 データ概要")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("分析期間", f"{df_filtered['date'].min().strftime('%Y-%m-%d')} 〜 {df_filtered['date'].max().strftime('%Y-%m-%d')}")
    
    with col2:
        st.metric("データ件数", f"{len(df_filtered)}件")
    
    with col3:
        st.metric("データ範囲", f"{(df_filtered['date'].max() - df_filtered['date'].min()).days}日間")

# ========================================
# Footer
# ========================================

st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #888; font-size: 12px;">
    Pachinko Analyzer Dashboard | Phase 3 Data Exploration
    <br>
    信頼性基準: G数 ≥ 1000G, サンプル数 ≥ 5
</div>
""", unsafe_allow_html=True)