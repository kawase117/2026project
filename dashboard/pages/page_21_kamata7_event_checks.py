"""Kamata7 event-checks dashboard page."""

from __future__ import annotations

import streamlit as st

from dashboard.pages import page_20_kamata7_theory as theory_page
from dashboard.utils import kamata7_theory as theory


def render() -> None:
    db_path = st.session_state.get("db_path")
    date_range = st.session_state.get("date_range")
    min_games = int(st.session_state.get("min_games", 1000))

    st.markdown("## Kamata7 Event Checks")
    st.caption("Event-day checks を独立ページで確認します。")

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
        key="kamata7_event_checks_min_n",
    )

    event_frame = theory.filter_theory_frame(frame, start_date=start_date, end_date=end_date, min_games=0)
    if event_frame.empty:
        st.info("指定範囲に event-day データがありません")
        return

    st.caption(
        f"Rows: {len(event_frame):,} | Dates: {event_frame['date_dt'].min():%Y-%m-%d} to {event_frame['date_dt'].max():%Y-%m-%d} | "
        f"min_games: {min_games}"
    )
    theory_page._render_event_tab(event_frame, min_n)


if __name__ == "__main__":
    render()
