from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

from eda.core import HALL_DBS, HALL_EVENT_DIGITS, load_hall_df
from Heatmap.coordinate_utils import find_floor_csvs

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_HALLS = ["蒲田7", "蒲田1", "みとや"]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "eda" / "results" / "hall_budget_allocation_light"
DEFAULT_PLAN_OUTPUT_ROOT = PROJECT_ROOT / "eda" / "results" / "hall_budget_allocation_plan"
PLAN_EXCLUDED_DATES = {"蒲田7": {"20250707"}}
DEFAULT_MIN_GAMES = 0
DEFAULT_MIN_CLASS_COUNT = 5
DEFAULT_MODEL_TEST_RATIO = 0.3
DEFAULT_OFFSETS = (1, 7, 14)
BUDGET_Z_LOW = -0.75
BUDGET_Z_HIGH = 0.75
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
WEEKDAY_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DD_BUCKETS = [(1, 7, "1-7"), (8, 14, "8-14"), (15, 21, "15-21"), (22, 28, "22-28"), (29, 31, "29-31")]

SOURCE_COLUMNS = [
    "hall",
    "date",
    "date_dt",
    "machine_number",
    "machine_name",
    "diff",
    "games",
    "plus",
    "dd",
    "month",
    "year_month",
    "day_of_week",
    "weekday_nth",
    "is_weekend",
    "is_x_day",
    "dd_bucket",
]

DAILY_COLUMNS = [
    "hall",
    "date",
    "date_dt",
    "dd",
    "month",
    "year_month",
    "day_of_week",
    "weekday_nth",
    "is_weekend",
    "is_x_day",
    "dd_bucket",
    "n_machine_days",
    "n_machines",
    "total_games",
    "total_diff",
    "avg_diff_per_machine",
    "avg_games_per_machine",
    "plus_rate",
    "budget_index",
    "budget_zscore",
    "budget_regime",
]

ALLOCATION_COLUMNS = [
    "hall",
    "axis",
    "axis_level",
    "n_days",
    "budget_index_sum",
    "budget_index_mean",
    "budget_abs_sum",
    "budget_abs_share",
    "under_budget_days",
    "balanced_days",
    "over_budget_days",
    "dominant_regime",
]

OFFSET_COLUMNS = [
    "hall",
    "offset_days",
    "date",
    "other_date",
    "budget_index",
    "other_budget_index",
    "delta_budget_index",
    "same_regime",
]

MODEL_COLUMNS = [
    "hall",
    "model_name",
    "n_rows",
    "train_rows",
    "test_rows",
    "positive_rows",
    "negative_rows",
    "positive_rate",
    "baseline_accuracy",
    "accuracy",
    "accuracy_delta",
    "balanced_accuracy",
    "roc_auc",
    "top_feature_1",
    "top_feature_2",
    "top_feature_3",
    "note",
]

SUMMARY_COLUMNS = [
    "hall",
    "n_source_rows",
    "n_days",
    "mean_budget_index",
    "median_budget_index",
    "under_budget_days",
    "balanced_days",
    "over_budget_days",
    "top_axis",
    "top_axis_level",
    "top_axis_budget_abs_share",
    "n_offset_pairs",
    "best_offset_days",
    "best_offset_same_regime_rate",
    "best_offset_expected_same_regime_rate",
    "best_offset_same_regime_uplift",
    "model_baseline_accuracy",
    "model_accuracy",
    "model_accuracy_delta",
    "model_roc_auc",
    "model_status",
    "model_metric",
    "note",
]

PLAN_AXES = ("machine_category", "machine_name", "floor", "atype", "section", "kakuban_bin", "dd", "event_type")
PLAN_SUMMARY_COLUMNS = [
    "hall",
    "n_source_rows",
    "n_days",
    "all_high_days",
    "focused_machine_days",
    "focused_category_days",
    "balanced_days",
    "recovery_days",
    "decoy_heavy_days",
    "top_axis",
    "top_axis_level",
    "top_axis_share_of_total_diff",
    "n_offset_pairs",
    "best_offset_days",
    "best_offset_gap",
    "note",
]


