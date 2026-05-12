"""
クロス検索一括ページ（page_16）専用ユーティリティ。
page_11 とは独立（ロジックは同等の集計定義に合わせる）。
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import plotly.express as px

from .data_loader import load_machine_detailed_results
from .attribute_calculator import get_attr_value
from ..design_system import premium_divider


def prepare_machine_df(
    db_path: str,
    date_range: tuple,
    min_games: int,
    show_low_confidence: bool,
) -> pd.DataFrame:
    """個別台データを読み込み、期間・G数でフィルタした DataFrame を返す（date は datetime）。"""
    all_machines = load_machine_detailed_results(db_path)
    if all_machines.empty:
        return pd.DataFrame()

    all_machines = all_machines.copy()
    all_machines['date'] = pd.to_datetime(all_machines['date'], format='%Y%m%d')
    filtered = all_machines[
        (all_machines['date'] >= date_range[0]) & (all_machines['date'] <= date_range[1])
    ]
    if filtered.empty:
        return pd.DataFrame()

    if not show_low_confidence:
        filtered = filtered[filtered['games_normalized'] >= min_games]
    return filtered


def _agg_win_rate(x: pd.Series) -> float:
    return (x > 0).sum() / len(x) * 100


def compute_cross_summary(df_prepared: pd.DataFrame, attr1: str, attr2: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    クロス集計を返す。

    Returns:
        (cross_summary, df_cross) — df_cross は機種辞書用に attr 列付きのコピー
    """
    df_cross = df_prepared.copy()
    df_cross['attr1'] = get_attr_value(df_cross, attr1)
    df_cross['attr2'] = get_attr_value(df_cross, attr2)

    cross_summary = df_cross.groupby(['attr1', 'attr2']).agg({
        'diff_coins_normalized': ['sum', 'mean', _agg_win_rate, 'count'],
        'games_normalized': 'mean',
    }).round(2)
    cross_summary.columns = ['total_diff', 'avg_diff', 'win_rate', 'count', 'avg_games']
    cross_summary = cross_summary.reset_index().sort_values('total_diff', ascending=False)
    return cross_summary, df_cross


def build_machine_name_dicts(df_cross: pd.DataFrame, attr1: str, attr2: str) -> tuple[dict, dict]:
    """台番号別の機種表示用辞書（新→古 / 最新のみ）。"""
    machine_names_dict: dict = {}
    latest_machine_dict: dict = {}

    if attr1 == '台番号別':
        for machine_num in df_cross[df_cross['attr1'].notna()]['attr1'].unique():
            machines_sorted = (
                df_cross[df_cross['attr1'] == machine_num]
                .sort_values('date', ascending=False)['machine_name']
                .unique()
            )
            machine_names_dict[machine_num] = ' → '.join(machines_sorted)
            latest_machine_dict[machine_num] = machines_sorted[0] if len(machines_sorted) > 0 else ''
    elif attr2 == '台番号別':
        for machine_num in df_cross[df_cross['attr2'].notna()]['attr2'].unique():
            machines_sorted = (
                df_cross[df_cross['attr2'] == machine_num]
                .sort_values('date', ascending=False)['machine_name']
                .unique()
            )
            machine_names_dict[machine_num] = ' → '.join(machines_sorted)
            latest_machine_dict[machine_num] = machines_sorted[0] if len(machines_sorted) > 0 else ''

    return machine_names_dict, latest_machine_dict


def _build_display_rows(
    df: pd.DataFrame,
    attr1: str,
    attr2: str,
    machine_names_dict: dict,
    latest_machine_dict: dict,
    show_latest_only: bool,
) -> list:
    rows = []
    for _, row in df.iterrows():
        row_data = {attr1: str(row['attr1'])}
        if attr1 == '台番号別' and row['attr1'] in machine_names_dict:
            row_data['機種'] = (
                latest_machine_dict[row['attr1']] if show_latest_only
                else machine_names_dict[row['attr1']]
            )
        row_data[attr2] = str(row['attr2'])
        if attr2 == '台番号別' and row['attr2'] in machine_names_dict:
            row_data['機種'] = (
                latest_machine_dict[row['attr2']] if show_latest_only
                else machine_names_dict[row['attr2']]
            )
        row_data['勝率'] = float(row['win_rate'])
        row_data['平均差枚'] = int(row['avg_diff'])
        row_data['平均G数'] = int(row['avg_games'])
        row_data['合計差枚'] = int(row['total_diff'])
        row_data['台数'] = int(row['count'])
        rows.append(row_data)
    return rows


def _render_cross_table(
    df: pd.DataFrame,
    attr1: str,
    attr2: str,
    machine_names_dict: dict,
    latest_machine_dict: dict,
    show_latest_only: bool,
    title: str,
) -> None:
    rows = _build_display_rows(
        df, attr1, attr2, machine_names_dict, latest_machine_dict, show_latest_only
    )
    if not rows:
        st.warning("⚠️ フィルタ条件に該当するデータがありません")
        return
    df_display = pd.DataFrame(rows)
    df_display['勝率'] = df_display['勝率'].apply(lambda x: f"{x:.1f}%")
    st.markdown(f"### {title}")
    st.dataframe(df_display, use_container_width=True, hide_index=True)


def render_cross_search_block(
    df_prepared: pd.DataFrame,
    attr1: str,
    attr2: str,
    widget_key_prefix: str,
) -> None:
    """
    page_11 と同等の 1 組み合わせブロック（グラフ・表）を描画する。
    グローバルフィルタはページ冒頭で一括適用。
    すべてのウィジェット key は widget_key_prefix で一意にする。
    """
    cross_summary, df_cross = compute_cross_summary(df_prepared, attr1, attr2)

    if cross_summary.empty:
        st.warning("⚠️ 集計結果がありません")
        return

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
            height=500,
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
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)

    show_latest_only = False
    if attr1 == '台番号別' or attr2 == '台番号別':
        show_latest_only = st.checkbox(
            "✓ 最新の機種名のみを表示（台番号別用）",
            value=True,
            help="チェック時：各台番号の最新の機種のみ表示\nチェック外：時系列で全機種を表示（新 → 古）",
            key=f"{widget_key_prefix}_latest_machine",
        )

    machine_names_dict, latest_machine_dict = build_machine_name_dicts(df_cross, attr1, attr2)

    premium_divider()
    _render_cross_table(
        cross_summary.head(20),
        attr1,
        attr2,
        machine_names_dict,
        latest_machine_dict,
        show_latest_only,
        "📋 クロス検索結果（TOP20）",
    )

    premium_divider()
    _render_cross_table(
        cross_summary,
        attr1,
        attr2,
        machine_names_dict,
        latest_machine_dict,
        show_latest_only,
        "📋 クロス検索結果（全データ）",
    )
