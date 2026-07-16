from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.design_system import premium_divider, section_title
from dashboard.utils import theory_engine as theory
from dashboard.utils.interaction_analysis import (
    DEFAULT_EFFECT_SIZE_THRESHOLD,
    INTERACTION_AXIS_OPTIONS,
    INTERACTION_METRIC_OPTIONS,
    attach_interaction_axes,
    axis_series,
    build_claim_draft,
    metric_series,
    run_pairwise_axis_test,
    sorted_axis_values,
    summarize_cells,
)


METRIC_TITLES = {
    "avg_diff": "avg_diff",
    "win_rate": "win_rate",
    "hit104_rate": "hit104_rate",
}

AXIS_LABELS = {
    "hanaban_min": "端番min",
    "hanaban_max": "端番max",
    "kakuban": "角番(通路)",
    "section": "Section",
    "machine_name": "機種名(全期間)",
    "machine_name_current": "機種名(最新日のみ)",
}


_AXIS_SOURCE_COLUMNS = {
    "hanaban_min": "rank_from_min",
    "hanaban_max": "rank_from_max",
    "kakuban": "rank_from_aisle",
    "section": "section",
}


def _axis_has_data(frame: pd.DataFrame, axis: str) -> bool:
    """Check the raw source column, not axis_series() output — several axes
    (segment/family/section/machine_name) fillna() before returning, which
    would make a notna() check on axis_series() always true."""

    source_column = _AXIS_SOURCE_COLUMNS.get(axis)
    if source_column is None:
        return True
    if source_column not in frame.columns:
        return False
    return bool(frame[source_column].notna().any())


def _resolve_hall_key() -> str:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")
    return theory.resolve_hall_key(hall_name=hall_name, db_path=db_path)


@st.cache_data(ttl=1800)
def _load_theory_frame_cached(db_path: str) -> pd.DataFrame:
    return theory.load_theory_frame(db_path)


def _format_axis_value(value: object, axis: str) -> str:
    if pd.isna(value):
        return "不明"
    if axis == "event_day":
        return "イベント日" if bool(value) else "通常日"
    if axis in {"dd", "hanaban_min", "hanaban_max", "kakuban", "machine_tail"}:
        try:
            return str(int(value))
        except Exception:
            return str(value)
    return str(value)


def _overall_metric(frame: pd.DataFrame, metric: str) -> float:
    series = metric_series(frame, metric)
    if series.dropna().empty:
        return float("nan")
    return float(series.mean())


def _render_pair_summary(frame: pd.DataFrame, axes: list[str], metric: str, min_n: int) -> list[tuple[str, object]]:
    pair_labels: list[tuple[str, object]] = []
    for idx, axis_a in enumerate(axes):
        for axis_b in axes[idx + 1 :]:
            stats = run_pairwise_axis_test(frame, axis_a, axis_b, metric=metric, min_n=min_n)
            pair_labels.append((f"{axis_a} x {axis_b}", stats))

    if not pair_labels:
        return pair_labels

    cols = st.columns(len(pair_labels))
    for col, (label, stats) in zip(cols, pair_labels, strict=True):
        with col:
            st.metric("軸ペア", label)
            st.metric("効果量", "" if pd.isna(stats.effect_size) else f"{stats.effect_size:.3f}")
            st.metric("p値", "" if pd.isna(stats.p_value) else f"{stats.p_value:.4g}")
            st.caption(
                f"{stats.test} | n={stats.n_obs:,} | groups={stats.n_groups} | sparse={stats.n_sparse_groups}"
                + (f" | {stats.note}" if stats.note else "")
            )
    return pair_labels


