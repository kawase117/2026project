"""Visual comparison test version of the single-day hall report page."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from Heatmap.coordinate_utils import find_floor_csvs
from dashboard.design_system import COLORS
from dashboard.pages.page_18_daily_report import (
    _format_date_key,
    _prepare_all_table,
    _render_heatmap_views,
    _render_metric_triplet,
    _render_table,
    _summarize_daily_kpis,
)
from dashboard.utils.data_loader import load_daily_hall_summary, load_machine_detailed_by_date
from dashboard.utils import daily_report as daily_report_utils
from dashboard.utils.filters import apply_machine_filters


GROUP_LABELS = {
    "machine_name": "機種別",
    "last_digit": "末尾別",
    "rank_from_min": "端番別（min側）",
    "section": "セクション別",
    "segment": "セグメント別",
}


def _jst_today() -> date:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


def _default_target_date() -> date:
    return _jst_today() - timedelta(days=1)


def _coerce_date(value: object, fallback: date) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return fallback


def _init_target_date(state_key: str, default_date: date) -> date:
    current = _coerce_date(st.session_state.get(state_key), default_date)
    st.session_state[state_key] = current
    return current


def _step_target_date(state_key: str, *, default_date: date | None = None) -> date:
    """Render date step buttons and return the updated target date."""

    fallback = default_date or _default_target_date()
    current = _init_target_date(state_key, fallback)
    prev_col, reset_col, next_col = st.columns(3)

    with prev_col:
        if st.button("前日へ", key=f"{state_key}_prev"):
            current = current - timedelta(days=1)

    with reset_col:
        if st.button("JST既定日へ", key=f"{state_key}_default"):
            current = fallback

    with next_col:
        if st.button("翌日へ", key=f"{state_key}_next"):
            current = current + timedelta(days=1)

    st.session_state[state_key] = current
    return current


def _render_visual_test_note(target_date: date) -> None:
    st.info(
        "テスト版: page_18_daily_report の日次レポートに、比較用の可視化を追加した検証ページです。"
        " ルーティング登録前の確認用で、本番ページではありません。"
    )
    st.caption(f"JST基準の既定日は前日 ({_default_target_date():%Y-%m-%d}) です。表示対象: {target_date:%Y-%m-%d}")


def _render_group_bar_chart(group_key: str, frame: pd.DataFrame) -> None:
    if frame.empty or group_key not in frame.columns:
        return

    work = frame.copy()
    work["win_rate_pct"] = pd.to_numeric(work["win_rate"], errors="coerce") * 100.0
    work["hit104_rate_pct"] = pd.to_numeric(work["hit104_rate"], errors="coerce") * 100.0
    work["avg_diff"] = pd.to_numeric(work["avg_diff"], errors="coerce")

    sort_columns = [column for column in ["hit104_rate_pct", "avg_diff", "n"] if column in work.columns]
    if sort_columns:
        work = work.sort_values(sort_columns, ascending=[False] * len(sort_columns), kind="mergesort")

    if group_key == "machine_name":
        work = work.head(20)
    else:
        work = work.head(40)

    long_frame = work.melt(
        id_vars=[group_key],
        value_vars=["win_rate_pct", "hit104_rate_pct"],
        var_name="metric",
        value_name="rate_pct",
    )
    long_frame["metric"] = long_frame["metric"].map(
        {
            "win_rate_pct": "勝率",
            "hit104_rate_pct": "104%以上率",
        }
    )

    title = f"{GROUP_LABELS.get(group_key, group_key)}: 勝率 / 104%以上率"
    fig = px.bar(
        long_frame,
        x=group_key,
        y="rate_pct",
        color="metric",
        barmode="group",
        title=title,
        labels={group_key: GROUP_LABELS.get(group_key, group_key), "rate_pct": "率 (%)", "metric": "指標"},
        hover_data={group_key: True, "rate_pct": ":.1f"},
    )
    fig.update_layout(xaxis_tickangle=-35, legend_title_text="", yaxis_range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)


def _render_grouped_bar_charts(group_frames: dict[str, pd.DataFrame]) -> None:
    st.markdown("### グループ別 可視化比較")
    ordered_keys = ["machine_name", "last_digit", "rank_from_min", "section"]
    available = [key for key in ordered_keys if key in group_frames and not group_frames[key].empty]
    if not available:
        st.info("グループ別チャートを作成できるデータがありません")
        return

    tabs = st.tabs([GROUP_LABELS.get(key, key) for key in available])
    for tab, key in zip(tabs, available):
        with tab:
            _render_group_bar_chart(key, group_frames[key])


def _render_kpi_trend_chart(trend_frame: pd.DataFrame, target_date: date) -> None:
    if trend_frame.empty or len(trend_frame) <= 1:
        st.info("トレンドを描画するのに十分なデータがありません")
        return

    work = trend_frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date", kind="mergesort")
    if work.empty or len(work) <= 1:
        st.info("トレンドを描画するのに十分なデータがありません")
        return

    target_ts = pd.Timestamp(target_date)
    work["win_rate_pct"] = pd.to_numeric(work["win_rate"], errors="coerce") * 100.0
    metric_specs = [
        ("avg_diff_per_machine", "平均差枚", COLORS["secondary_green"], "差枚"),
        ("win_rate_pct", "勝率", COLORS["secondary_blue"], "勝率 (%)"),
        ("avg_games_per_machine", "平均G数", COLORS["secondary_orange"], "ゲーム数"),
    ]
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        subplot_titles=[spec[1] for spec in metric_specs],
    )

    for row, (column, title, color, y_title) in enumerate(metric_specs, start=1):
        fig.add_trace(
            go.Scatter(
                x=work["date"],
                y=work[column],
                mode="lines+markers",
                line={"color": color, "width": 3},
                marker={"color": color, "size": 7},
                name=title,
                showlegend=False,
            ),
            row=row,
            col=1,
        )

        target_row = work.loc[work["date"] == target_ts]
        if not target_row.empty:
            fig.add_trace(
                go.Scatter(
                    x=[target_ts],
                    y=[target_row.iloc[0][column]],
                    mode="markers",
                    marker={
                        "size": 12,
                        "color": COLORS["primary_accent"],
                        "line": {"color": COLORS["neutral_50"], "width": 1},
                    },
                    name=f"{title} 当日",
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=row,
                col=1,
            )

        fig.update_yaxes(title_text=y_title, row=row, col=1)

    fig.update_yaxes(title_text="勝率 (%)", row=2, col=1, tickformat=".1f")
    fig.update_xaxes(title_text="日付", row=3, col=1)
    fig.update_layout(title="直近 KPI トレンド", hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def _render_diff_histogram(daily_df: pd.DataFrame) -> None:
    frame = daily_report_utils.add_hit104_flag(daily_df)
    if frame.empty or "diff_coins_normalized" not in frame.columns:
        st.info("差枚分布を描画するのに十分なデータがありません")
        return

    work = frame.copy()
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(subset=["diff_coins_normalized"])
    if work.empty:
        st.info("差枚分布を描画するのに十分なデータがありません")
        return

    stats = daily_report_utils.compute_diff_distribution_stats(work)
    st.markdown("### 差枚分布")
    work["hit104"] = work["hit104"].astype("string")
    fig = px.histogram(
        work,
        x="diff_coins_normalized",
        color="hit104",
        nbins=30,
        opacity=0.72,
        barmode="overlay",
        color_discrete_map={
            "0": COLORS["secondary_blue"],
            "1": COLORS["primary_accent"],
        },
        labels={
            "diff_coins_normalized": "差枚",
            "hit104": "104%以上",
        },
        title="差枚の分布",
    )
    fig.update_traces(marker_line_width=0)
    if pd.notna(stats["mean"]):
        fig.add_vline(
            x=stats["mean"],
            line_width=2,
            line_dash="dash",
            line_color=COLORS["secondary_green"],
            annotation_text=f"平均 {stats['mean']:+.0f}",
            annotation_position="top right",
        )
    if pd.notna(stats["median"]):
        fig.add_vline(
            x=stats["median"],
            line_width=2,
            line_dash="dot",
            line_color=COLORS["secondary_orange"],
            annotation_text=f"中央値 {stats['median']:+.0f}",
            annotation_position="top left",
        )
    fig.update_layout(barmode="overlay")
    st.plotly_chart(fig, use_container_width=True)


def _render_hanaban_section_heatmap(daily_df: pd.DataFrame, layout_frame: pd.DataFrame) -> None:
    required = {"machine_number", "rank_from_min", "section"}
    if layout_frame.empty or not required.issubset(layout_frame.columns):
        st.info("端番×セクションのヒートマップに必要なデータがありません")
        return

    st.markdown("### 端番×セクション ヒートマップ")
    metric = st.selectbox(
        "表示指標",
        ["avg_diff", "win_rate", "hit104_rate"],
        format_func=lambda value: {
            "avg_diff": "差枚",
            "win_rate": "勝率",
            "hit104_rate": "104%以上率",
        }[value],
        key="daily_report_visual_test_kakuban_metric",
    )

    pivot_frame = daily_report_utils.build_hanaban_section_pivot(daily_df, layout_frame)
    if pivot_frame.empty:
        st.info("端番×セクションのヒートマップを作成できるデータがありません")
        return

    matrix = pivot_frame.pivot(index="rank_from_min", columns="section", values=metric).sort_index().sort_index(axis=1)
    machine_matrix = pivot_frame.pivot(index="rank_from_min", columns="section", values="machine_name").reindex(
        index=matrix.index,
        columns=matrix.columns,
    )
    if matrix.dropna(how="all").empty:
        st.info("端番×セクションのヒートマップを作成できるデータがありません")
        return

    text_matrix = matrix.copy()
    if metric == "avg_diff":
        text_matrix = text_matrix.map(lambda value: "" if pd.isna(value) else f"{value:+.0f}")
    else:
        text_matrix = text_matrix.map(lambda value: "" if pd.isna(value) else f"{value:.1%}")

    fig = go.Figure(
        data=go.Heatmap(
            z=matrix.to_numpy(),
            x=[str(value) for value in matrix.columns],
            y=[int(value) if pd.notna(value) else value for value in matrix.index],
            customdata=machine_matrix.to_numpy(),
            text=text_matrix.to_numpy(),
            texttemplate="%{text}",
            colorscale="RdYlGn",
            colorbar={
                "title": {
                    "avg_diff": "平均差枚",
                    "win_rate": "勝率",
                    "hit104_rate": "104%以上率",
                }[metric]
            },
            hovertemplate=(
                "端番min=%{y}<br>"
                "セクション=%{x}<br>"
                "機種名=%{customdata}<br>"
                + {
                    "avg_diff": "平均差枚=%{z:+.0f}",
                    "win_rate": "勝率=%{z:.1%}",
                    "hit104_rate": "104%以上率=%{z:.1%}",
                }[metric]
                + "<extra></extra>"
            ),
        )
    )
    fig.update_layout(title="端番×セクションの成績分布")
    st.plotly_chart(fig, use_container_width=True)


def _render_diff_games_scatter(frame: pd.DataFrame) -> None:
    scatter = daily_report_utils.build_daily_scatter_frame(frame)
    if scatter.empty or not {"games_normalized", "diff_coins_normalized"} <= set(scatter.columns):
        st.info("散布図を作成できるデータがありません")
        return

    st.markdown("### 差枚 vs ゲーム数")
    fig = px.scatter(
        scatter,
        x="games_normalized",
        y="diff_coins_normalized",
        color="hit104" if "hit104" in scatter.columns else None,
        hover_data=[
            column for column in ["machine_number", "machine_name", "payout_rate"] if column in scatter.columns
        ],
        labels={
            "games_normalized": "ゲーム数",
            "diff_coins_normalized": "差枚",
            "hit104": "104%以上",
            "payout_rate": "推定機械割",
        },
        title="全台: 差枚とゲーム数の分布",
    )
    fig.update_traces(marker={"size": 8, "opacity": 0.72})
    st.plotly_chart(fig, use_container_width=True)


def render() -> None:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")
    min_games = int(st.session_state.get("min_games", 1000))
    show_low_confidence = bool(st.session_state.get("show_low_confidence", False))

    if not hall_name or not db_path:
        st.warning("Sidebarでホールを選択してください")
        return

    st.markdown("## 前日レポート Visual Test")
    state_key = f"daily_report_visual_test_date_{hall_name}"
    stepped_date = _step_target_date(state_key, default_date=_default_target_date())
    target_date = st.date_input("対象日", value=stepped_date, key=state_key)
    if not isinstance(target_date, date):
        st.warning("対象日を選択してください")
        return
    _render_visual_test_note(target_date)

    target_key = _format_date_key(target_date)
    daily_df = load_machine_detailed_by_date(str(db_path), target_key)
    if daily_df.empty:
        st.info("この日のデータがありません")
        return

    daily_df = apply_machine_filters(daily_df, None, min_games, show_low_confidence)
    if daily_df.empty:
        st.info("この日のデータは min_games フィルタ後に残りませんでした")
        return

    daily_df = daily_report_utils.add_hit104_flag(daily_df)

    hall_summary = load_daily_hall_summary(str(db_path))
    if hall_summary.empty:
        st.info("daily_hall_summary が見つかりません")
        return

    hall_summary["date"] = pd.to_datetime(hall_summary["date"], errors="coerce")
    try:
        kpis = _summarize_daily_kpis(hall_summary, pd.Timestamp(target_date))
    except KeyError:
        st.info("当日のホール集計が見つかりません")
        return

    st.markdown("### KPI サマリー")
    _render_metric_triplet("平均差枚", *kpis["avg_diff_per_machine"], icon="💰")
    _render_metric_triplet("勝率", *kpis["win_rate"], icon="📊", percent=True)
    _render_metric_triplet("平均G数", *kpis["avg_games_per_machine"], icon="🎲")

    st.markdown("### 蜑肴律繧ｵ繝槭Μ")
    st.write(
        daily_report_utils.build_daily_highlight_summary(
            daily_df,
            machine_label="讖溽ｨｮ蛻･",
        )
    )

    trend_frame = daily_report_utils.build_kpi_trend_frame(hall_summary, pd.Timestamp(target_date))
    _render_kpi_trend_chart(trend_frame, target_date)

    layout_frame = daily_report_utils.load_optional_table(str(db_path), "machine_layout")
    master_frame = daily_report_utils.load_optional_table(str(db_path), "machine_master")
    group_frames = daily_report_utils.build_visual_group_frames(
        daily_df,
        layout_frame=layout_frame,
        master_frame=master_frame,
    )

    st.markdown("---")
    _render_grouped_bar_charts(group_frames)
    _render_diff_histogram(daily_df)
    _render_diff_games_scatter(daily_df)
    _render_hanaban_section_heatmap(daily_df, layout_frame)

    st.markdown("---")
    st.markdown("### 集計テーブル")
    for group_key in ["machine_name", "last_digit", "rank_from_min", "section"]:
        if group_key in group_frames:
            _render_table(f"{GROUP_LABELS.get(group_key, group_key)}成績", group_frames[group_key])

    st.markdown("---")
    st.markdown("### 全台テーブル")
    all_table = _prepare_all_table(daily_df)
    if all_table.empty:
        st.info("全台テーブルが作成できません")
        return

    search_query = st.text_input(
        "台番号または機種名で検索", value="", key=f"daily_report_visual_test_search_{hall_name}"
    )
    filtered_all = daily_report_utils.filter_search_query(all_table, search_query)
    _render_table("台番号順", filtered_all)

    floor_csvs = find_floor_csvs(hall_name, str(Path(__file__).parents[2]))
    if floor_csvs:
        st.markdown("---")
        st.markdown("### フロアヒートマップ")
        hall_safe = hall_name.replace(" ", "_").replace("/", "_").replace("-", "_")
        _render_heatmap_views(floor_csvs, str(db_path), hall_name, hall_safe, target_date)


if __name__ == "__main__":
    render()
