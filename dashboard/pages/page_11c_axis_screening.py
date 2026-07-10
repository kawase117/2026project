from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

from dashboard.design_system import premium_divider, section_title
from dashboard.utils import theory_engine as theory
from eda import machine_axis_pattern_scan as analysis


SCREENING_AXES = ["dd_bin", "day_of_week"]


def _resolve_hall_key() -> str:
    hall_name = st.session_state.get("hall_name")
    db_path = st.session_state.get("db_path")
    return theory.resolve_hall_key(hall_name=hall_name, db_path=db_path)


@st.cache_data(ttl=1800)
def _load_theory_frame_cached(db_path: str) -> pd.DataFrame:
    return theory.load_theory_frame(db_path)


def _screening_cache_key(
    hall_key: str,
    db_path: str,
    *,
    min_games: int,
    min_machine_days_total: int,
    min_obs_for_ranking: int,
    top_n: int,
    effect_threshold: float,
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None,
) -> str:
    date_part = "none"
    if date_range is not None:
        date_part = f"{date_range[0]:%Y%m%d}-{date_range[1]:%Y%m%d}"
    return (
        f"{hall_key}|{db_path}|{date_part}|g{min_games}|m{min_machine_days_total}|"
        f"o{min_obs_for_ranking}|t{top_n}|e{effect_threshold:.3f}"
    )


