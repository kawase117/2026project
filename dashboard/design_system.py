"""
Pachinko Analyzer Design System
ラグジュアリー＆洗練されたデータ分析ダッシュボードの完全なデザインシステム

Design Philosophy:
- トーン：Refined Luxury + Data Precision（洗練された高級感 + データの正確性）
- カラー：深紺 + 金色アクセント + データ色（青・オレンジ・緑）
- タイポグラフィ：モダンで読みやすい + 数値の強調
- レイアウト：グリッドベース + 贅沢な余白
"""

import streamlit as st


# ========================================
# カラーパレット
# ========================================

COLORS = {
    # プライマリカラー（高級感）
    'primary_dark': '#0f172a',      # 深紺
    'primary_navy': '#1e3a5f',      # 紺
    'primary_accent': '#d4af37',    # 金色

    # セカンダリカラー（データ可視化）
    'secondary_blue': '#3b82f6',    # 勝率（青）
    'secondary_orange': '#f97316',  # G数（オレンジ）
    'secondary_green': '#10b981',   # 差枚（緑）
    'secondary_red': '#ef4444',     # 異常値（赤）

    # ニュートラルカラー
    'neutral_50': '#f9fafb',        # ほぼ白
    'neutral_100': '#f3f4f6',
    'neutral_200': '#e5e7eb',
    'neutral_300': '#d1d5db',
    'neutral_400': '#9ca3af',
    'neutral_500': '#6b7280',
    'neutral_600': '#4b5563',
    'neutral_700': '#374151',
    'neutral_800': '#1f2937',
    'neutral_900': '#111827',       # ほぼ黒

    # ステータスカラー
    'status_success': '#10b981',    # 成功（緑）
    'status_warning': '#f59e0b',    # 警告（黄）
    'status_error': '#ef4444',      # エラー（赤）
    'status_info': '#3b82f6',       # 情報（青）
}


# ========================================
# タイポグラフィシステム
# ========================================

TYPOGRAPHY = {
    # フォントファミリー
    'font_heading': '"Noto Sans JP", "Segoe UI", sans-serif',  # 見出し用（和モダン）
    'font_body': '"Segoe UI", "Roboto", sans-serif',           # 本文用
    'font_mono': '"Fira Code", "Monaco", monospace',           # 数値用

    # フォントサイズ体系
    'size_xs': '12px',    # ラベル、ヘルプテキスト
    'size_sm': '14px',    # サブテキスト
    'size_base': '16px',  # 本文
    'size_lg': '18px',    # 小見出し
    'size_xl': '20px',    # 見出し 3
    'size_2xl': '24px',   # 見出し 2
    'size_3xl': '32px',   # 見出し 1
    'size_4xl': '40px',   # ページタイトル

    # フォントウェイト
    'weight_light': 300,
    'weight_regular': 400,
    'weight_medium': 500,
    'weight_semibold': 600,
    'weight_bold': 700,

    # 行高さ
    'leading_tight': '1.2',
    'leading_normal': '1.5',
    'leading_relaxed': '1.75',
}


# ========================================
# スペーシング & レイアウト
# ========================================

SPACING = {
    'xs': '4px',
    'sm': '8px',
    'md': '16px',
    'lg': '24px',
    'xl': '32px',
    '2xl': '48px',
    '3xl': '64px',
}

LAYOUT = {
    'border_radius_sm': '4px',
    'border_radius_md': '8px',
    'border_radius_lg': '12px',
    'shadow_sm': '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
    'shadow_md': '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
    'shadow_lg': '0 10px 15px -3px rgba(0, 0, 0, 0.15)',
    'shadow_xl': '0 20px 25px -5px rgba(0, 0, 0, 0.2)',
}


# ========================================
# Streamlit CSS スタイリング
# ========================================

