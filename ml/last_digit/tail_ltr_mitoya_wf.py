from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ml.last_digit.mitoya_segmentation import (
    aggregate_mode_mitoya,
    build_base_rows_mitoya,
    classify_positive_combined_bucket,
)


def _load_base_module():
    module_name = "ml.last_digit._tail_ltr_mitoya_wf_base"
    module = sys.modules.get(module_name)
    if module is not None:
        return module

    module_path = Path(__file__).with_name("tail_ltr_split_rule_wf.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load base module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_BASE = _load_base_module()
_BASE.aggregate_mode = aggregate_mode_mitoya

Candidate = _BASE.Candidate
build_base_rows = build_base_rows_mitoya
aggregate_mode = aggregate_mode_mitoya

DAY_BUCKET_ORDER = ("x_day", "strong_zorome", "month_end_30", "dd_11", "others")
SUMMARY_KEY_BY_BUCKET = {
    "x_day": "x_day_only",
    "strong_zorome": "strong_zorome_days",
    "month_end_30": "month_end_30_days",
    "dd_11": "dd_11_days",
    "others": "others_days",
}
POSITIVE_DAY_BUCKET_ORDER = ("positive_day", "others")
POSITIVE_SUMMARY_KEY_BY_BUCKET = {
    "positive_day": "positive_day_only",
    "others": "others_days",
}
POSITION_FEATURE_COLS = ("mean_section_rank", "mean_physical_corner", "pct_strong_section")

# バケット別の位置特徴量使用フラグ
# x_day: 実験で mean_diff +23.7 の改善を確認 → 有効
# others: mean_diff 改善、hit@1 -2pp は要観察 → 有効（暫定）
# strong_zorome / month_end_30: observed_dates=2 の小サンプルで過学習リスク → 無効
# dd_11: 除外済みバケット → 無効
POSITION_FEATURES_BY_BUCKET: dict[str, bool] = {
    "x_day": True,
    "strong_zorome": False,
    "month_end_30": False,
    "dd_11": False,
    "others": True,
}


def _resolve_mitoya_db_path(raw: str) -> Path:
    if raw:
        return Path(raw)
    required_tables = {"machine_detailed_results", "machine_layout", "machine_master", "daily_hall_summary"}

    def has_required_tables(path: Path) -> bool:
        if not path.exists() or path.suffix != ".db":
            return False
        try:
            con = sqlite3.connect(str(path))
            rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            con.close()
        except sqlite3.Error:
            return False
        present = {row[0] for row in rows}
        return required_tables.issubset(present)

    entries = sorted(os.listdir("db"))
    if len(entries) > 6:
        candidate = Path("db") / entries[6]
        if has_required_tables(candidate):
            return candidate
    fallback = sorted(p for p in Path("db").glob("*.db") if "みとや" in p.name)
    for candidate in fallback:
        if has_required_tables(candidate):
            return candidate
    for candidate in sorted(Path("db").glob("*.db")):
        if has_required_tables(candidate):
            return candidate
    raise FileNotFoundError("Mitoya DB was not found under db/")


@dataclass(frozen=True)
class BucketConfig:
    name: str
    candidates: list[Candidate]
    q_grid: list[float]
    min_train_days: int


def specific_dd_from_date(value: pd.Timestamp) -> int | None:
    ts = pd.Timestamp(value)
    dd = int(ts.day) % 10
    if dd == 4:
        return 4
    if dd == 7:
        return 7
    return None


def classify_mitoya_day_bucket(value: pd.Timestamp, *, is_strong_zorome: bool = False) -> str:
    ts = pd.Timestamp(value)
    day = int(ts.day)
    if day % 10 in {4, 7}:
        return "x_day"
    if ts.month == ts.day:
        return "strong_zorome"
    if day == 30:
        return "month_end_30"
    if day == 11:
        return "dd_11"
    return "others"


def classify_positive_combined_day_bucket(value: pd.Timestamp) -> str:
    return classify_positive_combined_bucket(value)


def parse_position_bucket_overrides(raw: str) -> set[str]:
    return {part.strip() for part in str(raw).split(",") if part.strip()}


def should_use_position_features(
    bucket: str,
    global_flag: bool,
    override_buckets: set[str] | None = None,
) -> bool:
    """
    global_flag=False → 常に False（後方互換）
    global_flag=True  → POSITION_FEATURES_BY_BUCKET を参照
    override_buckets  → 指定バケットを強制 True に上書き
                        未指定バケットは POSITION_FEATURES_BY_BUCKET に従う
    """
    if not global_flag:
        return False
    if override_buckets and bucket in override_buckets:
        return True
    return POSITION_FEATURES_BY_BUCKET.get(bucket, False)


def add_mitoya_bucket_features(
    df: pd.DataFrame,
    *,
    include_specific_dd: bool = True,
    bucket_mode: str = "atype3",
) -> pd.DataFrame:
    out = _BASE.add_simple_features(df)
    dates = pd.to_datetime(out["date"])
    specific_dd = [specific_dd_from_date(dt) for dt in dates]
    if bucket_mode == "atype3":
        buckets = [classify_mitoya_day_bucket(dt) for dt in dates]
    elif bucket_mode == "positive_combined":
        buckets = [classify_positive_combined_day_bucket(dt) for dt in dates]
    else:
        raise ValueError(f"Unsupported bucket_mode: {bucket_mode}")
    if include_specific_dd:
        out["specific_dd"] = pd.array(specific_dd, dtype="Int64")
    out["day_bucket"] = pd.Series(buckets, index=out.index, dtype="string")
    if bucket_mode == "atype3":
        out["is_x_day"] = out["day_bucket"].eq("x_day").astype(int)
        out["is_strong_zorome_day"] = out["day_bucket"].eq("strong_zorome").astype(int)
        out["is_others_day"] = out["day_bucket"].eq("others").astype(int)
        out["x_day_x_weekday_delta"] = out["is_x_day"] * out["weekday_delta_from_mean"]
        out["x_day_x_days_since_last_top2"] = out["is_x_day"] * out["days_since_last_top2"]
        out["strong_zorome_x_weekday_delta"] = out["is_strong_zorome_day"] * out["weekday_delta_from_mean"]
        out["strong_zorome_x_days_since_last_top2"] = out["is_strong_zorome_day"] * out["days_since_last_top2"]
    else:
        out["is_positive_day"] = out["day_bucket"].eq("positive_day").astype(int)
        out["is_others_day"] = out["day_bucket"].eq("others").astype(int)
        out["positive_day_x_weekday_delta"] = out["is_positive_day"] * out["weekday_delta_from_mean"]
        out["positive_day_x_days_since_last_top2"] = out["is_positive_day"] * out["days_since_last_top2"]
    out = out.drop(
        columns=[
            "is_wed",
            "is_wed_nonevent",
            "is_wed_event",
            "wed_x_weekday_delta",
            "wed_x_days_since_last_top2",
        ],
        errors="ignore",
    )
    return out


def _empty_bucket_summary(*, bucket_order: tuple[str, ...], summary_key_by_bucket: dict[str, str]) -> dict[str, dict[str, float]]:
    base = {
        "mean": 0.0,
        "std": 0.0,
        "n_days": 0,
        "ci_low": 0.0,
        "ci_high": 0.0,
        "p_gt_0": 0.5,
        "hit_at_1": 0.0,
        "hit_at_2": 0.0,
        "played_rate": 0.0,
    }
    return {
        "overall": dict(base),
        **{summary_key_by_bucket[bucket_name]: dict(base) for bucket_name in bucket_order},
    }


def summarize_bucketed_days(
    day_df: pd.DataFrame,
    *,
    n_boot: int,
    bucket_order: tuple[str, ...],
    summary_key_by_bucket: dict[str, str],
) -> dict[str, dict[str, float]]:
    if day_df.empty:
        return _empty_bucket_summary(bucket_order=bucket_order, summary_key_by_bucket=summary_key_by_bucket)

    arr = day_df["excess"].to_numpy(dtype=float)
    summary: dict[str, dict[str, float]] = {
        "overall": {
            **_BASE.summarize_array(arr),
            **_BASE.bootstrap_ci(arr, n_boot=n_boot, seed=_BASE.BOOTSTRAP_SEED_SPLIT_RULE),
            "hit_at_1": float(pd.to_numeric(day_df.get("hit_at_1", 0.0), errors="coerce").fillna(0.0).mean()),
            "hit_at_2": float(pd.to_numeric(day_df.get("hit_at_2", 0.0), errors="coerce").fillna(0.0).mean()),
            "played_rate": float(pd.to_numeric(day_df["excess"], errors="coerce").fillna(0.0).ne(0.0).mean()),
        }
    }
    for bucket_name in bucket_order:
        key = summary_key_by_bucket[bucket_name]
        bucket_df = day_df.loc[day_df["day_bucket"].eq(bucket_name)].copy()
        values = bucket_df["excess"].to_numpy(dtype=float)
        summary[key] = {
            **_BASE.summarize_array(values),
            **_BASE.bootstrap_ci(values, n_boot=n_boot, seed=_BASE.BOOTSTRAP_SEED_SPLIT_RULE),
            "hit_at_1": float(pd.to_numeric(bucket_df.get("hit_at_1", 0.0), errors="coerce").fillna(0.0).mean()),
            "hit_at_2": float(pd.to_numeric(bucket_df.get("hit_at_2", 0.0), errors="coerce").fillna(0.0).mean()),
            "played_rate": float(pd.to_numeric(bucket_df["excess"], errors="coerce").fillna(0.0).ne(0.0).mean()),
    }
    return summary


def summarize_specific_dd_days(day_df: pd.DataFrame) -> list[dict[str, float | int]]:
    if day_df.empty or "specific_dd" not in day_df.columns:
        return []
    work = day_df.copy()
    work["specific_dd"] = pd.to_numeric(work["specific_dd"], errors="coerce")
    work = work[work["specific_dd"].isin([4, 7])].copy()
    if work.empty:
        return []
    collapsed = (
        work.groupby(["date", "specific_dd"], sort=True)
        .agg(
            excess=("excess", "mean"),
            hit_at_1=("hit_at_1", "mean"),
            hit_at_2=("hit_at_2", "mean"),
            played_rate=("excess", lambda s: float(pd.to_numeric(s, errors="coerce").fillna(0.0).ne(0.0).mean())),
        )
        .reset_index()
    )
    rows: list[dict[str, float | int]] = []
    for dd in (4, 7):
        bucket_df = collapsed.loc[collapsed["specific_dd"].eq(dd)].copy()
        values = bucket_df["excess"].to_numpy(dtype=float)
        rows.append(
            {
                "specific_dd": dd,
                "n_days": int(bucket_df["date"].nunique()),
                "mean_diff": float(_BASE.summarize_array(values)["mean"]) if len(values) else 0.0,
                "hit_at_1": float(bucket_df["hit_at_1"].mean()) if not bucket_df.empty else 0.0,
                "hit_at_2": float(bucket_df["hit_at_2"].mean()) if not bucket_df.empty else 0.0,
                "played_rate": float(bucket_df["played_rate"].mean()) if not bucket_df.empty else 0.0,
            }
        )
    return rows


def _unique_candidates(*candidate_lists: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, float]] = set()
    merged: list[Candidate] = []
    for candidate_list in candidate_lists:
        for cand in candidate_list:
            key = (cand.window_name, float(cand.decay_lambda))
            if key in seen:
                continue
            seen.add(key)
            merged.append(cand)
    return merged


