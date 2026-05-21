# Machine-Type ML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `ml/machine_type/` forecasting workflow for `machine_name` entities with leakage-safe feature generation, shrinkage-based labels, next-day prediction, monthly reliability checking, and README/report outputs, without breaking existing last-digit wrappers.

**Architecture:** Add a new `ml/machine_type/` package with a shared core module for loading, auditing, labeling, feature generation, and report writing. Keep the CLI entrypoints thin: one script for next-day prediction and one for monthly checking. Use tests to lock shrinkage labels, leakage-safe history, and machine lifecycle/count-change features before implementation expands.

**Tech Stack:** Python, pandas, numpy, sqlite3, pytest, existing repo CLI/module conventions

---

### Task 1: Prepare Workspace And Lock Test Targets

**Files:**
- Create: `ml/tests/test_machine_type_common.py`
- Create: `ml/tests/test_machine_type_cli.py`
- Modify: none
- Test: `ml/tests/test_machine_type_common.py`, `ml/tests/test_machine_type_cli.py`

- [ ] **Step 1: Write the failing common-module tests**

```python
from pathlib import Path

import pandas as pd
import pytest

from ml.machine_type import machine_type_common as common


def _sample_daily_machine_type_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "20260101", "machine_name": "A", "machine_count": 1, "total_games": 1000, "avg_games": 1000.0, "total_diff_coins": 10000, "avg_diff_coins": 10000.0},
            {"date": "20260101", "machine_name": "B", "machine_count": 40, "total_games": 40000, "avg_games": 1000.0, "total_diff_coins": 60000, "avg_diff_coins": 1500.0},
            {"date": "20260102", "machine_name": "A", "machine_count": 1, "total_games": 1200, "avg_games": 1200.0, "total_diff_coins": 5000, "avg_diff_coins": 5000.0},
            {"date": "20260102", "machine_name": "B", "machine_count": 42, "total_games": 42000, "avg_games": 1000.0, "total_diff_coins": 63000, "avg_diff_coins": 1500.0},
        ]
    )


def test_build_shrunk_labels_prefers_large_count_signal() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    day1 = ranked.loc[ranked["date"].eq(pd.Timestamp("2026-01-01"))].sort_values("shrunk_rank")
    assert day1.iloc[0]["machine_name"] == "A"
    assert {"raw_avg_rank", "shrunk_rank", "shrunk_avg_diff", "is_top_2"} <= set(day1.columns)


def test_lag_features_use_prior_only_history() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    row = featured.loc[(featured["machine_name"] == "A") & (featured["date"] == pd.Timestamp("2026-01-02"))].iloc[0]
    assert row["lag_1_avg_diff_coins"] == pytest.approx(10000.0)
    assert row["rolling_avg_diff_7d"] == pytest.approx(10000.0)


def test_count_change_and_new_machine_recency_features() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    row = featured.loc[(featured["machine_name"] == "B") & (featured["date"] == pd.Timestamp("2026-01-02"))].iloc[0]
    assert row["days_since_first_seen"] == 1.0
    assert row["count_delta_1d"] == 2.0
    assert row["count_increase_flag"] == 1
```

- [ ] **Step 2: Write the failing CLI tests**

```python
import subprocess
import sys


def test_machine_type_nextday_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ml.machine_type.machine_type_nextday", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "next-day" in result.stdout.lower() or "nextday" in result.stdout.lower()


def test_machine_type_monthly_check_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ml.machine_type.machine_type_monthly_check", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "monthly" in result.stdout.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py ml/tests/test_machine_type_cli.py -q`  
Expected: FAIL with `ModuleNotFoundError` or missing `ml.machine_type` symbols because the package does not exist yet.

- [ ] **Step 4: Commit the red test scaffold**

```bash
git add ml/tests/test_machine_type_common.py ml/tests/test_machine_type_cli.py
git commit -m "test: add machine type ml scaffolding"
```

### Task 2: Add Shared Package Skeleton And Data Preparation Core

**Files:**
- Create: `ml/machine_type/__init__.py`
- Create: `ml/machine_type/machine_type_common.py`
- Modify: `ml/tests/test_machine_type_common.py`
- Test: `ml/tests/test_machine_type_common.py`

- [ ] **Step 1: Write the minimal package implementation**

```python
# ml/machine_type/__init__.py
"""Machine-type ML package."""

from . import machine_type_common

__all__ = ["machine_type_common"]
```