def get_design_system_css():
    """完全なデザインシステムのCSS"""
    return f"""
    <style>
        /* ========================================
           グローバルスタイル
           ======================================== */

        * {{
            font-family: {TYPOGRAPHY['font_body']};
        }}

        /* ========================================
           背景＆テーマ
           ======================================== */

        [data-testid="stSidebar"] {{
            background: linear-gradient(135deg, {COLORS['primary_dark']} 0%, {COLORS['primary_navy']} 100%);
            box-shadow: inset -2px 0 8px rgba(0, 0, 0, 0.3);
        }}

        [data-testid="stAppViewContainer"] {{
            background-color: {COLORS['primary_dark']};
        }}

        /* ========================================
           テキストカラー
           ======================================== */

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{
            color: {COLORS['neutral_50']};
        }}

        [data-testid="stAppViewContainer"] {{
            color: {COLORS['neutral_100']};
        }}

        /* ========================================
           ヘッダー＆タイトル
           ======================================== */

        h1 {{
            font-family: {TYPOGRAPHY['font_heading']};
            font-size: {TYPOGRAPHY['size_4xl']};
            font-weight: {TYPOGRAPHY['weight_bold']};
            color: {COLORS['neutral_50']};
            letter-spacing: -0.02em;
            margin-bottom: {SPACING['lg']};
        }}

        h2 {{
            font-family: {TYPOGRAPHY['font_heading']};
            font-size: {TYPOGRAPHY['size_3xl']};
            font-weight: {TYPOGRAPHY['weight_bold']};
            color: {COLORS['primary_accent']};
            margin-top: {SPACING['2xl']};
            margin-bottom: {SPACING['lg']};
            padding-bottom: {SPACING['md']};
            border-bottom: 2px solid {COLORS['primary_accent']};
        }}

        h3 {{
            font-family: {TYPOGRAPHY['font_heading']};
            font-size: {TYPOGRAPHY['size_2xl']};
            font-weight: {TYPOGRAPHY['weight_semibold']};
            color: {COLORS['neutral_100']};
            margin-top: {SPACING['xl']};
            margin-bottom: {SPACING['md']};
        }}

        /* ========================================
           メトリクスカード
           ======================================== */

        .metric-container {{
            background: linear-gradient(135deg, {COLORS['primary_navy']} 0%, rgba({int("1e3a5f"[1:3], 16)}, {int("1e3a5f"[3:5], 16)}, {int("1e3a5f"[5:7], 16)}, 0.8) 100%);
            border: 1px solid {COLORS['primary_accent']};
            border-radius: {LAYOUT['border_radius_lg']};
            padding: {SPACING['lg']};
            margin: {SPACING['md']} 0;
            box-shadow: 0 4px 20px rgba(212, 175, 55, 0.1);
            backdrop-filter: blur(10px);
        }}

        /* ========================================
           ボタン
           ======================================== */

        button {{
            font-family: {TYPOGRAPHY['font_heading']};
            font-weight: {TYPOGRAPHY['weight_semibold']};
            border-radius: {LAYOUT['border_radius_md']};
            transition: all 0.3s ease;
        }}

        button:hover {{
            transform: translateY(-2px);
            box-shadow: {LAYOUT['shadow_lg']};
        }}

        /* ========================================
           入力フィーム
           ======================================== */

        [data-testid="stSidebar"] label {{
            color: {COLORS['primary_accent']};
            font-weight: {TYPOGRAPHY['weight_semibold']};
            font-size: {TYPOGRAPHY['size_sm']};
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}

        /* ========================================
           区切り線
           ======================================== */

        hr {{
            border-color: {COLORS['primary_accent']};
            opacity: 0.3;
            margin: {SPACING['lg']} 0;
        }}

        /* ========================================
           テーブル
           ======================================== */

        [data-testid="stDataframe"] {{
            border: 1px solid {COLORS['primary_accent']};
            border-radius: {LAYOUT['border_radius_md']};
            overflow: hidden;
        }}

        /* ========================================
           スクロールバー
           ======================================== */

        ::-webkit-scrollbar {{
            width: 8px;
        }}

        ::-webkit-scrollbar-track {{
            background: {COLORS['primary_navy']};
        }}

        ::-webkit-scrollbar-thumb {{
            background: {COLORS['primary_accent']};
            border-radius: 4px;
        }}

        ::-webkit-scrollbar-thumb:hover {{
            background: {COLORS['neutral_400']};
        }}

        /* ========================================
           アラート＆警告
           ======================================== */

        .alert {{
            border-left: 4px solid;
            border-radius: {LAYOUT['border_radius_md']};
            padding: {SPACING['md']};
            margin: {SPACING['md']} 0;
        }}

        .alert-success {{
            background: rgba({int("10b981"[1:3], 16)}, {int("10b981"[3:5], 16)}, {int("10b981"[5:7], 16)}, 0.1);
            border-color: {COLORS['status_success']};
        }}

        .alert-warning {{
            background: rgba({int("f59e0b"[1:3], 16)}, {int("f59e0b"[3:5], 16)}, {int("f59e0b"[5:7], 16)}, 0.1);
            border-color: {COLORS['status_warning']};
        }}

        .alert-error {{
            background: rgba({int("ef4444"[1:3], 16)}, {int("ef4444"[3:5], 16)}, {int("ef4444"[5:7], 16)}, 0.1);
            border-color: {COLORS['status_error']};
        }}
    </style>
    """


def apply_design_system():
    """デザインシステムを適用"""
    st.markdown(get_design_system_css(), unsafe_allow_html=True)


# ========================================
# コンポーネント関数
# ========================================

def metric_card(label: str, value: str, delta: str = None, icon: str = "📊"):
    """ラグジュアリーなメトリクスカード"""
    html = f"""<div style="
        background: linear-gradient(135deg, {COLORS['primary_navy']} 0%, rgba(30, 58, 95, 0.8) 100%);
        border: 1px solid {COLORS['primary_accent']};
        border-radius: {LAYOUT['border_radius_lg']};
        padding: {SPACING['lg']};
        margin: {SPACING['md']} 0;
        box-shadow: 0 4px 20px rgba(212, 175, 55, 0.1);
    ">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <div>
                <div style="
                    font-size: {TYPOGRAPHY['size_xs']};
                    color: {COLORS['neutral_400']};
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    font-weight: {TYPOGRAPHY['weight_semibold']};
                    margin-bottom: {SPACING['xs']};
                ">{label}</div>
                <div style="
                    font-size: {TYPOGRAPHY['size_3xl']};
                    font-weight: {TYPOGRAPHY['weight_bold']};
                    color: {COLORS['primary_accent']};
                    font-family: {TYPOGRAPHY['font_mono']};
                ">{value}</div>
            </div>
            <div style="font-size: {TYPOGRAPHY['size_4xl']}; opacity: 0.5;">{icon}</div>
        </div>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)


def section_title(title: str, subtitle: str = None):
    """セクションタイトル"""
    st.markdown(f"## {title}")
    if subtitle:
        st.markdown(f"*{subtitle}*", help=subtitle)


def premium_divider():
    """プレミアムな区切り線"""
    st.markdown(
        f"""
        <div style="
            height: 2px;
            background: linear-gradient(90deg, transparent, {COLORS['primary_accent']}, transparent);
            margin: {SPACING['lg']} 0;
            border-radius: 1px;
        "></div>
        """,
        unsafe_allow_html=True
    )


# ========================================
# エクスポート
# ========================================

__all__ = [
    'COLORS',
    'TYPOGRAPHY',
    'SPACING',
    'LAYOUT',
    'apply_design_system',
    'metric_card',
    'section_title',
    'premium_divider',
]
