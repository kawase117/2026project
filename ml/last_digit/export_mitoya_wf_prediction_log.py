from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from ml.last_digit.mitoya_segmentation import aggregate_mode_mitoya, build_base_rows_mitoya
from ml.last_digit.tail_ltr_mitoya_wf import (
    _BASE,
    _build_bucket_configs,
    add_mitoya_bucket_features,
    select_best_bucket_candidates,
)
from ml.last_digit.tail_ltr_mitoya_wf import build_parser as build_workflow_parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Export Mitoya walk-forward prediction log with actual top digits")
    p.add_argument("--output", default="db/experiments/mitoya_wf_prediction_log_seed42.csv")
    p.add_argument("--db-path", default="", help="Optional explicit DB path; defaults to the Mitoya DB under db/")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--warmup-days", type=int, default=56)
    p.add_argument("--test-days", type=int, default=14)
    p.add_argument("--use-gpu", action="store_true", help="Enable GPU learners when available")
    p.add_argument(
        "--gpu-backend",
        choices=["cuda", "gpu_hist"],
        default="cuda",
        help="GPU backend mode used when --use-gpu is set",
    )
    p.add_argument("--log-level", default="INFO")
    return p


def _resolve_mitoya_db_path(raw: str) -> Path:
    if raw:
        return Path(raw)
    candidates = sorted(p for p in Path("db").glob("*.db") if "みとや" in p.name)
    if not candidates:
        raise FileNotFoundError("Mitoya DB was not found under db/")
    return candidates[0]


def _sort_actual_day(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["date", "total_diff_coins", "last_digit"], ascending=[True, False, True]).reset_index(drop=True)


def _sort_pred_day(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["date", "pred", "last_digit"], ascending=[True, False, True]).reset_index(drop=True)