```python
# ml/machine_type/machine_type_common.py
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPORTS_DIR = Path("ml/machine_type/reports")


def prepare_machine_type_base_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], format="%Y%m%d")
    numeric_cols = ["machine_count", "total_games", "avg_games", "total_diff_coins", "avg_diff_coins"]
    for column in numeric_cols:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    out["efficiency"] = np.divide(
        out["total_diff_coins"],
        out["total_games"],
        out=np.zeros(len(out), dtype=float),
        where=out["total_games"].to_numpy(dtype=float) != 0.0,
    )
    return out.sort_values(["machine_name", "date"]).reset_index(drop=True)


def add_shrunk_rank_targets(df: pd.DataFrame, *, alpha: float) -> pd.DataFrame:
    ranked = df.copy()
    ranked["daily_global_avg_diff"] = ranked.groupby("date", sort=False)["avg_diff_coins"].transform("mean")
    ranked["shrunk_avg_diff"] = (
        (ranked["machine_count"] / (ranked["machine_count"] + alpha)) * ranked["avg_diff_coins"]
        + (alpha / (ranked["machine_count"] + alpha)) * ranked["daily_global_avg_diff"]
    )
    ranked["raw_avg_rank"] = ranked.groupby("date", sort=False)["avg_diff_coins"].rank(method="first", ascending=False)
    ranked["shrunk_rank"] = ranked.groupby("date", sort=False)["shrunk_avg_diff"].rank(method="first", ascending=False)
    ranked["is_rank_1"] = (ranked["shrunk_rank"] == 1).astype(int)
    ranked["is_top_2"] = (ranked["shrunk_rank"] <= 2).astype(int)
    ranked["is_top_3"] = (ranked["shrunk_rank"] <= 3).astype(int)
    ranked["is_top_5"] = (ranked["shrunk_rank"] <= 5).astype(int)
    return ranked
```

- [ ] **Step 2: Run common tests to verify partial progress**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py -q`  
Expected: fewer failures than before, with remaining failures on missing feature functions.

- [ ] **Step 3: Commit the shared package skeleton**

```bash
git add ml/machine_type/__init__.py ml/machine_type/machine_type_common.py
git commit -m "feat: add machine type data preparation core"
```

### Task 3: Implement Leakage-Safe Lifecycle And History Features

**Files:**
- Modify: `ml/machine_type/machine_type_common.py`
- Modify: `ml/tests/test_machine_type_common.py`
- Test: `ml/tests/test_machine_type_common.py`

- [ ] **Step 1: Extend the failing tests for feature columns**

```python
def test_feature_columns_include_operational_history_fields() -> None:
    df = common.prepare_machine_type_base_frame(_sample_daily_machine_type_summary())
    ranked = common.add_shrunk_rank_targets(df, alpha=5.0)
    featured = common.add_machine_type_features(ranked)
    required = {
        "lag_1_avg_diff_coins",
        "rolling_avg_diff_7d",
        "prior_top3_rate",
        "days_since_last_top3",
        "same_weekday_rank1_rate",
        "days_since_first_seen",
        "days_since_last_count_increase",
        "days_since_last_count_decrease",
        "count_delta_7d",
        "is_thursday",
    }
    assert required <= set(featured.columns)
```

- [ ] **Step 2: Run test to verify it fails on missing features**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py::test_feature_columns_include_operational_history_fields -q`  
Expected: FAIL because `add_machine_type_features` is not implemented or does not return the required columns.

- [ ] **Step 3: Implement `add_machine_type_features` with prior-only history**