def _build_atype3_bucket_configs(args: argparse.Namespace) -> dict[str, BucketConfig]:
    strong_candidates = [
        Candidate(w, l)
        for w in _BASE.parse_csv_strs(args.windows_strong_zorome)
        for l in _BASE.parse_csv_floats(args.lambdas_strong_zorome)
    ]
    strong_q_grid = (
        [float(args.q_grid_strong_zorome_override)]
        if float(args.q_grid_strong_zorome_override) >= 0.0
        else _BASE.parse_csv_floats(args.q_grid_strong_zorome)
    )
    return {
        "x_day": BucketConfig(
            name="x_day",
            candidates=[
                Candidate(w, l)
                for w in _BASE.parse_csv_strs(args.windows_x_day)
                for l in _BASE.parse_csv_floats(args.lambdas_x_day)
            ],
            q_grid=_BASE.parse_csv_floats(args.q_grid_x_day),
            min_train_days=int(args.min_train_days_x_day),
        ),
        "strong_zorome": BucketConfig(
            name="strong_zorome",
            candidates=strong_candidates,
            q_grid=strong_q_grid,
            min_train_days=int(args.min_train_days_strong_zorome),
        ),
        "month_end_30": BucketConfig(
            name="month_end_30",
            candidates=list(strong_candidates),
            q_grid=list(strong_q_grid),
            min_train_days=int(args.min_train_days_month_end_30),
        ),
        "dd_11": BucketConfig(
            name="dd_11",
            candidates=list(strong_candidates),
            q_grid=list(strong_q_grid),
            min_train_days=int(args.min_train_days_dd_11),
        ),
        "others": BucketConfig(
            name="others",
            candidates=[
                Candidate(w, l)
                for w in _BASE.parse_csv_strs(args.windows_others)
                for l in _BASE.parse_csv_floats(args.lambdas_others)
            ],
            q_grid=_BASE.parse_csv_floats(args.q_grid_others),
            min_train_days=int(args.min_train_days_others),
        ),
    }


