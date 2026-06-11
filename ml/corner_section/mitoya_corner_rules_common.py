from __future__ import annotations

from pathlib import Path

import pandas as pd

DEFAULT_OUTPUT_DIR = "data/mitoya_corner_deep"
COMPOSITE_FILENAME = "corner_composite.csv"

REQUIRED_COLUMNS = {
    "island",
    "dd_group",
    "day_of_week",
    "rank",
    "avg_diff",
    "avg_games",
    "plus_rate",
    "sample_n",
}


def load_corner_composite(output_dir: Path) -> pd.DataFrame:
    candidates = [
        output_dir / COMPOSITE_FILENAME,
        Path(DEFAULT_OUTPUT_DIR) / COMPOSITE_FILENAME,
        Path(__file__).resolve().parents[2] / DEFAULT_OUTPUT_DIR / COMPOSITE_FILENAME,
    ]
    for path in candidates:
        if path.exists():
            df = pd.read_csv(path)
            missing = REQUIRED_COLUMNS - set(df.columns)
            if missing:
                raise ValueError(f"corner_composite.csv is missing columns: {sorted(missing)}")
            return df
    raise FileNotFoundError(
        f"corner_composite.csv not found. Checked: {', '.join(str(path) for path in candidates)}"
    )


def normalize_corner_composite(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["rank"] = pd.to_numeric(work["rank"], errors="coerce")
    work["avg_diff"] = pd.to_numeric(work["avg_diff"], errors="coerce")
    work["avg_games"] = pd.to_numeric(work["avg_games"], errors="coerce")
    work["plus_rate"] = pd.to_numeric(work["plus_rate"], errors="coerce")
    work["sample_n"] = pd.to_numeric(work["sample_n"], errors="coerce")
    work = work.dropna(subset=["island", "dd_group", "day_of_week", "rank", "avg_diff", "avg_games", "plus_rate", "sample_n"]).copy()
    work["rank"] = work["rank"].astype(int)
    work["sample_n"] = work["sample_n"].astype(int)
    return work


def classify_jug_tier(avg_diff: float, plus_rate: float, sample_n: int) -> tuple[str, str]:
    if plus_rate < 60 or avg_diff < 500:
        return "Avoid", "plus_rate<60% or avg_diff<500"
    if sample_n >= 10 and plus_rate >= 80 and avg_diff >= 1500:
        return "A", "n>=10 and plus_rate>=80% and avg_diff>=1500"
    if sample_n >= 5 and plus_rate >= 70 and avg_diff >= 1200:
        return "B", "n>=5 and plus_rate>=70% and avg_diff>=1200"
    return "B", "mid-confidence band"


def classify_mix_tier(avg_diff: float, plus_rate: float, sample_n: int) -> str:
    if avg_diff < 0 or plus_rate < 40:
        return "Avoid"
    if avg_diff >= 1000 and plus_rate >= 57 and sample_n >= 50:
        return "A"
    if avg_diff >= 600 and plus_rate >= 52:
        return "B"
    return "C"

