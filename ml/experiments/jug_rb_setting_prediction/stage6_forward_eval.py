from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    from ml.experiments.jug_rb_setting_prediction import stage4_real_money as stage4  # noqa: E402
    from ml.experiments.jug_rb_setting_prediction.config import DEFAULT_OUTPUT_ROOT, HALL_SLUGS  # noqa: E402
else:  # pragma: no cover - exercised via package imports in tests
    from . import stage4_real_money as stage4  # noqa: E402
    from .config import DEFAULT_OUTPUT_ROOT, HALL_SLUGS  # noqa: E402

DEFAULT_FREEZE_PATH = DEFAULT_OUTPUT_ROOT / "mitoya" / "forward_test_freeze_20260706.json"
DEFAULT_STAGE5_CSV = DEFAULT_OUTPUT_ROOT / "mitoya" / "stage5_rank_daily.csv"
DEFAULT_RESULT_PATH = DEFAULT_OUTPUT_ROOT / "mitoya" / "stage6_forward_eval_result.json"


def _ensure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def _hall_slug(hall: str) -> str:
    return HALL_SLUGS.get(hall, hall)


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


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
    frame["date"] = frame["date"].astype(str)
    frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["games_normalized"] = pd.to_numeric(frame["games_normalized"], errors="coerce")
    frame["diff_coins_normalized"] = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce")
    frame["machine_name"] = frame["machine_name"].astype(str)
    frame = frame.dropna(
        subset=["date_dt", "machine_number", "machine_name", "games_normalized", "diff_coins_normalized"]
    ).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    frame["hall"] = ""
    frame["pay_rate_individual"] = (
        (3.0 * frame["games_normalized"] + frame["diff_coins_normalized"]) / (3.0 * frame["games_normalized"])
    ) * 100.0
    return frame


def _load_stage5_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = ["date", "machine_number", "machine_name", "pct_family"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} is missing required columns: {missing}")
    frame["date"] = frame["date"].astype(str)
    frame["date_dt"] = pd.to_datetime(frame["date"], format="%Y%m%d", errors="coerce")
    frame["machine_number"] = pd.to_numeric(frame["machine_number"], errors="coerce")
    frame["pct_family"] = pd.to_numeric(frame["pct_family"], errors="coerce")
    frame["machine_name"] = frame["machine_name"].astype(str)
    frame = frame.dropna(subset=["date_dt", "machine_number", "machine_name", "pct_family"]).copy()
    frame["machine_number"] = frame["machine_number"].astype(int)
    return frame


def _weighted_pay_rate(frame: pd.DataFrame) -> float:
    games_sum = pd.to_numeric(frame["games_normalized"], errors="coerce").sum()
    diff_sum = pd.to_numeric(frame["diff_coins_normalized"], errors="coerce").sum()
    if not np.isfinite(games_sum) or games_sum <= 0:
        return float("nan")
    return float((1.0 + diff_sum / (3.0 * games_sum)) * 100.0)


def _equal_pay_rate(frame: pd.DataFrame) -> float:
    if frame.empty:
        return float("nan")
    return float(pd.to_numeric(frame["pay_rate_individual"], errors="coerce").mean())


def _deterministic_seed(date_dt: pd.Timestamp, *, hall: str, method: str) -> int:
    return stage4._deterministic_seed(date_dt, hall=hall, method=method)


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


def _validate_eval_frame(eval_frame: pd.DataFrame, *, freeze_date: str) -> None:
    freeze_dt = pd.to_datetime(freeze_date, format="%Y%m%d", errors="raise")
    if not eval_frame.empty:
        assert eval_frame["date_dt"].gt(freeze_dt).all(), "eval frame contains freeze_date or earlier rows"


def _frozen_selection_order(stage5_frame: pd.DataFrame, *, freeze_date: str, frozen_candidates: list[int]) -> list[int]:
    freeze_dt = pd.to_datetime(freeze_date, format="%Y%m%d", errors="raise")
    work = stage5_frame.loc[
        stage5_frame["date_dt"].le(freeze_dt) & stage5_frame["machine_number"].isin(frozen_candidates)
    ].copy()
    if work.empty:
        raise ValueError("no freeze-date history for frozen candidates")
    ranked = stage4._add_b_rank_features(work)
    last_rows = (
        ranked.sort_values(["date_dt", "machine_number"], kind="mergesort")
        .groupby("machine_number", sort=False)
        .tail(1)
    )
    last_rows = last_rows.sort_values(["b_rank_180d", "machine_number"], ascending=[False, True], kind="mergesort")
    ordered = last_rows["machine_number"].astype(int).tolist()
    if len(ordered) < 3:
        raise ValueError("frozen candidate pool has fewer than 3 machines")
    return ordered


