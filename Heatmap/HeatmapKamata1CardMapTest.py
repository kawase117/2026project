"""Streamlit viewer for the Kamata1 card-map prototype."""

from __future__ import annotations

from generate_kamata1_cardmap_html import (
    DEFAULT_OUTPUT_PATH,
    FLOOR_SPECS,
    DB_PATH,
    METRICS,
    WEEKDAY_LABELS,
    build_kamata1_cardmap_html,
)


def main() -> None:
    import streamlit as st
    from streamlit.components.v1 import html as components_html

    try:
        from Heatmap.heatmap_common import render_last_digit_highlight
    except ModuleNotFoundError:
        from heatmap_common import render_last_digit_highlight

    st.set_page_config(
        page_title="蒲田1 カード型フロアマップ試作",
        layout="wide",
    )
    st.title("蒲田1 カード型フロアマップ試作")
    st.caption(
        "HTML/CSSカード版の検証ビューです。ページ再読み込み時にHTMLを再生成し、末尾ハイライトも確認できます。"
    )

    today = st.session_state.get("kamata1_today")
    if today is None:
        from datetime import date

        today = date.today()
        st.session_state["kamata1_today"] = today

    metric_key = st.sidebar.selectbox(
        "表示指標",
        list(METRICS.keys()),
        format_func=lambda key: METRICS[key].label,
        index=0,
    )
    date_range = st.sidebar.date_input(
        "表示期間",
        value=(today.replace(month=1, day=1), today),
        key="kamata1_cardmap_date_range",
    )
    weekday_labels = list(WEEKDAY_LABELS)
    selected_weekdays = st.sidebar.multiselect(
        "曜日で絞り込み",
        weekday_labels,
        default=[],
        help="空欄なら全曜日",
    )
    selected_day_of_months = st.sidebar.multiselect(
        "月内日付で絞り込み",
        list(range(1, 32)),
        default=[],
        help="空欄なら全日付",
    )
    st.sidebar.caption(f"出力先: {DEFAULT_OUTPUT_PATH}")
    st.sidebar.caption("曜日・日付フィルタはカード型マップに反映されます。")

    if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
        st.warning("開始日と終了日を両方選択してください")
        return

    start_date, end_date = date_range
    if start_date is None or end_date is None:
        st.warning("開始日と終了日を両方選択してください")
        return

    weekdays = [WEEKDAY_LABELS.index(label) for label in selected_weekdays] or None
    day_of_months = selected_day_of_months or None

    card_tab, digit_tab = st.tabs(["カード型フロアマップ", "末尾ハイライト"])

    with card_tab:
        try:
            html = build_kamata1_cardmap_html(
                output_path=DEFAULT_OUTPUT_PATH,
                metric_key=metric_key,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                weekdays=weekdays,
                day_of_months=day_of_months,
            )
        except Exception as exc:
            st.error(f"カード型フロアマップの生成に失敗しました: {exc}")
        else:
            components_html(html, height=1800, scrolling=True)

    with digit_tab:
        st.caption("末尾ハイライトは現在、日付範囲を共有します。")
        floor_tabs = st.tabs([spec.floor for spec in FLOOR_SPECS])
        for tab, spec in zip(floor_tabs, FLOOR_SPECS):
            with tab:
                render_last_digit_highlight(
                    title=f"蒲田1 {spec.floor} 末尾ハイライト",
                    coords_file=spec.coords_path,
                    db_path=str(DB_PATH),
                    hall_name="マルハンメガシティ2000-蒲田1",
                    floor=spec.floor,
                    date_range=(start_date, end_date),
                    widget_key_suffix=f"kamata1_{spec.floor}",
                    weekdays=weekdays,
                    day_of_months=day_of_months,
                )


if __name__ == "__main__":
    main()