def _render_matrix_figure(
    summary: pd.DataFrame,
    axis_x: str,
    axis_y: str,
    metric: str,
) -> go.Figure:
    pivot_metric = summary.pivot(index=axis_y, columns=axis_x, values=metric)
    pivot_n = summary.pivot(index=axis_y, columns=axis_x, values="n")

    y_order = sorted_axis_values(summary[axis_y], axis_y)
    x_order = sorted_axis_values(summary[axis_x], axis_x)
    pivot_metric = pivot_metric.reindex(index=y_order, columns=x_order)
    pivot_n = pivot_n.reindex(index=y_order, columns=x_order)

    text = pivot_n.map(lambda value: "" if pd.isna(value) else f"n={int(value)}")

    hover_templates = {
        "avg_diff": "%{customdata[0]}<br>%{customdata[1]}<br>n=%{customdata[2]}<br>avg_diff=%{z:.1f}<extra></extra>",
        "win_rate": "%{customdata[0]}<br>%{customdata[1]}<br>n=%{customdata[2]}<br>win_rate=%{z:.1%}<extra></extra>",
        "hit104_rate": "%{customdata[0]}<br>%{customdata[1]}<br>n=%{customdata[2]}<br>hit104_rate=%{z:.1%}<extra></extra>",
    }

    customdata = np.empty((len(pivot_metric.index), len(pivot_metric.columns), 3), dtype=object)
    for row_idx, y_value in enumerate(pivot_metric.index):
        for col_idx, x_value in enumerate(pivot_metric.columns):
            customdata[row_idx, col_idx, 0] = f"{axis_y}={_format_axis_value(y_value, axis_y)}"
            customdata[row_idx, col_idx, 1] = f"{axis_x}={_format_axis_value(x_value, axis_x)}"
            customdata[row_idx, col_idx, 2] = pivot_n.iloc[row_idx, col_idx]

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot_metric.to_numpy(),
            x=[_format_axis_value(value, axis_x) for value in pivot_metric.columns],
            y=[_format_axis_value(value, axis_y) for value in pivot_metric.index],
            text=text.to_numpy(),
            texttemplate="%{text}",
            customdata=customdata,
            colorscale="RdYlGn",
            colorbar={"title": METRIC_TITLES[metric]},
            hovertemplate=hover_templates[metric],
        )
    )
    fig.update_layout(height=520, margin={"l": 30, "r": 20, "t": 40, "b": 30})
    fig.update_xaxes(side="top")
    return fig


def _render_matrix_block(
    summary: pd.DataFrame,
    axis_x: str,
    axis_y: str,
    metric: str,
    *,
    facet_value: object | None = None,
    facet_axis: str | None = None,
) -> None:
    if summary.empty:
        st.info("表示できる行がありません。")
        return

    fig = _render_matrix_figure(summary, axis_x, axis_y, metric)
    title = f"{axis_y} x {axis_x}"
    if facet_axis is not None:
        title = f"{facet_axis}={_format_axis_value(facet_value, facet_axis)} | {title}"
    st.markdown(f"#### {title}")
    st.plotly_chart(fig, use_container_width=True)