def _build_positive_combined_bucket_configs(args: argparse.Namespace) -> dict[str, BucketConfig]:
    atype3 = _build_atype3_bucket_configs(args)
    positive_candidates = _unique_candidates(
        atype3["x_day"].candidates,
        atype3["strong_zorome"].candidates,
        atype3["month_end_30"].candidates,
        atype3["dd_11"].candidates,
    )
    positive_q_grid = sorted(
        {
            *atype3["x_day"].q_grid,
            *atype3["strong_zorome"].q_grid,
            *atype3["month_end_30"].q_grid,
            *atype3["dd_11"].q_grid,
        }
    )
    positive_min_train_days = int(
        min(
            atype3["x_day"].min_train_days,
            atype3["strong_zorome"].min_train_days,
            atype3["month_end_30"].min_train_days,
            atype3["dd_11"].min_train_days,
        )
    )
    return {
        "positive_day": BucketConfig(
            name="positive_day",
            candidates=positive_candidates,
            q_grid=positive_q_grid,
            min_train_days=positive_min_train_days,
        ),
        "others": atype3["others"],
    }


def _build_bucket_configs(args: argparse.Namespace, *, mode: str) -> dict[str, BucketConfig]:
    if mode == "positive_combined":
        return _build_positive_combined_bucket_configs(args)
    return _build_atype3_bucket_configs(args)


def add_bucket_observation_counts(
    summary: dict[str, dict[str, float]],
    *,
    bucket_key: str,
    total_dates: int,
    holdout_dates: int,
) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {key: dict(value) for key, value in summary.items()}
    bucket = dict(out.get(bucket_key, {}))
    bucket["observed_dates_total"] = int(total_dates)
    bucket["observed_dates_holdout"] = int(holdout_dates)
    out[bucket_key] = bucket
    return out


def _drop_position_feature_columns(df: pd.DataFrame, *, enabled: bool) -> pd.DataFrame:
    if enabled:
        return df
    drop_cols = [col for col in POSITION_FEATURE_COLS if col in df.columns]
    if not drop_cols:
        return df
    return df.drop(columns=drop_cols)


def _safe_auc_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true_arr = np.asarray(y_true, dtype=int)
    y_pred_arr = np.asarray(y_pred, dtype=float)
    if y_true_arr.size == 0 or len(np.unique(y_true_arr)) < 2:
        return 0.0
    try:
        return float(roc_auc_score(y_true_arr, y_pred_arr))
    except ValueError:
        return 0.0