def _build_day_rows_for_bucket(
    *,
    dataset: pd.DataFrame,
    features: list[str],
    seed: int,
    test_start: pd.Timestamp,
    test_end: pd.Timestamp,
    bucket_name: str,
    bucket_q_grid: list[float],
    selected_result: dict[str, Any],
    model_params: dict[str, Any],
) -> list[dict[str, Any]]:
    candidate = selected_result["candidate"]
    dts = pd.to_datetime(dataset["date"])
    tr_start, tr_end = _BASE.build_train_window(candidate.window_name, test_start)
    train = dataset[(dts >= tr_start) & (dts <= tr_end)].copy()
    test = dataset[(dts >= test_start) & (dts <= test_end)].copy()

    train = train[train["day_bucket"].eq(bucket_name)].copy()
    test = test[test["day_bucket"].eq(bucket_name)].copy()
    if train["date"].nunique() == 0 or test.empty:
        return []

    sort_cols = ["date", "entity_key"] if "entity_key" in test.columns else ["date"]
    test_sorted = test.sort_values(sort_cols).reset_index(drop=True).copy()
    _, tst_df, _ = _BASE.train_and_predict_fold(
        train_df=train,
        test_df=test_sorted,
        target="is_top_2",
        features=features,
        decay_lambda=candidate.decay_lambda,
        random_state=seed,
        model_params=model_params,
        temperature_candidates=_BASE.improved.CalibrationConfig().temperature_candidates,
        blend_weights=_BASE.improved.CalibrationConfig().blend_weights,
        q_grid=bucket_q_grid,
        k=2,
    )
    tst_df = tst_df.copy()
    tst_df["last_digit"] = test_sorted["last_digit"].to_numpy()

    pred_work = _sort_pred_day(tst_df)
    actual_work = _sort_actual_day(test_sorted)

    rows: list[dict[str, Any]] = []
    for date_value, pred_group in pred_work.groupby("date", sort=False):
        actual_group = actual_work[actual_work["date"].eq(date_value)].copy()
        if actual_group.empty:
            continue

        pred_top = pred_group.head(2)
        actual_top = actual_group.head(2)
        actual_top2_set = set(actual_top["last_digit"].astype(str).tolist())

        predicted_top1_digit = int(pred_top.iloc[0]["last_digit"]) if len(pred_top) >= 1 else None
        predicted_top2_digit = int(pred_top.iloc[1]["last_digit"]) if len(pred_top) >= 2 else None
        actual_top1_digit = int(actual_top.iloc[0]["last_digit"]) if len(actual_top) >= 1 else None
        actual_top2_digit = int(actual_top.iloc[1]["last_digit"]) if len(actual_top) >= 2 else None

        hit_at_1 = int(str(predicted_top1_digit) in actual_top2_set) if predicted_top1_digit is not None else 0
        hit_at_2 = int(
            any(str(x) in actual_top2_set for x in [predicted_top1_digit, predicted_top2_digit] if x is not None)
        )

        rows.append(
            {
                "date": pd.Timestamp(date_value).strftime("%Y-%m-%d"),
                "day_bucket": bucket_name,
                "predicted_top1_digit": predicted_top1_digit,
                "predicted_top2_digit": predicted_top2_digit,
                "actual_top1_digit": actual_top1_digit,
                "actual_top1_diff": float(actual_top.iloc[0]["total_diff_coins"]) if len(actual_top) >= 1 else None,
                "actual_top2_digit": actual_top2_digit,
                "actual_top2_diff": float(actual_top.iloc[1]["total_diff_coins"]) if len(actual_top) >= 2 else None,
                "hit_at_1": hit_at_1,
                "hit_at_2": hit_at_2,
            }
        )

    return rows


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _BASE.configure_logging(args.log_level)

    wf_args = build_workflow_parser().parse_args([])
    bucket_configs = _build_bucket_configs(wf_args)
    db_path = _resolve_mitoya_db_path(args.db_path)
    model_params = _BASE._build_model_params(use_gpu=bool(args.use_gpu), gpu_backend=str(args.gpu_backend))

    raw = build_base_rows_mitoya(db_path=db_path, a_weight=1.0, non_a_weight=1.0)
    dataset = add_mitoya_bucket_features(aggregate_mode_mitoya(raw, mode="atype3"))
    valid_cfg = _BASE.improved.build_fixed_split_configs(dataset)["regime_3_fixed_split"]
    valid_dates = sorted(pd.to_datetime(dataset["date"].unique()))
    valid_dates = [
        x for x in valid_dates if pd.Timestamp(valid_cfg["valid_start"]) <= x <= pd.Timestamp(valid_cfg["valid_end"])
    ]
    if not valid_dates:
        raise RuntimeError("No valid holdout dates were found for Mitoya.")

    features = _BASE.improved.get_numeric_features(dataset)
    features = [f for f in features if f not in {"is_top_2"}]

    rows: list[dict[str, Any]] = []
    idx = max(0, int(args.warmup_days))
    seed = int(args.seed)
    bucket_order = tuple(bucket_configs.keys())

    while idx < len(valid_dates):
        block = valid_dates[idx : idx + int(args.test_days)]
        if not block:
            break
        test_start = block[0]
        test_end = block[-1]

        selected = select_best_bucket_candidates(
            dataset=dataset,
            features=features,
            seed=seed,
            test_start=test_start,
            test_end=test_end,
            bucket_configs=bucket_configs,
            diff_col="total_diff_coins",
            model_params=model_params,
        )
        if selected is None:
            idx += int(args.test_days)
            continue

        for bucket_name in bucket_order:
            selected_result = selected.get(bucket_name)
            if selected_result is None:
                continue
            bucket_rows = _build_day_rows_for_bucket(
                dataset=dataset,
                features=features,
                seed=seed,
                test_start=test_start,
                test_end=test_end,
                bucket_name=bucket_name,
                bucket_q_grid=bucket_configs[bucket_name].q_grid,
                selected_result=selected_result,
                model_params=model_params,
            )
            rows.extend(bucket_rows)

        idx += int(args.test_days)

    if not rows:
        raise RuntimeError("No prediction rows were produced for the requested holdout range.")

    out = pd.DataFrame(rows).sort_values(["date", "day_bucket"]).reset_index(drop=True)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    _BASE.logger.info("Wrote %d rows to %s", len(out), out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
