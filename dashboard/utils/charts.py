"""
共通グラフ生成関数
全ページで重複していたグラフ生成ロジックを集約
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

try:
    from dashboard.design_system import COLORS
except ImportError:
    # streamlit が未インストールの環境（テスト等）用フォールバック
    COLORS = {
        'primary_dark': '#0f172a',
        'primary_navy': '#1e3a5f',
        'primary_accent': '#d4af37',
        'secondary_blue': '#3b82f6',
        'secondary_orange': '#f97316',
        'secondary_green': '#10b981',
        'secondary_red': '#ef4444',
    }

# ダークテーマ共通レイアウト設定
_DARK_LAYOUT = dict(
    plot_bgcolor='rgba(0,0,0,0)',
    paper_bgcolor='rgba(0,0,0,0)',
    font_color='#e2e8f0',
)


def create_bar_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: str = None,
    height: int = 400,
    **kwargs
) -> go.Figure:
    """統一されたバーチャートを生成する。空DataFrameは空のfigを返す。"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=height, **_DARK_LAYOUT)
        return fig
    bar_color = color or COLORS.get('secondary_blue', '#3b82f6')
    fig = px.bar(df, x=x, y=y, title=title, height=height, **kwargs)
    fig.update_traces(marker_color=bar_color)
    fig.update_layout(**_DARK_LAYOUT)
    return fig


def create_line_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: str = None,
    height: int = 400,
    **kwargs
) -> go.Figure:
    """統一された折れ線グラフを生成する。空DataFrameは空のfigを返す。"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=height, **_DARK_LAYOUT)
        return fig
    line_color = color or COLORS.get('secondary_blue', '#3b82f6')
    fig = px.line(df, x=x, y=y, title=title, height=height, **kwargs)
    fig.update_traces(line_color=line_color)
    fig.update_layout(**_DARK_LAYOUT)
    return fig


def create_scatter_chart(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    size: str = None,
    height: int = 400,
    **kwargs
) -> go.Figure:
    """統一された散布図を生成する。空DataFrameは空のfigを返す。"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=title, height=height, **_DARK_LAYOUT)
        return fig
    fig = px.scatter(df, x=x, y=y, title=title, size=size, height=height, **kwargs)
    fig.update_layout(**_DARK_LAYOUT)
    return fig
