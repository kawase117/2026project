"""Single-day hall report page."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from Heatmap.coordinate_utils import find_floor_csvs
from Heatmap.heatmap_common import render_heatmap_page
from dashboard.design_system import metric_card, metric_card_with_delta
from dashboard.utils.data_loader import load_daily_hall_summary, load_machine_detailed_by_date
from dashboard.utils.daily_report import (
    add_hit104_flag,
    build_layout_summary,
    build_top_rank_table,
    build_segment_summary,
    filter_search_query,
    load_optional_table,
    summarize_group_performance,
)
from dashboard.utils.filters import apply_machine_filters


def _jst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _default_target_date() -> date:
    return _jst_today() - timedelta(days=1)


def _format_date_key(value: date) -> str:
    return value.strftime("%Y%m%d")


def _render_metric_triplet(
    title: str,
    current_value: float,
    recent_7_value: float,
    recent_30_value: float,
    icon: str,
    *,
    percent: bool = False,
) -> None:
    col1, col2, col3 = st.columns(3)
    formatter = (lambda value: f"{value:.1f}%") if percent else (lambda value: f"{value:,.0f}")
    delta_suffix = "pp" if percent else ""
    with col1:
        metric_card_with_delta(
            title,
            formatter(current_value),
            current_value - recent_7_value,
            delta_label=f"{delta_suffix} vs 7日平均".strip(),
            icon=icon,
        )
    with col2:
        metric_card_with_delta(
            title,
            formatter(recent_7_value),
            recent_7_value - recent_30_value,
            delta_label=f"{delta_suffix} vs 30日平均".strip(),
            icon=icon,
        )
    with col3:
        metric_card(title, formatter(recent_30_value), icon=icon)


def _summarize_daily_kpis(summary_df: pd.DataFrame, target_date: pd.Timestamp) -> dict[str, tuple[float, float, float]]:
    history = summary_df.loc[summary_df["date"] < target_date].copy()
    current_row = summary_df.loc[summary_df["date"] == target_date]
    if current_row.empty:
        raise KeyError(f"Missing daily summary row for {target_date:%Y-%m-%d}")

    current = current_row.iloc[0]

    def _mean_between(days: int) -> pd.Series:
        start = target_date - pd.Timedelta(days=days)
        window = history.loc[history["date"] >= start]
        return window[["avg_diff_per_machine", "win_rate", "avg_games_per_machine"]].mean(numeric_only=True)

    mean_7 = _mean_between(7)
    mean_30 = _mean_between(30)
    return {
        "avg_diff_per_machine": (
            float(current["avg_diff_per_machine"]),
            float(mean_7["avg_diff_per_machine"]),
            float(mean_30["avg_diff_per_machine"]),
        ),
        "win_rate": (float(current["win_rate"]), float(mean_7["win_rate"]), float(mean_30["win_rate"])),
        "avg_games_per_machine": (
            float(current["avg_games_per_machine"]),
            float(mean_7["avg_games_per_machine"]),
            float(mean_30["avg_games_per_machine"]),
        ),
    }


def _render_table(title: str, frame: pd.DataFrame, *, use_index: bool = False) -> None:
    st.markdown(f"### {title}")
    if frame.empty:
        st.info("該当データがありません")
        return

    display_frame, column_config = _build_table_display(frame)
    st.dataframe(
        display_frame,
        use_container_width=True,
        hide_index=not use_index,
        column_config=column_config,
    )


def _build_table_display(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Keep numeric columns numeric and format them in Streamlit, not in the data."""

    work = frame.copy()
    column_config: dict[str, object] = {}
    percent_columns = {"win_rate", "hit104_rate"}
    payout_columns = {"payout_rate", "avg_payout_rate"}
    integer_columns = {
        "machine_number",
        "diff_coins_normalized",
        "games_normalized",
        "avg_diff",
        "avg_games",
        "hit104_count",
        "n",
        "hit104",
    }

    for column in work.columns:
        numeric = pd.to_numeric(work[column], errors="coerce")
        if column in payout_columns:
            work[column] = numeric
            column_config[column] = st.column_config.NumberColumn(format="%.1f%%")
        elif column in percent_columns:
            work[column] = numeric
            column_config[column] = st.column_config.NumberColumn(format="percent")
        elif column in integer_columns:
            work[column] = numeric
            column_config[column] = st.column_config.NumberColumn(format="%d")

    return work, column_config


