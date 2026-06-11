"""Dashboard page for floor-plan heatmaps."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import streamlit as st

try:
    from Heatmap.coordinate_utils import find_floor_csvs
    from Heatmap.heatmap_common import (
        render_heatmap_page,
        render_last_digit_highlight,
    )
except ModuleNotFoundError:
    from coordinate_utils import find_floor_csvs
    from heatmap_common import render_heatmap_page, render_last_digit_highlight


def render() -> None:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")

    if not hall_name or not db_path:
        st.warning("Sidebarでホールを選択してください")
        return

    project_root = str(Path(__file__).parents[2])
    csvs = find_floor_csvs(hall_name, project_root)

    if not csvs:
        st.info("このホールのフロア座標データが見つかりません")
        st.caption("Heatmap/ に floor_coordinates を含むCSVを配置してください")
        return

    hall_safe = hall_name.replace(" ", "_").replace("/", "_").replace("-", "_")

    date_range = st.date_input(
        "表示期間",
        value=(date(2026, 1, 1), datetime.now().date()),
        key=f"heatmap_date_{hall_safe}",
    )
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        st.warning("開始日と終了日を両方選択してください")
        return

    heatmap_tab, digit_tab = st.tabs(["ヒートマップ", "末尾ハイライト"])

    with heatmap_tab:
        _render_heatmap_views(csvs, str(db_path), hall_name, hall_safe, date_range)

    with digit_tab:
        _render_digit_views(csvs, str(db_path), hall_name, hall_safe, date_range)


def _render_heatmap_views(
    csvs: list[dict[str, str]],
    db_path: str,
    hall_name: str,
    hall_safe: str,
    date_range: tuple[date, date],
) -> None:
    if len(csvs) == 1:
        _render_one_floor_heat(csvs[0], db_path, hall_name, hall_safe, date_range)
        return

    floor_labels = [csv_info["floor"] for csv_info in csvs]
    floor_tabs = st.tabs(floor_labels)
    for tab, csv_info in zip(floor_tabs, csvs):
        with tab:
            _render_one_floor_heat(csv_info, db_path, hall_name, hall_safe, date_range)


def _render_digit_views(
    csvs: list[dict[str, str]],
    db_path: str,
    hall_name: str,
    hall_safe: str,
    date_range: tuple[date, date],
) -> None:
    if len(csvs) == 1:
        _render_one_floor_digit(csvs[0], db_path, hall_name, hall_safe, date_range)
        return

    floor_labels = [csv_info["floor"] for csv_info in csvs]
    floor_tabs = st.tabs(floor_labels)
    for tab, csv_info in zip(floor_tabs, csvs):
        with tab:
            _render_one_floor_digit(csv_info, db_path, hall_name, hall_safe, date_range)


def _render_one_floor_heat(
    csv_info: dict[str, str],
    db_path: str,
    hall_name: str,
    hall_safe: str,
    date_range: tuple[date, date],
) -> None:
    floor = csv_info["floor"]
    render_heatmap_page(
        title=f"{hall_name} {floor} フロアヒートマップ",
        subtitle="選択期間の台別実績をフロア上に表示します。",
        coords_file=csv_info["path"],
        hall_name=hall_name,
        floor=floor,
        db_path=db_path,
        date_key=f"heatmap_date_{hall_safe}_{floor}",
        metric_key=f"heatmap_metric_{hall_safe}_{floor}",
        default_start_date=datetime(2026, 1, 1),
        date_range=date_range,
    )


def _render_one_floor_digit(
    csv_info: dict[str, str],
    db_path: str,
    hall_name: str,
    hall_safe: str,
    date_range: tuple[date, date],
) -> None:
    floor = csv_info["floor"]
    render_last_digit_highlight(
        title=f"{hall_name} {floor} 末尾ハイライト",
        coords_file=csv_info["path"],
        db_path=db_path,
        hall_name=hall_name,
        floor=floor,
        date_range=date_range,
        widget_key_suffix=f"{hall_safe}_{floor}",
    )


_render_one_floor = _render_one_floor_heat
