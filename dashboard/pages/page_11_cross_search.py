"""
Page 11: クロス検索分析
複数属性の掛け算集計
"""

import streamlit as st
import pandas as pd
import plotly.express as px

from ..utils.data_loader import load_machine_detailed_results
from ..utils.attribute_calculator import get_attr_value
from ..design_system import section_title, premium_divider, COLORS


def _build_display_rows(
    df: pd.DataFrame,
    attr1: str,
    attr2: str,
    machine_names_dict: dict,
    latest_machine_dict: dict,
    show_latest_only: bool
) -> list:
    """クロス検索結果テーブルの行データを構築する（TOP20・全件共用）"""
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
        row_data['合計差枚'] = int(row['total_diff'])
        row_data['平均差枚'] = int(row['avg_diff'])
        row_data['平均G数'] = int(row['avg_games'])
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
    title: str
):
    """クロス検索結果テーブルを描画する"""
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


def render():
    """クロス検索分析のページを描画"""
    section_title("クロス検索分析", "複数の属性を組み合わせてフィルタリング・分析します")

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
            date_range = st.session_state.date_range
            min_games = st.session_state.min_games

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

                # min_games フィルタを適用（集計前）
                if not st.session_state.show_low_confidence:
                    df_cross = df_cross[df_cross['games_normalized'] >= min_games]

                # 属性値を計算（共有関数を使用）
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

                # 台番号別の場合、機種表示オプションを追加
                show_latest_only = False
                if attr1 == '台番号別' or attr2 == '台番号別':
                    show_latest_only = st.checkbox(
                        "✓ 最新の機種名のみを表示（台番号別用）",
                        value=True,
                        help="チェック時：各台番号の最新の機種のみ表示\nチェック外：時系列で全機種を表示（新 → 古）"
                    )

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

                # 台番号別の場合、機種名を日付順に取得
                machine_names_dict = {}  # すべての機種（新→古）
                latest_machine_dict = {}  # 最新の機種のみ

                if attr1 == '台番号別':
                    for machine_num in df_cross[df_cross['attr1'].notna()]['attr1'].unique():
                        machines_sorted = df_cross[df_cross['attr1'] == machine_num].sort_values('date', ascending=False)['machine_name'].unique()
                        machine_names_dict[machine_num] = ' → '.join(machines_sorted)  # 新→古
                        latest_machine_dict[machine_num] = machines_sorted[0] if len(machines_sorted) > 0 else ''
                elif attr2 == '台番号別':
                    for machine_num in df_cross[df_cross['attr2'].notna()]['attr2'].unique():
                        machines_sorted = df_cross[df_cross['attr2'] == machine_num].sort_values('date', ascending=False)['machine_name'].unique()
                        machine_names_dict[machine_num] = ' → '.join(machines_sorted)  # 新→古
                        latest_machine_dict[machine_num] = machines_sorted[0] if len(machines_sorted) > 0 else ''

                premium_divider()
                _render_cross_table(
                    cross_filtered.head(20), attr1, attr2,
                    machine_names_dict, latest_machine_dict, show_latest_only,
                    "📋 クロス検索結果（TOP20）"
                )

                premium_divider()
                _render_cross_table(
                    cross_filtered, attr1, attr2,
                    machine_names_dict, latest_machine_dict, show_latest_only,
                    "📋 クロス検索結果（全データ）"
                )

                # サマリー表示（フィルタ後）
                premium_divider()
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

                # Notion に保存ボタン
                premium_divider()
                st.markdown("### 📌 Notion に保存")
                if st.button("📌 結果を Notion に保存", key="save_to_notion"):
                    # セッション状態に保存
                    st.session_state.page_14_data = {
                        "date_range": (
                            st.session_state.date_range[0].strftime("%Y-%m-%d"),
                            st.session_state.date_range[1].strftime("%Y-%m-%d")
                        ),
                        "min_games": st.session_state.min_games,
                        "show_low_confidence": st.session_state.show_low_confidence,
                        "cross_attr1": attr1,
                        "cross_attr2": attr2,
                        "cross_filtered_data": cross_filtered,
                    }
                    st.switch_page("pages/page_14_notion_exporter.py")
