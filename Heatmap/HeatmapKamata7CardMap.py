"""Streamlit viewer for the Kamata7 card-map prototype."""

from __future__ import annotations

from generate_kamata7_cardmap_html import (
    DEFAULT_OUTPUT_PATH,
    METRICS,
    build_kamata7_cardmap_html,
)


def main() -> None:
    import streamlit as st
    from streamlit.components.v1 import html as components_html

    st.set_page_config(
        page_title="蒲田7 カード型フロアマップ試作",
        layout="wide",
    )
    st.title("蒲田7 カード型フロアマップ試作")
    st.caption(
        "HTML/CSSカード版の検証ビューです。ページ再読み込み時にHTMLを再生成します。"
    )

    metric_key = st.sidebar.selectbox(
        "表示指標",
        list(METRICS.keys()),
        format_func=lambda key: METRICS[key].label,
        index=0,
    )
    st.sidebar.caption(f"出力先: {DEFAULT_OUTPUT_PATH}")

    html = build_kamata7_cardmap_html(
        output_path=DEFAULT_OUTPUT_PATH,
        metric_key=metric_key,
    )
    components_html(html, height=1800, scrolling=True)


if __name__ == "__main__":
    main()
