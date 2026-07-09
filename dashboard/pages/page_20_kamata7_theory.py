"""蒲田7 セオリー検証ページ."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.utils import kamata7_theory as theory


SEGMENT_DISPLAY_ORDER = ["2F_L_N", "2F_R_N", "3F_L_A", "3F_L_N", "3F_R_A", "3F_R_N", "対象外"]
SEGMENT_DISPLAY_LABELS = theory.SEGMENT_LABELS
COOLING_DISPLAY_LABELS = theory.COOLING_ZONE_LABELS


def _available_columns(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in frame.columns]


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


def _with_display_segment_labels(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "segment" not in frame.columns:
        return frame
    work = frame.copy()
    work["segment"] = work["segment"].map(SEGMENT_DISPLAY_LABELS).fillna(work["segment"])
    order = {label: index for index, label in enumerate(SEGMENT_DISPLAY_ORDER)}
    work["_order"] = work["segment"].map(order).fillna(len(order) + 1)
    work = work.sort_values(["_order", "segment"]).drop(columns=["_order"])
    return work


def _with_display_cooling_labels(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "cooling_zone" not in frame.columns:
        return frame
    work = frame.copy()
    work["cooling_zone"] = work["cooling_zone"].map(COOLING_DISPLAY_LABELS).fillna(work["cooling_zone"])
    order = {label: index for index, label in enumerate(COOLING_DISPLAY_LABELS.values())}
    work["_order"] = work["cooling_zone"].map(order).fillna(len(order) + 1)
    work = work.sort_values(["_order", "cooling_zone"]).drop(columns=["_order"])
    return work


def _render_page_intro() -> None:
    st.markdown("## 蒲田7 セオリー検証")
    st.caption("蒲田7 理論の各切り口を、実データでそのまま確認するための検証ページです。")


def _render_coverage_tab() -> None:
    st.markdown("### 何をこのページで見られるか")
    st.caption("このページは、まず安全に出せる理論の切り口だけを並べています。未実装のものは後回しです。")
    st.dataframe(pd.DataFrame(theory.theory_coverage_rows()), use_container_width=True, hide_index=True)
    st.info("表示済みの切り口は、物理セグメント / イベント日 / DD×角番 / 冷却帯 / 反証メモです。")


def _render_event_tab(frame: pd.DataFrame, min_n: int) -> None:
    st.markdown("### イベント日チェック")
    st.caption("イベント日全体の強さを見るだけでなく、どの DD 系統が寄与しているかを分けて確認します。")

    comparison = theory.summarize_by(frame, ["is_event_day"], min_n=min_n)
    if not comparison.empty:
        st.markdown("#### イベント日 vs 通常日")
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

    st.markdown("#### DD 系統ごとの寄与")
    st.dataframe(_format_summary(kind_summary), use_container_width=True, hide_index=True)

    bucket_summary = theory.build_event_bucket_summary(frame, min_n=min_n)
    if not bucket_summary.empty:
        st.markdown("#### 1/7/ゾロ目/強ゾロ目/月末/30日 の寄与")
        st.caption("バケットは重複あり。たとえば 11日 は『1のつく日』と『ゾロ目の日』の両方に含まれます。")
        st.dataframe(_format_summary(bucket_summary), use_container_width=True, hide_index=True)

    chart = kind_summary.copy()
    chart["total_diff"] = pd.to_numeric(chart["total_diff"], errors="coerce")
    chart["diff_share_pct"] = pd.to_numeric(chart["diff_share"], errors="coerce") * 100.0
    fig = px.bar(
        chart,
        x="event_kind",
        y="total_diff",
        color="diff_share_pct",
        text="days",
        labels={
            "event_kind": "DD 系統",
            "total_diff": "合計差玉",
            "diff_share_pct": "全イベント日内の寄与率(%)",
        },
        title="DD 系統ごとの合計差玉",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 日別の寄与")
    if daily_summary.empty:
        st.info("日別の寄与を出せるサンプルがありません。")
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


def _render_segment_tab(frame: pd.DataFrame, min_n: int) -> None:
    st.markdown("### 6 物理セグメント")
    st.caption("2F は左右のみ、3F は左右×A/N の 4 区分で見ます。対象外は layout 未取得や分類不能の台です。")

    segment_summary = theory.summarize_by(frame, ["segment"], min_n=min_n)
    if segment_summary.empty and min_n > 1:
        st.warning(f"現在の最小サンプル={min_n} ではセグメントが出ないため、参考として最小サンプル=1 を表示します。")
        segment_summary = theory.summarize_by(frame, ["segment"], min_n=1)

    if segment_summary.empty:
        st.info("セグメントの集計対象がありませんでした。")
        return

    segment_summary = _with_display_segment_labels(segment_summary)
    st.dataframe(_format_summary(segment_summary), use_container_width=True, hide_index=True)

    plot_frame = segment_summary.loc[
        segment_summary["segment"].isin([SEGMENT_DISPLAY_LABELS[key] for key in theory.KAMATA7_SEGMENT_ORDER])
    ].copy()
    if plot_frame.empty:
        plot_frame = segment_summary.copy()

    fig = px.bar(
        plot_frame,
        x="segment",
        y="avg_diff",
        color="hit104_rate",
        text="n",
        category_orders={"segment": [SEGMENT_DISPLAY_LABELS[key] for key in theory.KAMATA7_SEGMENT_ORDER] + ["対象外"]},
        labels={"segment": "セグメント", "avg_diff": "平均差玉", "hit104_rate": "104%率"},
        title="セグメント別の平均差玉",
    )
    st.plotly_chart(fig, use_container_width=True)

    outside_count = int(frame["segment"].eq("対象外").sum()) if "segment" in frame.columns else 0
    if outside_count:
        st.caption(f"対象外に落ちた行は {outside_count:,} 件あります。layout 未取得や 3F の A/N 判定不能が原因です。")


def _render_dd_kakuban_tab(frame: pd.DataFrame, min_n: int) -> None:
    st.markdown("### DD × 角番")
    st.caption(
        "縦軸が DD、横軸がセクション内の角番です。最小サンプル数が高すぎると何も出ないので、必要なら参考表示に落とします。"
    )

    metric = st.selectbox(
        "表示指標",
        ["avg_diff", "hit104_rate", "win_rate", "avg_games"],
        format_func=lambda value: {
            "avg_diff": "平均差玉",
            "hit104_rate": "104%率",
            "win_rate": "勝率",
            "avg_games": "平均ゲーム数",
        }[value],
        key="kamata7_theory_dd_metric",
    )

    matrix = theory.build_dd_kakuban_matrix(frame, metric=metric, min_n=min_n)
    used_min_n = min_n
    if matrix.empty and min_n > 1:
        st.warning(f"現在の最小サンプル={min_n} ではセルが出ないため、参考として最小サンプル=1 を表示します。")
        matrix = theory.build_dd_kakuban_matrix(frame, metric=metric, min_n=1)
        used_min_n = 1

    if matrix.empty:
        st.info("DD × 角番のセルがまだ作れませんでした。")
        return

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
            hovertemplate="DD=%{y}<br>角番=%{x}<br>値=%{z}<extra></extra>",
        )
    )
    fig.update_layout(title=f"DD × 角番: {metric}", xaxis_title="角番", yaxis_title="DD")
    st.plotly_chart(fig, use_container_width=True)

    if "rank_from_min" in frame.columns:
        summary = theory.summarize_by(frame, ["dd", "rank_from_min"], min_n=used_min_n)
    else:
        summary = pd.DataFrame()
    if not summary.empty:
        st.dataframe(_format_summary(summary.head(100)), use_container_width=True, hide_index=True)
    else:
        st.info("rank_from_min 縺後≠繧翫∪縺帙ｓ縺ｧ縺励◆。DD × 角番の表は layout 付与済みのホールでのみ表示します。")


def _render_cooling_tab(frame: pd.DataFrame, min_n: int) -> None:
    st.markdown("### 冷却帯")
    st.caption("可変冷却帯はイベント日だけ回復する候補、構造冷却帯は原則回避候補です。対象外は範囲外の台です。")

    cooling_summary = theory.summarize_by(frame, ["cooling_zone"], min_n=min_n)
    if cooling_summary.empty and min_n > 1:
        st.warning(f"現在の最小サンプル={min_n} では冷却帯の内訳が出ないため、参考として最小サンプル=1 を表示します。")
        cooling_summary = theory.summarize_by(frame, ["cooling_zone"], min_n=1)

    if cooling_summary.empty:
        st.info("冷却帯の集計対象がありませんでした。")
        return

    cooling_summary = _with_display_cooling_labels(cooling_summary)
    st.dataframe(_format_summary(cooling_summary), use_container_width=True, hide_index=True)

    fig = px.bar(
        cooling_summary,
        x="cooling_zone",
        y="avg_diff",
        color="hit104_rate",
        text="n",
        labels={"cooling_zone": "冷却帯", "avg_diff": "平均差玉", "hit104_rate": "104%率"},
        title="冷却帯別の平均差玉",
    )
    st.plotly_chart(fig, use_container_width=True)

    detail_rows = []
    for zone_name in ["variable", "structural"]:
        detail_columns = _available_columns(frame, ["machine_number", "segment", "rank_from_min", "section"])
        if not detail_columns:
            continue
        subset = frame.loc[frame["cooling_zone"].eq(zone_name), detail_columns]
        if subset.empty:
            continue
        for _, row in subset.drop_duplicates("machine_number").sort_values("machine_number").iterrows():
            detail_rows.append({"冷却帯": COOLING_DISPLAY_LABELS[zone_name], **row.to_dict()})

    if detail_rows:
        detail = pd.DataFrame(detail_rows)
        detail["segment"] = detail["segment"].map(SEGMENT_DISPLAY_LABELS).fillna(detail["segment"])
        st.markdown("#### 冷却帯の対象台")
        st.dataframe(detail, use_container_width=True, hide_index=True)
    else:
        st.info("可変冷却帯 / 構造冷却帯に入る台は、現在の条件ではありませんでした。")


def _render_warning_tab() -> None:
    st.markdown("### 反証メモ")
    st.caption("ここは理論を強く見せる欄ではなく、誤読しやすい論点を先に明示する欄です。")
    st.dataframe(pd.DataFrame(theory.refutation_warnings()), use_container_width=True, hide_index=True)


def render() -> None:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")
    date_range = st.session_state.get("date_range")
    min_games = int(st.session_state.get("min_games", 1000))

    _render_page_intro()

    if not db_path:
        st.warning("サイドバーでホール DB を選択してください。")
        return

    if hall_name and "7" not in str(hall_name):
        st.warning("このページは蒲田7 用です。正しい DB を選ぶと解釈が安定します。")

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
        f"min_games: {min_games}"
    )

    tabs = st.tabs(["概要", "イベント日", "物理セグメント", "DD×角番", "冷却帯", "反証メモ"])
    with tabs[0]:
        _render_coverage_tab()
    with tabs[1]:
        _render_event_tab(event_frame, min_n)
    with tabs[2]:
        _render_segment_tab(filtered, min_n)
    with tabs[3]:
        _render_dd_kakuban_tab(filtered, min_n)
    with tabs[4]:
        _render_cooling_tab(filtered, min_n)
    with tabs[5]:
        _render_warning_tab()


if __name__ == "__main__":
    render()
