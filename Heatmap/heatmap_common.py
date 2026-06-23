"""
Shared Streamlit renderers for pachinko floor plans.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from html import escape

import pandas as pd
import streamlit as st

try:
    from Heatmap.coordinate_utils import get_display_columns
except ModuleNotFoundError:
    from coordinate_utils import get_display_columns

try:
    from Heatmap.generate_kamata7_cardmap_html import (
        DIGIT_CATEGORY_COLORS,
        METRICS,
        build_html_document,
        build_machine_stats,
        build_tone_thresholds,
        format_filter_label,
        sanitize_filename,
        render_floor_section,
        render_last_digit_floor_section,
    )
except ModuleNotFoundError:
    from generate_kamata7_cardmap_html import (
        DIGIT_CATEGORY_COLORS,
        METRICS,
        build_html_document,
        build_machine_stats,
        build_tone_thresholds,
        format_filter_label,
        sanitize_filename,
        render_floor_section,
        render_last_digit_floor_section,
    )


WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")
WEEKDAY_TO_INDEX = {label: index for index, label in enumerate(WEEKDAY_LABELS)}

# ホールごとのカード型フロアマップのレイアウト設定。
# slot_x/slot_y/pad はカード1枚分のピッチ(px)、fit_mode/min_scale は
# build_html_document に渡す表示モード。exclude_machine_numbers は
# カードマップから除外する台番号（例: 蒲田1の5円スロット島）。
HALL_CARD_CONFIG: dict[str, dict[str, object]] = {
    "マルハンメガシティ2000-蒲田7": {
        "slot_x": 40,
        "slot_y": 28,
        "pad": 10,
        "fit_mode": "contain",
        "min_scale": 0.6,
        "exclude_machine_numbers": (),
    },
    "マルハンメガシティ2000-蒲田1": {
        "slot_x": 40,
        "slot_y": 30,
        "pad": 8,
        "fit_mode": "scroll",
        "min_scale": 0.65,
        # 2331-2340 は5円スロット島のため、カード型フロアマップでは除外する。
        "exclude_machine_numbers": tuple(range(2331, 2341)),
    },
}

_DEFAULT_CARD_CONFIG: dict[str, object] = {
    "slot_x": 40,
    "slot_y": 28,
    "pad": 10,
    "fit_mode": "contain",
    "min_scale": 0.6,
    "exclude_machine_numbers": (),
}

# ヒートマップタブの「表示指標」選択肢 -> generate_kamata7_cardmap_html.METRICS のキー
HEATMAP_METRIC_OPTIONS: dict[str, str] = {
    "平均差枚": "avg_diff",
    "勝率(%)": "win_rate",
    "平均機械割(%)": "avg_kaiwari",
    "機械割104%以上率(%)": "hit104_rate",
}


def _get_card_config(hall_name: str | None) -> dict[str, object]:
    return HALL_CARD_CONFIG.get(hall_name or "", _DEFAULT_CARD_CONFIG)


def _build_export_filename(
    *,
    hall_name: str | None,
    floor: str | None,
    kind: str,
    descriptor: str,
    date_start_key: str,
    date_end_key: str,
) -> str:
    hall_part = sanitize_filename(hall_name or "hall")
    floor_part = sanitize_filename(floor or "-")
    descriptor_part = sanitize_filename(descriptor)
    parts = [hall_part, floor_part, kind]
    if descriptor_part and descriptor_part != kind:
        parts.append(descriptor_part)
    parts.append(f"{date_start_key}-{date_end_key}")
    return "_".join(parts) + ".png"


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


def _normalize_weekday_selection(values: list[int | str] | None) -> list[int]:
    if not values:
        return []

    normalized: list[int] = []
    for value in values:
        if value is None or pd.isna(value):
            continue
        candidate: int | None = None
        if isinstance(value, int) and not isinstance(value, bool):
            candidate = int(value)
        else:
            text = str(value).strip()
            if text in WEEKDAY_TO_INDEX:
                candidate = WEEKDAY_TO_INDEX[text]
            elif text.isdigit():
                candidate = int(text)
        if candidate is None or not 0 <= candidate <= 6:
            raise ValueError(f"Unsupported weekday selection: {value}")
        normalized.append(candidate)
    return sorted(set(normalized))


def _normalize_day_of_month_selection(values: list[int | str] | None) -> list[int]:
    if not values:
        return []

    normalized: list[int] = []
    for value in values:
        if value is None or pd.isna(value):
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            candidate = int(value)
        else:
            text = str(value).strip()
            if not text.isdigit():
                raise ValueError(f"Unsupported day-of-month selection: {value}")
            candidate = int(text)
        if not 1 <= candidate <= 31:
            raise ValueError(f"Unsupported day-of-month selection: {value}")
        normalized.append(candidate)
    return sorted(set(normalized))


def _apply_calendar_filters(
    frame: pd.DataFrame,
    *,
    weekdays: list[int] | list[str] | None = None,
    day_of_months: list[int] | list[str] | None = None,
) -> pd.DataFrame:
    filtered = frame.copy()
    filtered["date"] = pd.to_datetime(filtered["date"])

    normalized_weekdays = _normalize_weekday_selection(weekdays)
    if normalized_weekdays:
        filtered = filtered[filtered["date"].dt.weekday.isin(normalized_weekdays)]

    normalized_days = _normalize_day_of_month_selection(day_of_months)
    if normalized_days:
        filtered = filtered[filtered["date"].dt.day.isin(normalized_days)]

    return filtered.reset_index(drop=True)


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
    weekdays: list[int] | list[str] | None = None,
    day_of_months: list[int] | list[str] | None = None,
) -> None:
    """Render a floor-plan heatmap as a card-map HTML document."""

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
        metric_label_jp = st.radio(
            "表示指標",
            list(HEATMAP_METRIC_OPTIONS.keys()),
            key=metric_key,
            horizontal=False,
        )
    metric = HEATMAP_METRIC_OPTIONS[metric_label_jp]

    start_date, end_date = validated_range

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

    card_config = _get_card_config(hall_name)
    exclude_numbers = card_config["exclude_machine_numbers"]
    if exclude_numbers:
        coords_df = coords_df[
            ~coords_df["machine_number"].isin(exclude_numbers)
        ].reset_index(drop=True)

    date_start_key = start_date.strftime("%Y%m%d")
    date_end_key = end_date.strftime("%Y%m%d")

    try:
        with sqlite3.connect(db_path) as conn:
            raw = pd.read_sql_query(
                "SELECT date, machine_number, machine_name, diff_coins_normalized, games_normalized "
                "FROM machine_detailed_results WHERE date >= ? AND date <= ? ORDER BY date",
                conn,
                params=(date_start_key, date_end_key),
            )
    except Exception as exc:
        st.error(f"DB load error: {exc}")
        st.stop()

    if raw.empty:
        st.warning("選択期間にデータがありません")
        st.stop()

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d")
    raw = _apply_calendar_filters(
        raw,
        weekdays=weekdays,
        day_of_months=day_of_months,
    )
    if raw.empty:
        st.warning("選択した曜日・日付に該当するデータがありません")
        st.stop()

    stats_df = build_machine_stats(raw)
    frame = coords_df.merge(stats_df, on="machine_number", how="left")

    filter_label = format_filter_label(
        weekdays=weekdays,
        day_of_months=day_of_months,
    )
    st.caption(f"追加フィルタ: {filter_label}")

    thresholds = build_tone_thresholds(frame[metric].dropna())
    export_filename = _build_export_filename(
        hall_name=hall_name or title,
        floor=floor,
        kind="heatmap",
        descriptor=metric,
        date_start_key=date_start_key,
        date_end_key=date_end_key,
    )

    section_html = render_floor_section(
        frame,
        floor_label=floor if floor is not None else "-",
        floor_title=title,
        metric_key=metric,
        thresholds=thresholds,
        filter_label=filter_label,
        slot_x=card_config["slot_x"],
        slot_y=card_config["slot_y"],
        pad=card_config["pad"],
        export_filename=export_filename,
    )

    html = build_html_document(
        floor_sections=[
            {
                "floor": floor if floor is not None else "-",
                "title": title,
                "html": section_html,
            }
        ],
        hall_name=hall_name,
        generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        date_range_label=f"{start_date:%Y-%m-%d} 〜 {end_date:%Y-%m-%d}",
        filter_label=filter_label,
        metric_key=metric,
        metric_label=METRICS[metric].label,
        fit_mode=card_config["fit_mode"],
        min_scale=card_config["min_scale"],
    )

    from streamlit.components.v1 import html as components_html

    components_html(html, height=1800, scrolling=True)


def render_last_digit_highlight(
    *,
    title: str,
    coords_file: str,
    db_path: str,
    hall_name: str | None = None,
    floor: str | None = None,
    date_range: tuple[date, date],
    widget_key_suffix: str,
    weekdays: list[int] | list[str] | None = None,
    day_of_months: list[int] | list[str] | None = None,
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

    filter_label = format_filter_label(
        weekdays=weekdays,
        day_of_months=day_of_months,
    )
    st.caption(
        f"期間: {start_date.strftime('%Y-%m-%d')} 〜 {end_date.strftime('%Y-%m-%d')}"
    )
    st.caption(f"追加フィルタ: {filter_label}")

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

    card_config = _get_card_config(hall_name)
    exclude_numbers = card_config["exclude_machine_numbers"]
    if exclude_numbers:
        coords_df = coords_df[
            ~coords_df["machine_number"].isin(exclude_numbers)
        ].reset_index(drop=True)

    date_start_key = start_date.strftime("%Y%m%d")
    date_end_key = end_date.strftime("%Y%m%d")

    try:
        with sqlite3.connect(db_path) as conn:
            table_info = pd.read_sql_query(
                "PRAGMA table_info(machine_detailed_results)",
                conn,
            )
            has_is_zorome = "is_zorome" in table_info["name"].tolist()

            query_columns = [
                "date",
                "machine_number",
                "machine_name",
                "diff_coins_normalized",
                "games_normalized",
            ]
            if has_is_zorome:
                query_columns.append("is_zorome")

            raw_query = (
                "SELECT "
                + ", ".join(query_columns)
                + " FROM machine_detailed_results WHERE date >= ? AND date <= ? ORDER BY date"
            )
            raw = pd.read_sql_query(raw_query, conn, params=(date_start_key, date_end_key))
    except Exception as exc:
        st.error(f"DB load error: {exc}")
        st.stop()

    if raw.empty:
        st.warning("選択期間にデータがありません")
        st.stop()

    raw["date"] = pd.to_datetime(raw["date"], format="%Y%m%d")
    raw = _apply_calendar_filters(
        raw,
        weekdays=weekdays,
        day_of_months=day_of_months,
    )
    if raw.empty:
        st.warning("選択した曜日・日付に該当するデータがありません")
        st.stop()

    stats_df = build_machine_stats(raw)
    if has_is_zorome and "is_zorome" in raw.columns:
        zorome_df = (
            raw.groupby("machine_number")
            .agg(is_zorome=("is_zorome", "max"))
            .reset_index()
        )
        stats_df = stats_df.merge(zorome_df, on="machine_number", how="left")

    heatmap_df = coords_df.merge(stats_df, on="machine_number", how="left")
    x_axis_col, y_axis_col = get_display_columns(heatmap_df.columns)

    def _is_zorome(row: pd.Series) -> bool:
        if "is_zorome" in row and not pd.isna(row["is_zorome"]):
            return int(row["is_zorome"]) == 1
        machine_number = int(row["machine_number"])
        last_two_digits = machine_number % 100
        return last_two_digits // 10 == last_two_digits % 10

    heatmap_df["category"] = heatmap_df.apply(
        lambda row: "ゾロ目" if _is_zorome(row) else str(int(row["machine_number"]) % 10),
        axis=1,
    )
    heatmap_df["section"] = floor if floor is not None else "-"
    heatmap_df.attrs["date_range_label"] = f"{start_date:%Y-%m-%d} 〜 {end_date:%Y-%m-%d}"
    export_filename = _build_export_filename(
        hall_name=hall_name or title,
        floor=floor,
        kind="digit_highlight",
        descriptor="digit_highlight",
        date_start_key=date_start_key,
        date_end_key=date_end_key,
    )

    selected_categories = set(
        st.multiselect(
            "ハイライトする末尾を選択",
            options=list(DIGIT_CATEGORY_COLORS.keys()),
            default=[],
            key=f"digit_select_{widget_key_suffix}",
        )
    )

    section_html = render_last_digit_floor_section(
        heatmap_df,
        floor_label=floor if floor is not None else "-",
        floor_title=title,
        filter_label=filter_label,
        selected_categories=selected_categories,
        slot_x=card_config["slot_x"],
        slot_y=card_config["slot_y"],
        pad=card_config["pad"],
        export_filename=export_filename,
    )

    hero_badges_html = "".join(
        f'<span class="badge{" high" if category in selected_categories else ""}"><span class="swatch" style="background: {color};"></span>{escape(category)}</span>'
        for category, color in DIGIT_CATEGORY_COLORS.items()
    )
    html = build_html_document(
        floor_sections=[
            {
                "floor": floor if floor is not None else "-",
                "title": title,
                "html": section_html,
            }
        ],
        hall_name=hall_name,
        generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        date_range_label=f"{start_date:%Y-%m-%d} 〜 {end_date:%Y-%m-%d}",
        filter_label=filter_label,
        metric_key="avg_diff",
        metric_label="末尾ハイライト",
        hero_title=f"{hall_name or 'ホール'} 末尾ハイライト",
        hero_eyebrow="Last Digit Prototype",
        hero_copy=(
            "末尾とゾロ目のカードハイライトを、ヒートマップと同じカードデザインで表示します。"
            "色は末尾カテゴリ、枠線は平均G数です。"
        ),
        hero_badges_html=hero_badges_html,
        footer_note=(
            "このHTMLは試作です。末尾カテゴリの選択、カード配色、枠線判例が視認しやすいか確認してください。"
        ),
        fit_mode=card_config["fit_mode"],
        min_scale=card_config["min_scale"],
    )

    from streamlit.components.v1 import html as components_html

    components_html(html, height=1800, scrolling=True)