```python
def _days_since_last_positive(flags: pd.Series) -> pd.Series:
    out: list[float] = []
    last_idx: int | None = None
    for idx, flag in enumerate(flags.astype(int).tolist()):
        out.append(999.0 if last_idx is None else float(idx - last_idx))
        if flag == 1:
            last_idx = idx
    return pd.Series(out, index=flags.index, dtype=float)


def add_machine_type_features(df: pd.DataFrame) -> pd.DataFrame:
    featured = df.copy()
    featured["day_of_week"] = featured["date"].dt.dayofweek
    featured["day_of_month"] = featured["date"].dt.day
    featured["month_progress"] = (featured["day_of_month"] - 1) / featured["date"].dt.daysinmonth
    featured["is_thursday"] = (featured["day_of_week"] == 3).astype(int)
    groups: list[pd.DataFrame] = []
    for _, group in featured.groupby("machine_name", sort=False):
        group = group.sort_values("date").copy()
        group["lag_1_avg_diff_coins"] = group["avg_diff_coins"].shift(1).fillna(0.0)
        group["lag_7_avg_diff_coins"] = group["avg_diff_coins"].shift(7).fillna(0.0)
        group["rolling_avg_diff_7d"] = group["avg_diff_coins"].shift(1).rolling(window=7, min_periods=1).mean().fillna(0.0)
        group["prior_rank1_rate"] = group["is_rank_1"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_top2_rate"] = group["is_top_2"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_top3_rate"] = group["is_top_3"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["prior_top5_rate"] = group["is_top_5"].shift(1).expanding(min_periods=1).mean().fillna(0.0)
        group["days_since_last_rank1"] = _days_since_last_positive(group["is_rank_1"])
        group["days_since_last_top2"] = _days_since_last_positive(group["is_top_2"])
        group["days_since_last_top3"] = _days_since_last_positive(group["is_top_3"])
        group["days_since_last_top5"] = _days_since_last_positive(group["is_top_5"])
        group["days_since_first_seen"] = np.arange(len(group), dtype=float)
        group["count_delta_1d"] = group["machine_count"].diff().fillna(0.0)
        group["count_delta_7d"] = group["machine_count"].diff(7).fillna(0.0)
        group["count_increase_flag"] = (group["count_delta_1d"] > 0).astype(int)
        group["count_decrease_flag"] = (group["count_delta_1d"] < 0).astype(int)
        group["days_since_last_count_increase"] = _days_since_last_positive(group["count_increase_flag"])
        group["days_since_last_count_decrease"] = _days_since_last_positive(group["count_decrease_flag"])
        group["same_weekday_rank1_rate"] = (
            group.groupby("day_of_week", sort=False)["is_rank_1"]
            .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
            .fillna(0.0)
        )
        group["same_weekday_top3_rate"] = (
            group.groupby("day_of_week", sort=False)["is_top_3"]
            .transform(lambda s: s.shift(1).expanding(min_periods=1).mean())
            .fillna(0.0)
        )
        group["same_weekday_rolling_rank_sum_3"] = (
            group.groupby("day_of_week", sort=False)["shrunk_rank"]
            .transform(lambda s: s.shift(1).rolling(window=3, min_periods=1).sum())
            .fillna(0.0)
        )
        groups.append(group)
    return pd.concat(groups, ignore_index=True)
```

- [ ] **Step 4: Run the common tests to verify they pass**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py -q`  
Expected: PASS

- [ ] **Step 5: Commit the feature implementation**

```bash
git add ml/machine_type/machine_type_common.py ml/tests/test_machine_type_common.py
git commit -m "feat: add machine type lifecycle and history features"
```

### Task 4: Add Audit Reporting And Shared Persistence Helpers

**Files:**
- Modify: `ml/machine_type/machine_type_common.py`
- Modify: `ml/tests/test_machine_type_common.py`
- Test: `ml/tests/test_machine_type_common.py`

- [ ] **Step 1: Add a failing audit test**

```python
def test_build_audit_report_summarizes_duplicates_and_missing_values(tmp_path: Path) -> None:
    df = _sample_daily_machine_type_summary()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    df.loc[0, "machine_count"] = None
    report = common.build_audit_report(df)
    assert report["row_count"] == 5
    assert report["duplicate_date_machine_name_rows"] == 1
    assert report["missing_machine_count_rows"] == 1
```

- [ ] **Step 2: Run the audit test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py::test_build_audit_report_summarizes_duplicates_and_missing_values -q`  
Expected: FAIL because `build_audit_report` is missing.

- [ ] **Step 3: Implement audit and report writers**

```python
import json


def ensure_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def build_audit_report(df: pd.DataFrame) -> dict[str, object]:
    work = df.copy()
    duplicates = work.duplicated(subset=["date", "machine_name"]).sum()
    return {
        "row_count": int(len(work)),
        "duplicate_date_machine_name_rows": int(duplicates),
        "missing_machine_count_rows": int(work["machine_count"].isna().sum()),
        "missing_avg_diff_rows": int(work["avg_diff_coins"].isna().sum()),
        "missing_total_games_rows": int(work["total_games"].isna().sum()),
        "unique_machine_names": int(work["machine_name"].nunique()),
        "min_date": str(pd.to_datetime(work["date"]).min().date()),
        "max_date": str(pd.to_datetime(work["date"]).max().date()),
    }


def write_json_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run the common tests again**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py -q`  
Expected: PASS

