"""Kamata7 theory dashboard helpers."""

from __future__ import annotations

import calendar
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from dashboard.utils.daily_report import add_hit104_flag


KAMATA7_EVENT_DIGITS = frozenset({1, 7, 11, 17, 21, 22, 27, 30, 31})
KAMATA7_SEGMENT_ORDER = ["2F_L_N", "2F_R_N", "3F_L_A", "3F_L_N", "3F_R_A", "3F_R_N"]
THEORY_MIN_SAMPLE = 5

COOLING_ZONES_VARIABLE = ((3061, 3070), (3081, 3090))
COOLING_ZONES_STRUCTURAL = ((3131, 3140),)

SEGMENT_LABELS = {
    "2F_L_N": "2F 左 N",
    "2F_R_N": "2F 右 N",
    "3F_L_A": "3F 左 A",
    "3F_L_N": "3F 左 N",
    "3F_R_A": "3F 右 A",
    "3F_R_N": "3F 右 N",
    "対象外": "対象外",
    "不明": "不明",
}

COOLING_ZONE_LABELS = {
    "variable": "可変冷却帯",
    "structural": "構造冷却帯",
    "outside": "対象外",
    "unknown": "不明",
}

THEORY_COVERAGE_ROWS = [
    {"優先度": "P1", "論点": "6つの物理セグメント", "状態": "表示済み", "ダッシュボード": "物理セグメント"},
    {"優先度": "P2", "論点": "イベント日チェック", "状態": "表示済み", "ダッシュボード": "イベント日"},
    {"優先度": "P3", "論点": "DD×角番マトリクス", "状態": "表示済み", "ダッシュボード": "DD×角番"},
    {"優先度": "P4", "論点": "冷却帯", "状態": "表示済み", "ダッシュボード": "冷却帯"},
    {"優先度": "P5", "論点": "反証警告パネル", "状態": "表示済み", "ダッシュボード": "反証メモ"},
    {"優先度": "保留", "論点": "GATED / NOGATE", "状態": "後回し", "ダッシュボード": "別設計が必要"},
    {"優先度": "保留", "論点": "debut / regime", "状態": "後回し", "ダッシュボード": "別設計が必要"},
    {"優先度": "保留", "論点": "機種別 DD の広域表示", "状態": "後回し", "ダッシュボード": "ホワイトリスト化後"},
]


