"""
Shared Streamlit renderers for pachinko floor plans.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from Heatmap.coordinate_utils import get_display_columns
except ModuleNotFoundError:
    from coordinate_utils import get_display_columns


CATEGORY_COLORS: dict[str, str] = {
    "0": "#1f77b4",
    "1": "#ff7f0e",
    "2": "#2ca02c",
    "3": "#d62728",
    "4": "#9467bd",
    "5": "#8c564b",
    "6": "#e377c2",
    "7": "#bcbd22",
    "8": "#17becf",
    "9": "#aec7e8",
    "ゾロ目": "#FFD700",
}
UNSELECTED_COLOR = "#d3d3d3"


def load_coordinate_frame(
    coords_path: str | os.PathLike[str],
    hall_name: str | None = None,
    floor: str | None = None,
) -> pd.DataFrame:
    """Load a coordinate CSV and apply optional hall/floor filters."""

    coords_df = pd.read_csv(coords_path, dtype=str)

    if hall_name is not None and "hall_name" in coords_df.columns:
        coords_df = coords_df[coords_df["hall_name"] == hall_name].reset_index(
            drop=True
        )
    if floor is not None and "floor" in coords_df.columns:
        coords_df = coords_df[coords_df["floor"] == floor].reset_index(drop=True)

    for column in ("machine_number", "X", "Y", "display_x", "display_y"):
        if column in coords_df.columns:
            coords_df[column] = pd.to_numeric(coords_df[column], errors="coerce")

    return coords_df


def _as_date(value: datetime | date) -> date:
    return value.date() if hasattr(value, "date") else value


def _resolve_path(path: str, script_dir: str) -> str:
    return path if os.path.isabs(path) else os.path.join(script_dir, path)


def _ensure_date_range(
    date_range: tuple[date, date] | list[date] | None,
) -> tuple[date, date] | None:
    if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
        return None
    start_date, end_date = date_range[0], date_range[1]
    if start_date is None or end_date is None:
        return None
    return _as_date(start_date), _as_date(end_date)


def _format_metric_options() -> list[str]:
    return ["勝率(%)", "平均差枚", "平均ゲーム数"]


def _format_metric_label(metric: str) -> tuple[str, str, str]:
    if metric == "勝率(%)":
        return "win_rate", "勝率(%)", "RdYlGn"
    if metric == "平均差枚":
        return "avg_diff", "平均差枚", "RdYlGn"
    return "avg_games", "平均ゲーム数", "Blues"


def _render_metric_summary(machine_stats: pd.DataFrame) -> None:
    st.markdown("---")
    st.markdown("### 分析サマリー")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("台数", f"{len(machine_stats)}")
    with c2:
        st.metric("平均勝率", f"{machine_stats['win_rate'].mean():.1f}%")
    with c3:
        st.metric("平均差枚", f"{machine_stats['avg_diff'].mean():.0f}")
    with c4:
        st.metric("最高勝率", f"{machine_stats['win_rate'].max():.1f}%")
    with c5:
        st.metric("最高差枚", f"{machine_stats['avg_diff'].max():.0f}")


def _render_top_tables(machine_stats: pd.DataFrame) -> None:
    st.markdown("---")
    st.markdown("### 指標別 TOP 10")
    tab1, tab2, tab3 = st.tabs(["勝率 TOP10", "平均差枚 TOP10", "平均ゲーム数 TOP10"])

    def top_table(col: str) -> None:
        df = machine_stats.nlargest(10, col)[
            ["machine_number", "win_rate", "avg_diff", "avg_games"]
        ].copy()
        df.columns = ["台番号", "勝率(%)", "平均差枚", "平均ゲーム数"]
        df.insert(0, "順位", range(1, len(df) + 1))
        st.dataframe(df, use_container_width=True, hide_index=True)

    with tab1:
        top_table("win_rate")
    with tab2:
        top_table("avg_diff")
    with tab3:
        top_table("avg_games")


def render_heatmap_page(
    *,
    title: str,
    subtitle: str,
    coords_file: str,
    db_path: str,
    date_key: str,
    metric_key: str,
    default_start_date: datetime,
    hall_name: str | None = None,
    floor: str | None = None,
    date_range: tuple[date, date] | None = None,
) -> None:
    """Render a floor-plan heatmap from coordinate CSV + SQLite data."""

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    coords_path = _resolve_path(coords_file, script_dir)
    db_path = _resolve_path(db_path, project_root)

    if not os.path.exists(coords_path):
        st.error(f"Coordinate file not found: {coords_path}")
        st.stop()
    if not os.path.exists(db_path):
        st.error(f"DB file not found: {db_path}")
        st.stop()

    st.markdown(f"## {title}")
    st.markdown(subtitle)

    coords_df = load_coordinate_frame(
        coords_path,
        hall_name=hall_name,
        floor=floor,
    )
    if coords_df.empty:
        st.warning(
            f"Coordinate data is empty (hall_name={hall_name}, floor={floor})"
        )
        st.stop()

    coords_df["machine_number"] = coords_df["machine_number"].astype(int)
    coords_df["X"] = coords_df["X"].astype(int)
    coords_df["Y"] = coords_df["Y"].astype(int)
    if "display_x" in coords_df.columns:
        coords_df["display_x"] = coords_df["display_x"].astype(int)
    if "display_y" in coords_df.columns:
        coords_df["display_y"] = coords_df["display_y"].astype(int)
    if "hall_name" in coords_df.columns:
        hall_names = coords_df["hall_name"].dropna().astype(str).unique().tolist()
        if len(hall_names) == 1:
            st.caption(f"対象ホール: {hall_names[0]}")

    try:
        with sqlite3.connect(db_path) as conn:
            all_machines = pd.read_sql_query(
                "SELECT * FROM machine_detailed_results ORDER BY date DESC",
                conn,
            )
    except Exception as exc:
        st.error(f"DB load error: {exc}")
        st.stop()

    if all_machines.empty:
        st.warning("No machine data found")
        st.stop()

    validated_range = _ensure_date_range(date_range)
    if date_range is not None and validated_range is None:
        st.warning("開始日と終了日を両方選択してください")
        return

    col_l, col_r = st.columns([2, 1])
    if validated_range is None:
        with col_l:
            selected_range = st.date_input(
                "期間",
                value=(_as_date(default_start_date), datetime.now().date()),
                key=date_key,
            )
        validated_range = _ensure_date_range(selected_range)
        if validated_range is None:
            st.warning("開始日と終了日を両方選択してください")
            return
    else:
        start_date, end_date = validated_range
        with col_l:
            st.caption(
                f"期間: {start_date.strftime('%Y-%m-%d')} 〜 {end_date.strftime('%Y-%m-%d')}"
            )

    with col_r:
        metric = st.radio(
            "表示指標",
            _format_metric_options(),
            key=metric_key,
            horizontal=False,
        )

    start_date, end_date = validated_range
    all_machines["date"] = pd.to_datetime(all_machines["date"], format="%Y%m%d")
    filtered = all_machines[
        (all_machines["date"] >= pd.Timestamp(start_date))
        & (all_machines["date"] <= pd.Timestamp(end_date))
    ]

    if filtered.empty:
        st.warning("選択期間にデータがありません")
        st.stop()

    machine_stats = (
        filtered.groupby("machine_number")
        .agg(
            avg_diff=("diff_coins_normalized", "mean"),
            win_rate=("diff_coins_normalized", lambda x: (x > 0).sum() / len(x) * 100),
            avg_games=("games_normalized", "mean"),
        )
        .round(2)
        .reset_index()
    )

    heatmap_data = coords_df.merge(machine_stats, on="machine_number", how="left")
    x_axis_col, y_axis_col = get_display_columns(heatmap_data.columns)

    metric_col, metric_label, colorscale = _format_metric_label(metric)
    if metric == "勝率(%)":
        zmin, zmax = 0, 100
        fmt = "{:.1f}%"
    else:
        # ホール全体（全フロア）の値域を使用し、フロア間で色基準を統一する
        zmin = machine_stats[metric_col].min()
        zmax = machine_stats[metric_col].max()
        if metric == "平均差枚":
            limit = max(abs(zmin), abs(zmax))
            zmin, zmax = -limit, limit
        fmt = "{:.0f}" if metric == "平均差枚" else "{:.0f}G"

    max_x = int(heatmap_data[x_axis_col].max())
    max_y = int(heatmap_data[y_axis_col].max())
    z_mat = np.full((max_y, max_x), np.nan)
    mn_mat = np.full((max_y, max_x), "", dtype=object)
    val_mat = np.full((max_y, max_x), "", dtype=object)

    for _, row in heatmap_data.iterrows():
        xi = int(row[x_axis_col]) - 1
        yi = int(row[y_axis_col]) - 1
        mn_mat[yi, xi] = str(int(row["machine_number"]))
        if not pd.isna(row[metric_col]):
            z_mat[yi, xi] = row[metric_col]
            val_mat[yi, xi] = fmt.format(row[metric_col])

    height = max(600, max_y * 22 + 200)

    fig = go.Figure(
        data=go.Heatmap(
            z=z_mat,
            x=list(range(1, max_x + 1)),
            y=list(range(1, max_y + 1)),
            colorscale=colorscale,
            customdata=np.stack([mn_mat, val_mat], axis=-1),
            hovertemplate="<b>台番号: %{customdata[0]}</b><br>"
            + f"{metric_label}: %{{customdata[1]}}<br>"
            + "X=%{x}, Y=%{y}<extra></extra>",
            zmin=zmin,
            zmax=zmax,
            xgap=0.5,
            ygap=0.5,
        )
    )

    fig.update_traces(
        colorbar=dict(
            title=dict(text=metric_label, side="right"),
            thickness=18,
            len=0.7,
        )
    )

    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            xanchor="center",
            font=dict(size=18),
        ),
        height=height,
        hovermode="closest",
        yaxis=dict(
            autorange="reversed",
            side="left",
            showgrid=True,
            gridwidth=0.5,
            gridcolor="rgba(200,200,200,0.2)",
        ),
        xaxis=dict(
            showgrid=True,
            gridwidth=0.5,
            gridcolor="rgba(200,200,200,0.2)",
        ),
        font=dict(family="Arial, sans-serif", size=11, color="black"),
        margin=dict(l=60, r=110, t=80, b=60),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_xaxes(scaleanchor="y", scaleratio=1)

    st.plotly_chart(fig, use_container_width=True)

    _render_metric_summary(machine_stats)
    _render_top_tables(machine_stats)


def _build_highlight_customdata(
    row: pd.Series,
    category: str,
) -> list[str]:
    machine_name = row.get("machine_name")
    machine_name_str = "不明" if pd.isna(machine_name) else str(machine_name)

    win_rate = row.get("win_rate")
    avg_diff = row.get("avg_diff")
    win_rate_str = "-" if pd.isna(win_rate) else f"{float(win_rate):.1f}%"
    avg_diff_str = "-" if pd.isna(avg_diff) else f"{float(avg_diff):.0f}"

    return [
        str(int(row["machine_number"])),
        machine_name_str,
        category,
        win_rate_str,
        avg_diff_str,
    ]


def render_last_digit_highlight(
    *,
    title: str,
    coords_file: str,
    db_path: str,
    hall_name: str | None = None,
    floor: str | None = None,
    date_range: tuple[date, date],
    widget_key_suffix: str,
) -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    coords_path = _resolve_path(coords_file, script_dir)
    db_path = _resolve_path(db_path, project_root)

    if not os.path.exists(coords_path):
        st.error(f"Coordinate file not found: {coords_path}")
        st.stop()
    if not os.path.exists(db_path):
        st.error(f"DB file not found: {db_path}")
        st.stop()

    validated_range = _ensure_date_range(date_range)
    if validated_range is None:
        st.warning("開始日と終了日を両方選択してください")
        return
    start_date, end_date = validated_range

    st.markdown(f"## {title}")
    st.caption(
        f"期間: {start_date.strftime('%Y-%m-%d')} 〜 {end_date.strftime('%Y-%m-%d')}"
    )

    coords_df = load_coordinate_frame(
        coords_path,
        hall_name=hall_name,
        floor=floor,
    )
    if coords_df.empty:
        st.warning(
            f"Coordinate data is empty (hall_name={hall_name}, floor={floor})"
        )
        st.stop()

    coords_df["machine_number"] = coords_df["machine_number"].astype(int)
    coords_df["X"] = coords_df["X"].astype(int)
    coords_df["Y"] = coords_df["Y"].astype(int)
    if "display_x" in coords_df.columns:
        coords_df["display_x"] = coords_df["display_x"].astype(int)
    if "display_y" in coords_df.columns:
        coords_df["display_y"] = coords_df["display_y"].astype(int)

    date_start_key = start_date.strftime("%Y%m%d")
    date_end_key = end_date.strftime("%Y%m%d")

    try:
        with sqlite3.connect(db_path) as conn:
            table_info = pd.read_sql_query(
                "PRAGMA table_info(machine_detailed_results)",
                conn,
            )
            has_is_zorome = "is_zorome" in table_info["name"].tolist()

        latest_name_query = """
            SELECT r.machine_number, r.machine_name
            FROM machine_detailed_results r
            JOIN (
                SELECT machine_number, MAX(date) AS max_date
                FROM machine_detailed_results
                GROUP BY machine_number
            ) m ON r.machine_number = m.machine_number AND r.date = m.max_date
            GROUP BY r.machine_number
            ORDER BY r.machine_number
        """
        latest_names = pd.read_sql_query(latest_name_query, conn)

        if has_is_zorome:
            period_stats_query = """
                SELECT machine_number,
                       AVG(diff_coins_normalized) AS avg_diff,
                       100.0 * SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END)
                           / COUNT(*) AS win_rate,
                       MAX(is_zorome) AS is_zorome
                FROM machine_detailed_results
                WHERE date >= ? AND date <= ?
                GROUP BY machine_number
            """
        else:
            period_stats_query = """
                SELECT machine_number,
                       AVG(diff_coins_normalized) AS avg_diff,
                       100.0 * SUM(CASE WHEN diff_coins_normalized > 0 THEN 1 ELSE 0 END)
                           / COUNT(*) AS win_rate
                FROM machine_detailed_results
                WHERE date >= ? AND date <= ?
                GROUP BY machine_number
            """
        period_stats = pd.read_sql_query(
            period_stats_query,
            conn,
            params=(date_start_key, date_end_key),
        )
    except Exception as exc:
        st.error(f"DB load error: {exc}")
        st.stop()

    heatmap_df = coords_df.merge(latest_names, on="machine_number", how="left")
    heatmap_df = heatmap_df.merge(period_stats, on="machine_number", how="left")
    x_axis_col, y_axis_col = get_display_columns(heatmap_df.columns)

    def _is_zorome(row: pd.Series) -> bool:
        if "is_zorome" in row and not pd.isna(row["is_zorome"]):
            return int(row["is_zorome"]) == 1
        machine_number = int(row["machine_number"])
        last_two_digits = machine_number % 100
        return last_two_digits // 10 == last_two_digits % 10

    plot_rows: list[dict[str, object]] = []
    for _, row in heatmap_df.iterrows():
        machine_number = int(row["machine_number"])
        category = "ゾロ目" if _is_zorome(row) else str(machine_number % 10)
        plot_rows.append(
            {
                "x": row[x_axis_col],
                "y": row[y_axis_col],
                "machine_number": machine_number,
                "machine_name": "不明" if pd.isna(row.get("machine_name")) else str(row["machine_name"]),
                "category": category,
                "customdata": _build_highlight_customdata(row, category),
                "label": str(machine_number)[-3:],
            }
        )

    plot_df = pd.DataFrame(plot_rows)
    selected = st.multiselect(
        "ハイライトする末尾を選択",
        options=list(CATEGORY_COLORS.keys()),
        default=[],
        key=f"digit_select_{widget_key_suffix}",
    )

    max_x = int(plot_df["x"].max())
    max_y = int(plot_df["y"].max())
    height = max(600, max_y * 22 + 200)
    fig = go.Figure()

    def add_trace(subset: pd.DataFrame, *, name: str, color: str, size: int, showlegend: bool, text_color: str) -> None:
        if subset.empty:
            return
        fig.add_trace(
            go.Scatter(
                x=subset["x"],
                y=subset["y"],
                mode="markers+text",
                name=name,
                showlegend=showlegend,
                text=subset["label"],
                textposition="middle center",
                textfont=dict(size=7, color=text_color),
                marker=dict(
                    symbol="square",
                    size=size,
                    color=color,
                ),
                customdata=subset["customdata"].tolist(),
                hovertemplate=(
                    "<b>台番号: %{customdata[0]}</b><br>"
                    "機種: %{customdata[1]}<br>"
                    "末尾: %{customdata[2]}<br>"
                    "勝率: %{customdata[3]}<br>"
                    "平均差枚: %{customdata[4]}<extra></extra>"
                ),
            )
        )

    if selected:
        unselected_df = plot_df[~plot_df["category"].isin(selected)]
    else:
        unselected_df = plot_df

    add_trace(
        unselected_df,
        name="未選択",
        color=UNSELECTED_COLOR,
        size=14,
        showlegend=False,
        text_color="black",
    )

    for category in selected:
        add_trace(
            plot_df[plot_df["category"] == category],
            name=category,
            color=CATEGORY_COLORS[category],
            size=18,
            showlegend=True,
            text_color="white",
        )

    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            xanchor="center",
            font=dict(size=18),
        ),
        height=height,
        hovermode="closest",
        yaxis=dict(
            autorange="reversed",
            side="left",
            showgrid=True,
            gridwidth=0.5,
            gridcolor="rgba(200,200,200,0.2)",
        ),
        xaxis=dict(
            showgrid=True,
            gridwidth=0.5,
            gridcolor="rgba(200,200,200,0.2)",
        ),
        font=dict(family="Arial, sans-serif", size=11, color="black"),
        margin=dict(l=60, r=110, t=80, b=60),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=True,
    )
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_xaxes(scaleanchor="y", scaleratio=1)

    st.plotly_chart(fig, use_container_width=True)
