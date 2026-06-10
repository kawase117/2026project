"""Streamlit viewer for the Kamata7 2F / 3F combined heatmap HTML."""

from __future__ import annotations

from pathlib import Path


HTML_PATH = Path(__file__).with_name("kamata7_2f_3f_heatmap.html")


def load_report_html(path: Path = HTML_PATH) -> str:
    """Load the prebuilt standalone HTML report."""

    if not path.exists():
        raise FileNotFoundError(f"HTML report not found: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    import streamlit as st
    from streamlit.components.v1 import html as components_html

    st.set_page_config(
        page_title="蒲田7 2F / 3F 同時ヒートマップ",
        layout="wide",
    )
    st.title("蒲田7 2F / 3F 同時ヒートマップ")
    st.caption("生成済みHTMLをそのまま表示します。先に `python Heatmap\\generate_kamata7_dual_html.py` を実行してください。")

    html = load_report_html()
    components_html(html, height=1400, scrolling=True)


if __name__ == "__main__":
    main()