def _ensure_output_root(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def _parse_halls(value: str) -> list[str]:
    halls = [item.strip() for item in value.split(",") if item.strip()]
    if not halls:
        raise argparse.ArgumentTypeError("halls must not be empty")
    return halls


def _rename_input_columns(frame: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    if "games_normalized" in frame.columns and "games" not in frame.columns:
        rename_map["games_normalized"] = "games"
    if "diff_coins_normalized" in frame.columns and "diff" not in frame.columns:
        rename_map["diff_coins_normalized"] = "diff"
    if rename_map:
        frame = frame.rename(columns=rename_map)
    return frame


def _to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _dd_bucket(dd: object) -> object:
    if pd.isna(dd):
        return np.nan
    dd_int = int(dd)
    for lo, hi, label in DD_BUCKETS:
        if lo <= dd_int <= hi:
            return label
    return np.nan


def classify_budget_regime(budget_zscore: float, *, low: float = BUDGET_Z_LOW, high: float = BUDGET_Z_HIGH) -> str:
    if pd.isna(budget_zscore):
        return "unknown"
    if budget_zscore <= low:
        return "under_budget"
    if budget_zscore >= high:
        return "over_budget"
    return "balanced"


def prepare_source_frame(
    raw: pd.DataFrame, *, hall: str | None = None, min_games: int = DEFAULT_MIN_GAMES
) -> pd.DataFrame:
    frame = _rename_input_columns(raw).copy()
    required = {"date", "machine_number", "machine_name", "diff", "games"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"source frame missing required columns: {sorted(missing)}")

    frame["date_dt"] = _to_datetime(frame["date"])
    frame = frame.loc[frame["date_dt"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    frame["date_dt"] = pd.to_datetime(frame["date_dt"])
    frame["date"] = frame["date_dt"].dt.strftime("%Y%m%d")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["diff"] = pd.to_numeric(frame["diff"], errors="coerce")
    frame["games"] = pd.to_numeric(frame["games"], errors="coerce")
    frame = frame.loc[frame["machine_number"].notna() & frame["diff"].notna() & frame["games"].notna()].copy()
    if min_games > 0:
        frame = frame.loc[frame["games"] >= min_games].copy()
    if frame.empty:
        return pd.DataFrame(columns=SOURCE_COLUMNS)

    frame["machine_number"] = frame["machine_number"].astype(int)
    weekday = frame["date_dt"].dt.weekday
    frame["hall"] = hall if hall is not None else frame.get("hall", "hall")
    frame["plus"] = (frame["diff"] > 0).astype(int)
    frame["dd"] = frame["date_dt"].dt.day.astype(int)
    frame["month"] = frame["date_dt"].dt.month.astype(int)
    frame["year_month"] = frame["date_dt"].dt.strftime("%Y%m")
    frame["day_of_week"] = weekday.map(lambda idx: WEEKDAY_JP[int(idx)])
    frame["weekday_nth"] = frame["date_dt"].map(lambda dt: f"{WEEKDAY_EN[dt.weekday()]}{((dt.day - 1) // 7) + 1}")
    frame["is_weekend"] = (weekday >= 5).astype(int)
    event_days = set(HALL_EVENT_DIGITS.get(str(hall), [])) if hall is not None else set()
    frame["is_x_day"] = frame["dd"].isin(event_days).astype(int)
    frame["dd_bucket"] = frame["dd"].map(_dd_bucket)

    return frame.loc[:, [col for col in SOURCE_COLUMNS if col in frame.columns]].reset_index(drop=True)


def build_daily_budget_index(source_frame: pd.DataFrame) -> pd.DataFrame:
    if source_frame.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    frame = source_frame.copy()
    if "hall" not in frame.columns:
        frame["hall"] = "hall"
    if "date_dt" not in frame.columns:
        frame["date_dt"] = _to_datetime(frame["date"])
    if "dd" not in frame.columns:
        frame["dd"] = frame["date_dt"].dt.day.astype(int)
    if "month" not in frame.columns:
        frame["month"] = frame["date_dt"].dt.month.astype(int)
    if "year_month" not in frame.columns:
        frame["year_month"] = frame["date_dt"].dt.strftime("%Y%m")
    if "day_of_week" not in frame.columns:
        frame["day_of_week"] = frame["date_dt"].dt.weekday.map(lambda idx: WEEKDAY_JP[int(idx)])
    if "weekday_nth" not in frame.columns:
        frame["weekday_nth"] = frame["date_dt"].map(lambda dt: f"{WEEKDAY_EN[dt.weekday()]}{((dt.day - 1) // 7) + 1}")
    if "is_weekend" not in frame.columns:
        frame["is_weekend"] = frame["date_dt"].dt.weekday.ge(5).astype(int)
    if "dd_bucket" not in frame.columns:
        frame["dd_bucket"] = frame["dd"].map(_dd_bucket)
    if "is_x_day" not in frame.columns:
        frame["is_x_day"] = 0

    grouped = (
        frame.groupby(["hall", "date", "date_dt"], as_index=False, sort=True)
        .agg(
            dd=("dd", "first"),
            month=("month", "first"),
            year_month=("year_month", "first"),
            day_of_week=("day_of_week", "first"),
            weekday_nth=("weekday_nth", "first"),
            is_weekend=("is_weekend", "first"),
            is_x_day=("is_x_day", "first"),
            dd_bucket=("dd_bucket", "first"),
            n_machine_days=("machine_number", "size"),
            n_machines=("machine_number", "nunique"),
            total_games=("games", "sum"),
            total_diff=("diff", "sum"),
            avg_diff_per_machine=("diff", "mean"),
            avg_games_per_machine=("games", "mean"),
            plus_rate=("plus", "mean"),
        )
        .sort_values(["hall", "date_dt"], kind="mergesort")
        .reset_index(drop=True)
    )
    total_games = grouped["total_games"].replace(0, np.nan)
    grouped["budget_index"] = (grouped["total_diff"] / total_games) * 100.0
    hall_mean = grouped.groupby("hall")["budget_index"].transform("mean")
    hall_std = grouped.groupby("hall")["budget_index"].transform(lambda s: s.std(ddof=0)).replace(0, np.nan)
    grouped["budget_zscore"] = ((grouped["budget_index"] - hall_mean) / hall_std).fillna(0.0)
    grouped["budget_regime"] = grouped["budget_zscore"].map(classify_budget_regime)
    return grouped.loc[:, DAILY_COLUMNS].reset_index(drop=True)


def build_allocation_by_axis(
    daily_frame: pd.DataFrame, *, axes: Iterable[str] = ("day_of_week", "dd_bucket", "is_x_day", "dd")
) -> pd.DataFrame:
    if daily_frame.empty:
        return pd.DataFrame(columns=ALLOCATION_COLUMNS)

    frame = daily_frame.copy()
    if "hall" not in frame.columns:
        frame["hall"] = "hall"

    rows: list[dict[str, object]] = []
    for axis in axes:
        if axis not in frame.columns:
            continue
        for hall, hall_frame in frame.groupby("hall", sort=True):
            axis_totals = hall_frame.groupby(axis, sort=True)
            abs_total = float(pd.to_numeric(hall_frame["budget_index"], errors="coerce").abs().sum())
            for axis_level, axis_frame in axis_totals:
                budget_index = pd.to_numeric(axis_frame["budget_index"], errors="coerce")
                abs_sum = float(budget_index.abs().sum())
                denom = abs_total if abs_total != 0 else np.nan
                regimes = axis_frame["budget_regime"].astype(str)
                rows.append(
                    {
                        "hall": hall,
                        "axis": axis,
                        "axis_level": axis_level,
                        "n_days": int(len(axis_frame)),
                        "budget_index_sum": float(budget_index.sum()),
                        "budget_index_mean": float(budget_index.mean()),
                        "budget_abs_sum": abs_sum,
                        "budget_abs_share": float(abs_sum / denom) if pd.notna(denom) else np.nan,
                        "under_budget_days": int((regimes == "under_budget").sum()),
                        "balanced_days": int((regimes == "balanced").sum()),
                        "over_budget_days": int((regimes == "over_budget").sum()),
                        "dominant_regime": regimes.mode().iat[0] if not regimes.mode().empty else "unknown",
                    }
                )

    allocation = pd.DataFrame(rows, columns=ALLOCATION_COLUMNS)
    if allocation.empty:
        return allocation
    allocation["axis_level"] = allocation["axis_level"].astype(object)
    return allocation.sort_values(
        ["hall", "axis", "budget_abs_share", "axis_level"], ascending=[True, True, False, True], kind="mergesort"
    ).reset_index(drop=True)


def build_offset_pairs(daily_frame: pd.DataFrame, *, offsets: Iterable[int] = DEFAULT_OFFSETS) -> pd.DataFrame:
    if daily_frame.empty:
        return pd.DataFrame(columns=OFFSET_COLUMNS)

    frame = daily_frame.copy()
    if "hall" not in frame.columns:
        frame["hall"] = "hall"
    frame["date_dt"] = pd.to_datetime(frame["date_dt"], errors="coerce")
    frame = frame.loc[frame["date_dt"].notna()].copy()
    if frame.empty:
        return pd.DataFrame(columns=OFFSET_COLUMNS)

    rows: list[dict[str, object]] = []
    base = frame.loc[:, ["hall", "date_dt", "budget_index", "budget_regime"]].copy()
    for offset_days in offsets:
        offset = pd.Timedelta(days=int(offset_days))
        for hall, hall_frame in base.groupby("hall", sort=True):
            earlier = hall_frame.copy()
            later = hall_frame.rename(
                columns={
                    "date_dt": "other_date_dt",
                    "budget_index": "other_budget_index",
                    "budget_regime": "other_budget_regime",
                }
            ).copy()
            later["date_dt"] = later["other_date_dt"] - offset
            pair = earlier.merge(later, on=["hall", "date_dt"], how="inner")
            if pair.empty:
                continue
            for row in pair.itertuples(index=False):
                rows.append(
                    {
                        "hall": hall,
                        "offset_days": int(offset_days),
                        "date": row.date_dt,
                        "other_date": row.other_date_dt,
                        "budget_index": float(row.budget_index),
                        "other_budget_index": float(row.other_budget_index),
                        "delta_budget_index": float(row.other_budget_index - row.budget_index),
                        "same_regime": bool(row.budget_regime == row.other_budget_regime),
                    }
                )

    offset_pairs = pd.DataFrame(rows, columns=OFFSET_COLUMNS)
    if offset_pairs.empty:
        return offset_pairs
    offset_pairs["date"] = pd.to_datetime(offset_pairs["date"], errors="coerce")
    offset_pairs["other_date"] = pd.to_datetime(offset_pairs["other_date"], errors="coerce")
    return offset_pairs.sort_values(["hall", "offset_days", "date"], kind="mergesort").reset_index(drop=True)


def evaluate_lightweight_model(
    daily_frame: pd.DataFrame,
    *,
    min_class_count: int = DEFAULT_MIN_CLASS_COUNT,
    test_ratio: float = DEFAULT_MODEL_TEST_RATIO,
) -> pd.DataFrame:
    if daily_frame.empty:
        return pd.DataFrame([_model_skip_row("", "no daily rows")], columns=MODEL_COLUMNS)

    frame = daily_frame.copy()
    if "hall" not in frame.columns:
        frame["hall"] = "hall"
    frame = frame.sort_values(["hall", "date_dt"], kind="mergesort").reset_index(drop=True)
    frame["target"] = (frame["budget_regime"] == "over_budget").astype(int)

    rows: list[dict[str, object]] = []
    for hall, hall_frame in frame.groupby("hall", sort=True):
        hall_frame = hall_frame.reset_index(drop=True)
        positive_rows = int(hall_frame["target"].sum())
        negative_rows = int(len(hall_frame) - positive_rows)
        if positive_rows < min_class_count or negative_rows < min_class_count:
            rows.append(_model_skip_row(hall, f"skipped: class balance insufficient ({positive_rows}/{negative_rows})"))
            continue

        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
        except Exception:
            rows.append(_model_skip_row(hall, "skipped: sklearn unavailable"))
            continue

        feature_frame = hall_frame.loc[
            :, ["dd", "month", "day_of_week", "dd_bucket", "weekday_nth", "is_weekend", "is_x_day"]
        ].copy()
        feature_frame = pd.get_dummies(
            feature_frame, columns=["day_of_week", "dd_bucket", "weekday_nth"], dummy_na=False
        )

        split_idx = int(round(len(hall_frame) * (1 - test_ratio)))
        split_idx = min(max(split_idx, 1), len(hall_frame) - 1)
        train_index = hall_frame.index[:split_idx]
        test_index = hall_frame.index[split_idx:]
        train_y = hall_frame.loc[train_index, "target"]
        test_y = hall_frame.loc[test_index, "target"]
        if train_y.nunique() < 2 or test_y.nunique() < 2:
            rows.append(_model_skip_row(hall, "skipped: split class balance insufficient"))
            continue

        train_x = feature_frame.loc[train_index]
        test_x = feature_frame.loc[test_index].reindex(columns=train_x.columns, fill_value=0)

        model = LogisticRegression(max_iter=1000, class_weight="balanced", solver="liblinear")
        model.fit(train_x, train_y)
        proba = model.predict_proba(test_x)[:, 1]
        pred = (proba >= 0.5).astype(int)

        top_features = _rank_top_features(model, train_x.columns)
        try:
            auc = float(roc_auc_score(test_y, proba))
        except Exception:
            auc = np.nan
        rows.append(
            {
                "hall": hall,
                "model_name": "logistic_regression",
                "n_rows": int(len(hall_frame)),
                "train_rows": int(len(train_index)),
                "test_rows": int(len(test_index)),
                "positive_rows": positive_rows,
                "negative_rows": negative_rows,
                "positive_rate": float(positive_rows / len(hall_frame)),
                "baseline_accuracy": float(max(test_y.mean(), 1 - test_y.mean())),
                "accuracy": float(accuracy_score(test_y, pred)),
                "accuracy_delta": float(accuracy_score(test_y, pred) - max(test_y.mean(), 1 - test_y.mean())),
                "balanced_accuracy": float(balanced_accuracy_score(test_y, pred)),
                "roc_auc": auc,
                "top_feature_1": top_features[0] if len(top_features) > 0 else "",
                "top_feature_2": top_features[1] if len(top_features) > 1 else "",
                "top_feature_3": top_features[2] if len(top_features) > 2 else "",
                "note": "trained",
            }
        )

    return pd.DataFrame(rows, columns=MODEL_COLUMNS)


def _model_skip_row(hall: str, note: str) -> dict[str, object]:
    return {
        "hall": hall,
        "model_name": "logistic_regression",
        "n_rows": 0,
        "train_rows": 0,
        "test_rows": 0,
        "positive_rows": 0,
        "negative_rows": 0,
        "positive_rate": np.nan,
        "baseline_accuracy": np.nan,
        "accuracy": np.nan,
        "accuracy_delta": np.nan,
        "balanced_accuracy": np.nan,
        "roc_auc": np.nan,
        "top_feature_1": "",
        "top_feature_2": "",
        "top_feature_3": "",
        "note": note,
    }


def _rank_top_features(model: object, columns: Iterable[str]) -> list[str]:
    try:
        coefs = np.asarray(model.coef_)[0]
    except Exception:
        return []
    ranked = sorted(zip(columns, coefs), key=lambda item: abs(item[1]), reverse=True)
    return [f"{name}:{coef:.4f}" for name, coef in ranked[:3]]


def _machine_category_from_name(machine_name: object) -> str:
    name = str(machine_name)
    if (
        "ジャグラー" in name
        or "ゴーゴージャグラー" in name
        or "ファンキージャグラー" in name
        or "ハッピージャグラー" in name
        or "ミスタージャグラー" in name
    ):
        return "juggler"
    if "ハナ" in name or "ハナハナ" in name or "沖ドキ" in name:
        return "hana_oki"
    smart_markers = (
        "スマスロ",
        "L ",
        "L",
        "ヴァルヴレイヴ",
        "北斗",
        "モンキー",
        "かぐや",
        "からくり",
        "炎炎",
        "東京喰種",
        "カバネリ",
        "バイオ",
        "番長",
        "銭形",
    )
    if any(marker in name for marker in smart_markers):
        return "at_smart"
    if "BT" in name or "ボーナストリガー" in name or "ボーナストリガ" in name:
        return "bt"
    return "other"


def _atype_from_category(category: object) -> str:
    return "A" if str(category) in {"juggler", "hana_oki", "bt"} else "N"


def _kakuban_bin_from_number(machine_number: object) -> str:
    try:
        number = int(machine_number)
    except Exception:
        return "unknown"
    if number <= 0:
        return "unknown"
    start = ((number - 1) // 10) * 10 + 1
    end = start + 9
    return f"{start}-{end}"


# Halls with a real physical layout CSV that we trust enough to compute genuine
# section groupings and rank-from-min kakuban position. All other halls fall
# back to a machine-number decade substitute for both axes (per explicit
# instruction: only these 3 halls get real layout-derived axes).
EXACT_LAYOUT_HALLS = {"蒲田7", "蒲田1", "みとや"}


def _kakuban_rank_bin_from_number(machine_number: object) -> str:
    """rank_from_min within the machine's local 10-number row, binned into thirds.

    This approximates the corner/edge position within a row of adjacent
    machines (rank 0-2 and 6-9 are near the row edges, 3-5 is the middle),
    which is the actual 角番 concept -- distinct from a raw section index.
    """
    try:
        number = int(machine_number)
    except Exception:
        return "unknown"
    if number <= 0:
        return "unknown"
    local_rank = (number - 1) % 10
    if local_rank <= 2:
        return "0-2"
    if local_rank <= 5:
        return "3-5"
    return "6-9"


@lru_cache(maxsize=None)
def _hall_has_layout_csv(hall: str) -> bool:
    return bool(find_floor_csvs(hall, str(PROJECT_ROOT)))


def _section_from_machine_numbers(machine_numbers: pd.Series) -> pd.Series:
    numbers = sorted(
        int(x) for x in pd.to_numeric(machine_numbers, errors="coerce").dropna().astype(int).unique().tolist()
    )
    if not numbers:
        return pd.Series(dtype=object)
    sections: dict[int, str] = {}
    start = prev = numbers[0]
    for num in numbers[1:]:
        if num - prev > 1:
            label = f"{start}-{prev}" if start != prev else f"{start}"
            for value in range(start, prev + 1):
                sections[value] = label
            start = num
        prev = num
    label = f"{start}-{prev}" if start != prev else f"{start}"
    for value in range(start, prev + 1):
        sections[value] = label
    return pd.Series(sections)


def _plan_section_map(machine_numbers: pd.Series, *, hall: str | None = None) -> pd.Series:
    if hall is None or hall not in EXACT_LAYOUT_HALLS:
        numbers = pd.to_numeric(machine_numbers, errors="coerce").dropna().astype(int).unique().tolist()
        return pd.Series({number: _kakuban_bin_from_number(number) for number in numbers})
    return _section_from_machine_numbers(machine_numbers)


def _plan_kakuban_bin_map(machine_numbers: pd.Series, *, hall: str | None = None) -> pd.Series:
    numbers = pd.to_numeric(machine_numbers, errors="coerce").dropna().astype(int).unique().tolist()
    if hall is not None and hall in EXACT_LAYOUT_HALLS:
        return pd.Series({number: _kakuban_rank_bin_from_number(number) for number in numbers})
    return pd.Series({number: _kakuban_bin_from_number(number) for number in numbers})


def _event_type_from_row(row: pd.Series) -> str:
    if int(row.get("is_x_day", 0) or 0) == 1 and int(row.get("is_weekend", 0) or 0) == 1:
        return "weekend_x_day"
    if int(row.get("is_x_day", 0) or 0) == 1:
        return "x_day"
    if int(row.get("is_weekend", 0) or 0) == 1:
        return "weekend"
    if int(row.get("is_month_end", 0) or 0) == 1:
        return "month_end"
    if int(row.get("is_month_start", 0) or 0) == 1:
        return "month_start"
    if int(row.get("dd", 0) or 0) in {11, 22}:
        return "mmdd_zorome"
    return "weekday"


def prepare_plan_source_frame(
    raw: pd.DataFrame, *, hall: str | None = None, min_games: int = DEFAULT_MIN_GAMES
) -> pd.DataFrame:
    frame = prepare_source_frame(raw, hall=hall, min_games=min_games).copy()
    if frame.empty:
        return frame
    if hall in PLAN_EXCLUDED_DATES:
        frame = frame.loc[~frame["date"].astype(str).isin(PLAN_EXCLUDED_DATES[hall])].copy()
        if frame.empty:
            return frame

    frame["machine_category"] = frame["machine_name"].map(_machine_category_from_name)
    frame["atype"] = frame["machine_category"].map(_atype_from_category)
    kakuban_map = _plan_kakuban_bin_map(frame["machine_number"], hall=hall)
    frame["kakuban_bin"] = frame["machine_number"].map(kakuban_map).fillna("unknown")
    frame["event_type"] = frame.apply(_event_type_from_row, axis=1)
    frame["is_month_start"] = frame["date_dt"].dt.day.eq(1).astype(int)
    month_end = frame["date_dt"].dt.days_in_month
    frame["is_month_end"] = frame["date_dt"].dt.day.eq(month_end).astype(int)

    section_map = _plan_section_map(frame["machine_number"], hall=hall)
    frame["section"] = frame["machine_number"].map(section_map).fillna("unknown")
    return frame


def _empty_plan_allocation_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "hall",
            "date",
            "axis",
            "axis_value",
            "n_machines",
            "total_games",
            "total_diff",
            "avg_diff",
            "plus_rate",
            "hit104_rate",
            "games_share",
            "share_of_total_diff",
            "excess_vs_hall_day",
            "hit104_lift",
        ]
    )


def build_plan_allocation_by_axis(source_frame: pd.DataFrame, axes: Iterable[str] = PLAN_AXES) -> pd.DataFrame:
    if source_frame.empty:
        return _empty_plan_allocation_frame()

    frame = source_frame.copy()
    if "hall" not in frame.columns:
        frame["hall"] = "hall"
    if "date_dt" not in frame.columns:
        frame["date_dt"] = _to_datetime(frame["date"])
    if "hit104" not in frame.columns:
        payout_rate = ((frame["games"] * 3.0) + frame["diff"]) / (frame["games"] * 3.0).replace(0, np.nan) * 100.0
        frame["hit104"] = payout_rate.ge(104.0).astype(int)
    if "machine_category" not in frame.columns:
        frame["machine_category"] = frame["machine_name"].map(_machine_category_from_name)
    if "atype" not in frame.columns:
        frame["atype"] = frame["machine_category"].map(_atype_from_category)
    single_hall = (
        frame["hall"].iloc[0] if "hall" in frame.columns and frame["hall"].nunique(dropna=False) == 1 else None
    )
    if "kakuban_bin" not in frame.columns:
        kakuban_map = _plan_kakuban_bin_map(frame["machine_number"], hall=single_hall)
        frame["kakuban_bin"] = frame["machine_number"].map(kakuban_map).fillna("unknown")
    if "section" not in frame.columns:
        section_map = _plan_section_map(frame["machine_number"], hall=single_hall)
        frame["section"] = frame["machine_number"].map(section_map).fillna("unknown")
    if "event_type" not in frame.columns:
        frame["event_type"] = frame.apply(_event_type_from_row, axis=1)

    daily = (
        frame.groupby(["hall", "date", "date_dt"], as_index=False, sort=True)
        .agg(
            hall_total_games=("games", "sum"),
            hall_total_diff=("diff", "sum"),
            hall_avg_diff=("diff", "mean"),
            hall_hit104_rate=("hit104", "mean"),
        )
        .sort_values(["hall", "date_dt"], kind="mergesort")
        .reset_index(drop=True)
    )

    rows: list[dict[str, object]] = []
    for axis in axes:
        if axis not in frame.columns:
            continue
        grouped = (
            frame.groupby(["hall", "date", "date_dt", axis], as_index=False, sort=True)
            .agg(
                n_machines=("machine_number", "nunique"),
                total_games=("games", "sum"),
                total_diff=("diff", "sum"),
                avg_diff=("diff", "mean"),
                plus_rate=("plus", "mean"),
                hit104_rate=("hit104", "mean"),
            )
            .rename(columns={axis: "axis_value"})
        )
        merged = grouped.merge(daily, on=["hall", "date", "date_dt"], how="left")
        merged["axis"] = axis
        merged["games_share"] = merged["total_games"] / merged["hall_total_games"].replace(0, np.nan)
        merged["share_of_total_diff"] = merged["total_diff"] / merged["hall_total_diff"].replace(0, np.nan)
        merged["excess_vs_hall_day"] = merged["avg_diff"] - merged["hall_avg_diff"]
        merged["hit104_lift"] = merged["hit104_rate"] - merged["hall_hit104_rate"]
        rows.append(
            merged.loc[
                :,
                [
                    "hall",
                    "date",
                    "axis",
                    "axis_value",
                    "n_machines",
                    "total_games",
                    "total_diff",
                    "avg_diff",
                    "plus_rate",
                    "hit104_rate",
                    "games_share",
                    "share_of_total_diff",
                    "excess_vs_hall_day",
                    "hit104_lift",
                ],
            ]
        )

    allocation = pd.concat(rows, ignore_index=True) if rows else _empty_plan_allocation_frame()
    if allocation.empty:
        return allocation
    allocation["axis_value"] = allocation["axis_value"].astype(object)
    return allocation.sort_values(["hall", "date", "axis", "axis_value"], kind="mergesort").reset_index(drop=True)


def _empty_plan_offset_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "hall",
            "axis",
            "focus_value",
            "offset_value",
            "n_days",
            "focus_mean_excess",
            "offset_mean_excess",
            "offset_gap",
            "corr_excess",
            "verdict",
        ]
    )


def compute_plan_offset_pairs(allocation: pd.DataFrame, *, min_days: int = 5) -> pd.DataFrame:
    if allocation.empty:
        return _empty_plan_offset_frame()

    rows: list[dict[str, object]] = []
    for (hall, axis), group in allocation.groupby(["hall", "axis"], sort=True):
        pivot = group.pivot_table(index="date", columns="axis_value", values="excess_vs_hall_day", aggfunc="mean")
        if pivot.empty:
            continue
        axis_values = list(pivot.columns)
        for focus_value in axis_values:
            focus_series = pivot[focus_value]
            focus_days = pivot[focus_series > 0]
            if len(focus_days) < min_days:
                continue
            focus_mean = float(focus_days[focus_value].mean())
            for offset_value in axis_values:
                if focus_value == offset_value:
                    continue
                pair = focus_days[[focus_value, offset_value]].dropna()
                if len(pair) < min_days:
                    continue
                offset_mean = float(pair[offset_value].mean())
                corr = float(pair[focus_value].corr(pair[offset_value])) if len(pair) >= 3 else np.nan
                verdict = (
                    "offset_candidate"
                    if focus_mean > 0 and offset_mean < 0 and (pd.isna(corr) or corr <= 0.2)
                    else "no_offset"
                )
                rows.append(
                    {
                        "hall": hall,
                        "axis": axis,
                        "focus_value": focus_value,
                        "offset_value": offset_value,
                        "n_days": int(len(pair)),
                        "focus_mean_excess": focus_mean,
                        "offset_mean_excess": offset_mean,
                        "offset_gap": float(focus_mean - offset_mean),
                        "corr_excess": corr,
                        "verdict": verdict,
                    }
                )

    offset_pairs = pd.DataFrame(rows, columns=_empty_plan_offset_frame().columns)
    if offset_pairs.empty:
        return offset_pairs
    return offset_pairs.sort_values(
        ["hall", "axis", "offset_gap", "n_days"], ascending=[True, True, False, False], kind="mergesort"
    ).reset_index(drop=True)


def _classify_plan_day(row: pd.Series) -> str:
    z = float(row.get("budget_zscore", np.nan))
    top_axis = str(row.get("top_axis", ""))
    top_share = float(row.get("top_axis_share_of_total_diff", np.nan))
    top_value = str(row.get("top_axis_level", ""))
    top_diff = float(row.get("top_axis_total_diff", np.nan))
    event_share = float(row.get("event_type_share", np.nan))
    if pd.notna(z) and z <= -0.75:
        return "recovery"
    if pd.notna(z) and z >= 0.75 and pd.notna(top_share) and top_share >= 0.35:
        return "all_high"
    if top_axis == "machine_name" and pd.notna(top_share) and top_share >= 0.35 and top_diff > 0:
        return "focused_machine"
    if (
        top_axis in {"machine_category", "atype", "floor", "section", "kakuban_bin"}
        and pd.notna(top_share)
        and top_share >= 0.30
    ):
        return "focused_category"
    if pd.notna(top_share) and top_share < 0.22 and pd.notna(z) and abs(z) < 0.5:
        return "balanced"
    if (
        top_axis == "event_type"
        and top_value in {"x_day", "weekend_x_day"}
        and pd.notna(event_share)
        and event_share >= 0.25
        and top_diff <= 0
    ):
        return "decoy_heavy"
    return "balanced"


def _build_plan_daily_frame(source_frame: pd.DataFrame, allocation: pd.DataFrame) -> pd.DataFrame:
    if source_frame.empty:
        return pd.DataFrame(
            columns=[
                "hall",
                "date",
                "date_dt",
                "n_machines",
                "total_games",
                "total_diff",
                "avg_diff",
                "hit104_rate",
                "budget_index",
                "budget_zscore",
                "budget_regime",
                "plan_regime",
            ]
        )

    daily = (
        source_frame.groupby(["hall", "date", "date_dt"], as_index=False, sort=True)
        .agg(
            n_machines=("machine_number", "nunique"),
            total_games=("games", "sum"),
            total_diff=("diff", "sum"),
            avg_diff=("diff", "mean"),
            hit104_rate=("diff", lambda s: float((s.ge(0)).mean())),
        )
        .sort_values(["hall", "date_dt"], kind="mergesort")
        .reset_index(drop=True)
    )
    daily["budget_index"] = (daily["total_diff"] / daily["total_games"].replace(0, np.nan)) * 100.0
    hall_mean = daily.groupby("hall")["budget_index"].transform("mean")
    hall_std = daily.groupby("hall")["budget_index"].transform(lambda s: s.std(ddof=0)).replace(0, np.nan)
    daily["budget_zscore"] = ((daily["budget_index"] - hall_mean) / hall_std).fillna(0.0)
    daily["budget_regime"] = daily["budget_zscore"].map(classify_budget_regime)

    top_cells = (
        allocation.sort_values(["hall", "date", "share_of_total_diff"], ascending=[True, True, False], kind="mergesort")
        .groupby(["hall", "date"], as_index=False, sort=False)
        .head(1)
        .rename(
            columns={
                "axis": "top_axis",
                "axis_value": "top_axis_level",
                "share_of_total_diff": "top_axis_share_of_total_diff",
                "total_diff": "top_axis_total_diff",
                "hit104_lift": "top_axis_hit104_lift",
                "games_share": "top_axis_games_share",
            }
        )
        .loc[
            :,
            [
                "hall",
                "date",
                "top_axis",
                "top_axis_level",
                "top_axis_share_of_total_diff",
                "top_axis_total_diff",
                "top_axis_hit104_lift",
                "top_axis_games_share",
            ],
        ]
    )
    daily = daily.merge(top_cells, on=["hall", "date"], how="left")
    event_share = (
        allocation.loc[allocation["axis"].eq("event_type")]
        .groupby(["hall", "date"], as_index=False)["share_of_total_diff"]
        .sum()
    )
    event_share = event_share.rename(columns={"share_of_total_diff": "event_type_share"})
    daily = daily.merge(event_share, on=["hall", "date"], how="left")
    daily["plan_regime"] = daily.apply(_classify_plan_day, axis=1)
    return daily


def build_plan_report(
    hall: str,
    source_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    allocation: pd.DataFrame,
    offset_pairs: pd.DataFrame,
) -> str:
    lines = [f"# {hall} Plan Budget Regime Report", ""]
    lines.append(
        "- caution: diff-only is coarse; prefer share_of_total_diff plus hit104_lift for reading concentration"
    )
    lines.append(f"- source rows: {len(source_frame)}")
    lines.append(f"- days: {len(daily_frame)}")
    if not daily_frame.empty:
        for regime in ["all_high", "focused_machine", "focused_category", "balanced", "recovery", "decoy_heavy"]:
            lines.append(f"- {regime}: {int((daily_frame['plan_regime'] == regime).sum())}")
    lines.append("")
    lines.append("## Top Axes")
    if allocation.empty:
        lines.append("- none")
    else:
        top_axes = (
            allocation.groupby(["axis", "axis_value"], as_index=False)
            .agg(
                cumulative_share_of_total_diff=(
                    "share_of_total_diff",
                    lambda s: float(pd.to_numeric(s, errors="coerce").sum()),
                ),
                mean_excess=("excess_vs_hall_day", "mean"),
                mean_hit104_lift=("hit104_lift", "mean"),
            )
            .sort_values(["cumulative_share_of_total_diff", "mean_excess"], ascending=[False, False], kind="mergesort")
            .head(12)
        )
        for row in top_axes.itertuples(index=False):
            lines.append(
                f"- {row.axis}={row.axis_value}: cumulative_share_of_total_diff={row.cumulative_share_of_total_diff:.3f}, "
                f"mean_excess={row.mean_excess:.3f}, hit104_lift={row.mean_hit104_lift:.3f}"
            )
    lines.append("")
    lines.append("## Offset Candidates")
    candidates = offset_pairs[offset_pairs["verdict"].eq("offset_candidate")].head(12)
    if candidates.empty:
        lines.append("- none")
    else:
        for row in candidates.itertuples(index=False):
            lines.append(
                f"- {row.axis}: {row.focus_value} -> {row.offset_value}, gap={row.offset_gap:.3f}, "
                f"corr={row.corr_excess:.3f}, n={int(row.n_days)}"
            )
    lines.append("")
    lines.append("## Regime Notes")
    lines.append("- all_high: concentrated positive days")
    lines.append("- focused_machine: one machine_name dominates")
    lines.append("- focused_category: one broader category dominates")
    lines.append("- recovery: hall-relative z-score is low")
    lines.append("- decoy_heavy: event-like days that do not convert into strong diff")
    lines.append("")
    return "\n".join(lines)


def _summarize_plan_hall(
    hall: str,
    source_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    allocation: pd.DataFrame,
    offset_pairs: pd.DataFrame,
) -> pd.DataFrame:
    top_cell = None
    if not allocation.empty:
        top_cell = allocation.sort_values(
            ["share_of_total_diff", "n_machines", "axis", "axis_value"],
            ascending=[False, False, True, True],
            kind="mergesort",
        ).iloc[0]
    best_offset = offset_pairs.iloc[0] if not offset_pairs.empty else pd.Series(dtype=object)
    summary_row = {
        "hall": hall,
        "n_source_rows": int(len(source_frame)),
        "n_days": int(len(daily_frame)),
        "all_high_days": int((daily_frame["plan_regime"] == "all_high").sum()) if not daily_frame.empty else 0,
        "focused_machine_days": int((daily_frame["plan_regime"] == "focused_machine").sum())
        if not daily_frame.empty
        else 0,
        "focused_category_days": int((daily_frame["plan_regime"] == "focused_category").sum())
        if not daily_frame.empty
        else 0,
        "balanced_days": int((daily_frame["plan_regime"] == "balanced").sum()) if not daily_frame.empty else 0,
        "recovery_days": int((daily_frame["plan_regime"] == "recovery").sum()) if not daily_frame.empty else 0,
        "decoy_heavy_days": int((daily_frame["plan_regime"] == "decoy_heavy").sum()) if not daily_frame.empty else 0,
        "top_axis": top_cell.axis if top_cell is not None else "",
        "top_axis_level": top_cell.axis_value if top_cell is not None else "",
        "top_axis_share_of_total_diff": float(top_cell.share_of_total_diff) if top_cell is not None else np.nan,
        "n_offset_pairs": int(len(offset_pairs)),
        "best_offset_days": int(best_offset.n_days) if not best_offset.empty else np.nan,
        "best_offset_gap": float(best_offset.offset_gap) if not best_offset.empty else np.nan,
        "note": "",
    }
    return pd.DataFrame([summary_row], columns=PLAN_SUMMARY_COLUMNS)


def run_plan_output(
    hall: str,
    raw: pd.DataFrame | None = None,
    *,
    output_root: Path = DEFAULT_PLAN_OUTPUT_ROOT,
    min_games: int = DEFAULT_MIN_GAMES,
) -> dict[str, object]:
    if raw is None:
        raw = load_hall_df(hall)

    output_root = _ensure_output_root(Path(output_root))
    source_frame = prepare_plan_source_frame(raw, hall=hall, min_games=min_games)
    allocation = build_plan_allocation_by_axis(source_frame)
    daily_frame = _build_plan_daily_frame(source_frame, allocation)
    offset_pairs = compute_plan_offset_pairs(allocation)
    report_text = build_plan_report(hall, source_frame, daily_frame, allocation, offset_pairs)
    summary = _summarize_plan_hall(hall, source_frame, daily_frame, allocation, offset_pairs)

    hall_slug = hall
    paths = {
        "allocation": output_root / f"{hall_slug}_allocation_by_axis.csv",
        "offset_pairs": output_root / f"{hall_slug}_offset_pairs.csv",
        "report": output_root / f"{hall_slug}_budget_regime_report.md",
        "summary": output_root / "summary_report.csv",
    }
    allocation.to_csv(paths["allocation"], index=False, encoding="utf-8-sig")
    offset_pairs.to_csv(paths["offset_pairs"], index=False, encoding="utf-8-sig")
    paths["report"].write_text(report_text, encoding="utf-8")
    summary.to_csv(paths["summary"], index=False, encoding="utf-8-sig")

    return {
        "source": source_frame,
        "daily": daily_frame,
        "allocation": allocation,
        "offset_pairs": offset_pairs,
        "report": report_text,
        "summary": summary,
        "paths": paths,
    }


def _same_regime_baseline_rate(daily_frame: pd.DataFrame) -> float:
    if daily_frame.empty or "budget_regime" not in daily_frame.columns:
        return np.nan
    regime_counts = daily_frame["budget_regime"].dropna().value_counts(normalize=True)
    if regime_counts.empty:
        return np.nan
    return float((regime_counts**2).sum())


def _summarize_offset_pairs(offset_pairs: pd.DataFrame, daily_frame: pd.DataFrame) -> pd.DataFrame:
    if offset_pairs.empty:
        return pd.DataFrame(
            columns=[
                "offset_days",
                "n_pairs",
                "mean_delta",
                "mean_abs_delta",
                "same_regime_rate",
                "expected_same_regime_rate",
                "same_regime_uplift",
            ]
        )
    expected_same_regime_rate = _same_regime_baseline_rate(daily_frame)
    summary = (
        offset_pairs.groupby("offset_days", as_index=False)
        .agg(
            n_pairs=("date", "size"),
            mean_delta=("delta_budget_index", "mean"),
            mean_abs_delta=("delta_budget_index", lambda s: float(np.abs(pd.to_numeric(s, errors="coerce")).mean())),
            same_regime_rate=("same_regime", "mean"),
        )
        .assign(
            expected_same_regime_rate=expected_same_regime_rate,
        )
    )
    summary["same_regime_uplift"] = summary["same_regime_rate"] - summary["expected_same_regime_rate"]
    summary = summary.sort_values(
        ["same_regime_uplift", "same_regime_rate", "mean_abs_delta", "n_pairs", "offset_days"],
        ascending=[False, False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return summary


def _top_allocation_cell(allocation: pd.DataFrame) -> pd.Series | None:
    if allocation.empty:
        return None
    return allocation.sort_values(
        ["budget_abs_share", "n_days", "axis", "axis_level"], ascending=[False, False, True, True], kind="mergesort"
    ).iloc[0]


def build_report(
    hall: str,
    source_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    allocation: pd.DataFrame,
    offset_pairs: pd.DataFrame,
    model_eval: pd.DataFrame,
) -> str:
    lines = [f"# {hall} Hall Budget Allocation Light", ""]
    lines.append(f"- source rows: {len(source_frame)}")
    lines.append(f"- days: {len(daily_frame)}")
    if not daily_frame.empty:
        lines.append(f"- mean budget index: {daily_frame['budget_index'].mean():.3f}")
        lines.append(f"- median budget index: {daily_frame['budget_index'].median():.3f}")
        if "budget_zscore" in daily_frame.columns:
            lines.append(f"- mean budget zscore: {daily_frame['budget_zscore'].mean():.3f}")
            lines.append(f"- median budget zscore: {daily_frame['budget_zscore'].median():.3f}")
        lines.append(f"- under budget days: {int((daily_frame['budget_regime'] == 'under_budget').sum())}")
        lines.append(f"- balanced days: {int((daily_frame['budget_regime'] == 'balanced').sum())}")
        lines.append(f"- over budget days: {int((daily_frame['budget_regime'] == 'over_budget').sum())}")
    lines.append("")
    lines.append("## Allocation")
    top_cell = _top_allocation_cell(allocation)
    if top_cell is None:
        lines.append("- none")
    else:
        lines.append(
            f"- top cell: {top_cell.axis}={top_cell.axis_level} "
            f"(share={top_cell.budget_abs_share:.3f}, n={int(top_cell.n_days)})"
        )
    lines.append("")
    lines.append("## Offset Pairs")
    offset_summary = _summarize_offset_pairs(offset_pairs, daily_frame)
    if offset_summary.empty:
        lines.append("- none")
    else:
        if not daily_frame.empty:
            baseline_same_regime_rate = _same_regime_baseline_rate(daily_frame)
            if pd.notna(baseline_same_regime_rate):
                lines.append(f"- chance same-regime rate: {baseline_same_regime_rate:.3f}")
        for row in offset_summary.itertuples(index=False):
            lines.append(
                f"- offset {row.offset_days}: n={int(row.n_pairs)}, "
                f"mean_delta={row.mean_delta:.3f}, same_regime_rate={row.same_regime_rate:.3f}, "
                f"uplift={row.same_regime_uplift:.3f}"
            )
    lines.append("")
    lines.append("## Lightweight Model")
    if model_eval.empty:
        lines.append("- none")
    else:
        row = model_eval.iloc[0]
        lines.append(f"- note: {row['note']}")
        lines.append("- status basis: roc_auc")
        lines.append(f"- baseline accuracy: {row['baseline_accuracy']}")
        lines.append(f"- accuracy: {row['accuracy']}")
        lines.append(f"- accuracy delta: {row['accuracy_delta']}")
        lines.append(f"- roc_auc: {row['roc_auc']}")
        if row["top_feature_1"]:
            lines.append(f"- top feature: {row['top_feature_1']}")
    lines.append("")
    return "\n".join(lines)


def _summarize_hall(
    hall: str,
    source_frame: pd.DataFrame,
    daily_frame: pd.DataFrame,
    allocation: pd.DataFrame,
    offset_pairs: pd.DataFrame,
    model_eval: pd.DataFrame,
) -> pd.DataFrame:
    top_cell = _top_allocation_cell(allocation)
    offset_summary = _summarize_offset_pairs(offset_pairs, daily_frame)
    if offset_summary.empty:
        best_offset_days = np.nan
        best_offset_same_regime_rate = np.nan
        best_offset_expected_same_regime_rate = np.nan
        best_offset_same_regime_uplift = np.nan
    else:
        best_offset = offset_summary.iloc[0]
        best_offset_days = int(best_offset.offset_days)
        best_offset_same_regime_rate = float(best_offset.same_regime_rate)
        best_offset_expected_same_regime_rate = float(best_offset.expected_same_regime_rate)
        best_offset_same_regime_uplift = float(best_offset.same_regime_uplift)

    model_row = model_eval.iloc[0] if not model_eval.empty else pd.Series(dtype=object)
    if not model_row.empty and str(model_row.get("note", "")).startswith("trained"):
        baseline_accuracy = float(model_row.get("baseline_accuracy", np.nan))
        model_accuracy = float(model_row.get("accuracy", np.nan))
        model_accuracy_delta = float(model_row.get("accuracy_delta", model_accuracy - baseline_accuracy))
        model_metric = float(model_row.get("roc_auc", np.nan))
        if pd.isna(model_metric):
            model_status = "trained_unknown"
        elif model_metric >= 0.6:
            model_status = "trained_above_baseline"
        elif model_metric <= 0.55:
            model_status = "trained_below_baseline"
        else:
            model_status = "trained_near_baseline"
    elif not model_row.empty:
        model_status = "skipped"
        model_metric = np.nan
        baseline_accuracy = float(model_row.get("baseline_accuracy", np.nan))
        model_accuracy = float(model_row.get("accuracy", np.nan))
        model_accuracy_delta = float(model_row.get("accuracy_delta", np.nan))
    else:
        model_status = "skipped"
        model_metric = np.nan
        baseline_accuracy = np.nan
        model_accuracy = np.nan
        model_accuracy_delta = np.nan

    summary_row = {
        "hall": hall,
        "n_source_rows": int(len(source_frame)),
        "n_days": int(len(daily_frame)),
        "mean_budget_index": float(daily_frame["budget_index"].mean()) if not daily_frame.empty else np.nan,
        "median_budget_index": float(daily_frame["budget_index"].median()) if not daily_frame.empty else np.nan,
        "under_budget_days": int((daily_frame["budget_regime"] == "under_budget").sum())
        if not daily_frame.empty
        else 0,
        "balanced_days": int((daily_frame["budget_regime"] == "balanced").sum()) if not daily_frame.empty else 0,
        "over_budget_days": int((daily_frame["budget_regime"] == "over_budget").sum()) if not daily_frame.empty else 0,
        "top_axis": f"{top_cell.axis}" if top_cell is not None else "",
        "top_axis_level": top_cell.axis_level if top_cell is not None else "",
        "top_axis_budget_abs_share": float(top_cell.budget_abs_share) if top_cell is not None else np.nan,
        "n_offset_pairs": int(len(offset_pairs)),
        "best_offset_days": best_offset_days,
        "best_offset_same_regime_rate": best_offset_same_regime_rate,
        "best_offset_expected_same_regime_rate": best_offset_expected_same_regime_rate,
        "best_offset_same_regime_uplift": best_offset_same_regime_uplift,
        "model_baseline_accuracy": baseline_accuracy,
        "model_accuracy": model_accuracy,
        "model_accuracy_delta": model_accuracy_delta,
        "model_roc_auc": model_metric,
        "model_status": model_status,
        "model_metric": model_metric,
        "note": "",
    }
    return pd.DataFrame([summary_row], columns=SUMMARY_COLUMNS)


def run_hall_analysis(
    hall: str,
    raw: pd.DataFrame | None = None,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    min_games: int = DEFAULT_MIN_GAMES,
    offsets: Iterable[int] = DEFAULT_OFFSETS,
    model_min_class_count: int = DEFAULT_MIN_CLASS_COUNT,
) -> dict[str, object]:
    if raw is None:
        raw = load_hall_df(hall)

    output_root = _ensure_output_root(Path(output_root))
    source_frame = prepare_source_frame(raw, hall=hall, min_games=min_games)
    daily_frame = build_daily_budget_index(source_frame)
    allocation = build_allocation_by_axis(daily_frame)
    offset_pairs = build_offset_pairs(daily_frame, offsets=offsets)
    model_eval = evaluate_lightweight_model(daily_frame, min_class_count=model_min_class_count)
    report_text = build_report(hall, source_frame, daily_frame, allocation, offset_pairs, model_eval)
    summary = _summarize_hall(hall, source_frame, daily_frame, allocation, offset_pairs, model_eval)

    daily_path = output_root / f"{hall}_daily_budget_index.csv"
    allocation_path = output_root / f"{hall}_allocation_by_axis.csv"
    offset_path = output_root / f"{hall}_offset_pairs.csv"
    model_path = output_root / f"{hall}_lightweight_model.csv"
    report_path = output_root / f"{hall}_report.md"

    daily_frame.to_csv(daily_path, index=False, encoding="utf-8-sig")
    allocation.to_csv(allocation_path, index=False, encoding="utf-8-sig")
    offset_pairs.to_csv(offset_path, index=False, encoding="utf-8-sig")
    model_eval.to_csv(model_path, index=False, encoding="utf-8-sig")
    report_path.write_text(report_text, encoding="utf-8")
    summary.to_csv(output_root / "summary_report.csv", index=False, encoding="utf-8-sig")

    return {
        "source": source_frame,
        "daily": daily_frame,
        "allocation": allocation,
        "offset_pairs": offset_pairs,
        "model": model_eval,
        "report": report_text,
        "summary": summary,
        "paths": {
            "daily": daily_path,
            "allocation": allocation_path,
            "offset_pairs": offset_path,
            "model": model_path,
            "report": report_path,
            "summary": output_root / "summary_report.csv",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="hall budget allocation light")
    parser.add_argument("--halls", nargs="+", default=DEFAULT_HALLS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--plan-output-root", type=Path, default=None)
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    parser.add_argument("--model-min-class-count", type=int, default=DEFAULT_MIN_CLASS_COUNT)
    parser.add_argument("--offsets", nargs="+", type=int, default=list(DEFAULT_OFFSETS))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = _ensure_output_root(Path(args.output_root))
    summary_frames: list[pd.DataFrame] = []
    plan_summary_frames: list[pd.DataFrame] = []
    plan_output_root = _ensure_output_root(Path(args.plan_output_root)) if args.plan_output_root is not None else None

    for hall in args.halls:
        if hall not in HALL_DBS:
            raise ValueError(f"unknown hall: {hall}")
        result = run_hall_analysis(
            hall,
            raw=None,
            output_root=output_root,
            min_games=args.min_games,
            offsets=tuple(args.offsets),
            model_min_class_count=args.model_min_class_count,
        )
        summary_frames.append(result["summary"])
        if plan_output_root is not None:
            plan_result = run_plan_output(
                hall,
                raw=None,
                output_root=plan_output_root,
                min_games=args.min_games,
            )
            plan_summary_frames.append(plan_result["summary"])

    summary = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame(columns=SUMMARY_COLUMNS)
    summary.to_csv(output_root / "summary_report.csv", index=False, encoding="utf-8-sig")
    if plan_output_root is not None:
        plan_summary = (
            pd.concat(plan_summary_frames, ignore_index=True)
            if plan_summary_frames
            else pd.DataFrame(columns=PLAN_SUMMARY_COLUMNS)
        )
        plan_summary.to_csv(plan_output_root / "summary_report.csv", index=False, encoding="utf-8-sig")
    print(f"written: {output_root}")
    if plan_output_root is not None:
        print(f"written: {plan_output_root}")
    return 0


# Backwards-compatible aliases for the helper names used in earlier local drafts.
compute_daily_budget_index = build_daily_budget_index
compute_allocation_by_axis = build_allocation_by_axis
compute_offset_pairs = build_offset_pairs
run_lightweight_budget_model = evaluate_lightweight_model


if __name__ == "__main__":
    raise SystemExit(main())