def build_forward_eval_result(
    *,
    freeze_json: Path = DEFAULT_FREEZE_PATH,
    db_path: Path | None = None,
    stage5_csv: Path | None = None,
) -> dict[str, object]:
    freeze = _load_json(freeze_json)
    hall = str(freeze["hall"])
    resolved_db_path = Path(db_path) if db_path is not None else PROJECT_ROOT / str(freeze["db_path"])
    resolved_stage5 = Path(stage5_csv) if stage5_csv is not None else DEFAULT_STAGE5_CSV
    freeze_date = str(freeze["freeze_date"])
    frozen_candidates = [int(value) for value in freeze["frozen_candidates"]]
    eval_start = str(freeze["eval_protocol"]["eval_start"])
    min_eval_days = int(freeze["eval_protocol"]["min_eval_days"])

    stage5_frame = _load_stage5_frame(resolved_stage5)
    frozen_order = _frozen_selection_order(stage5_frame, freeze_date=freeze_date, frozen_candidates=frozen_candidates)
    frozen_top3 = frozen_order[:3]

    db_frame = _load_db_frame(resolved_db_path)
    db_frame = db_frame.loc[db_frame["machine_name"].str.contains("繧ｸ繝｣繧ｰ繝ｩ繝ｼ", na=False, regex=False)].copy()
    eval_frame = db_frame.loc[db_frame["date"].gt(freeze_date)].copy()
    _validate_eval_frame(eval_frame, freeze_date=freeze_date)

    if eval_frame.empty:
        result = {
            "status": "insufficient_data",
            "message": "データ不足（現在0日）",
            "freeze_date": freeze_date,
            "hall": hall,
            "eval_start": eval_start,
            "min_eval_days": min_eval_days,
            "current_eval_days": 0,
            "frozen_candidates": frozen_candidates,
            "frozen_top3": frozen_top3,
        }
        return result

    daily_rows: list[dict[str, object]] = []
    for date_dt, day_rows in eval_frame.groupby("date_dt", sort=True):
        day_rows = day_rows.sort_values(["machine_number"], kind="mergesort").reset_index(drop=True)
        if len(day_rows) < 10:
            continue
        selected = day_rows.loc[day_rows["machine_number"].isin(frozen_top3)].copy()
        if len(selected) != len(frozen_top3):
            raise ValueError(f"missing frozen candidate rows on {date_dt:%Y%m%d}")
        b0_seed = _deterministic_seed(date_dt, hall=hall, method="B0")
        rng = np.random.default_rng(b0_seed)
        b0_ranked = day_rows.copy()
        b0_ranked["score"] = rng.random(len(b0_ranked))
        b0_ranked = b0_ranked.sort_values(
            ["score", "machine_number"], ascending=[False, True], kind="mergesort"
        ).reset_index(drop=True)
        b0_selected = b0_ranked.head(3).copy()

        daily_rows.append(
            {
                "date": date_dt.strftime("%Y%m%d"),
                "selected_weighted": _weighted_pay_rate(selected),
                "hall_weighted": _weighted_pay_rate(day_rows),
                "selected_equal": _equal_pay_rate(selected),
                "hall_equal": _equal_pay_rate(day_rows),
                "b0_weighted": _weighted_pay_rate(b0_selected),
                "b0_equal": _equal_pay_rate(b0_selected),
            }
        )

    daily_frame = pd.DataFrame(daily_rows)
    current_eval_days = int(len(daily_frame))
    if current_eval_days < min_eval_days:
        return {
            "status": "insufficient_data",
            "message": f"データ不足（現在{current_eval_days}日）",
            "freeze_date": freeze_date,
            "hall": hall,
            "eval_start": eval_start,
            "min_eval_days": min_eval_days,
            "current_eval_days": current_eval_days,
            "frozen_candidates": frozen_candidates,
            "frozen_top3": frozen_top3,
            "daily_rows": daily_rows,
        }

    daily_frame["selected_minus_hall_weighted"] = daily_frame["selected_weighted"] - daily_frame["hall_weighted"]
    daily_frame["selected_minus_b0_weighted"] = daily_frame["selected_weighted"] - daily_frame["b0_weighted"]
    daily_frame["selected_minus_hall_equal"] = daily_frame["selected_equal"] - daily_frame["hall_equal"]
    daily_frame["selected_minus_b0_equal"] = daily_frame["selected_equal"] - daily_frame["b0_equal"]

    result = {
        "status": "ok",
        "freeze_date": freeze_date,
        "hall": hall,
        "eval_start": eval_start,
        "min_eval_days": min_eval_days,
        "current_eval_days": current_eval_days,
        "frozen_candidates": frozen_candidates,
        "frozen_top3": frozen_top3,
        "primary": {
            "selected_minus_hall_weighted": _moving_block_bootstrap_ci(
                daily_frame["selected_minus_hall_weighted"].to_numpy(dtype=float)
            ),
            "selected_weighted_mean": float(daily_frame["selected_weighted"].mean()),
            "hall_weighted_mean": float(daily_frame["hall_weighted"].mean()),
        },
        "secondary": {
            "selected_minus_b0_weighted": _moving_block_bootstrap_ci(
                daily_frame["selected_minus_b0_weighted"].to_numpy(dtype=float)
            ),
            "selected_weighted_mean": float(daily_frame["selected_weighted"].mean()),
            "b0_weighted_mean": float(daily_frame["b0_weighted"].mean()),
        },
        "daily_rows": daily_rows,
    }
    return result


def save_forward_eval_result(result: dict[str, object], output_path: Path = DEFAULT_RESULT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="Mitoya forward eval from frozen candidates")
    parser.add_argument("--freeze-json", type=Path, default=DEFAULT_FREEZE_PATH)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--stage5-csv", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULT_PATH)
    args = parser.parse_args(argv)

    result = build_forward_eval_result(freeze_json=args.freeze_json, db_path=args.db_path, stage5_csv=args.stage5_csv)
    save_forward_eval_result(result, args.output)
    print(result["message"])
    print(f"[OK] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
