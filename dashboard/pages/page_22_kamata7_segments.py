"""Kamata7 segment dashboard page."""

from __future__ import annotations

import streamlit as st

from dashboard.pages import page_20_kamata7_theory as theory_page
from dashboard.utils import kamata7_theory as theory


def render() -> None:
    db_path = st.session_state.get("db_path")
    date_range = st.session_state.get("date_range")
    min_games = int(st.session_state.get("min_games", 1000))

    st.markdown("## Kamata7 Segments")
    st.caption("6 physical segments を独立ページで確認します。")

    if not db_path:
        st.warning("Sidebar でホール DB を選択してください")
        return

    frame = theory_page._load_theory_frame_cached(str(db_path))
    if frame.empty:
        st.info("対象ホールの理論データが見つかりませんでした")
        return

    start_date = end_date = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range

    min_n = st.slider(
        "セルごとの最小サンプル数",
        min_value=1,
        max_value=30,
        value=theory.THEORY_MIN_SAMPLE,
        step=1,
        key="kamata7_segments_min_n",
    )

    filtered = theory.filter_theory_frame(frame, start_date=start_date, end_date=end_date, min_games=min_games)
    if filtered.empty:
        st.info("指定範囲と min_games 条件で segment データがありません")
        return

    st.caption(
        f"Rows: {len(filtered):,} | Dates: {filtered['date_dt'].min():%Y-%m-%d} to {filtered['date_dt'].max():%Y-%m-%d} | "
        f"min_games: {min_games}"
    )
    theory_page._render_segment_tab(filtered, min_n)


if __name__ == "__main__":
    render()
