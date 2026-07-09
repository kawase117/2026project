"""単一軸ビューア共通ロジック

旧 page_02(日別)/03(曜日別)/05(末尾別)/06(日末日別)/07(第X曜日別)/09(台番号末尾別)
を1ページに統合するための共通描画関数群。

instincts（weekday-digit-nth-single-dim-all-null 等）によりこれらの単一軸は
効果なし確定のため、ここはあくまで生データの目視確認用途として提供する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

from ..design_system import COLORS, premium_divider
from .data_loader import load_last_digit_summary
from .filters import apply_sidebar_filters

DOW_LABELS = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]


def _derive_weekday(df: pd.DataFrame) -> pd.Series:
    return df["date"].dt.dayofweek.map(DOW_LABELS)


def _derive_day_last_digit(df: pd.DataFrame) -> pd.Series:
    return df["date"].dt.strftime("%d").str[-1].astype(int)


CATEGORICAL_AXES = {
    "weekday": {
        "label": "曜日別",
        "column": "day_name",
        "axis_label": "曜日",
        "order": DOW_ORDER,
        "derive": _derive_weekday,
    },
    "day_last_digit": {
        "label": "日末日別",
        "column": "day_last_digit",
        "axis_label": "日付末尾",
        "order": None,
        "derive": _derive_day_last_digit,
    },
    "nth_weekday": {
        "label": "第X曜日別",
        "column": "weekday_nth",
        "axis_label": "第X曜日",
        "order": None,
        "derive": None,
    },
}

AXIS_LABELS = {
    "daily_trend": "日別（トレンド）",
    **{key: config["label"] for key, config in CATEGORICAL_AXES.items()},
    "machine_tail": "台番号末尾別（ゾロ目含む）",
}


def render_daily_trend(df_filtered: pd.DataFrame) -> None:
    col1, col2 = st.columns(2)

    with col1:
        fig_win = px.line(
            df_filtered,
            x="date",
            y="win_rate",
            title="📊 勝率の推移",
            markers=True,
            labels={"date": "日付", "win_rate": "勝率(%)"},
        )
        fig_win.update_traces(line_color=COLORS["secondary_blue"], marker_size=6)
        fig_win.update_layout(height=400, hovermode="x unified")
        st.plotly_chart(fig_win, use_container_width=True)

    with col2:
        fig_games = px.line(
            df_filtered,
            x="date",
            y="avg_games_per_machine",
            title="🎲 平均G数の推移",
            markers=True,
            labels={"date": "日付", "avg_games_per_machine": "平均G数"},
        )
        fig_games.update_traces(line_color=COLORS["secondary_orange"], marker_size=6)
        fig_games.update_layout(height=400, hovermode="x unified")
        st.plotly_chart(fig_games, use_container_width=True)

    col3, col4 = st.columns(2)

    with col3:
        fig_diff = px.line(
            df_filtered,
            x="date",
            y="avg_diff_per_machine",
            title="💰 平均差枚の推移",
            markers=True,
            labels={"date": "日付", "avg_diff_per_machine": "平均差枚"},
        )
        fig_diff.update_traces(line_color=COLORS["secondary_green"], marker_size=6)
        fig_diff.update_layout(height=400, hovermode="x unified")
        st.plotly_chart(fig_diff, use_container_width=True)

    with col4:
        fig_machines = px.bar(
            df_filtered,
            x="date",
            y="total_machines",
            title="🤖 稼働台数の推移",
            labels={"date": "日付", "total_machines": "稼働台数"},
        )
        fig_machines.update_traces(marker_color=COLORS["secondary_red"])
        fig_machines.update_layout(height=400, hovermode="x unified")
        st.plotly_chart(fig_machines, use_container_width=True)

    premium_divider()
    st.markdown("### 📊 統計情報")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("平均勝率", f"{df_filtered['win_rate'].mean():.1f}%")
        st.metric("勝率 (最高)", f"{df_filtered['win_rate'].max():.1f}%")
        st.metric("勝率 (最低)", f"{df_filtered['win_rate'].min():.1f}%")

    with col2:
        st.metric("平均G数", f"{int(df_filtered['avg_games_per_machine'].mean()):,}G")
        st.metric("G数 (最高)", f"{int(df_filtered['avg_games_per_machine'].max()):,}G")
        st.metric("G数 (最低)", f"{int(df_filtered['avg_games_per_machine'].min()):,}G")

    with col3:
        st.metric("平均差枚", f"{int(df_filtered['avg_diff_per_machine'].mean()):,}枚")
        st.metric("差枚 (最高)", f"{int(df_filtered['avg_diff_per_machine'].max()):,}枚")
        st.metric("差枚 (最低)", f"{int(df_filtered['avg_diff_per_machine'].min()):,}枚")


def render_categorical_axis(df_filtered: pd.DataFrame, axis_key: str) -> None:
    config = CATEGORICAL_AXES[axis_key]
    work = df_filtered.copy()
    column = config["column"]
    axis_label = config["axis_label"]

    derive: Callable[[pd.DataFrame], pd.Series] | None = config["derive"]
    if derive is not None:
        work[column] = derive(work)
    elif column not in work.columns:
        st.warning(f"⚠️ {column} データが利用できません")
        return

    order = config["order"] or sorted(work[column].unique())
    grouped = work.groupby(column)[["win_rate", "avg_games_per_machine", "avg_diff_per_machine"]].mean()
    grouped = grouped.reindex(order)

    col1, col2, col3 = st.columns(3)

    with col1:
        fig1 = px.bar(
            x=grouped.index.astype(str),
            y=grouped["win_rate"],
            title=f"📊 {config['label']}勝率",
            labels={"x": axis_label, "y": "勝率(%)"},
        )
        fig1.update_traces(marker_color=COLORS["secondary_blue"])
        fig1.update_xaxes(tickangle=-45)
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=grouped.index.astype(str),
            y=grouped["avg_games_per_machine"],
            title=f"🎲 {config['label']}平均G数",
            labels={"x": axis_label, "y": "平均G数"},
        )
        fig2.update_traces(marker_color=COLORS["secondary_orange"])
        fig2.update_xaxes(tickangle=-45)
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=grouped.index.astype(str),
            y=grouped["avg_diff_per_machine"],
            title=f"💰 {config['label']}平均差枚",
            labels={"x": axis_label, "y": "平均差枚"},
        )
        fig3.update_traces(marker_color=COLORS["secondary_green"])
        fig3.update_xaxes(tickangle=-45)
        st.plotly_chart(fig3, use_container_width=True)

    premium_divider()
    st.markdown(f"### 📋 {config['label']}詳細統計")

    table_data = []
    for value in order:
        subset = work[work[column] == value]
        if not subset.empty:
            table_data.append(
                {
                    axis_label: value,
                    "平均勝率": float(subset["win_rate"].mean()),
                    "平均G数": int(subset["avg_games_per_machine"].mean()),
                    "平均差枚": int(subset["avg_diff_per_machine"].mean()),
                    "サンプル数": len(subset),
                }
            )

    df_display = pd.DataFrame(table_data)
    df_display["平均勝率"] = df_display["平均勝率"].apply(lambda x: f"{x:.1f}%")
    st.dataframe(df_display, use_container_width=True, hide_index=True)


ZOROME_LABEL = "ゾロ目"


def render_machine_tail(
    *,
    db_path: str,
    date_range: Tuple[datetime, datetime],
    min_games: int,
    show_low_confidence: bool,
    machine_type: str,
) -> None:
    """台番号末尾別（0-9 + ゾロ目）を表示する。

    last_digit_summary_* テーブルは last_digit 列（TEXT）に "0"-"9" に加えて
    "ゾロ目" 集計行を machine_type 別にあらかじめ持っているため、それをそのまま使う
    （machine_detailed_results から作り直すと machine_type フィルタが効かなくなる）。
    """
    df_last_digit = load_last_digit_summary(str(db_path), machine_type)
    if df_last_digit.empty:
        st.warning(f"⚠️ 末尾別データが利用できません（機種: {machine_type}）")
        return

    df_filtered = apply_sidebar_filters(
        df_last_digit,
        date_range=date_range,
        min_games=min_games,
        show_low_confidence=show_low_confidence,
        games_column="avg_games",
    )
    if df_filtered.empty:
        st.warning("⚠️ フィルタ条件に合致するデータがありません")
        return

    tail_summary = (
        df_filtered.groupby("last_digit")
        .agg({"win_rate": "mean", "avg_games": "mean", "avg_diff_coins": "mean", "machine_count": "mean"})
        .round(2)
    )

    # last_digit_summary_* は "0"-"9" 以外にゾロ目集計行を1件持つ。
    # DB側のエンコード不整合でラベル文字列がそのまま一致しない場合があるため、
    # 数値に変換できるかどうかで判定し、表示は常に ZOROME_LABEL に統一する。
    digit_order = sorted((t for t in tail_summary.index if str(t).isdigit()), key=int)
    zorome_keys = [t for t in tail_summary.index if not str(t).isdigit()]
    has_zorome = bool(zorome_keys)
    zorome_key = zorome_keys[0] if zorome_keys else None

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        fig1 = px.bar(
            x=digit_order,
            y=[tail_summary.loc[t, "win_rate"] for t in digit_order],
            title="📊 末尾別勝率",
            labels={"x": "台番号末尾", "y": "勝率(%)"},
        )
        fig1.update_traces(marker_color=COLORS["secondary_blue"])
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = px.bar(
            x=digit_order,
            y=[tail_summary.loc[t, "avg_games"] for t in digit_order],
            title="🎲 末尾別平均G数",
            labels={"x": "台番号末尾", "y": "平均G数"},
        )
        fig2.update_traces(marker_color=COLORS["secondary_orange"])
        st.plotly_chart(fig2, use_container_width=True)

    with col3:
        fig3 = px.bar(
            x=digit_order,
            y=[tail_summary.loc[t, "avg_diff_coins"] for t in digit_order],
            title="💰 末尾別平均差枚",
            labels={"x": "台番号末尾", "y": "平均差枚"},
        )
        fig3.update_traces(marker_color=COLORS["secondary_green"])
        st.plotly_chart(fig3, use_container_width=True)

    with col4:
        fig4 = px.bar(
            x=digit_order,
            y=[tail_summary.loc[t, "machine_count"] for t in digit_order],
            title="🤖 末尾別台数",
            labels={"x": "台番号末尾", "y": "台数"},
        )
        fig4.update_traces(marker_color=COLORS["secondary_red"])
        st.plotly_chart(fig4, use_container_width=True)

    premium_divider()
    st.markdown("### 📋 台番号末尾別詳細統計")

    table_data = []
    for tail in digit_order:
        row = tail_summary.loc[tail]
        table_data.append(
            {
                "末尾": tail,
                "平均勝率": float(row["win_rate"]),
                "平均G数": int(row["avg_games"]),
                "平均差枚": int(row["avg_diff_coins"]),
                "平均台数": int(row["machine_count"]),
            }
        )

    if has_zorome:
        row = tail_summary.loc[zorome_key]
        table_data.append(
            {
                "末尾": ZOROME_LABEL,
                "平均勝率": float(row["win_rate"]),
                "平均G数": int(row["avg_games"]),
                "平均差枚": int(row["avg_diff_coins"]),
                "平均台数": int(row["machine_count"]),
            }
        )

    df_display = pd.DataFrame(table_data)
    df_display["平均勝率"] = df_display["平均勝率"].apply(lambda x: f"{x:.1f}%")
    st.dataframe(df_display, use_container_width=True, hide_index=True)