def _build_raw_like_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    required = [
        "date",
        "machine_name",
        "machine_number",
        "diff_coins_normalized",
        "games_normalized",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise KeyError(f"missing columns: {missing}")

    work = frame.loc[:, required].copy()
    work = work.rename(columns={"diff_coins_normalized": "diff", "games_normalized": "games"})
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["dd"] = work["date_dt"].dt.day.astype("Int64")
    work["day_of_week"] = work["date_dt"].dt.weekday.map(
        lambda idx: analysis.WEEKDAY_ORDER[int(idx)] if pd.notna(idx) else np.nan
    )
    if "is_event_day" in frame.columns:
        work["is_x_day"] = frame["is_event_day"].fillna(False).astype(bool).astype(int)
    else:
        work["is_x_day"] = 0
    return work.reset_index(drop=True)


def _add_screen_axes(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    work = frame.copy()
    work["diff"] = pd.to_numeric(work["diff"], errors="coerce")
    work["games"] = pd.to_numeric(work["games"], errors="coerce")
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["dd"] = work["date_dt"].dt.day.astype("Int64")
    work["day_of_week"] = work["date_dt"].dt.weekday.map(
        lambda idx: analysis.WEEKDAY_ORDER[int(idx)] if pd.notna(idx) else np.nan
    )
    work["dd_bin"] = analysis._compute_dd_bin(work["dd"])
    work["plus"] = work["diff"].gt(0).astype(int)
    denom = work["games"] * 3
    work["payout_rate"] = np.where(denom.gt(0), ((denom + work["diff"]) / denom) * 100.0, np.nan)
    work["hit104"] = (work["payout_rate"] >= 104.0).astype(int)
    if "is_event_day" in work.columns:
        work["is_x_day"] = work["is_event_day"].fillna(False).astype(bool).astype(int)
    else:
        work["is_x_day"] = 0
    return work


def _filter_screening_frame(
    frame: pd.DataFrame,
    *,
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp | None,
    min_games: int,
) -> pd.DataFrame:
    filtered = theory.filter_theory_frame(frame, start_date=start_date, end_date=end_date, min_games=min_games)
    return filtered.reset_index(drop=True)


def _rank_screening_results(
    pattern_summary: pd.DataFrame,
    *,
    effect_threshold: float,
) -> pd.DataFrame:
    if pattern_summary.empty:
        return pd.DataFrame()

    ranked = pattern_summary.loc[
        pattern_summary["axis"].isin(SCREENING_AXES)
        & pattern_summary["effect_size"].notna()
        & (pattern_summary["effect_size"] >= float(effect_threshold))
    ].copy()
    if ranked.empty:
        return ranked

    ranked["sparse_warning"] = ranked["note"].astype(str).str.contains("warning", case=False, na=False) | (
        pd.to_numeric(ranked["n_sparse_levels"], errors="coerce").fillna(0) > 0
    )
    ranked = ranked.sort_values(
        ["effect_size", "n_obs", "machine_name", "axis", "outcome"],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return ranked.loc[
        :,
        [
            "machine_name",
            "axis",
            "outcome",
            "n_obs",
            "effect_size",
            "p_value",
            "sparse_warning",
            "note",
        ],
    ]


def _window_bounds(
    max_date: pd.Timestamp,
) -> tuple[tuple[pd.Timestamp, pd.Timestamp], tuple[pd.Timestamp, pd.Timestamp]]:
    recent_start = max_date - pd.Timedelta(days=89)
    previous_end = recent_start - pd.Timedelta(days=1)
    previous_start = previous_end - pd.Timedelta(days=89)
    return (recent_start, max_date), (previous_start, previous_end)


def _window_machine_rows(
    frame: pd.DataFrame,
    *,
    hall_key: str,
    machine_name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    work = frame.loc[
        frame["date_dt"].between(start, end) & frame["machine_name"].astype(str).eq(str(machine_name))
    ].copy()
    if work.empty:
        return pd.DataFrame(columns=analysis.PATTERN_SUMMARY_COLUMNS)

    extra_columns = [column for column in ["is_event_day"] if column in work.columns]
    if {"diff", "games"}.issubset(work.columns):
        screen_raw = work.loc[:, ["date", "machine_name", "machine_number", "diff", "games", *extra_columns]].copy()
    else:
        screen_raw = (
            work.loc[
                :,
                ["date", "machine_name", "machine_number", "diff_coins_normalized", "games_normalized", *extra_columns],
            ]
            .rename(columns={"diff_coins_normalized": "diff", "games_normalized": "games"})
            .copy()
        )
    prepared = analysis._prepare_frame(screen_raw, shindai_exclude_days=analysis.DEFAULT_SHINDAI_EXCLUDE_DAYS)
    prepared = analysis._apply_currently_installed_filter(
        prepared,
        grace_days=analysis.DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
    )
    machine_frame = _add_screen_axes(prepared)

    rows: list[dict[str, Any]] = []
    rows.extend(
        analysis._machine_axis_outcome_rows(
            hall_key,
            str(machine_name),
            machine_frame,
            min_cell_n=analysis.MIN_CELL_N,
        )
    )
    out = pd.DataFrame(rows, columns=analysis.PATTERN_SUMMARY_COLUMNS)
    if out.empty:
        return out
    return out.loc[out["axis"].isin(SCREENING_AXES)].reset_index(drop=True)


def _build_reproducibility_table(
    frame: pd.DataFrame,
    ranked: pd.DataFrame,
    *,
    hall_key: str,
    top_n: int,
    effect_threshold: float,
) -> pd.DataFrame:
    if frame.empty or ranked.empty:
        return pd.DataFrame()

    max_date = pd.to_datetime(frame["date_dt"], errors="coerce").max()
    if pd.isna(max_date):
        return pd.DataFrame()

    recent_window, previous_window = _window_bounds(pd.Timestamp(max_date))
    top_rows = ranked.head(int(top_n)).copy()

    rows: list[dict[str, Any]] = []
    for _, row in top_rows.iterrows():
        machine_name = str(row["machine_name"])
        axis = str(row["axis"])
        outcome = str(row["outcome"])

        recent_rows = _window_machine_rows(
            frame,
            hall_key=hall_key,
            machine_name=machine_name,
            start=recent_window[0],
            end=recent_window[1],
        )
        previous_rows = _window_machine_rows(
            frame,
            hall_key=hall_key,
            machine_name=machine_name,
            start=previous_window[0],
            end=previous_window[1],
        )

        recent_match = recent_rows.loc[(recent_rows["axis"].eq(axis)) & (recent_rows["outcome"].eq(outcome))]
        previous_match = previous_rows.loc[(previous_rows["axis"].eq(axis)) & (previous_rows["outcome"].eq(outcome))]

        recent_effect = float(recent_match["effect_size"].iloc[0]) if not recent_match.empty else np.nan
        recent_p = float(recent_match["p_value"].iloc[0]) if not recent_match.empty else np.nan
        previous_effect = float(previous_match["effect_size"].iloc[0]) if not previous_match.empty else np.nan
        previous_p = float(previous_match["p_value"].iloc[0]) if not previous_match.empty else np.nan

        rows.append(
            {
                "machine_name": machine_name,
                "axis": axis,
                "outcome": outcome,
                "recent_90_effect_size": recent_effect,
                "recent_90_p_value": recent_p,
                "previous_90_effect_size": previous_effect,
                "previous_90_p_value": previous_p,
                "holds_in_both": bool(
                    pd.notna(recent_effect)
                    and pd.notna(previous_effect)
                    and recent_effect >= float(effect_threshold)
                    and previous_effect >= float(effect_threshold)
                ),
            }
        )

    return pd.DataFrame(rows)


def _render_result_table(ranked: pd.DataFrame) -> None:
    if ranked.empty:
        st.info("しきい値を超える有意な結果はありませんでした。")
        return

    display = ranked.copy()
    display["effect_size"] = pd.to_numeric(display["effect_size"], errors="coerce").map(lambda value: f"{value:.3f}")
    display["p_value"] = pd.to_numeric(display["p_value"], errors="coerce").map(
        lambda value: "" if pd.isna(value) else f"{value:.4g}"
    )
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_reproducibility_table(repro: pd.DataFrame) -> None:
    if repro.empty:
        st.info("再現性チェックの対象行が生成されませんでした。")
        return

    display = repro.copy()
    for column in ["recent_90_effect_size", "previous_90_effect_size"]:
        display[column] = pd.to_numeric(display[column], errors="coerce").map(
            lambda value: "" if pd.isna(value) else f"{value:.3f}"
        )
    for column in ["recent_90_p_value", "previous_90_p_value"]:
        display[column] = pd.to_numeric(display[column], errors="coerce").map(
            lambda value: "" if pd.isna(value) else f"{value:.4g}"
        )
    st.dataframe(display, use_container_width=True, hide_index=True)


def _scan_hall(
    frame: pd.DataFrame,
    *,
    hall_key: str,
    min_machine_days_total: int,
    min_obs_for_ranking: int,
    effect_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_like = _build_raw_like_frame(frame)
    pattern_summary, _, _, _ = analysis.build_hall_outputs(
        hall_key,
        raw_like,
        shindai_exclude_days=analysis.DEFAULT_SHINDAI_EXCLUDE_DAYS,
        currently_installed_grace_days=analysis.DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS,
        min_machine_days_total=min_machine_days_total,
        min_obs_for_ranking=min_obs_for_ranking,
        top_n=max(50, min_obs_for_ranking),
    )
    ranked = _rank_screening_results(pattern_summary, effect_threshold=effect_threshold)
    repro = _build_reproducibility_table(
        frame,
        ranked,
        hall_key=hall_key,
        top_n=min(10, len(ranked)),
        effect_threshold=effect_threshold,
    )
    return ranked, repro


def render() -> None:
    hall_key = _resolve_hall_key()
    db_path = st.session_state.get("db_path")
    date_range = st.session_state.get("date_range")
    min_games = int(st.session_state.get("min_games", 1000))

    section_title(
        "横断スクリーニング",
        "全機種を dd_bin と day_of_week 軸でスキャンし、上位結果を直近90日ウィンドウで再確認します。",
    )
    premium_divider()

    if not db_path:
        st.warning("サイドバーでホール DB を選択してください。")
        return

    theory_frame = _load_theory_frame_cached(str(db_path))
    if theory_frame.empty:
        st.info("理論検証に使える台履歴を読み込めませんでした。")
        return

    start_date = end_date = None
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    filtered = _filter_screening_frame(theory_frame, start_date=start_date, end_date=end_date, min_games=min_games)
    if filtered.empty:
        st.info("現在の期間フィルタと min_games フィルタを通すと、対象行が残りませんでした。")
        return

    min_machine_days_total = st.slider(
        "機種あたりの最小稼働日数",
        min_value=1,
        max_value=200,
        value=30,
        step=1,
        key=f"screening_min_machine_days_{hall_key}",
    )
    min_obs_for_ranking = st.slider(
        "ランキング対象の最小サンプル数",
        min_value=1,
        max_value=200,
        value=100,
        step=1,
        key=f"screening_min_obs_{hall_key}",
    )
    top_n = st.slider("上位表示件数", min_value=1, max_value=100, value=20, step=1, key=f"screening_top_n_{hall_key}")
    effect_threshold = st.slider(
        "効果量のしきい値",
        min_value=0.0,
        max_value=0.5,
        value=analysis.EFFECT_SIZE_THRESHOLD,
        step=0.01,
        key=f"screening_effect_threshold_{hall_key}",
    )

    cache_slot = f"axis_screening:{hall_key}:{db_path}"
    current_key = _screening_cache_key(
        hall_key,
        str(db_path),
        min_games=min_games,
        min_machine_days_total=min_machine_days_total,
        min_obs_for_ranking=min_obs_for_ranking,
        top_n=top_n,
        effect_threshold=effect_threshold,
        date_range=(pd.Timestamp(start_date), pd.Timestamp(end_date))
        if start_date is not None and end_date is not None
        else None,
    )

    cached = st.session_state.get(cache_slot)
    results: pd.DataFrame | None = None
    repro: pd.DataFrame | None = None
    if isinstance(cached, dict) and cached.get("cache_key") == current_key:
        results = cached.get("ranked")
        repro = cached.get("repro")

    if st.button("スクリーニングを実行", key=f"screening_run_{hall_key}"):
        with st.spinner("スクリーニング実行中..."):
            results, repro = _scan_hall(
                filtered,
                hall_key=hall_key,
                min_machine_days_total=min_machine_days_total,
                min_obs_for_ranking=min_obs_for_ranking,
                effect_threshold=effect_threshold,
            )
            st.session_state[cache_slot] = {
                "cache_key": current_key,
                "ranked": results,
                "repro": repro,
            }

    if results is None or repro is None:
        st.info("「スクリーニングを実行」を押すと結果が計算されます。")
        return

    st.caption(f"Rows: {len(filtered):,} | スクリーニング対象行数: {len(results):,}")

    st.markdown("### 📋 ランキング結果")
    _render_result_table(results.head(top_n))

    st.markdown("### 📆 直近90日 vs それ以前の再現性")
    _render_reproducibility_table(repro)


if __name__ == "__main__":
    render()
