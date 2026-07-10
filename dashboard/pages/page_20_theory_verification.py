"""Generic theory verification page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.utils import theory_engine as theory


STATUS_COLORS = {
    "robust": "#2f9e44",
    "fragile": "#f08c00",
    "refuted": "#e03131",
    "watching": "#228be6",
}

METRIC_LABELS = {
    "avg_diff": "平均差玉",
    "win_rate": "勝率",
    "hit104_rate": "104%率",
    "avg_games": "平均ゲーム数",
}


@dataclass(frozen=True)
class ClaimComparison:
    subset_n: int
    baseline_n: int
    recent_subset_n: int
    recent_baseline_n: int
    full_value: float
    full_baseline_value: float
    recent_value: float
    recent_baseline_value: float
    effect_size: float


@st.cache_data(ttl=1800)
def _load_theory_frame_cached(db_path: str) -> pd.DataFrame:
    return theory.load_theory_frame(db_path)


def _format_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    work = frame.copy()
    for column in ["avg_diff", "avg_games", "total_diff"]:
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").round(0)
    for column in ["win_rate", "hit104_rate", "avg_hit104_rate", "diff_share"]:
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"{value * 100:.1f}%"
            )
    for column in ["days", "machine_count", "n"]:
        if column in work.columns:
            work[column] = pd.to_numeric(work[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"{int(value)}"
            )
    if "is_event_day" in work.columns:
        work["is_event_day"] = work["is_event_day"].map({True: "イベント日", False: "通常日"})
    return work


def _resolve_hall_key() -> str:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")
    return theory.resolve_hall_key(hall_name=hall_name, db_path=db_path)


def _status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#868e96")
    return (
        f"<span style='display:inline-block;padding:0.15rem 0.55rem;border-radius:999px;"
        f"background:{color};color:white;font-size:0.82rem;font-weight:600;'>{status}</span>"
    )


def _format_metric_value(metric: str, value: float) -> str:
    if pd.isna(value):
        return ""
    if metric in {"win_rate", "hit104_rate"}:
        return f"{value * 100:.1f}%"
    if metric == "avg_games":
        return f"{value:.1f}"
    return f"{value:.3f}"


def _metric_series(frame: pd.DataFrame, metric: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype="float64")
    if metric == "avg_diff":
        return pd.to_numeric(frame.get("diff_coins_normalized"), errors="coerce")
    if metric == "win_rate":
        return pd.to_numeric(frame.get("diff_coins_normalized"), errors="coerce").gt(0).astype(float)
    if metric == "hit104_rate":
        return pd.to_numeric(frame.get("hit104"), errors="coerce")
    if metric == "avg_games":
        return pd.to_numeric(frame.get("games_normalized"), errors="coerce")
    raise KeyError(metric)


def _cohens_d(sample_a: pd.Series, sample_b: pd.Series) -> float:
    a = pd.to_numeric(sample_a, errors="coerce").dropna()
    b = pd.to_numeric(sample_b, errors="coerce").dropna()
    if len(a) < 2 or len(b) < 2:
        return np.nan
    var_a = a.var(ddof=1)
    var_b = b.var(ddof=1)
    pooled = ((len(a) - 1) * var_a + (len(b) - 1) * var_b) / (len(a) + len(b) - 2)
    if pd.isna(pooled) or pooled <= 0:
        return np.nan
    return float((a.mean() - b.mean()) / np.sqrt(pooled))


def _claim_mask(frame: pd.DataFrame, claim_segment: dict[str, Any]) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)

    mask = pd.Series(True, index=frame.index)
    for key, expected in claim_segment.items():
        if key == "floor":
            mask &= frame["floor"].astype(str).eq(str(expected))
        elif key == "lr":
            mask &= frame["lr"].astype(str).eq(str(expected))
        elif key == "family":
            mask &= frame["family"].astype(str).eq(str(expected))
        elif key == "event_day":
            mask &= frame["is_event_day"].fillna(False).eq(bool(expected))
        elif key == "strong_mmdd":
            strong = frame["date_dt"].dt.month.eq(frame["date_dt"].dt.day)
            mask &= strong.eq(bool(expected))
        elif key == "cooling_zone":
            mask &= frame["cooling_zone"].astype(str).eq(str(expected))
        elif key == "segment":
            values = expected if isinstance(expected, list) else [expected]
            mask &= frame["segment"].isin(values)
        elif key == "dd":
            values = expected if isinstance(expected, list) else [expected]
            mask &= frame["dd"].isin(values)
        elif key == "machine_tail":
            values = expected if isinstance(expected, list) else [expected]
            if "last_digit" in frame.columns:
                tail = pd.to_numeric(frame["last_digit"], errors="coerce")
            else:
                tail = pd.to_numeric(frame["machine_number"], errors="coerce").mod(10)
            mask &= tail.isin([pd.to_numeric(value, errors="coerce") for value in values])
        elif key == "machine_number":
            values = expected if isinstance(expected, list) else [expected]
            mask &= frame["machine_number"].isin(values)
        elif key == "kakuban":
            values = expected if isinstance(expected, list) else [expected]
            axis = frame.get("kakuban", pd.Series(pd.NA, index=frame.index))
            mask &= pd.to_numeric(axis, errors="coerce").isin(values)
        elif key == "hanaban":
            values = expected if isinstance(expected, list) else [expected]
            axis = frame.get("hanaban", pd.Series(pd.NA, index=frame.index))
            mask &= pd.to_numeric(axis, errors="coerce").isin(values)
        else:
            values = expected if isinstance(expected, list) else [expected]
            if key in frame.columns:
                mask &= frame[key].isin(values)
    return mask


def _baseline_mask(frame: pd.DataFrame, baseline: str, claim_segment: dict[str, Any] | None = None) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    if baseline == "hall_all":
        return pd.Series(True, index=frame.index)
    if baseline == "hall_event":
        return frame["is_event_day"].fillna(False)
    if baseline == "hall_non_event":
        return ~frame["is_event_day"].fillna(False)
    if baseline == "segment_non_event":
        # Same segment definition, but forced to the opposite side of the
        # event_day axis — needed for claims about the event_day effect
        # *within* a segment (e.g. family=A), where hall_all mixes in other
        # families with a structurally different baseline metric level.
        segment_ex_event = {k: v for k, v in (claim_segment or {}).items() if k != "event_day"}
        return _claim_mask(frame, segment_ex_event) & ~frame["is_event_day"].fillna(False)
    raise ValueError(f"Unsupported baseline: {baseline}")


def _summarize_claim(frame: pd.DataFrame, claim: dict[str, Any]) -> tuple[pd.DataFrame, ClaimComparison]:
    claim_segment = claim.get("segment", {})
    baseline = str(claim.get("baseline", "hall_all"))
    metric = str(claim.get("metric", "avg_diff"))

    subset_mask = _claim_mask(frame, claim_segment)
    baseline_mask = _baseline_mask(frame, baseline, claim_segment)
    subset = frame.loc[subset_mask].copy()
    baseline_frame = frame.loc[baseline_mask].copy()

    if baseline == "hall_all" and not subset.empty:
        baseline_frame = frame.copy()

    if subset.empty:
        empty = pd.DataFrame(
            columns=["scope", "n", "value", "mean", "effect_size"],
        )
        comparison = ClaimComparison(0, len(baseline_frame), 0, 0, np.nan, np.nan, np.nan, np.nan, np.nan)
        return empty, comparison

    recent_start = frame["date_dt"].max() - pd.Timedelta(days=89)
    recent_subset = subset.loc[subset["date_dt"] >= recent_start].copy()
    recent_baseline = baseline_frame.loc[baseline_frame["date_dt"] >= recent_start].copy()

    subset_metric = _metric_series(subset, metric)
    baseline_metric = _metric_series(baseline_frame, metric)
    recent_subset_metric = _metric_series(recent_subset, metric)
    recent_baseline_metric = _metric_series(recent_baseline, metric)

    summary = pd.DataFrame(
        [
            {
                "scope": "全期間",
                "n": int(len(subset_metric.dropna())),
                "claim_value": float(subset_metric.mean()) if not subset_metric.dropna().empty else np.nan,
                "baseline_value": float(baseline_metric.mean()) if not baseline_metric.dropna().empty else np.nan,
                "delta": float(subset_metric.mean() - baseline_metric.mean())
                if not subset_metric.dropna().empty and not baseline_metric.dropna().empty
                else np.nan,
            },
            {
                "scope": "直近90日",
                "n": int(len(recent_subset_metric.dropna())),
                "claim_value": float(recent_subset_metric.mean())
                if not recent_subset_metric.dropna().empty
                else np.nan,
                "baseline_value": float(recent_baseline_metric.mean())
                if not recent_baseline_metric.dropna().empty
                else np.nan,
                "delta": float(recent_subset_metric.mean() - recent_baseline_metric.mean())
                if not recent_subset_metric.dropna().empty and not recent_baseline_metric.dropna().empty
                else np.nan,
            },
        ]
    )
    effect_size = _cohens_d(subset_metric, baseline_metric)
    comparison = ClaimComparison(
        subset_n=int(len(subset)),
        baseline_n=int(len(baseline_frame)),
        recent_subset_n=int(len(recent_subset)),
        recent_baseline_n=int(len(recent_baseline)),
        full_value=float(subset_metric.mean()) if not subset_metric.dropna().empty else np.nan,
        full_baseline_value=float(baseline_metric.mean()) if not baseline_metric.dropna().empty else np.nan,
        recent_value=float(recent_subset_metric.mean()) if not recent_subset_metric.dropna().empty else np.nan,
        recent_baseline_value=float(recent_baseline_metric.mean())
        if not recent_baseline_metric.dropna().empty
        else np.nan,
        effect_size=effect_size,
    )
    return summary, comparison


def _comparison_chart(summary: pd.DataFrame, metric: str, claim_title: str) -> go.Figure:
    value_label = METRIC_LABELS.get(metric, metric)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Claim",
            x=summary["scope"],
            y=summary["claim_value"],
            marker_color="#2f9e44",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Baseline",
            x=summary["scope"],
            y=summary["baseline_value"],
            marker_color="#868e96",
        )
    )
    fig.update_layout(
        title=claim_title,
        barmode="group",
        yaxis_title=value_label,
        xaxis_title="期間",
        legend_title_text="比較対象",
        height=320,
    )
    if metric in {"win_rate", "hit104_rate"}:
        fig.update_yaxes(tickformat=".0%")
    return fig


def _position_breakdown_chart(
    frame: pd.DataFrame,
    claim_segment: dict[str, Any],
    metric: str,
    focus: dict[str, Any],
    axis_col: str,
    title: str,
) -> go.Figure:
    subset = frame.loc[_claim_mask(frame, claim_segment)].copy()
    value_label = METRIC_LABELS.get(metric, metric)
    axis_label = {"hanaban": "端番", "kakuban": "角番"}.get(axis_col, axis_col)
    fig = go.Figure()

    if subset.empty or axis_col not in subset.columns:
        fig.update_layout(
            title=title,
            yaxis_title=value_label,
            xaxis_title=axis_label,
            height=320,
        )
        return fig

    work = pd.DataFrame(
        {
            axis_col: pd.to_numeric(subset[axis_col], errors="coerce"),
            "metric": _metric_series(subset, metric),
        }
    ).dropna(subset=[axis_col, "metric"])

    if work.empty:
        fig.update_layout(
            title=title,
            yaxis_title=value_label,
            xaxis_title=axis_label,
            height=320,
        )
        return fig

    grouped = (
        work.groupby(axis_col, as_index=False)
        .agg(value=("metric", "mean"), n=("metric", "size"))
        .loc[lambda data: data["n"] >= 5]
        .sort_values(axis_col)
    )

    best = {int(value) for value in (focus.get("best") or []) if pd.notna(value)}
    avoid = {int(value) for value in (focus.get("avoid") or []) if pd.notna(value)}
    colors = [
        "#2f9e44" if int(value) in best else "#e03131" if int(value) in avoid else "#868e96"
        for value in grouped[axis_col]
    ]

    fig.add_trace(
        go.Bar(
            x=grouped[axis_col].astype(int),
            y=grouped["value"],
            marker_color=colors,
            text=[f"n={int(value)}" for value in grouped["n"]],
            textposition="outside",
            hovertemplate=f"{axis_label}=%{{x}}<br>値=%{{y}}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        yaxis_title=value_label,
        xaxis_title=axis_label,
        height=320,
        showlegend=False,
    )
    if metric in {"win_rate", "hit104_rate"}:
        fig.update_yaxes(tickformat=".0%")
    return fig


def _zorome_digit_breakdown_chart(frame: pd.DataFrame, claim_segment: dict[str, Any], metric: str) -> go.Figure:
    subset = frame.loc[_claim_mask(frame, claim_segment)].copy()
    value_label = METRIC_LABELS.get(metric, metric)
    fig = go.Figure()

    if subset.empty or "last_digit" not in subset.columns:
        fig.update_layout(
            title="ゾロ目桁別内訳（00〜99）",
            yaxis_title=value_label,
            xaxis_title="桁",
            height=320,
        )
        return fig

    work = pd.DataFrame(
        {
            "digit": pd.to_numeric(subset["last_digit"], errors="coerce"),
            "metric": _metric_series(subset, metric),
        }
    ).dropna(subset=["digit", "metric"])

    if work.empty:
        fig.update_layout(
            title="ゾロ目桁別内訳（00〜99）",
            yaxis_title=value_label,
            xaxis_title="桁",
            height=320,
        )
        return fig

    grouped = (
        work.groupby("digit", as_index=False)
        .agg(value=("metric", "mean"), n=("metric", "size"))
        .loc[lambda data: data["n"] >= 5]
        .sort_values("digit")
    )

    fig.add_trace(
        go.Bar(
            x=grouped["digit"].astype(int),
            y=grouped["value"],
            marker_color="#4263eb",
            text=[f"n={int(value)}" for value in grouped["n"]],
            textposition="outside",
            hovertemplate="桁=%{x}<br>値=%{y}<extra></extra>",
        )
    )
    fig.update_layout(
        title="ゾロ目桁別内訳（00〜99）",
        yaxis_title=value_label,
        xaxis_title="桁",
        height=320,
        showlegend=False,
    )
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(10)),
        ticktext=[f"{digit}{digit}" for digit in range(10)],
    )
    if metric in {"win_rate", "hit104_rate"}:
        fig.update_yaxes(tickformat=".0%")
    return fig


def _render_claim_block(frame: pd.DataFrame, hall_config: dict[str, Any], claim: dict[str, Any]) -> None:
    summary, comparison = _summarize_claim(frame, claim)
    metric = str(claim.get("metric", "avg_diff"))
    title = str(claim.get("title", ""))
    status = str(claim.get("status", "watching"))
    source = str(claim.get("source", ""))
    min_n = int(claim.get("min_n", theory.THEORY_MIN_SAMPLE))

    expander_label = f"{title} [{status}]"
    with st.expander(expander_label, expanded=status == "robust"):
        st.markdown(f"### {title} {_status_badge(status)}", unsafe_allow_html=True)
        if source:
            st.caption(f"Source: {source}")

        if comparison.subset_n < min_n:
            st.warning(f"この claim は n={comparison.subset_n} で min_n={min_n} を下回ります。")

        values = st.columns(4)
        values[0].metric("Full claim", _format_metric_value(metric, comparison.full_value))
        values[1].metric("Full baseline", _format_metric_value(metric, comparison.full_baseline_value))
        values[2].metric("Recent claim", _format_metric_value(metric, comparison.recent_value))
        values[3].metric("Recent baseline", _format_metric_value(metric, comparison.recent_baseline_value))

        stats = st.columns(4)
        stats[0].metric("Claim n", f"{comparison.subset_n:,}")
        stats[1].metric("Baseline n", f"{comparison.baseline_n:,}")
        stats[2].metric("Effect size", "" if pd.isna(comparison.effect_size) else f"{comparison.effect_size:.2f}")
        stats[3].metric(
            "Full delta",
            ""
            if summary.empty or pd.isna(summary.iloc[0]["delta"])
            else _format_metric_value(metric, float(summary.iloc[0]["delta"])),
        )

        display_summary = summary.copy()
        for column in ["claim_value", "baseline_value", "delta"]:
            display_summary[column] = pd.to_numeric(display_summary[column], errors="coerce").map(
                lambda value: "" if pd.isna(value) else f"{value:.4f}"
            )
        display_summary["n"] = pd.to_numeric(display_summary["n"], errors="coerce").map(
            lambda value: "" if pd.isna(value) else f"{int(value)}"
        )
        st.dataframe(display_summary, use_container_width=True, hide_index=True)

        st.plotly_chart(_comparison_chart(summary, metric, title), use_container_width=True)
        hanaban_focus = claim.get("hanaban_focus")
        if hanaban_focus:
            note = hanaban_focus.get("note")
            if note:
                st.caption(str(note))
            st.plotly_chart(
                _position_breakdown_chart(
                    frame, claim.get("segment", {}), metric, hanaban_focus, "hanaban", "端番別内訳"
                ),
                use_container_width=True,
            )
        kakuban_focus = claim.get("kakuban_focus")
        if (
            kakuban_focus
            and "kakuban" in frame.columns
            and pd.to_numeric(frame["kakuban"], errors="coerce").notna().any()
        ):
            note = kakuban_focus.get("note")
            if note:
                st.caption(str(note))
            st.plotly_chart(
                _position_breakdown_chart(
                    frame,
                    claim.get("segment", {}),
                    metric,
                    kakuban_focus,
                    "kakuban",
                    "角番別内訳（通路距離）",
                ),
                use_container_width=True,
            )
        if claim.get("id") == "k7-zorome-tail":
            st.plotly_chart(
                _zorome_digit_breakdown_chart(frame, claim.get("segment", {}), metric),
                use_container_width=True,
            )


_HEALTH_SORT_ORDER = {
    "❌ 消失/逆転": 0,
    "⚠️ 弱化": 1,
    "⚠️ サンプル不足": 2,
    "✅ 健在": 3,
    "ℹ️ 対象外": 4,
    "🚫 却下済み": 5,
}


def _claim_health(claim: dict[str, Any], comparison: ClaimComparison) -> str:
    if str(claim.get("status", "")) == "refuted":
        return "🚫 却下済み"

    direction = str(claim.get("direction", "up"))
    if direction not in {"up", "down"}:
        return "ℹ️ 対象外"

    min_n = int(claim.get("min_n", theory.THEORY_MIN_SAMPLE))
    if comparison.recent_subset_n < min_n:
        return "⚠️ サンプル不足"

    if pd.isna(comparison.recent_value) or pd.isna(comparison.recent_baseline_value):
        return "⚠️ サンプル不足"

    recent_delta = comparison.recent_value - comparison.recent_baseline_value
    expected_sign = 1 if direction == "up" else -1

    if recent_delta * expected_sign <= 0:
        return "❌ 消失/逆転"

    full_delta = comparison.full_value - comparison.full_baseline_value
    if not pd.isna(full_delta) and full_delta != 0 and abs(recent_delta) < abs(full_delta) * 0.5:
        return "⚠️ 弱化"

    return "✅ 健在"


def _render_registry_overview(frame: pd.DataFrame, registry: dict[str, Any]) -> None:
    claims = registry.get("claims", [])
    if not claims:
        st.info("このホールの theory registry には claims がありません。")
        return

    rows = []
    for claim in claims:
        _, comparison = _summarize_claim(frame, claim)
        metric = str(claim.get("metric", "avg_diff"))
        full_delta = comparison.full_value - comparison.full_baseline_value
        recent_delta = comparison.recent_value - comparison.recent_baseline_value
        rows.append(
            {
                "id": claim.get("id", ""),
                "title": claim.get("title", ""),
                "status": claim.get("status", ""),
                "health(直近90日)": _claim_health(claim, comparison),
                "full_delta": _format_metric_value(metric, full_delta) if not pd.isna(full_delta) else "",
                "recent_delta": _format_metric_value(metric, recent_delta) if not pd.isna(recent_delta) else "",
                "recent_n": comparison.recent_subset_n,
                "last_reviewed": claim.get("last_reviewed", ""),
            }
        )

    overview = pd.DataFrame(rows)
    overview["_order"] = overview["health(直近90日)"].map(_HEALTH_SORT_ORDER).fillna(9)
    overview = overview.sort_values(["_order", "title"]).drop(columns=["_order"]).reset_index(drop=True)
    st.caption(
        "health(直近90日) は各クレームの direction に対し、直近90日の delta が同符号かつ全期間比50%以上を"
        "維持しているかで判定。並び順は問題のあるクレームが上に来るようにしています。"
    )
    st.dataframe(overview, use_container_width=True, hide_index=True)


def _render_segment_tab(frame: pd.DataFrame, hall_config: dict[str, Any], min_n: int) -> None:
    st.markdown("### セグメント")
    st.caption("ホールごとの segment scheme に従って、物理区分の差を確認します。")

    segment_summary = theory.summarize_by(frame, ["segment"], min_n=min_n)
    if segment_summary.empty and min_n > 1:
        st.warning(f"現在の最小サンプル={min_n} ではセグメントが出ないため、参考として最小サンプル=1 を表示します。")
        segment_summary = theory.summarize_by(frame, ["segment"], min_n=1)

    if segment_summary.empty:
        st.info("セグメントの集計対象がありませんでした。")
        return

    labels = hall_config.get("segment_scheme", {}).get("labels", {})
    order = hall_config.get("segment_scheme", {}).get("order", [])
    segment_summary["segment"] = segment_summary["segment"].map(labels).fillna(segment_summary["segment"])
    if order:
        label_order = [labels.get(key, key) for key in order]
        segment_summary["_order"] = segment_summary["segment"].map(
            {label: idx for idx, label in enumerate(label_order)}
        )
        segment_summary = segment_summary.sort_values(["_order", "segment"]).drop(columns=["_order"])
    st.dataframe(_format_summary(segment_summary), use_container_width=True, hide_index=True)

    if "hit104_rate" in segment_summary.columns:
        fig = go.Figure(
            data=go.Bar(
                x=segment_summary["segment"],
                y=segment_summary["avg_diff"],
                marker_color="#2f9e44",
                text=segment_summary["n"],
            )
        )
        fig.update_layout(title="セグメント別の平均差玉", xaxis_title="セグメント", yaxis_title="平均差玉")
        st.plotly_chart(fig, use_container_width=True)


def _render_event_tab(frame: pd.DataFrame, min_n: int) -> None:
    st.markdown("### イベント日")
    st.caption("イベント日の全体感と、DD 系統ごとの寄与を確認します。")

    comparison = theory.summarize_by(frame, ["is_event_day"], min_n=min_n)
    if not comparison.empty:
        st.dataframe(_format_summary(comparison), use_container_width=True, hide_index=True)

    kind_summary = theory.build_event_kind_summary(frame, min_n=min_n)
    if kind_summary.empty and min_n > 1:
        st.warning(f"現在の最小サンプル={min_n} では日別の内訳が出ないため、参考として最小サンプル=1 も表示します。")
        kind_summary = theory.build_event_kind_summary(frame, min_n=1)
        daily_summary = theory.build_daily_event_summary(frame, min_n=1)
    else:
        daily_summary = theory.build_daily_event_summary(frame, min_n=min_n)

    if kind_summary.empty:
        st.info("イベント日データが十分に残っていないため、DD 系統別の集計は出ませんでした。")
        return

    st.dataframe(_format_summary(kind_summary), use_container_width=True, hide_index=True)

    bucket_summary = theory.build_event_bucket_summary(frame, min_n=min_n)
    if not bucket_summary.empty:
        st.dataframe(_format_summary(bucket_summary), use_container_width=True, hide_index=True)

    if daily_summary.empty:
        return

    display_daily = daily_summary.loc[
        :,
        [
            "date_label",
            "weekday",
            "event_kind",
            "machine_count",
            "total_diff",
            "avg_diff",
            "avg_games",
            "hit104_rate",
            "diff_share",
        ],
    ].copy()
    st.dataframe(_format_summary(display_daily), use_container_width=True, hide_index=True)


def _render_dd_kakuban_tab(frame: pd.DataFrame, min_n: int) -> None:
    st.markdown("### DD × 位置軸")
    st.caption("DD×端番min、DD×端番max、DD×角番（通路距離）を確認します。")

    metric = st.selectbox(
        "表示指標",
        ["avg_diff", "hit104_rate", "win_rate", "avg_games"],
        format_func=lambda value: METRIC_LABELS[value],
        key="theory_dd_metric",
    )

    axes = [
        ("rank_from_min", "端番min"),
        ("rank_from_max", "端番max"),
    ]
    if "kakuban" in frame.columns and pd.to_numeric(frame["kakuban"], errors="coerce").notna().any():
        axes.append(("kakuban", "角番（通路）"))

    rendered = False
    for axis_column, axis_label in axes:
        if axis_column not in frame.columns:
            continue

        matrix = theory.build_dd_position_matrix(frame, axis_column, metric=metric, min_n=min_n)
        used_min_n = min_n
        if matrix.empty and min_n > 1:
            st.warning(
                f"{axis_label}: 現在の最小サンプル={min_n} ではセルが出ないため、参考として最小サンプル=1 を表示します。"
            )
            matrix = theory.build_dd_position_matrix(frame, axis_column, metric=metric, min_n=1)
            used_min_n = 1

        if matrix.empty:
            continue

        rendered = True
        text = matrix.copy()
        if metric in {"hit104_rate", "win_rate"}:
            text = text.map(lambda value: "" if pd.isna(value) else f"{value * 100:.0f}%")
        else:
            text = text.map(lambda value: "" if pd.isna(value) else f"{value:.0f}")

        fig = go.Figure(
            data=go.Heatmap(
                z=matrix.to_numpy(),
                x=[str(column) for column in matrix.columns],
                y=[int(index) for index in matrix.index],
                text=text.to_numpy(),
                texttemplate="%{text}",
                colorscale="RdYlGn",
                colorbar={"title": metric},
                hovertemplate=f"DD=%{{y}}<br>{axis_label}=%{{x}}<br>値=%{{z}}<extra></extra>",
            )
        )
        fig.update_layout(title=f"DD × {axis_label}: {METRIC_LABELS[metric]}", xaxis_title=axis_label, yaxis_title="DD")
        st.plotly_chart(fig, use_container_width=True)

        summary = theory.summarize_by(frame, ["dd", axis_column], min_n=used_min_n)
        if not summary.empty:
            st.dataframe(_format_summary(summary.head(100)), use_container_width=True, hide_index=True)

    if not rendered:
        st.info("DD × 位置軸のセルがまだ作れませんでした。")


def _render_cooling_tab(frame: pd.DataFrame, hall_config: dict[str, Any], min_n: int) -> None:
    st.markdown("### 冷却帯")
    st.caption("可変冷却帯と構造冷却帯を分けて確認します。")

    if not hall_config.get("cooling_zones"):
        st.info("このホールには cooling zone の定義がありません。")
        return

    cooling_summary = theory.summarize_by(frame, ["cooling_zone"], min_n=min_n)
    if cooling_summary.empty and min_n > 1:
        st.warning(f"現在の最小サンプル={min_n} では冷却帯の内訳が出ないため、参考として最小サンプル=1 を表示します。")
        cooling_summary = theory.summarize_by(frame, ["cooling_zone"], min_n=1)

    if cooling_summary.empty:
        st.info("冷却帯の集計対象がありませんでした。")
        return

    labels = {zone["name"]: zone.get("label", zone["name"]) for zone in hall_config.get("cooling_zones", [])}
    cooling_summary["cooling_zone"] = (
        cooling_summary["cooling_zone"].map(labels).fillna(cooling_summary["cooling_zone"])
    )
    st.dataframe(_format_summary(cooling_summary), use_container_width=True, hide_index=True)

    fig = go.Figure(
        data=go.Bar(
            x=cooling_summary["cooling_zone"],
            y=cooling_summary["avg_diff"],
            marker_color="#228be6",
            text=cooling_summary["n"],
        )
    )
    fig.update_layout(title="冷却帯別の平均差玉", xaxis_title="冷却帯", yaxis_title="平均差玉")
    st.plotly_chart(fig, use_container_width=True)


def _render_warning_tab(hall_config: dict[str, Any]) -> None:
    st.markdown("### 警告")
    warnings = hall_config.get("warnings", [])
    if not warnings:
        st.info("このホールの警告メモはありません。")
        return
    st.dataframe(pd.DataFrame(warnings), use_container_width=True, hide_index=True)


def _render_claims(frame: pd.DataFrame, hall_config: dict[str, Any], registry: dict[str, Any]) -> None:
    claims = registry.get("claims", [])
    if not claims:
        st.info("このホールの theory registry には claims がありません。")
        return

    for claim in claims:
        _render_claim_block(frame, hall_config, claim)


def render() -> None:
    hall_key = _resolve_hall_key()
    hall_config = theory.load_hall_config(hall_key)
    registry = theory.load_theory_registry(hall_key)
    db_path = st.session_state.get("db_path")
    date_range = st.session_state.get("date_range")
    min_games = int(st.session_state.get("min_games", 1000))

    display_name = hall_config.get("display_name", hall_key)
    st.markdown(f"## {display_name} Theory Verification")
    st.caption("Claim-driven verification for the current hall, with raw-axis tabs kept as a secondary view.")

    with st.expander("用語集", expanded=False):
        st.markdown(
            """- **角番 (kakuban)**: メイン通路からの距離でカウントする位置番号（`rank_from_aisle`）。通路が定義されたホール（蒲田7）でのみ有効。角番1=通路直近、数字が大きいほど通路から遠い。