def _prepare_all_table(frame: pd.DataFrame) -> pd.DataFrame:
    work = add_hit104_flag(frame)
    columns = [
        "machine_number",
        "machine_name",
        "last_digit",
        "diff_coins_normalized",
        "games_normalized",
        "payout_rate",
        "hit104",
    ]
    available = [column for column in columns if column in work.columns]
    return (
        work.loc[:, available].sort_values(["machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)
    )


def _render_top5_tabs(title: str, tables: list[tuple[str, pd.DataFrame]]) -> None:
    st.markdown(f"### {title}")
    if not tables:
        st.info("該当データがありません")
        return

    tab_labels = [label for label, _ in tables]
    tabs = st.tabs(tab_labels)
    for tab, (label, frame) in zip(tabs, tables):
        with tab:
            _render_table(label, frame.head(5))


def _render_heatmap_views(
    csvs: list[dict[str, str]],
    db_path: str,
    hall_name: str,
    hall_safe: str,
    target_date: date,
) -> None:
    if not csvs:
        return

    if len(csvs) == 1:
        _render_one_floor_heat(csvs[0], db_path, hall_name, hall_safe, target_date)
        return

    floor_tabs = st.tabs([csv_info["floor"] for csv_info in csvs])
    for tab, csv_info in zip(floor_tabs, csvs):
        with tab:
            _render_one_floor_heat(csv_info, db_path, hall_name, hall_safe, target_date)


def _render_one_floor_heat(
    csv_info: dict[str, str],
    db_path: str,
    hall_name: str,
    hall_safe: str,
    target_date: date,
) -> None:
    floor = csv_info["floor"]
    render_heatmap_page(
        title=f"{hall_name} {floor} 日次レポート",
        subtitle="選択日の実績をフロア上に表示します。",
        coords_file=csv_info["path"],
        db_path=db_path,
        date_key=f"daily_report_date_{hall_safe}_{floor}",
        metric_key=f"daily_report_metric_{hall_safe}_{floor}",
        default_start_date=datetime.combine(target_date, datetime.min.time()),
        hall_name=hall_name,
        floor=floor,
        date_range=(target_date, target_date),
    )


def render() -> None:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")
    min_games = int(st.session_state.get("min_games", 1000))
    show_low_confidence = bool(st.session_state.get("show_low_confidence", False))

    if not hall_name or not db_path:
        st.warning("Sidebarでホールを選択してください")
        return

    st.markdown("## 前日レポート")
    st.caption("特定の1日を選ぶと、その日のホール全体を1ページで確認できます。")

    target_date = st.date_input("対象日", value=_default_target_date(), key=f"daily_report_date_{hall_name}")
    if not isinstance(target_date, date):
        st.warning("対象日を選択してください")
        return

    target_key = _format_date_key(target_date)
    daily_df = load_machine_detailed_by_date(str(db_path), target_key)
    if daily_df.empty:
        st.info("この日のデータがありません")
        return

    daily_df = apply_machine_filters(daily_df, None, min_games, show_low_confidence)
    if daily_df.empty:
        st.info("この日のデータは min_games フィルタ後に残りませんでした")
        return

    daily_df = daily_df.copy()
    daily_df = add_hit104_flag(daily_df)

    hall_summary = load_daily_hall_summary(str(db_path))
    if hall_summary.empty:
        st.info("daily_hall_summary が見つかりません")
        return

    hall_summary["date"] = pd.to_datetime(hall_summary["date"], errors="coerce")
    target_ts = pd.Timestamp(target_date)
    try:
        kpis = _summarize_daily_kpis(hall_summary, target_ts)
    except KeyError:
        st.info("当日のホール集計が見つかりません")
        return

    st.markdown("### KPI サマリー")
    _render_metric_triplet("平均差枚", *kpis["avg_diff_per_machine"], icon="💰")
    _render_metric_triplet("勝率", *kpis["win_rate"], icon="📊", percent=True)
    _render_metric_triplet("平均G数", *kpis["avg_games_per_machine"], icon="🎲")

    st.markdown("---")

    machine_summary = summarize_group_performance(daily_df, "machine_name")
    last_digit_summary = summarize_group_performance(daily_df, "last_digit")
    _render_table("機種別成績", machine_summary)
    _render_table("末尾別成績", last_digit_summary)

    layout_frame = load_optional_table(str(db_path), "machine_layout")
    if not layout_frame.empty and {"machine_number", "rank_from_min", "section"} <= set(layout_frame.columns):
        kakuban_summary = build_layout_summary(daily_df, layout_frame, group_column="rank_from_min")
        section_summary = build_layout_summary(daily_df, layout_frame, group_column="section")
        _render_table("端番別（min側）成績", kakuban_summary)
        _render_table("Section別成績", section_summary)

    master_frame = load_optional_table(str(db_path), "machine_master")
    if not master_frame.empty:
        segment_summary = build_segment_summary(daily_df, master_frame)
        if not segment_summary.empty:
            _render_table("セグメント別成績", segment_summary)

    st.markdown("---")
    st.markdown("### TOP5")

    all_table = _prepare_all_table(daily_df)
    if all_table.empty:
        st.info("全台テーブルが作成できません")
        return

    layout_available = not layout_frame.empty and {"machine_number"} <= set(layout_frame.columns)

    metric_specs = [
        ("勝率TOP5", "win_rate", 1),
        ("差枚TOP5", "avg_diff", 1),
        ("回転数TOP5", "avg_games", 1),
        ("104超えTOP5", "hit104_rate", 3),
    ]

    for metric_title, sort_by, min_group_size in metric_specs:
        tables: list[tuple[str, pd.DataFrame]] = [
            (
                "機種別",
                build_top_rank_table(
                    daily_df,
                    group_column="machine_name",
                    sort_by=sort_by,
                    min_group_size=min_group_size,
                ),
            ),
            (
                "末尾別",
                build_top_rank_table(
                    daily_df,
                    group_column="last_digit",
                    sort_by=sort_by,
                    min_group_size=min_group_size,
                ),
            ),
        ]

        if layout_available and "rank_from_min" in layout_frame.columns:
            tables.insert(
                1,
                (
                    "端番別（min側）",
                    build_layout_summary(
                        daily_df,
                        layout_frame,
                        group_column="rank_from_min",
                        min_group_size=min_group_size,
                        sort_by=sort_by,
                    ),
                ),
            )

        if layout_available and "section" in layout_frame.columns:
            tables.append(
                (
                    "セクション別",
                    build_layout_summary(
                        daily_df,
                        layout_frame,
                        group_column="section",
                        min_group_size=min_group_size,
                        sort_by=sort_by,
                    ),
                )
            )

        _render_top5_tabs(metric_title, tables)

    st.markdown("---")
    st.markdown("### 全台テーブル")
    search_query = st.text_input("台番号または機種名で検索", value="", key=f"daily_report_search_{hall_name}")
    filtered_all = filter_search_query(all_table, search_query)
    _render_table("台番号順", filtered_all)

    floor_csvs = find_floor_csvs(hall_name, str(Path(__file__).parents[2]))
    if floor_csvs:
        st.markdown("---")
        st.markdown("### フロアヒートマップ")
        hall_safe = hall_name.replace(" ", "_").replace("/", "_").replace("-", "_")
        _render_heatmap_views(floor_csvs, str(db_path), hall_name, hall_safe, target_date)