def _row_level_metrics(row_df: pd.DataFrame) -> dict[str, float]:
    if row_df.empty:
        return {"auc": 0.0, "ndcg_at_2": 0.0, "ndcg_at_3": 0.0, "n_rows": 0.0}
    work = row_df.copy()
    y_true = pd.to_numeric(work["is_top_2"], errors="coerce").fillna(0).to_numpy(dtype=int)
    y_pred = pd.to_numeric(work["pred"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    dates = pd.to_datetime(work["date"]).to_numpy()
    return {
        "auc": _safe_auc_score(y_true, y_pred),
        "ndcg_at_2": float(_BASE.improved.ndcg_at_k(y_true, y_pred, dates, 2)),
        "ndcg_at_3": float(_BASE.improved.ndcg_at_k(y_true, y_pred, dates, 3)),
        "n_rows": float(len(work)),
    }


def add_strong_zorome_observation_counts(
    summary: dict[str, dict[str, float]],
    *,
    total_dates: int,
    holdout_dates: int,
) -> dict[str, dict[str, float | int]]:
    return add_bucket_observation_counts(
        summary,
        bucket_key="strong_zorome_days",
        total_dates=total_dates,
        holdout_dates=holdout_dates,
    )

def summary_to_rows(
    summary: dict[str, dict[str, float]],
    *,
    position_feature_used_by_summary_key: dict[str, bool] | None = None,
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for bucket_key, payload in summary.items():
        position_feature_used = None
        if bucket_key != "overall" and position_feature_used_by_summary_key is not None:
            position_feature_used = bool(position_feature_used_by_summary_key.get(bucket_key, False))
        rows.append(
            {
                "bucket": bucket_key,
                "n_days": int(payload["n_days"]),
                "mean_diff": float(payload["mean"]),
                "hit_at_1": float(payload["hit_at_1"]),
                "hit_at_2": float(payload["hit_at_2"]),
                "played_rate": float(payload["played_rate"]),
                "position_feature_used": position_feature_used,
            }
        )
    return rows


def _build_day_hit_table(df: pd.DataFrame) -> pd.DataFrame:
    work = df.sort_values(["date", "pred"], ascending=[True, False]).copy()
    work["hit_at_1"] = (
        work.groupby("date", sort=False)["is_top_2"]
        .transform(lambda s: float(pd.to_numeric(s.iloc[:1], errors="coerce").fillna(0).max() > 0))
    )
    work["hit_at_2"] = (
        work.groupby("date", sort=False)["is_top_2"]
        .transform(lambda s: float(pd.to_numeric(s.iloc[:2], errors="coerce").fillna(0).max() > 0))
    )
    return work.groupby("date", sort=False)[["hit_at_1", "hit_at_2"]].first().reset_index()


def _attach_test_hits(
    *,
    original_test_df: pd.DataFrame,
    predicted_test_df: pd.DataFrame,
) -> pd.DataFrame:
    sort_cols = ["date", "entity_key"] if "entity_key" in original_test_df.columns else ["date"]
    test_for_hits = original_test_df.sort_values(sort_cols).reset_index(drop=True).copy()
    if len(test_for_hits) != len(predicted_test_df):
        raise ValueError("Prediction/test row count mismatch while building Hit@ metrics.")
    test_for_hits["pred"] = predicted_test_df["pred"].to_numpy(dtype=float)
    return _build_day_hit_table(test_for_hits)


def eval_candidate_for_bucket(
    *,
    dataset: pd.DataFrame,
    features: list[str],
    seed: int,
    candidate: Candidate,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    q_grid: list[float],
    bucket_name: str,
    min_train_days: int,
    diff_col: str,
    model_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    dts = pd.to_datetime(dataset["date"])
    tr_start, tr_end = _BASE.build_train_window(candidate.window_name, test_start)
    train = dataset[(dts >= tr_start) & (dts <= tr_end)].copy()
    test = dataset[(dts >= test_start) & (dts <= test_end)].copy()

    train = train[train["day_bucket"].eq(bucket_name)].copy()
    test = test[test["day_bucket"].eq(bucket_name)].copy()
    if train["date"].nunique() < min_train_days or test.empty:
        return None

    sort_cols = ["date", "entity_key"] if "entity_key" in test.columns else ["date"]
    test_sorted = test.sort_values(sort_cols).reset_index(drop=True).copy()

    if diff_col != "total_diff_coins":
        if diff_col not in train.columns or diff_col not in test_sorted.columns:
            return None
        train["total_diff_coins"] = pd.to_numeric(train[diff_col], errors="coerce").fillna(0.0)
        test_sorted["total_diff_coins"] = pd.to_numeric(test_sorted[diff_col], errors="coerce").fillna(0.0)

    cal_df, tst_df, choice = _BASE.train_and_predict_fold(
        train_df=train,
        test_df=test_sorted,
        target="is_top_2",
        features=features,
        decay_lambda=candidate.decay_lambda,
        random_state=seed,
        model_params=model_params or {},
        temperature_candidates=_BASE.improved.CalibrationConfig().temperature_candidates,
        blend_weights=_BASE.improved.CalibrationConfig().blend_weights,
        q_grid=q_grid,
        k=2,
    )
    tst_df = tst_df.copy()
    tst_df["is_top_2"] = test_sorted["is_top_2"].to_numpy(dtype=int)
    cal_day = _BASE.topk_day_table(cal_df, "pred", k=2, diff_col="total_diff_coins", mc_col="machine_count")
    tst_day = _BASE.topk_day_table(tst_df, "pred", k=2, diff_col="total_diff_coins", mc_col="machine_count")
    tst_hits = _attach_test_hits(original_test_df=test_sorted, predicted_test_df=tst_df)
    tst_day = tst_day.merge(tst_hits, on="date", how="left")
    keep_c = cal_day["margin"] >= choice["threshold"]
    keep_t = tst_day["margin"] >= choice["threshold"]
    cal_ex = np.where(keep_c.to_numpy(), cal_day["excess"].to_numpy(), 0.0)
    tst_ex = np.where(keep_t.to_numpy(), tst_day["excess"].to_numpy(), 0.0)
    tst_day = tst_day.copy()
    tst_day["excess_played"] = tst_ex
    tst_day["day_bucket"] = bucket_name
    return {
        "candidate": candidate,
        "choice": choice,
        "cal_score": float(np.mean(cal_ex)),
        "test_day": tst_day,
        "test_rows": tst_df,
        "test_metrics": {
            **_row_level_metrics(tst_df),
            "hit_at_1": float(tst_day["hit_at_1"].mean()) if not tst_day.empty else 0.0,
            "hit_at_2": float(tst_day["hit_at_2"].mean()) if not tst_day.empty else 0.0,
        },
    }


def select_best_bucket_candidates(
    *,
    dataset: pd.DataFrame,
    features: list[str],
    seed: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    bucket_configs: dict[str, BucketConfig],
    diff_col: str,
    model_params: dict[str, Any] | None,
    position_feature_used_by_bucket: dict[str, bool] | None = None,
) -> dict[str, dict[str, Any]] | None:
    selected: dict[str, dict[str, Any]] = {}
    for bucket_name, config in bucket_configs.items():
        bucket_enabled = bool(position_feature_used_by_bucket.get(bucket_name, False)) if position_feature_used_by_bucket else False
        bucket_dataset = _drop_position_feature_columns(dataset, enabled=bucket_enabled)
        bucket_features = [col for col in features if col in bucket_dataset.columns]
        rows: list[dict[str, Any]] = []
        for cand in config.candidates:
            result = eval_candidate_for_bucket(
                dataset=bucket_dataset,
                features=bucket_features,
                seed=seed,
                candidate=cand,
                test_start=test_start,
                test_end=test_end,
                q_grid=config.q_grid,
                bucket_name=bucket_name,
                min_train_days=config.min_train_days,
                diff_col=diff_col,
                model_params=model_params,
            )
            if result is not None:
                rows.append(result)
        if rows:
            selected[bucket_name] = sorted(rows, key=lambda x: x["cal_score"], reverse=True)[0]
    return selected if selected else None


def run_mode_bucketed(
    *,
    dataset: pd.DataFrame,
    seeds: list[int],
    test_days: int,
    warmup_days: int,
    bucket_configs: dict[str, BucketConfig],
    bucket_order: tuple[str, ...],
    summary_key_by_bucket: dict[str, str],
    diff_col: str,
    model_params: dict[str, Any] | None = None,
    position_feature_used_by_bucket: dict[str, bool] | None = None,
    max_blocks: int = 0,
    n_boot: int = 10000,
) -> tuple[pd.DataFrame, dict[str, dict[str, float]], dict[str, float]]:
    d = dataset.sort_values("date").reset_index(drop=True)
    valid_cfg = _BASE.improved.build_fixed_split_configs(d)["regime_3_fixed_split"]
    valid_dates = sorted(pd.to_datetime(d["date"].unique()))
    valid_dates = [
        x for x in valid_dates if pd.Timestamp(valid_cfg["valid_start"]) <= x <= pd.Timestamp(valid_cfg["valid_end"])
    ]
    features = _BASE.improved.get_numeric_features(d)
    features = [f for f in features if f not in {"is_top_2"}]

    rows: list[dict[str, Any]] = []
    row_frames: list[pd.DataFrame] = []
    for seed in seeds:
        idx = max(0, warmup_days)
        block_count = 0
        while idx < len(valid_dates):
            if max_blocks > 0 and block_count >= max_blocks:
                break
            test_start = valid_dates[idx]
            block = valid_dates[idx : idx + test_days]
            if not block:
                break
            test_end = block[-1]

            selected = select_best_bucket_candidates(
                dataset=d,
                features=features,
                seed=seed,
                test_start=test_start,
                test_end=test_end,
                bucket_configs=bucket_configs,
                diff_col=diff_col,
                model_params=model_params,
                position_feature_used_by_bucket=position_feature_used_by_bucket,
            )
            if selected is None:
                idx += test_days
                continue

            bucket_frames = [selected[bucket_name]["test_day"] for bucket_name in bucket_order if bucket_name in selected]
            if not bucket_frames:
                idx += test_days
                continue
            for bucket_name in bucket_order:
                if bucket_name in selected and "test_rows" in selected[bucket_name]:
                    row_frames.append(selected[bucket_name]["test_rows"].copy())
            td = pd.concat(bucket_frames, ignore_index=True).sort_values(["date", "day_bucket"])
            td["weekday"] = pd.to_datetime(td["date"]).dt.day_name()
            for _, r in td.iterrows():
                specific_dd = None
                if str(r["day_bucket"]) == "x_day":
                    specific_dd = int(pd.Timestamp(r["date"]).day % 10)
                rows.append(
                    {
                        "seed": seed,
                        "date": str(r["date"]),
                        "weekday": r["weekday"],
                        "day_bucket": str(r["day_bucket"]),
                        "specific_dd": specific_dd,
                        "excess": float(r["excess_played"]),
                        "hit_at_1": float(r.get("hit_at_1", 0.0)),
                        "hit_at_2": float(r.get("hit_at_2", 0.0)),
                    }
                )
            idx += test_days
            block_count += 1

    day_df = pd.DataFrame(rows)
    summary = summarize_bucketed_days(
        day_df,
        n_boot=n_boot,
        bucket_order=bucket_order,
        summary_key_by_bucket=summary_key_by_bucket,
    )
    row_df = pd.concat(row_frames, ignore_index=True) if row_frames else pd.DataFrame()
    row_metrics = _row_level_metrics(row_df) if not row_df.empty else {"auc": 0.0, "ndcg_at_2": 0.0, "ndcg_at_3": 0.0, "n_rows": 0.0}
    if not day_df.empty:
        hit1_series = pd.to_numeric(day_df["hit_at_1"], errors="coerce").fillna(0.0) if "hit_at_1" in day_df else pd.Series(dtype=float)
        hit2_series = pd.to_numeric(day_df["hit_at_2"], errors="coerce").fillna(0.0) if "hit_at_2" in day_df else pd.Series(dtype=float)
        row_metrics["hit_at_1"] = float(hit1_series.mean()) if not hit1_series.empty else 0.0
        row_metrics["hit_at_2"] = float(hit2_series.mean()) if not hit2_series.empty else 0.0
    else:
        row_metrics["hit_at_1"] = 0.0
        row_metrics["hit_at_2"] = 0.0
    return day_df, summary, row_metrics


def _evaluate_one_mode(
    *,
    mode: str,
    raw: pd.DataFrame,
    out_prefix: Path,
    seeds: list[int],
    args: argparse.Namespace,
    bucket_configs: dict[str, BucketConfig],
    model_params: dict[str, Any],
) -> dict[str, Any]:
    if mode == "positive_combined":
        bucket_order = POSITIVE_DAY_BUCKET_ORDER
        summary_key_by_bucket = POSITIVE_SUMMARY_KEY_BY_BUCKET
        bucket_mode = "positive_combined"
    else:
        bucket_order = DAY_BUCKET_ORDER
        summary_key_by_bucket = SUMMARY_KEY_BY_BUCKET
        bucket_mode = "atype3"

    d = add_mitoya_bucket_features(aggregate_mode(raw, mode=mode), bucket_mode=bucket_mode)
    override_buckets = parse_position_bucket_overrides(getattr(args, "position_buckets", ""))
    position_feature_used_by_bucket = {
        bucket_name: should_use_position_features(bucket_name, bool(args.use_position_features), override_buckets)
        for bucket_name in bucket_order
    }
    day_raw, s_raw, raw_row_metrics = run_mode_bucketed(
        dataset=d,
        seeds=seeds,
        test_days=args.test_days,
        warmup_days=args.warmup_days,
        bucket_configs=bucket_configs,
        bucket_order=bucket_order,
        summary_key_by_bucket=summary_key_by_bucket,
        diff_col="total_diff_coins",
        model_params=model_params,
        position_feature_used_by_bucket=position_feature_used_by_bucket,
        max_blocks=int(args.max_blocks),
        n_boot=int(args.n_boot),
    )
    day_focus, s_focus, focus_row_metrics = run_mode_bucketed(
        dataset=d,
        seeds=seeds,
        test_days=args.test_days,
        warmup_days=args.warmup_days,
        bucket_configs=bucket_configs,
        bucket_order=bucket_order,
        summary_key_by_bucket=summary_key_by_bucket,
        diff_col="total_diff_coins_focus",
        model_params=model_params,
        position_feature_used_by_bucket=position_feature_used_by_bucket,
        max_blocks=int(args.max_blocks),
        n_boot=int(args.n_boot),
    )
    day_raw.to_csv(out_prefix.with_name(out_prefix.name + f"_{mode}_raw_days.csv"), index=False, encoding="utf-8-sig")
    day_focus.to_csv(out_prefix.with_name(out_prefix.name + f"_{mode}_focus_days.csv"), index=False, encoding="utf-8-sig")

    payload: dict[str, Any] = {
        "raw": s_raw,
        "focus_nonA": s_focus,
        "raw_row_metrics": raw_row_metrics,
        "focus_row_metrics": focus_row_metrics,
        "raw_specific_dd": summarize_specific_dd_days(day_raw),
        "bucket_order": list(bucket_order),
        "summary_key_by_bucket": dict(summary_key_by_bucket),
        "bucket_summary_keys": [summary_key_by_bucket[bucket_name] for bucket_name in bucket_order],
        "position_feature_used_by_bucket": {
            bucket_name: bool(position_feature_used_by_bucket.get(bucket_name, False)) for bucket_name in bucket_order
        },
        "position_feature_used_by_summary_key": {
            summary_key_by_bucket[bucket_name]: bool(position_feature_used_by_bucket.get(bucket_name, False))
            for bucket_name in bucket_order
        },
    }
    for bucket_name in bucket_order:
        summary_key = summary_key_by_bucket[bucket_name]
        total_dates = int(pd.to_datetime(d.loc[d["day_bucket"].eq(bucket_name), "date"]).nunique())
        holdout_dates = int(pd.to_datetime(day_raw.loc[day_raw["day_bucket"].eq(bucket_name), "date"]).nunique())
        payload["raw"] = add_bucket_observation_counts(
            payload["raw"],
            bucket_key=summary_key,
            total_dates=total_dates,
            holdout_dates=holdout_dates,
        )
        payload["focus_nonA"] = add_bucket_observation_counts(
            payload["focus_nonA"],
            bucket_key=summary_key,
            total_dates=total_dates,
            holdout_dates=holdout_dates,
        )
    _BASE.logger.info("[%s] raw=%.4f focus=%.4f", mode, s_raw["overall"]["mean"], s_focus["overall"]["mean"])
    return payload


def _build_focus_ranking(results: dict[str, Any], modes: list[str]) -> list[dict[str, float | str]]:
    ranking: list[dict[str, float | str]] = []
    for mode in modes:
        mode_payload = results["modes"][mode]
        bucket_keys = [key for key in mode_payload.get("bucket_order", []) if key != "others"]
        ranking.append(
            {
                "mode": mode,
                "focus_overall_mean": float(mode_payload["focus_nonA"]["overall"]["mean"]),
                "focus_bucket_1_mean": float(mode_payload["focus_nonA"][mode_payload["summary_key_by_bucket"][bucket_keys[0]]]["mean"]) if len(bucket_keys) >= 1 else 0.0,
                "focus_bucket_2_mean": float(mode_payload["focus_nonA"][mode_payload["summary_key_by_bucket"][bucket_keys[1]]]["mean"]) if len(bucket_keys) >= 2 else 0.0,
                "focus_bucket_3_mean": float(mode_payload["focus_nonA"][mode_payload["summary_key_by_bucket"][bucket_keys[2]]]["mean"]) if len(bucket_keys) >= 3 else 0.0,
                "focus_bucket_4_mean": float(mode_payload["focus_nonA"][mode_payload["summary_key_by_bucket"][bucket_keys[3]]]["mean"]) if len(bucket_keys) >= 4 else 0.0,
                "focus_hit_at_1": float(mode_payload["focus_nonA"]["overall"]["hit_at_1"]),
                "focus_hit_at_2": float(mode_payload["focus_nonA"]["overall"]["hit_at_2"]),
                "focus_auc": float(mode_payload["focus_row_metrics"]["auc"]),
                "focus_ndcg_at_2": float(mode_payload["focus_row_metrics"]["ndcg_at_2"]),
                "focus_ndcg_at_3": float(mode_payload["focus_row_metrics"]["ndcg_at_3"]),
                "focus_played_rate": float(mode_payload["focus_nonA"]["overall"]["played_rate"]),
                "raw_overall_mean": float(mode_payload["raw"]["overall"]["mean"]),
                "raw_hit_at_1": float(mode_payload["raw"]["overall"]["hit_at_1"]),
                "raw_hit_at_2": float(mode_payload["raw"]["overall"]["hit_at_2"]),
                "raw_auc": float(mode_payload["raw_row_metrics"]["auc"]),
                "raw_ndcg_at_2": float(mode_payload["raw_row_metrics"]["ndcg_at_2"]),
                "raw_ndcg_at_3": float(mode_payload["raw_row_metrics"]["ndcg_at_3"]),
                "raw_played_rate": float(mode_payload["raw"]["overall"]["played_rate"]),
            }
        )
    ranking.sort(
        key=lambda x: (
            float(x["focus_overall_mean"]),
            float(x.get("focus_bucket_1_mean", 0.0)),
            float(x.get("focus_bucket_2_mean", 0.0)),
        ),
        reverse=True,
    )
    return ranking


def build_agg_comparison_rows(results: dict[str, Any], modes: list[str]) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for mode in modes:
        bucket_keys = ["overall", *results["modes"][mode]["bucket_summary_keys"]]
        for bucket in bucket_keys:
            payload = results["modes"][mode]["raw"][bucket]
            position_feature_used = None
            if bucket != "overall":
                position_feature_used = bool(
                    results["modes"][mode].get("position_feature_used_by_summary_key", {}).get(bucket, False)
                )
            rows.append(
                {
                    "mode": mode,
                    "bucket": bucket,
                    "mean_diff": float(payload["mean"]),
                    "hit_at_2": float(payload["hit_at_2"]),
                    "position_feature_used": position_feature_used,
                }
            )
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Split-rule (Mitoya atype3) walk-forward comparison")
    p.add_argument("--output-prefix", default="db/experiments/tail_ltr_mitoya_wf")
    p.add_argument("--output-json", default="", help="Optional explicit output JSON path. Defaults to <output-prefix>.json")
    p.add_argument("--db-path", default="", help="DB path (optional)")
    p.add_argument("--db-glob", default="みとや大森町店.db", help="DB auto-detect glob pattern used when --db-path is empty")
    p.add_argument("--seeds", default="42,77,123,202,303,404,505,606")
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--warmup-days", type=int, default=56)
    p.add_argument("--min-train-days-x-day", type=int, default=10)
    p.add_argument(
        "--min-train-days-strong-zorome",
        type=int,
        default=5,
        help="strong_zorome bucket の最小学習日数。年最大12日のため 5 をデフォルトとする。",
    )
    p.add_argument("--min-train-days-month-end-30", type=int, default=5)
    p.add_argument("--min-train-days-dd-11", type=int, default=5)
    p.add_argument("--min-train-days-others", type=int, default=20)
    p.add_argument("--windows-x-day", default="full_2025")
    p.add_argument("--lambdas-x-day", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-x-day", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--windows-strong-zorome", default="full_2025")
    p.add_argument("--lambdas-strong-zorome", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-strong-zorome", default="0.0,0.1,0.2,0.3,0.4")
    p.add_argument("--q-grid-strong-zorome-override", type=float, default=-1.0)
    p.add_argument("--windows-others", default="recent_60d,full_2025")
    p.add_argument("--lambdas-others", default="0.75,1.0,1.25")
    p.add_argument("--q-grid-others", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
    p.add_argument("--a-weight", type=float, default=1.0, help="A-type weight for focus objective")
    p.add_argument("--non-a-weight", type=float, default=1.0, help="Non-A weight for focus objective")
    p.add_argument("--a-gate-weight", type=float, default=1.0, help="Retained for compatibility; unused in atype3 mode")
    p.add_argument("--non-a-gate-weight", type=float, default=1.0, help="Retained for compatibility; unused in atype3 mode")
    p.add_argument(
        "--use-position-features",
        action="store_true",
        default=False,
        help="Include Mitoya position features (mean_section_rank, mean_physical_corner, pct_strong_section).",
    )
    p.add_argument(
        "--position-buckets",
        type=str,
        default="",
        help="Comma-separated list of buckets to force-enable position features. Overrides POSITION_FEATURES_BY_BUCKET for named buckets only.",
    )
    p.add_argument("--modes", default="atype3", help="Comma-separated modes to evaluate (atype3,N_only,positive_combined)")
    p.add_argument("--enable-moe", action="store_true", help="Unused for Mitoya atype3 mode")
    p.add_argument("--max-blocks", type=int, default=0, help="Max number of test blocks per seed (0=unlimited)")
    p.add_argument("--smoke", action="store_true", help="Shortcut for a short run (equivalent to --max-blocks 1 when unset)")
    p.add_argument("--n-boot", type=int, default=10000, help="Bootstrap resample count for CI (smaller is faster)")
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU for XGBoost training")
    p.add_argument(
        "--gpu-backend",
        choices=["cuda", "gpu_hist"],
        default="cuda",
        help="GPU backend mode: 'cuda' (tree_method=hist+device=cuda) or 'gpu_hist' (legacy)",
    )
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    return p

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _BASE.configure_logging(args.log_level)
    if bool(args.smoke) and int(args.max_blocks) == 0:
        args.max_blocks = 1
    out_prefix = Path(args.output_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.output_json) if args.output_json else out_prefix.with_suffix(".json")
    out_json.parent.mkdir(parents=True, exist_ok=True)

    seeds = _BASE.parse_csv_ints(args.seeds)
    model_params: dict[str, Any] = _BASE._build_model_params(use_gpu=args.use_gpu, gpu_backend=args.gpu_backend)

    raw = build_base_rows_mitoya(
        db_path=_resolve_mitoya_db_path(args.db_path),
        a_weight=float(args.a_weight),
        non_a_weight=float(args.non_a_weight),
    )

    allowed_modes = {"atype3", "N_only", "positive_combined"}
    modes = _BASE.parse_csv_strs(args.modes)
    if not modes:
        modes = ["atype3"]
    unknown_modes = [m for m in modes if m not in allowed_modes]
    if unknown_modes:
        raise ValueError(f"Unknown modes: {unknown_modes}. Allowed: {sorted(allowed_modes)}")
    results: dict[str, Any] = {"config": vars(args), "modes": {}}

    for mode in modes:
        bucket_configs = _build_bucket_configs(args, mode=mode)
        results["modes"][mode] = _evaluate_one_mode(
            mode=mode,
            raw=raw,
            out_prefix=out_prefix,
            seeds=seeds,
            args=args,
            bucket_configs=bucket_configs,
            model_params=model_params,
        )

    if "atype3" in results["modes"]:
        rebucket_rows = summary_to_rows(
            results["modes"]["atype3"]["raw"],
            position_feature_used_by_summary_key=results["modes"]["atype3"].get("position_feature_used_by_summary_key", {}),
        )
        pd.DataFrame(rebucket_rows).to_csv(
            out_prefix.with_name("mitoya_rebucket_summary.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        specific_dd_rows = results["modes"]["atype3"].get("raw_specific_dd", [])
        pd.DataFrame(specific_dd_rows).to_csv(
            out_prefix.with_name("mitoya_specific_dd_summary.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    ranking = _build_focus_ranking(results, modes)
    results["ranking_focus_nonA"] = ranking
    results["recommended_mode_focus_nonA"] = ranking[0]["mode"] if ranking else ""

    if modes:
        pd.DataFrame(build_agg_comparison_rows(results, modes)).to_csv(
            out_prefix.with_name("mitoya_agg_comparison.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    _BASE.logger.info("Saved: %s", out_json)
    _BASE.logger.info(
        "%s",
        json.dumps(
            {
                "recommended_mode_focus_nonA": results["recommended_mode_focus_nonA"],
                "ranking_focus_nonA": ranking,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