- [ ] **Step 5: Commit the audit helpers**

```bash
git add ml/machine_type/machine_type_common.py ml/tests/test_machine_type_common.py
git commit -m "feat: add machine type audit reporting"
```

### Task 5: Implement Next-Day Prediction CLI

**Files:**
- Create: `ml/machine_type/machine_type_nextday.py`
- Modify: `ml/tests/test_machine_type_cli.py`
- Modify: `ml/machine_type/machine_type_common.py`
- Test: `ml/tests/test_machine_type_cli.py`

- [ ] **Step 1: Write a failing smoke test for the next-day module import path**

```python
def test_machine_type_nextday_module_has_parser() -> None:
    from ml.machine_type import machine_type_nextday

    parser = machine_type_nextday.build_parser()
    assert parser.prog
```

- [ ] **Step 2: Run the CLI tests to verify failure**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_cli.py -q`  
Expected: FAIL because `ml.machine_type.machine_type_nextday` does not exist yet.

- [ ] **Step 3: Implement the next-day CLI**

```python
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from . import machine_type_common as common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Next-day machine-type prediction")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--alpha", type=float, default=5.0)
    parser.add_argument("--output-prefix", default="ml/machine_type/reports/machine_type_nextday_prediction")
    return parser


def _resolve_db_path(raw: str) -> Path:
    if raw:
        return Path(raw)
    candidates = sorted(Path("db").glob("*7.db"))
    if not candidates:
        raise FileNotFoundError("No '*7.db' database found under db/")
    return candidates[0]


def _load_daily_machine_type_summary(db_path: Path) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        return pd.read_sql_query(
            """
            SELECT date, machine_name, machine_count, total_games, avg_games, total_diff_coins, avg_diff_coins
            FROM daily_machine_type_summary
            ORDER BY date, machine_name
            """,
            conn,
        )
    finally:
        conn.close()