def _render_claim_draft(
    frame: pd.DataFrame,
    cell_summary: pd.DataFrame,
    axes: list[str],
    metric: str,
    hall_key: str,
    min_n: int,
) -> None:
    candidates = cell_summary.loc[cell_summary["n"] >= int(min_n)].copy()
    if candidates.empty:
        st.info("クレーム下書きの候補セルがありません。")
        return

    candidates["overall_metric"] = _overall_metric(frame, metric)
    candidates["delta"] = pd.to_numeric(candidates[metric], errors="coerce") - candidates["overall_metric"]
    candidates["axes"] = [tuple(axes)] * len(candidates)
    candidates = candidates.sort_values([metric, "n"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )

    def _label(row: pd.Series) -> str:
        parts = [f"{axis}={_format_axis_value(row[axis], axis)}" for axis in axes]
        value = row[metric]
        delta = row["delta"]
        return " | ".join(parts + [f"n={int(row['n'])}", f"{metric}={value:.3f}", f"delta={delta:+.3f}"])

    options = {_label(row): idx for idx, row in candidates.iterrows()}
    selected_label = st.selectbox("気になるセル", list(options.keys()), key=f"interaction_claim_{hall_key}_{metric}")
    selected_row = candidates.iloc[options[selected_label]].copy()
    selected_row["claim_title"] = f"{' x '.join(axes)} {metric}"
    selected_row["claim_id"] = (
        (
            f"{hall_key}-"
            + "-".join(f"{axis}-{_format_axis_value(selected_row[axis], axis)}" for axis in axes)
            + f"-{metric}"
        )
        .replace(" ", "_")
        .replace("/", "_")
    )
    selected_row["min_n"] = int(min_n)

    yaml_text = build_claim_draft(
        selected_row,
        hall_key=hall_key,
        metric=metric,
        source="document/plans/2026-07-10-dashboard-refactoring-plan.md#phase-3",
        last_reviewed=str(date.today()),
    )

    st.code(yaml_text, language="yaml")


def render() -> None:
    hall_key = _resolve_hall_key()
    db_path = st.session_state.get("db_path")
    date_range = st.session_state.get("date_range")
    min_games = int(st.session_state.get("min_games", 1000))

    section_title(
        "交互作用エクスプローラ", "2〜3軸を組み合わせてヒートマップを確認し、クレーム下書きをコピーできます。"
    )
    premium_divider()

    if not db_path:
        st.warning("サイドバーでホール DB を選択してください。")
        return

    frame = _load_theory_frame_cached(str(db_path))
    if frame.empty:
        st.info("理論検証に使える台履歴を読み込めませんでした。")
        return

    frame = attach_interaction_axes(frame)
    start_date = end_date = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    filtered = theory.filter_theory_frame(frame, start_date=start_date, end_date=end_date, min_games=min_games)
    if filtered.empty:
        st.info("現在の期間フィルタと min_games フィルタを通すと、対象行が残りませんでした。")
        return

    st.caption(
        f"ホール: {hall_key} | Rows: {len(filtered):,} | Dates: {filtered['date_dt'].min():%Y-%m-%d} to {filtered['date_dt'].max():%Y-%m-%d}"
    )

    axis_options = [axis for axis in INTERACTION_AXIS_OPTIONS if _axis_has_data(frame, axis)]
    axes = st.multiselect(
        "🔎 軸を選択（2〜3軸）",
        axis_options,
        default=["segment", "dd_bin"],
        format_func=lambda value: AXIS_LABELS.get(value, value),
        key=f"interaction_axes_{hall_key}",
    )
    if len(axes) < 2:
        st.warning("軸を2〜3個選択してください。")
        return
    if len(axes) > 3:
        st.warning("先頭の3軸のみ使用します。")
        axes = axes[:3]

    metric = st.selectbox("表示指標", INTERACTION_METRIC_OPTIONS, key=f"interaction_metric_{hall_key}")
    min_n = st.slider(
        "セルごとの最小サンプル数", min_value=1, max_value=30, value=5, step=1, key=f"interaction_min_n_{hall_key}"
    )
    effect_threshold = st.slider(
        "効果量のしきい値",
        min_value=0.0,
        max_value=0.5,
        value=DEFAULT_EFFECT_SIZE_THRESHOLD,
        step=0.01,
        key=f"interaction_effect_threshold_{hall_key}",
    )

    pairwise = _render_pair_summary(filtered, axes, metric, min_n)
    pairwise = [item for item in pairwise if pd.notna(item[1].effect_size) and item[1].effect_size >= effect_threshold]
    if pairwise:
        st.caption("しきい値を超えたペアの結果は以下で確認できます。")

    axis_x, axis_y = axes[0], axes[1]
    facet_axis = axes[2] if len(axes) == 3 else None

    if facet_axis is None:
        summary = summarize_cells(filtered, [axis_x, axis_y], metric=metric)
        if summary.empty:
            st.info("クロス集計データがありません。")
            return
        _render_matrix_block(summary, axis_x, axis_y, metric)
        with st.expander("クレーム下書きをコピー", expanded=False):
            _render_claim_draft(filtered, summary, [axis_x, axis_y], metric, hall_key, min_n)
        return

    facet_values = sorted_axis_values(axis_series(filtered, facet_axis), facet_axis)
    tabs = st.tabs([f"{facet_axis}={_format_axis_value(value, facet_axis)}" for value in facet_values])
    all_cells: list[pd.DataFrame] = []
    for tab, facet_value in zip(tabs, facet_values, strict=True):
        with tab:
            subset = filtered.loc[axis_series(filtered, facet_axis).eq(facet_value)].copy()
            summary = summarize_cells(subset, [axis_x, axis_y], metric=metric)
            if summary.empty:
                st.info("このファセットには行がありません。")
                continue
            all_cells.append(summary.assign(**{facet_axis: facet_value}))
            _render_matrix_block(summary, axis_x, axis_y, metric, facet_value=facet_value, facet_axis=facet_axis)

    if not all_cells:
        st.info("現在の選択条件に一致するファセットがありませんでした。")
        return

    with st.expander("クレーム下書きをコピー", expanded=False):
        combined = pd.concat(all_cells, ignore_index=True)
        _render_claim_draft(filtered, combined, axes, metric, hall_key, min_n)


if __name__ == "__main__":
    render()