def _coerce_machine_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def infer_floor(machine_number: object) -> str:
    """Infer the floor label from a machine number."""

    value = pd.to_numeric(pd.Series([machine_number]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "不明"
    number = int(value)
    if 2000 <= number < 3000:
        return "2F"
    if 3000 <= number < 4000:
        return "3F"
    return "不明"


def infer_lr(layout: pd.DataFrame) -> pd.Series:
    """Infer L/R inside each section using the section median X coordinate."""

    out = pd.Series("不明", index=layout.index, dtype="string")
    if layout.empty or "section" not in layout.columns:
        return out

    x_column = "x" if "x" in layout.columns else "X" if "X" in layout.columns else None
    if x_column is None:
        return out

    x = pd.to_numeric(layout[x_column], errors="coerce")
    section_nunique = x.groupby(layout["section"]).transform("nunique")
    section_median_x = x.groupby(layout["section"]).transform("median")
    floor_median_x = x.median()
    valid = x.notna() & section_median_x.notna()
    vertical = valid & (section_nunique == 1)
    normal = valid & ~vertical
    out.loc[normal & (x <= section_median_x)] = "L"
    out.loc[normal & (x > section_median_x)] = "R"
    out.loc[vertical & (x <= floor_median_x)] = "L"
    out.loc[vertical & (x > floor_median_x)] = "R"
    return out


def classify_setting_family(machine_name: object) -> str:
    """Classify the machine family used by the 3F A/N split."""

    text = "" if machine_name is None else str(machine_name)
    a_keywords = (
        "ジャグラー",
        "アイム",
        "マイジャグ",
        "ファンキー",
        "ゴーゴー",
        "ハッピー",
        "ハナハナ",
        "沖ドキ",
        "チバリヨ",
        "ニューパル",
        "ディスクアップ",
        "クランキー",
        "バーサス",
        "アレックス",
        "エヴァ",
        "マタドール",
        "ウルトラミラクル",
        "ピンクパンサー",
        "トリプルクラウン",
    )
    return "A" if _contains_any(text, a_keywords) else "N"


def classify_theory_segment(floor: object, lr: object, family: object) -> str:
    """Return one of the six Kamata7 theory segments or an outside bucket."""

    floor_text = "" if floor is None else str(floor)
    lr_text = "" if lr is None else str(lr)
    family_text = "" if family is None else str(family)

    if floor_text == "2F" and lr_text in {"L", "R"}:
        return f"2F_{lr_text}_N"
    if floor_text == "3F" and lr_text in {"L", "R"} and family_text in {"A", "N"}:
        return f"3F_{lr_text}_{family_text}"
    return "対象外"


def prepare_layout_segments(layout: pd.DataFrame) -> pd.DataFrame:
    """Attach floor, L/R, and section size fields needed by theory summaries."""

    if layout.empty or "machine_number" not in layout.columns:
        return pd.DataFrame()

    work = layout.copy()
    work["machine_number"] = _coerce_machine_number(work["machine_number"])
    work = work.dropna(subset=["machine_number"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["floor"] = work["machine_number"].map(infer_floor)
    work["lr"] = infer_lr(work)

    if {"section_min", "section_max"}.issubset(work.columns):
        section_min = pd.to_numeric(work["section_min"], errors="coerce")
        section_max = pd.to_numeric(work["section_max"], errors="coerce")
        work["section_size"] = (section_max - section_min + 1).astype("Int64")
    elif "section" in work.columns:
        work["section_size"] = work.groupby("section")["machine_number"].transform("nunique").astype("Int64")
    else:
        work["section_size"] = pd.NA
    return work


def attach_theory_axes(machine_frame: pd.DataFrame, layout_frame: pd.DataFrame) -> pd.DataFrame:
    """Join machine rows to the theory axes used by the dashboard."""

    if machine_frame.empty:
        return pd.DataFrame()

    work = machine_frame.copy()
    work["machine_number"] = _coerce_machine_number(work["machine_number"])
    work = work.dropna(subset=["machine_number"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["dd"] = work["date_dt"].dt.day.astype("Int64")

    machine_name = work["machine_name"] if "machine_name" in work.columns else pd.Series("", index=work.index)
    work["family"] = machine_name.map(classify_setting_family)

    layout = prepare_layout_segments(layout_frame)
    if not layout.empty:
        keep_columns = [
            column
            for column in [
                "machine_number",
                "floor",
                "lr",
                "section",
                "section_min",
                "section_max",
                "section_size",
                "rank_from_min",
                "rank_from_max",
            ]
            if column in layout.columns
        ]
        work = work.merge(layout.loc[:, keep_columns], on="machine_number", how="left", validate="m:1")
    else:
        work["floor"] = work["machine_number"].map(infer_floor)
        work["lr"] = "不明"

    work["segment"] = work.apply(
        lambda row: classify_theory_segment(row.get("floor"), row.get("lr"), row.get("family")),
        axis=1,
    )
    work["is_event_day"] = is_event_day_series(work["date_dt"])
    work["cooling_zone"] = work["machine_number"].map(classify_cooling_zone)
    return add_hit104_flag(work)


def is_event_day_series(dates: pd.Series) -> pd.Series:
    """Return the Kamata7 event-day flag used by the dashboard."""

    parsed = pd.to_datetime(dates, errors="coerce")
    dd = parsed.dt.day
    month_end = parsed.map(lambda value: calendar.monthrange(value.year, value.month)[1] if pd.notna(value) else np.nan)
    is_mmdd_zorome = parsed.dt.month.eq(parsed.dt.day)
    return (dd.isin(KAMATA7_EVENT_DIGITS) | dd.eq(month_end) | is_mmdd_zorome).fillna(False)


def build_event_bucket_summary(frame: pd.DataFrame, *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Summarize daily event rows into overlapping calendar buckets."""

    daily = build_daily_event_summary(frame, min_n=min_n)
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "event_bucket",
                "days",
                "machine_count",
                "total_diff",
                "avg_diff",
                "avg_hit104_rate",
                "diff_share",
            ]
        )

    work = daily.copy()
    work["date_dt"] = pd.to_datetime(work["date_dt"], errors="coerce")
    work = work.dropna(subset=["date_dt"]).copy()
    if work.empty:
        return pd.DataFrame(
            columns=[
                "event_bucket",
                "days",
                "machine_count",
                "total_diff",
                "avg_diff",
                "avg_hit104_rate",
                "diff_share",
            ]
        )

    dd = work["date_dt"].dt.day
    month_end = work["date_dt"].map(
        lambda value: calendar.monthrange(value.year, value.month)[1] if pd.notna(value) else np.nan
    )
    bucket_specs = [
        ("1のつく日", dd.isin({1, 11, 21, 31})),
        ("7のつく日", dd.isin({7, 17, 27})),
        ("ゾロ目の日", dd.isin({11, 22})),
        ("強ゾロ目の日", work["date_dt"].dt.month.eq(dd)),
        ("月末", dd.eq(month_end)),
        ("30日", dd.eq(30)),
    ]

    rows: list[dict[str, object]] = []
    for bucket_name, mask in bucket_specs:
        subset = work.loc[mask].copy()
        if subset.empty:
            continue

        total_diff = float(subset["total_diff"].sum()) if pd.notna(subset["total_diff"]).any() else 0.0
        machine_count = pd.to_numeric(subset["machine_count"], errors="coerce").fillna(0)
        hit104_rate = pd.to_numeric(subset["hit104_rate"], errors="coerce")
        weight_total = float(machine_count.sum())
        hit104_weighted = float((hit104_rate.fillna(0) * machine_count).sum())
        rows.append(
            {
                "event_bucket": bucket_name,
                "days": int(subset["date_dt"].nunique()),
                "machine_count": int(weight_total),
                "total_diff": total_diff,
                "avg_diff": float(total_diff / weight_total) if weight_total else np.nan,
                "avg_hit104_rate": float(hit104_weighted / weight_total) if weight_total else np.nan,
                "diff_share": total_diff,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "event_bucket",
                "days",
                "machine_count",
                "total_diff",
                "avg_diff",
                "avg_hit104_rate",
                "diff_share",
            ]
        )

    summary = pd.DataFrame(rows)
    total_diff_all = float(summary["total_diff"].sum()) if pd.notna(summary["total_diff"]).any() else 0.0
    summary["diff_share"] = summary["total_diff"] / total_diff_all if total_diff_all else np.nan
    return summary.sort_values(["total_diff", "days"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )


def load_theory_frame(db_path: str | Path) -> pd.DataFrame:
    """Load machine history and attach Kamata7 theory axes."""

    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()

    try:
        with sqlite3.connect(str(path)) as con:
            machines = pd.read_sql_query("SELECT * FROM machine_detailed_results", con)
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
            layout = (
                pd.read_sql_query("SELECT * FROM machine_layout", con) if "machine_layout" in tables else pd.DataFrame()
            )
    except sqlite3.Error:
        return pd.DataFrame()
    return attach_theory_axes(machines, layout)


def filter_theory_frame(
    frame: pd.DataFrame,
    *,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
    min_games: int = 0,
) -> pd.DataFrame:
    """Apply the shared dashboard filters before aggregation."""

    if frame.empty:
        return frame

    work = frame.copy()
    if start_date is not None:
        work = work.loc[work["date_dt"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        work = work.loc[work["date_dt"] <= pd.Timestamp(end_date)]
    if min_games > 0 and "games_normalized" in work.columns:
        games = pd.to_numeric(work["games_normalized"], errors="coerce")
        work = work.loc[games >= int(min_games)]
    return work.reset_index(drop=True)


def summarize_by(frame: pd.DataFrame, group_columns: list[str], *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Build the common performance summary for one or more theory axes."""

    if frame.empty or any(column not in frame.columns for column in group_columns):
        return pd.DataFrame()

    work = frame.copy()
    for column in group_columns:
        work[column] = work[column].fillna("不明")

    grouped = (
        work.groupby(group_columns, dropna=False)
        .agg(
            n=("machine_number", "size"),
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            win_rate=("diff_coins_normalized", lambda s: float(pd.to_numeric(s, errors="coerce").gt(0).mean())),
            hit104_rate=(
                "hit104",
                lambda s: float(pd.to_numeric(s, errors="coerce").dropna().mean()) if s.notna().any() else np.nan,
            ),
        )
        .reset_index()
    )
    grouped = grouped.loc[grouped["n"] >= int(min_n)].copy()
    if grouped.empty:
        return grouped
    return grouped.sort_values(
        ["hit104_rate", "avg_diff", "n"], ascending=[False, False, False], kind="mergesort"
    ).reset_index(drop=True)


def build_dd_kakuban_matrix(
    frame: pd.DataFrame, *, metric: str = "avg_diff", min_n: int = THEORY_MIN_SAMPLE
) -> pd.DataFrame:
    """Return a DD x rank_from_min matrix for the requested metric."""

    summary = summarize_by(frame, ["dd", "rank_from_min"], min_n=min_n)
    if summary.empty or metric not in summary.columns:
        return pd.DataFrame()
    return summary.pivot(index="dd", columns="rank_from_min", values=metric).sort_index().sort_index(axis=1)


def classify_event_kind(date_value: object) -> str:
    """Classify a date into a DD/event-family label."""

    parsed = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(parsed):
        return "不明"

    dd = int(parsed.day)
    if dd in KAMATA7_EVENT_DIGITS:
        return f"DD{dd}"

    month_end = calendar.monthrange(parsed.year, parsed.month)[1]
    if dd == month_end:
        return "月末"

    if parsed.month == parsed.day:
        return f"{parsed.month:02d}/{parsed.day:02d}ゾロ"

    return "その他"


def build_daily_event_summary(frame: pd.DataFrame, *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Summarize event days by date and event kind."""

    required = {"date_dt", "is_event_day", "machine_number", "diff_coins_normalized", "games_normalized"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()

    work = frame.loc[frame["is_event_day"].eq(True)].copy()
    if work.empty:
        return pd.DataFrame()

    work["event_kind"] = work["date_dt"].map(classify_event_kind)
    daily = (
        work.groupby(["date_dt", "event_kind"], dropna=False)
        .agg(
            machine_count=("machine_number", "size"),
            total_diff=("diff_coins_normalized", "sum"),
            avg_diff=("diff_coins_normalized", "mean"),
            avg_games=("games_normalized", "mean"),
            hit104_rate=(
                "hit104",
                lambda s: float(pd.to_numeric(s, errors="coerce").dropna().mean()) if s.notna().any() else np.nan,
            ),
        )
        .reset_index()
    )
    daily = daily.loc[daily["machine_count"] >= int(min_n)].copy()
    if daily.empty:
        return daily

    total_diff_all = float(daily["total_diff"].sum()) if pd.notna(daily["total_diff"]).any() else 0.0
    daily["diff_share"] = daily["total_diff"] / total_diff_all if total_diff_all else np.nan
    daily["weekday"] = pd.to_datetime(daily["date_dt"], errors="coerce").dt.day_name()
    daily["date_label"] = pd.to_datetime(daily["date_dt"], errors="coerce").dt.strftime("%Y-%m-%d")
    return daily.sort_values(["total_diff", "date_dt"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )


def build_event_kind_summary(frame: pd.DataFrame, *, min_n: int = THEORY_MIN_SAMPLE) -> pd.DataFrame:
    """Summarize event days by event kind."""

    daily = build_daily_event_summary(frame, min_n=min_n)
    if daily.empty:
        return daily

    work = daily.copy()
    work["hit104_weighted"] = pd.to_numeric(work["hit104_rate"], errors="coerce").fillna(0) * pd.to_numeric(
        work["machine_count"], errors="coerce"
    ).fillna(0)
    summary = (
        work.groupby("event_kind", dropna=False)
        .agg(
            days=("date_dt", "nunique"),
            machine_count=("machine_count", "sum"),
            total_diff=("total_diff", "sum"),
            hit104_weighted=("hit104_weighted", "sum"),
        )
        .reset_index()
    )
    summary["avg_diff"] = summary["total_diff"] / summary["machine_count"]
    summary["avg_hit104_rate"] = summary["hit104_weighted"] / summary["machine_count"]
    summary = summary.drop(columns=["hit104_weighted"])
    total_diff_all = float(summary["total_diff"].sum()) if pd.notna(summary["total_diff"]).any() else 0.0
    summary["diff_share"] = summary["total_diff"] / total_diff_all if total_diff_all else np.nan
    return summary.sort_values(["total_diff", "days"], ascending=[False, False], kind="mergesort").reset_index(
        drop=True
    )


def classify_cooling_zone(machine_number: object) -> str:
    """Classify known 3F cooling-zone ranges."""

    value = pd.to_numeric(pd.Series([machine_number]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    number = int(value)
    for start, end in COOLING_ZONES_VARIABLE:
        if start <= number <= end:
            return "variable"
    for start, end in COOLING_ZONES_STRUCTURAL:
        if start <= number <= end:
            return "structural"
    return "outside"


def refutation_warnings() -> list[dict[str, str]]:
    """Return guardrail warnings from the current Kamata7 theory review."""

    return [
        {
            "論点": "L/R を機械番号の偶奇で決めない",
            "注意": "左右判定はセクション内の X 座標で決める。機械番号の並びだけでは左右が逆転する。",
        },
        {
            "論点": "DD×角番の細かいセルは少数サンプルに弱い",
            "注意": "サンプルが薄いセルはすぐにブレる。ヒートマップは必ず n と一緒に読む。",
        },
        {
            "論点": "104% は主指標ではなく補助指標",
            "注意": "hit104 は閾値判定であり、差玉の大きさや分散を代替しない。",
        },
        {
            "論点": "GATED / NOGATE は表示補助に留める",
            "注意": "このページでは日付ゲートの説明に使うが、結論そのものにはしない。",
        },
        {
            "論点": "機種別 DD の広域表示はノイズが大きい",
            "注意": "ホワイトリストや対象機種の固定がない広域表示は誤読しやすい。",
        },
        {
            "論点": "サンプル 5 未満は参考値",
            "注意": "少数セルを強い結論として扱わない。必要なら閾値を下げた参考表示を併記する。",
        },
    ]


def theory_coverage_rows() -> list[dict[str, str]]:
    """Return the coverage checklist displayed by the theory hub."""

    return THEORY_COVERAGE_ROWS.copy()