- **端番 (hanaban)**: 列（島）の両端からの距離でカウントする位置番号。1台は min 側・max 側の2つの端番を持つ（`rank_from_min` / `rank_from_max`）。クレーム別内訳では両端の近い方に折りたたんだ値（`min(rank_from_min, rank_from_max)`、値1〜11）を使い、探索用の DD ヒートマップでは min と max を折りたたまず別々に表示する。
- **台特定シグナル**: 効果が「末尾」や「角番/端番」という一般ルールではなく、少数の特定物理台（台番号）に集中している場合の判定。上位2台を除外して再検定し、有意性が消える場合にこの判定となる。
- **可変冷却帯 / 構造冷却帯**: 全期間平均が低い「冷却ゾーン」の分類。判定基準はDD7（イベント日）での104%率リフト。可変冷却=リフト≧5pp（イベント日に通常水準まで回復、非イベント日のみ回避すればよい）。構造冷却=リフト<2pp（イベント日でも回復しない、常時回避）。
- **「最強」「最優先」「構造的に強い」などの表現について**: これらは全て「そのセグメントで対象の軸が統計的に有意（p<0.001程度）かつ耐久性検証（split-half等）を通過した」ことを指す定性的な表現であり、強さの序列を表すものではない。具体的な数値は各クレームの本文・チャートを参照すること。"""
        )

    if not db_path:
        st.warning("サイドバーでホール DB を選択してください。")
        return

    frame = _load_theory_frame_cached(str(db_path))
    if frame.empty:
        st.info("理論検証に使える台履歴または layout がありませんでした。")
        return

    start_date = end_date = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range

    min_n = st.slider("セルごとの最小サンプル数", min_value=1, max_value=30, value=theory.THEORY_MIN_SAMPLE, step=1)
    filtered = theory.filter_theory_frame(frame, start_date=start_date, end_date=end_date, min_games=min_games)
    event_frame = theory.filter_theory_frame(frame, start_date=start_date, end_date=end_date, min_games=0)
    if filtered.empty:
        st.info("現在の期間フィルタと min_games フィルタを通すと、対象行が残りませんでした。")
        return

    st.caption(
        f"Rows: {len(filtered):,} | Dates: {filtered['date_dt'].min():%Y-%m-%d} to {filtered['date_dt'].max():%Y-%m-%d} | "
        f"min_games: {min_games} | claims: {len(registry.get('claims', []))}"
    )

    st.markdown("### Claims")
    _render_registry_overview(filtered, registry)
    _render_claims(filtered, hall_config, registry)

    tabs = st.tabs(["segment", "event", "dd-kakuban", "cooling", "warnings"])
    with tabs[0]:
        _render_segment_tab(filtered, hall_config, min_n)
    with tabs[1]:
        _render_event_tab(event_frame, min_n)
    with tabs[2]:
        _render_dd_kakuban_tab(filtered, min_n)
    with tabs[3]:
        _render_cooling_tab(filtered, hall_config, min_n)
    with tabs[4]:
        _render_warning_tab(hall_config)


if __name__ == "__main__":
    render()