def main() -> int:
    args = build_parser().parse_args()
    db_path = _resolve_db_path(args.db_path)
    raw = _load_daily_machine_type_summary(db_path)
    audit = common.build_audit_report(raw)
    prepared = common.prepare_machine_type_base_frame(raw)
    ranked = common.add_shrunk_rank_targets(prepared, alpha=args.alpha)
    featured = common.add_machine_type_features(ranked)
    latest_date = featured["date"].max()
    latest = featured.loc[featured["date"].eq(latest_date)].copy()
    latest = latest.sort_values(["shrunk_rank", "machine_name"]).reset_index(drop=True)
    prefix = Path(args.output_prefix)
    common.write_json_report(prefix.with_suffix(".json"), {"prediction_date": str(latest_date.date()), "rows": latest.to_dict(orient="records")})
    latest.to_csv(prefix.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    common.write_json_report(prefix.with_name(prefix.name + "_audit_report.json"), audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests to verify they pass**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_cli.py -q`  
Expected: PASS

- [ ] **Step 5: Commit the next-day CLI**

```bash
git add ml/machine_type/machine_type_nextday.py ml/tests/test_machine_type_cli.py ml/machine_type/machine_type_common.py
git commit -m "feat: add machine type next-day prediction cli"
```

### Task 6: Implement Monthly Reliability Check CLI

**Files:**
- Create: `ml/machine_type/machine_type_monthly_check.py`
- Modify: `ml/tests/test_machine_type_cli.py`
- Modify: `ml/machine_type/machine_type_common.py`
- Test: `ml/tests/test_machine_type_cli.py`

- [ ] **Step 1: Add a failing parser smoke test**

```python
def test_machine_type_monthly_check_module_has_parser() -> None:
    from ml.machine_type import machine_type_monthly_check

    parser = machine_type_monthly_check.build_parser()
    assert parser.prog
```

- [ ] **Step 2: Run the targeted test to verify failure**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_cli.py::test_machine_type_monthly_check_module_has_parser -q`  
Expected: FAIL because the module does not exist yet.

- [ ] **Step 3: Implement the monthly-check CLI**

```python
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from . import machine_type_common as common
from .machine_type_nextday import _load_daily_machine_type_summary, _resolve_db_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monthly reliability check for machine-type predictions")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--alpha", type=float, default=5.0)
    parser.add_argument("--output-prefix", default="ml/machine_type/reports/machine_type_reliability")
    return parser


def _build_daily_reliability(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for dt, group in df.groupby("date", sort=True):
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "month": dt.strftime("%Y-%m"),
                "is_thursday": int(group["is_thursday"].iloc[0]),
                "hit_at_1": float((group["shrunk_rank"] <= 1).any()),
                "hit_at_2": float((group["shrunk_rank"] <= 2).any()),
                "hit_at_3": float((group["shrunk_rank"] <= 3).any()),
                "hit_at_5": float((group["shrunk_rank"] <= 5).any()),
                "predicted_count": int(len(group)),
                "skip_rate": 0.0,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    args = build_parser().parse_args()
    db_path = _resolve_db_path(args.db_path)
    raw = _load_daily_machine_type_summary(db_path)
    prepared = common.prepare_machine_type_base_frame(raw)
    ranked = common.add_shrunk_rank_targets(prepared, alpha=args.alpha)
    featured = common.add_machine_type_features(ranked)
    daily = _build_daily_reliability(featured)
    monthly = daily.groupby(["month", "is_thursday"], sort=True).mean(numeric_only=True).reset_index()
    prefix = Path(args.output_prefix)
    daily.to_csv(prefix.with_name(prefix.name + "_daily.csv"), index=False, encoding="utf-8-sig")
    monthly.to_csv(prefix.with_name(prefix.name + "_monthly.csv"), index=False, encoding="utf-8-sig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full CLI test file**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_cli.py -q`  
Expected: PASS

- [ ] **Step 5: Commit the monthly-check CLI**

```bash
git add ml/machine_type/machine_type_monthly_check.py ml/tests/test_machine_type_cli.py ml/machine_type/machine_type_common.py
git commit -m "feat: add machine type monthly reliability cli"
```

### Task 7: Write README And Align Output Contract

**Files:**
- Create: `ml/machine_type/README.md`
- Modify: `ml/machine_type/machine_type_nextday.py`
- Modify: `ml/machine_type/machine_type_monthly_check.py`
- Test: manual read plus CLI help checks

- [ ] **Step 1: Write the README**

```md
# Machine-Type ML

## Purpose

Forecast machine-name-level strength using shrinkage-ranked labels and leakage-safe history.

## Commands

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --help
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --help
```

## Key Outputs

- `*_nextday_prediction.json/csv`
- `*_audit_report.json`
- `*_daily.csv`
- `*_monthly.csv`

## Reading Thursday Split

Monthly outputs include `is_thursday` so Thursday and non-Thursday can be compared before any weekday-specific model split is introduced.
```
```

- [ ] **Step 2: Make sure output filenames match the agreed contract**

```python
# nextday defaults
parser.add_argument("--output-prefix", default="ml/machine_type/reports/machine_type_nextday_prediction")

# monthly defaults
parser.add_argument("--output-prefix", default="ml/machine_type/reports/machine_type_reliability")
```

- [ ] **Step 3: Run CLI help verification**

Run:

- `venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --help`
- `venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --help`

Expected: both return code `0` and display the expected command descriptions.

- [ ] **Step 4: Commit the README and output alignment**

```bash
git add ml/machine_type/README.md ml/machine_type/machine_type_nextday.py ml/machine_type/machine_type_monthly_check.py
git commit -m "docs: add machine type ml readme"
```

### Task 8: Run Minimal End-To-End Verification

**Files:**
- Modify: none unless fixes are required
- Test: generated artifacts under `ml/machine_type/reports/`

- [ ] **Step 1: Run the test suite for the new package**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_machine_type_common.py ml/tests/test_machine_type_cli.py -q`  
Expected: PASS

- [ ] **Step 2: Run next-day prediction**

Run: `venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --alpha 5.0`  
Expected: `ml/machine_type/reports/machine_type_nextday_prediction.json`, `.csv`, and `_audit_report.json` are created.

- [ ] **Step 3: Run monthly reliability check**

Run: `venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --alpha 5.0`  
Expected: `ml/machine_type/reports/machine_type_reliability_daily.csv` and `_monthly.csv` are created.

- [ ] **Step 4: Inspect generated artifacts**

Run:

- `Get-ChildItem 'ml/machine_type/reports'`
- `Get-Content 'ml/machine_type/reports/machine_type_nextday_prediction.json' -TotalCount 40`
- `Get-Content 'ml/machine_type/reports/machine_type_reliability_monthly.csv' -TotalCount 20`

Expected: files exist, machine names are present, and Thursday breakdown fields are included where specified.

- [ ] **Step 5: Commit if verification required follow-up fixes**

```bash
git add ml/machine_type ml/tests
git commit -m "fix: finalize machine type ml verification"
```
