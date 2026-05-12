"""
Page 16: クロス検索一括
DD別・曜日別タブで、末尾 / 機種 / 台番号とのクロスを一括表示する。
冒頭のグローバルフィルタで DD別・曜日別を一括選択可能。
"""

import streamlit as st
import pandas as pd

from ..design_system import section_title, premium_divider
from ..utils.cross_search_bulk import prepare_machine_df, render_cross_search_block
from ..utils.attribute_calculator import get_attr_value


def render():
    """クロス検索一括ページを描画"""
    section_title(
        "クロス検索一括",
        "DD別・曜日別ごとに、末尾・機種・台番号とのクロス集計をまとめて表示します（サイドバーの期間・G数フィルタを適用）。",
    )

    df_prepared = prepare_machine_df(
        str(st.session_state.db_path),
        st.session_state.date_range,
        st.session_state.min_games,
        st.session_state.show_low_confidence,
    )

    if df_prepared.empty:
        st.warning("⚠️ 個別台データがないか、指定期間・フィルタに該当するデータがありません")
        return

    st.markdown("### 🔍 グローバルフィルタ")
    filter_col1, filter_col2 = st.columns(2)

    df_with_attrs = df_prepared.copy()
    df_with_attrs['_dd'] = get_attr_value(df_with_attrs, 'DD別')
    df_with_attrs['_weekday'] = get_attr_value(df_with_attrs, '曜日')

    with filter_col1:
        dd_options = sorted([str(x) for x in df_with_attrs['_dd'].dropna().unique()])
        dd_filter = st.multiselect(
            "DD別（日付）で絞り込み（複数選択可）",
            dd_options,
            key="bulk16_global_dd_filter",
        )

    with filter_col2:
        weekday_options = sorted([str(x) for x in df_with_attrs['_weekday'].dropna().unique()])
        weekday_filter = st.multiselect(
            "曜日で絞り込み（複数選択可）",
            weekday_options,
            key="bulk16_global_weekday_filter",
        )

    premium_divider()

    def apply_global_filter(df: pd.DataFrame, attr: str, filter_values: list) -> pd.DataFrame:
        """グローバルフィルタを適用"""
        if not filter_values:
            return df
        df_temp = df.copy()
        df_temp['_attr'] = get_attr_value(df_temp, attr)
        return df_temp[df_temp['_attr'].astype(str).isin(filter_values)].drop(columns=['_attr'])

    df_dd_filtered = apply_global_filter(df_prepared, 'DD別', dd_filter)
    df_weekday_filtered = apply_global_filter(df_prepared, '曜日', weekday_filter)

    tab_dd, tab_weekday = st.tabs(["DD別", "曜日別"])

    with tab_dd:
        if df_dd_filtered.empty:
            st.warning("⚠️ 選択されたDD条件に該当するデータがありません")
        else:
            st.markdown("### DD別 × 台番号末尾")
            render_cross_search_block(df_dd_filtered, "DD別", "台番号末尾", "bulk16_dd_lastdigit")
            premium_divider()

            st.markdown("### DD別 × 機種別")
            render_cross_search_block(df_dd_filtered, "DD別", "機種別", "bulk16_dd_machine")
            premium_divider()

            st.markdown("### DD別 × 台番号別")
            render_cross_search_block(df_dd_filtered, "DD別", "台番号別", "bulk16_dd_machineno")

    with tab_weekday:
        if df_weekday_filtered.empty:
            st.warning("⚠️ 選択された曜日条件に該当するデータがありません")
        else:
            st.markdown("### 曜日 × 台番号末尾")
            render_cross_search_block(df_weekday_filtered, "曜日", "台番号末尾", "bulk16_dow_lastdigit")
            premium_divider()

            st.markdown("### 曜日 × 機種別")
            render_cross_search_block(df_weekday_filtered, "曜日", "機種別", "bulk16_dow_machine")
            premium_divider()

            st.markdown("### 曜日 × 台番号別")
            render_cross_search_block(df_weekday_filtered, "曜日", "台番号別", "bulk16_dow_machineno")
