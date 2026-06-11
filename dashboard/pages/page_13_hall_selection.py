"""
Page 13: ホール選択支援
複数ホール間での日付属性別成績比較
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from pathlib import Path
import sqlite3

from ..utils.data_loader import get_all_hall_paths
from ..utils.filters import apply_sidebar_filters, filter_by_min_games
from ..design_system import section_title, premium_divider, COLORS


def render():
    """ホール選択支援ページを描画"""
    section_title("ホール選択支援", "複数ホール間での日付属性別成績比較")

    # すべてのホール DB パスを取得
    hall_paths = get_all_hall_paths(Path('./db'))

    if not hall_paths:
        st.warning("⚠️ ホール DB が見つかりません")
        return

    # 8つの属性タブを定義
    tabs = st.tabs([
        "曜日別",
        "DD別",
        "日末尾別",
        "月初別",
        "月末別",
        "ゾロ目別",
        "強ゾロ目別",
        "全期間"
    ])

    # タブごとの属性定義
    attribute_configs = [
        {"attribute": "day_of_week", "label": "曜日別", "type": "categorical"},
        {"attribute": "none", "label": "DD別", "type": "dd"},
        {"attribute": "last_digit", "label": "日末尾別", "type": "numeric"},
        {"attribute": "is_month_start", "label": "月初別", "type": "binary"},
        {"attribute": "is_month_end", "label": "月末別", "type": "binary"},
        {"attribute": "is_zorome", "label": "ゾロ目別", "type": "binary"},
        {"attribute": "is_strong_zorome", "label": "強ゾロ目別", "type": "binary"},
        {"attribute": "all", "label": "全期間", "type": "all"}
    ]

    # ベースラインを一度だけ計算（キャッシュ対応）
    hall_paths_tuple = tuple(sorted(hall_paths.items()))
    hall_baselines = compute_hall_baselines(hall_paths_tuple, st.session_state.min_games, st.session_state.show_low_confidence)

    # 各タブの処理
    for idx, tab in enumerate(tabs):
        with tab:
            config = attribute_configs[idx]
            render_attribute_tab(config, hall_paths, hall_baselines)


@st.cache_data(ttl=3600)
def load_daily_hall_summary_all(db_path: str) -> pd.DataFrame:
    """ホール全体の日別集計データをすべて読み込み"""
    try:
        with sqlite3.connect(db_path) as conn:
            query = "SELECT * FROM daily_hall_summary ORDER BY date"
            df = pd.read_sql_query(query, conn)

        if not df.empty:
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')

        return df
    except Exception as e:
        st.warning(f"データ読み込みエラー ({db_path}): {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def compute_hall_baselines(hall_paths_tuple: tuple, min_games: int, show_low: bool) -> dict:
    """
    各ホールの DB 全期間ベースライン（日別平均の平均）。
    日付スライダーは適用せず、min_games / 参考値はサイドバーと同一。

    注：hall_paths は dict のままではキャッシュ不可なので tuple に変換してから渡す
    """
    baselines = {}

    for hall_name, hall_path in hall_paths_tuple:
        df_full = load_daily_hall_summary_all(str(hall_path))
        if df_full.empty:
            continue
        if not show_low:
            df_full = filter_by_min_games(df_full, min_games, 'avg_games_per_machine')
        if df_full.empty:
            continue
        baselines[hall_name] = {
            'win_rate': float(df_full['win_rate'].mean()),
            'avg_games': float(df_full['avg_games_per_machine'].mean()),
            'avg_diff': float(df_full['avg_diff_per_machine'].mean()),
        }
    return baselines


def _compute_attribute_groups(df: pd.DataFrame, attr_type: str, attribute: str, label: str = None) -> list:
    """属性タイプに基づいてグループ化"""
    groups = []

    if attr_type == "all":
        groups.append(('全期間', df))
    elif attr_type == "binary":
        df_filtered = df[df[attribute] == 1]
        if not df_filtered.empty:
            # binary型の場合、日本語ラベルを使用（例：label="月初別" で "月初" と表示）
            group_label = label.rstrip('別') if label else attribute
            groups.append((group_label, df_filtered))
    elif attr_type == "numeric":
        for digit in range(10):
            df_filtered = df[df[attribute] == digit]
            if not df_filtered.empty:
                groups.append((f'末尾{digit}', df_filtered))
    elif attr_type == "categorical":
        for attr_val in sorted(df[attribute].dropna().unique()):
            df_filtered = df[df[attribute] == attr_val]
            if not df_filtered.empty:
                groups.append((str(attr_val), df_filtered))
    elif attr_type == "dd":
        df['dd'] = df['date'].dt.day
        for dd in sorted(df['dd'].unique()):
            df_filtered = df[df['dd'] == dd]
            if not df_filtered.empty:
                groups.append((f'{int(dd)}日', df_filtered))
        df.drop(columns=['dd'], inplace=True)

    return groups


def render_attribute_tab(config, hall_paths, hall_baselines):
    """属性別タブを描画"""
    attribute = config["attribute"]
    label = config["label"]
    attr_type = config["type"]

    st.markdown(f"### {label}")

    # 全ホールのデータを統合
    all_hall_data = {}
    for hall_name, hall_path in sorted(hall_paths.items()):
        df = load_daily_hall_summary_all(str(hall_path))
        if df.empty:
            continue
        df = apply_sidebar_filters(
            df,
            date_range=st.session_state.date_range,
            min_games=st.session_state.min_games,
            show_low_confidence=st.session_state.show_low_confidence,
        )
        if not df.empty:
            all_hall_data[hall_name] = df

    if not all_hall_data:
        st.warning("⚠️ 指定条件に該当するデータがありません")
        return

    # 属性に基づいて集計
    all_rows = []
    for hall_name, df in all_hall_data.items():
        groups = _compute_attribute_groups(df, attr_type, attribute, label)
        for attr_label, df_group in groups:
            all_rows.append({
                'ホール': hall_name,
                '属性': attr_label,
                '勝率': df_group['win_rate'].mean(),
                '平均G数': df_group['avg_games_per_machine'].mean(),
                '平均差枚': df_group['avg_diff_per_machine'].mean(),
                'データ日数': len(df_group)
            })

    if not all_rows:
        st.warning("⚠️ フィルタ後、該当するデータがありません")
        return

    df_raw = pd.DataFrame(all_rows)

    # フィルタ機能を追加
    st.markdown("**フィルタ機能:**")
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        hall_filter = st.multiselect(
            "ホールで絞り込み（複数選択可）",
            sorted(df_raw['ホール'].unique()),
            key=f"hall_filter_{label}"
        )

    with filter_col2:
        attr_filter = st.multiselect(
            f"{label}で絞り込み（複数選択可）",
            sorted([str(x) for x in df_raw['属性'].unique()]),
            key=f"attr_filter_{label}"
        )

    # フィルタを適用
    df_filtered = df_raw.copy()
    if hall_filter:
        df_filtered = df_filtered[df_filtered['ホール'].isin(hall_filter)]
    if attr_filter:
        df_filtered = df_filtered[df_filtered['属性'].astype(str).isin(attr_filter)]

    if df_filtered.empty:
        st.warning("⚠️ フィルタ条件に該当するデータがありません")
        return

    st.caption(
        "勝率差・平均差枚差・平均G数差は、そのホールの DB 全期間平均（日付は未絞り、最小G数・参考値はサイドバーと同一）との差。"
        "勝率差の単位はパーセントポイント（pt）。ベースラインが無い行は差が空欄になります。"
    )

    def get_baseline_series(df_filtered: pd.DataFrame, hall_baselines: dict, key: str) -> pd.Series:
        return df_filtered['ホール'].apply(lambda n: hall_baselines.get(n, {}).get(key, float('nan')))

    base_win = get_baseline_series(df_filtered, hall_baselines, 'win_rate')
    base_games = get_baseline_series(df_filtered, hall_baselines, 'avg_games')
    base_diff = get_baseline_series(df_filtered, hall_baselines, 'avg_diff')

    df_display = pd.DataFrame({
        'ホール': df_filtered['ホール'],
        '属性': df_filtered['属性'],
        '勝率': (df_filtered['勝率']).round(1),
        '勝率差': (df_filtered['勝率'] - base_win).round(1),
        '平均差枚': (df_filtered['平均差枚']).round().astype('Int64'),
        '平均差枚差': (df_filtered['平均差枚'] - base_diff).round().astype('Int64'),
        '平均G数': (df_filtered['平均G数']).round().astype('Int64'),
        '平均G数差': (df_filtered['平均G数'] - base_games).round().astype('Int64'),
        'データ日数': df_filtered['データ日数'],
    })

    premium_divider()
    st.markdown(f"### 📋 {label} 比較結果")
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # グラフ表示
    if attr_type != "all" and len(df_filtered) > 0:
        premium_divider()
        st.markdown("### 📊 グラフ")

        col1, col2 = st.columns(2)

        with col1:
            top_data = df_filtered.nlargest(15, '平均差枚') if len(df_filtered) > 15 else df_filtered
            fig = px.bar(
                top_data,
                x='ホール',
                y='平均差枚',
                color='属性',
                title='平均差枚 TOP',
                labels={'平均差枚': '平均差枚 (枚)', 'ホール': 'ホール'},
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = px.scatter(
                df_filtered,
                x='平均G数',
                y='平均差枚',
                color='ホール',
                size='データ日数',
                title='G数 vs 差枚',
                labels={'平均G数': '平均G数 (G)', '平均差枚': '平均差枚 (枚)'},
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)

    # サマリー
    premium_divider()
    st.markdown("### 📊 サマリー統計")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("ホール数", len(df_filtered['ホール'].unique()))

    with col2:
        st.metric("属性バリエーション", len(df_filtered['属性'].unique()))

    with col3:
        st.metric("平均差枚", f"{int(df_filtered['平均差枚'].mean()):,}枚")

    with col4:
        st.metric("平均勝率", f"{df_filtered['勝率'].mean():.1f}%")
