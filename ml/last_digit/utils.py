from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

NDCG_RANDOM_STATE_OFFSET = 7
BOOTSTRAP_SEED_SPLIT_RULE = 20260527
BOOTSTRAP_SEED_FULL_WALKFORWARD = 20260520
DEFAULT_DB_GLOB = "*7.db"
TARGET_COLUMNS = ("is_rank_1", "is_top_3", "is_top_5", "is_worst_1", "is_worst_3", "is_top_2")
META_COLUMNS = frozenset({"store_id", "entity_key", "date", *TARGET_COLUMNS})
FORECAST_EXCLUDED_COLUMNS = frozenset(
    {
        "total_games",
        "avg_games",
        "total_diff_coins",
        "avg_diff_coins",
        "win_rate",
        "high_profit_rate",
        "efficiency",
        # Always excluded: value-dependent bins (can leak if computed with future rows).
        "total_games_bin",
        "avg_games_bin",
        "total_diff_coins_bin",
        "avg_diff_coins_bin",
        "efficiency_bin",
    }
)


def parse_csv_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_strs(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def summarize_array(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {"mean": 0.0, "std": 0.0, "n_days": 0}
    return {
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "n_days": int(values.size),
    }


def resolve_db_path(raw: str = "", pattern: str = DEFAULT_DB_GLOB) -> Path:
    if raw:
        return Path(raw)
    candidates = sorted(Path("db").glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"No '{pattern}' file found under db/")
    return candidates[0]


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, str(level).upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def cohens_d(arr1: np.ndarray, arr2: np.ndarray) -> float:
    a = np.asarray(arr1, dtype=float)
    b = np.asarray(arr2, dtype=float)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return float("nan")
    var_a = np.var(a, ddof=1)
    var_b = np.var(b, ddof=1)
    pooled = ((len(a) - 1) * var_a + (len(b) - 1) * var_b) / max((len(a) + len(b) - 2), 1)
    if pooled <= 0:
        return float("nan")
    return float((np.mean(a) - np.mean(b)) / np.sqrt(pooled))


def interpret_cohens_d(d: float) -> str:
    if not np.isfinite(d):
        return "na"
    ad = abs(float(d))
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"
