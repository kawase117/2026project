from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from ml.experiments.jug_rb_setting_prediction.config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_DBS, HALL_SLUGS  # noqa: E402
else:  # pragma: no cover - exercised via package imports in tests
    from .config import DEFAULT_HALL, DEFAULT_OUTPUT_ROOT, HALL_DBS, HALL_SLUGS  # noqa: E402

STAGE3_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "G",
    "rb",
    "bb",
    "p_high",
    "e_setting",
    "e_payout",
    "b_machine_180d",
]

STAGE5_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "pct_family",
]

DB_REQUIRED_COLUMNS = [
    "date",
    "machine_number",
    "machine_name",
    "games_normalized",
    "diff_coins_normalized",
]

METHOD_ORDER = ("B0", "B1", "B1R")
EVAL_START_DATE = pd.Timestamp("2026-01-01")
SELECTION_COLUMNS = [
    "date",
    "method",
    "selected_rank",
    "machine_number",
    "machine_name",
    "score",
    "G",
    "rb",
    "bb",
    "p_high",
    "e_setting",
    "e_payout",
    "games_normalized",
    "diff_coins_normalized",
    "pay_rate_individual",
    "b_machine_180d",
    "b_rank_90d",
    "b_rank_180d",
]
SUMMARY_COLUMNS = [
    "method",
    "n_eval_days",
    "n_skipped_lt10",
    "mean_selected_pay_rate_weighted",
    "mean_hall_pay_rate_weighted",
    "mean_lift_pp_weighted",
    "mean_selected_pay_rate_equal_weight",
    "mean_hall_pay_rate_equal_weight",
    "mean_lift_pp_equal_weight",
    "mean_p_high_top3",
    "mean_spearman",
    "n_selected_rows",
    "train_start",
    "train_end",
    "eval_start",
    "eval_end",
    "note",
]


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _resolve_stage3_csv(hall: str, stage3_csv: Path | None = None) -> Path:
    if stage3_csv is not None:
        return Path(stage3_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage3_features.csv"


def _resolve_stage5_csv(hall: str, stage5_csv: Path | None = None) -> Path:
    if stage5_csv is not None:
        return Path(stage5_csv)
    return DEFAULT_OUTPUT_ROOT / _hall_slug(hall) / "stage5_rank_daily.csv"


def _resolve_db_path(hall: str, db_path: Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    try:
        return HALL_DBS[hall]
    except KeyError as exc:  # pragma: no cover - argparse validates hall
        raise KeyError(f"unknown hall: {hall}") from exc


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, encoding="utf-8-sig")


def _load_db_frame(db_path: Path) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                date,
                machine_number,
                machine_name,
                games_normalized,
                diff_coins_normalized
            FROM machine_detailed_results
            """,
            conn,
        )
    missing = [column for column in DB_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"machine_detailed_results is missing required columns: {missing}")
    return frame


def _prepare_stage3(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    missing = [column for column in STAGE3_REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        raise ValueError(f"stage3 frame is missing required columns: {missing}")
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    for column in ("G", "rb", "bb", "p_high", "e_setting", "e_payout", "b_machine_180d"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "G", "rb", "bb", "p_high"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["machine_name"] = work["machine_name"].astype(str)
    work["hall"] = hall
    return work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)


def _prepare_stage5(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    missing = [column for column in STAGE5_REQUIRED_COLUMNS if column not in work.columns]
    if missing:
        raise ValueError(f"stage5 frame is missing required columns: {missing}")
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["pct_family"] = pd.to_numeric(work["pct_family"], errors="coerce")
    work = work.dropna(subset=["date_dt", "machine_number", "machine_name", "pct_family"]).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["machine_name"] = work["machine_name"].astype(str)
    work["hall"] = hall
    return work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)


def _prepare_db_frame(frame: pd.DataFrame, *, hall: str) -> pd.DataFrame:
    work = frame.copy()
    for column in ("date", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"):
        if column not in work.columns:
            raise ValueError(f"db frame is missing required column: {column}")
    work["date"] = work["date"].astype(str)
    work["date_dt"] = pd.to_datetime(work["date"], format="%Y%m%d", errors="coerce")
    work["machine_number"] = pd.to_numeric(work["machine_number"], errors="coerce")
    work["games_normalized"] = pd.to_numeric(work["games_normalized"], errors="coerce")
    work["diff_coins_normalized"] = pd.to_numeric(work["diff_coins_normalized"], errors="coerce")
    work = work.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    work["machine_number"] = work["machine_number"].astype(int)
    work["machine_name"] = work["machine_name"].astype(str)
    work["hall"] = hall
    work["pay_rate_individual"] = (
        (3.0 * work["games_normalized"] + work["diff_coins_normalized"]) / (3.0 * work["games_normalized"])
    ) * 100.0
    return work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)


def _merge_frames(stage3_frame: pd.DataFrame, stage5_frame: pd.DataFrame, db_frame: pd.DataFrame) -> pd.DataFrame:
    merged = stage3_frame.merge(
        stage5_frame.loc[:, ["date", "machine_number", "machine_name", "pct_family", "hall"]],
        on=["date", "machine_number", "machine_name", "hall"],
        how="inner",
        validate="one_to_one",
    )
    merged = merged.merge(
        db_frame.loc[
            :,
            [
                "date",
                "machine_number",
                "machine_name",
                "games_normalized",
                "diff_coins_normalized",
                "pay_rate_individual",
                "hall",
            ],
        ],
        on=["date", "machine_number", "machine_name", "hall"],
        how="inner",
        validate="one_to_one",
    )
    if merged.empty:
        raise ValueError("No rows remained after merging stage3, stage5, and db frames")
    return merged.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)


def _add_b_rank_features(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.sort_values(["machine_number", "date_dt", "machine_name"], kind="mergesort").copy()

    def _rolling_shrink(group: pd.DataFrame, window_days: int) -> pd.Series:
        indexed = group.set_index("date_dt")["pct_family"]
        rolling = indexed.rolling(f"{window_days}D", closed="left").agg(["mean", "count"])
        mean = rolling["mean"].fillna(0.5)
        count = rolling["count"].fillna(0.0)
        weight = count / (count + 20.0)
        shrunk = weight * mean + (1.0 - weight) * 0.5
        return pd.Series(shrunk.to_numpy(dtype=float), index=group.index, dtype=float)

    work["b_rank_90d"] = work.groupby("machine_number", group_keys=False, sort=False).apply(
        lambda group: _rolling_shrink(group, 90)
    )
    work["b_rank_180d"] = work.groupby("machine_number", group_keys=False, sort=False).apply(
        lambda group: _rolling_shrink(group, 180)
    )
    return work.sort_values(["date_dt", "machine_number", "machine_name"], kind="mergesort").reset_index(drop=True)


def _deterministic_seed(date_dt: pd.Timestamp, *, hall: str, method: str) -> int:
    base = int(date_dt.strftime("%Y%m%d"))
    hall_token = sum(ord(ch) for ch in hall)
    method_token = sum(ord(ch) for ch in method)
    return (base * 97 + hall_token * 13 + method_token * 17) % (2**32 - 1)


def _rank_day(
    day_rows: pd.DataFrame, *, method: str, score: pd.Series | None = None, ascending: bool = False
) -> pd.DataFrame:
    ranked = day_rows.copy().reset_index(drop=True)
    if method == "B0":
        rng = np.random.default_rng(
            _deterministic_seed(ranked["date_dt"].iloc[0], hall=str(ranked["hall"].iloc[0]), method=method)
        )
        ranked["score"] = rng.random(len(ranked))
        ranked = ranked.sort_values(["score", "machine_number"], ascending=[False, True], kind="mergesort").reset_index(
            drop=True
        )
    else:
        if score is None:
            raise ValueError("score is required for deterministic ranking")
        ranked["score"] = score.to_numpy(dtype=float)
        ranked = ranked.sort_values(
            ["score", "machine_number"], ascending=[ascending, True], kind="mergesort", na_position="last"
        ).reset_index(drop=True)
    ranked["selected_rank"] = np.arange(1, len(ranked) + 1, dtype=int)
    return ranked


def _real_money_metrics(ranked: pd.DataFrame, *, method: str, skipped_nan_rows: int = 0) -> dict[str, object]:
    selected = ranked.head(3).copy()

    def _pay_rate(frame: pd.DataFrame) -> float:
        games_sum = pd.to_numeric(frame["games_normalized"], errors="coerce").sum()
        diff_sum = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce").sum()
        if not np.isfinite(games_sum) or games_sum <= 0:
            return float("nan")
        return float(((3.0 * games_sum + diff_sum) / (3.0 * games_sum)) * 100.0)

    def _equal_weight(frame: pd.DataFrame) -> float:
        if frame.empty:
            return float("nan")
        return float(pd.to_numeric(frame["pay_rate_individual"], errors="coerce").mean())

    selected_weighted = _pay_rate(selected)
    hall_weighted = _pay_rate(ranked)
    selected_equal = _equal_weight(selected)
    hall_equal = _equal_weight(ranked)
    lift_weighted = (
        selected_weighted - hall_weighted
        if np.isfinite(selected_weighted) and np.isfinite(hall_weighted)
        else float("nan")
    )
    lift_equal = (
        selected_equal - hall_equal if np.isfinite(selected_equal) and np.isfinite(hall_equal) else float("nan")
    )
    spearman_value = float("nan")
    if (
        len(ranked) >= 2
        and ranked["score"].nunique(dropna=True) >= 2
        and ranked["pay_rate_individual"].nunique(dropna=True) >= 2
    ):
        rho, _ = spearmanr(ranked["score"], ranked["pay_rate_individual"])
        if np.isfinite(rho):
            spearman_value = float(rho)
    return {
        "date": ranked["date"].iloc[0] if not ranked.empty else "",
        "method": method,
        "n_candidates": int(len(ranked)),
        "n_selected": int(len(selected)),
        "selected_games_sum": float(pd.to_numeric(selected["games_normalized"], errors="coerce").sum())
        if not selected.empty
        else float("nan"),
        "selected_diff_sum": float(pd.to_numeric(selected["diff_coins_normalized"], errors="coerce").sum())
        if not selected.empty
        else float("nan"),
        "hall_games_sum": float(pd.to_numeric(ranked["games_normalized"], errors="coerce").sum())
        if not ranked.empty
        else float("nan"),
        "hall_diff_sum": float(pd.to_numeric(ranked["diff_coins_normalized"], errors="coerce").sum())
        if not ranked.empty
        else float("nan"),
        "selected_pay_rate_weighted": selected_weighted,
        "hall_pay_rate_weighted": hall_weighted,
        "lift_pp_weighted": lift_weighted,
        "selected_pay_rate_equal_weight": selected_equal,
        "hall_pay_rate_equal_weight": hall_equal,
        "lift_pp_equal_weight": lift_equal,
        "mean_p_high_top3": float(selected["p_high"].mean()) if not selected.empty else float("nan"),
        "spearman": spearman_value,
        "skipped_nan_rows": int(skipped_nan_rows),
    }


def _moving_block_bootstrap_ci(
    values: np.ndarray, *, n_bootstrap: int = 2000, block_size: int = 7, seed: int = 42
) -> dict[str, float]:
    clean = np.asarray(values, dtype=float)
    clean = clean[~np.isnan(clean)]
    if len(clean) == 0:
        return {"mean": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": 0}
    if len(clean) == 1:
        value = float(clean[0])
        return {"mean": value, "ci_lower": value, "ci_upper": value, "n": 1}

    rng = np.random.default_rng(seed)
    boot_means: list[float] = []
    for _ in range(n_bootstrap):
        sample: list[float] = []
        while len(sample) < len(clean):
            start = int(rng.integers(0, len(clean)))
            for offset in range(block_size):
                sample.append(float(clean[(start + offset) % len(clean)]))
                if len(sample) >= len(clean):
                    break
        boot_means.append(float(np.mean(sample[: len(clean)])))
    return {
        "mean": float(np.mean(clean)),
        "ci_lower": float(np.percentile(boot_means, 2.5)),
        "ci_upper": float(np.percentile(boot_means, 97.5)),
        "n": int(len(clean)),
    }


def _score_day(day_rows: pd.DataFrame, *, method: str) -> pd.DataFrame:
    if method == "B0":
        return _rank_day(day_rows, method=method)
    if method == "B1":
        return _rank_day(day_rows, method=method, score=day_rows["b_machine_180d"], ascending=False)
    if method == "B1R":
        return _rank_day(day_rows, method=method, score=day_rows["b_rank_180d"], ascending=False)
    raise ValueError(f"unknown method: {method}")


def _train_eval_days(
    frame: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, object]], dict[str, list[float]], int]:
    method_rows: dict[str, list[pd.DataFrame]] = {method: [] for method in METHOD_ORDER}
    summaries: list[dict[str, object]] = []
    daily_metric_store: dict[str, list[float]] = {method: [] for method in METHOD_ORDER}
    n_skipped_lt10 = 0

    eval_frame = frame.loc[frame["date_dt"].ge(EVAL_START_DATE)].copy()
    for date_dt, day_rows in eval_frame.groupby("date_dt", sort=True):
        if len(day_rows) < 10:
            n_skipped_lt10 += 1
            continue
        for method in METHOD_ORDER:
            ranked = _score_day(day_rows, method=method)
            if ranked.empty:
                continue
            summary_row = _real_money_metrics(ranked, method=method)
            summaries.append(summary_row)
            daily_metric_store[method].append(float(summary_row["lift_pp_weighted"]))
            selection = ranked.head(3).copy()
            selection["method"] = method
            selection["selected_rank"] = np.arange(1, len(selection) + 1, dtype=int)
            selection = selection.loc[:, SELECTION_COLUMNS].copy()
            method_rows[method].append(selection)

    selection_tables = {
        method: pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=SELECTION_COLUMNS)
        for method, parts in method_rows.items()
    }
    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["method", "date"], kind="mergesort").reset_index(drop=True)
    return selection_tables, summaries, daily_metric_store, n_skipped_lt10


def _build_summary(
    *,
    hall: str,
    summary_rows: list[dict[str, object]],
    n_skipped_lt10: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if summary_rows:
        summary_frame = pd.DataFrame(summary_rows)
    else:
        summary_frame = pd.DataFrame(columns=SUMMARY_COLUMNS)
    for method in METHOD_ORDER:
        method_frame = (
            summary_frame.loc[summary_frame["method"].eq(method)].copy() if not summary_frame.empty else pd.DataFrame()
        )
        if method_frame.empty:
            rows.append(
                {
                    "method": method,
                    "n_eval_days": 0,
                    "n_skipped_lt10": 0,
                    "mean_selected_pay_rate_weighted": np.nan,
                    "mean_hall_pay_rate_weighted": np.nan,
                    "mean_lift_pp_weighted": np.nan,
                    "mean_selected_pay_rate_equal_weight": np.nan,
                    "mean_hall_pay_rate_equal_weight": np.nan,
                    "mean_lift_pp_equal_weight": np.nan,
                    "mean_p_high_top3": np.nan,
                    "mean_spearman": np.nan,
                    "n_selected_rows": 0,
                    "train_start": "",
                    "train_end": "",
                    "eval_start": "",
                    "eval_end": "",
                    "note": "no evaluated days",
                }
            )
            continue
        rows.append(
            {
                "method": method,
                "n_eval_days": int(len(method_frame)),
                "n_skipped_lt10": int(n_skipped_lt10),
                "mean_selected_pay_rate_weighted": float(method_frame["selected_pay_rate_weighted"].mean()),
                "mean_hall_pay_rate_weighted": float(method_frame["hall_pay_rate_weighted"].mean()),
                "mean_lift_pp_weighted": float(method_frame["lift_pp_weighted"].mean()),
                "mean_selected_pay_rate_equal_weight": float(method_frame["selected_pay_rate_equal_weight"].mean()),
                "mean_hall_pay_rate_equal_weight": float(method_frame["hall_pay_rate_equal_weight"].mean()),
                "mean_lift_pp_equal_weight": float(method_frame["lift_pp_equal_weight"].mean()),
                "mean_p_high_top3": float(method_frame["mean_p_high_top3"].mean()),
                "mean_spearman": float(method_frame["spearman"].mean()),
                "n_selected_rows": int(method_frame["n_selected"].sum()),
                "train_start": "",
                "train_end": "",
                "eval_start": str(method_frame["date"].min()),
                "eval_end": str(method_frame["date"].max()),
                "note": "B1R uses shrunk rolling pct_family; eval starts 2026-01-01",
            }
        )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def _build_bootstrap_json(summary_rows: list[dict[str, object]]) -> dict[str, object]:
    summary_frame = pd.DataFrame(summary_rows)
    if summary_frame.empty:
        comparisons = {
            "B1R_minus_B0": _moving_block_bootstrap_ci(np.array([], dtype=float)),
            "B1R_minus_B1": _moving_block_bootstrap_ci(np.array([], dtype=float)),
            "B1_minus_B0": _moving_block_bootstrap_ci(np.array([], dtype=float)),
        }
        return {
            "metric": "lift_pp_weighted",
            "block_size": 7,
            "n_bootstrap": 2000,
            "comparisons": comparisons,
        }
    daily_lifts = {
        method: summary_frame.loc[summary_frame["method"].eq(method), "lift_pp_weighted"].astype(float).to_numpy()
        if not summary_frame.empty
        else np.array([], dtype=float)
        for method in METHOD_ORDER
    }
    comparisons = {
        "B1R_minus_B0": _moving_block_bootstrap_ci(
            daily_lifts["B1R"] - daily_lifts["B0"]
            if len(daily_lifts["B1R"]) and len(daily_lifts["B0"])
            else np.array([], dtype=float)
        ),
        "B1R_minus_B1": _moving_block_bootstrap_ci(
            daily_lifts["B1R"] - daily_lifts["B1"]
            if len(daily_lifts["B1R"]) and len(daily_lifts["B1"])
            else np.array([], dtype=float)
        ),
        "B1_minus_B0": _moving_block_bootstrap_ci(
            daily_lifts["B1"] - daily_lifts["B0"]
            if len(daily_lifts["B1"]) and len(daily_lifts["B0"])
            else np.array([], dtype=float)
        ),
    }
    return {
        "metric": "lift_pp_weighted",
        "block_size": 7,
        "n_bootstrap": 2000,
        "comparisons": comparisons,
    }


def build_stage4_real_money_outputs(
    *,
    hall: str,
    db_path: Path | None = None,
    stage3_csv: Path | None = None,
    stage5_csv: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, pd.DataFrame | dict[str, object] | Path]:
    resolved_db_path = _resolve_db_path(hall, db_path)
    resolved_stage3 = _resolve_stage3_csv(hall, stage3_csv)
    resolved_stage5 = _resolve_stage5_csv(hall, stage5_csv)
    resolved_output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_ROOT / _hall_slug(hall)

    stage3_frame = _prepare_stage3(_load_csv(resolved_stage3), hall=hall)
    stage5_frame = _prepare_stage5(_load_csv(resolved_stage5), hall=hall)
    db_frame = _prepare_db_frame(_load_db_frame(resolved_db_path), hall=hall)
    merged = _merge_frames(stage3_frame, stage5_frame, db_frame)
    merged = _add_b_rank_features(merged)

    selection_tables, summary_rows, _, n_skipped_lt10 = _train_eval_days(merged)
    summary = _build_summary(hall=hall, summary_rows=summary_rows, n_skipped_lt10=n_skipped_lt10)
    bootstrap_json = _build_bootstrap_json(summary_rows)

    return {
        "selection_tables": selection_tables,
        "summary": summary,
        "bootstrap_json": bootstrap_json,
        "output_dir": resolved_output_dir,
        "stage3_csv": resolved_stage3,
        "stage5_csv": resolved_stage5,
        "db_path": resolved_db_path,
    }


def save_stage4_real_money_outputs(
    outputs: dict[str, pd.DataFrame | dict[str, object] | Path], output_dir: Path
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    selection_tables = outputs["selection_tables"]
    assert isinstance(selection_tables, dict)
    for method, table in selection_tables.items():
        assert isinstance(table, pd.DataFrame)
        table.to_csv(output_dir / f"stage4_daily_selections_{method}.csv", index=False, encoding="utf-8-sig")
    summary = outputs["summary"]
    assert isinstance(summary, pd.DataFrame)
    summary.to_csv(output_dir / "stage4_real_money_summary.csv", index=False, encoding="utf-8-sig")
    bootstrap_json = outputs["bootstrap_json"]
    assert isinstance(bootstrap_json, dict)
    (output_dir / "stage4_real_money_bootstrap_ci.json").write_text(
        json.dumps(bootstrap_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Stage 4 real-money evaluation with B1R")
    parser.add_argument("--hall", default=DEFAULT_HALL)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--stage3-csv", type=Path, default=None)
    parser.add_argument("--stage5-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / _hall_slug(args.hall))
    outputs = build_stage4_real_money_outputs(
        hall=args.hall,
        db_path=args.db_path,
        stage3_csv=args.stage3_csv,
        stage5_csv=args.stage5_csv,
        output_dir=output_dir,
    )
    save_stage4_real_money_outputs(outputs, output_dir)
    print(f"[OK] wrote {output_dir / 'stage4_real_money_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
