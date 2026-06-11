# Corner Rank Prediction By Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a section-local CatBoostClassifier that predicts whether the corner machine will land in the top 30% of daily section performance.

**Architecture:** Reuse the existing section walk-forward pipeline pattern from `ml/prediction/tail_rank_prediction_by_section.py`, but switch the target to a binary `target_corner_top_flag` and change the output metrics to classification metrics. Load section layout and machine master data from SQLite, derive leakage-safe historical features with `shift(1)`, and keep the first version on full-day scope so sample size is not artificially reduced.

**Tech Stack:** Python, pandas, numpy, scikit-learn metrics, CatBoost, pytest.

---

### Task 1: Add regression tests for corner target construction and walk-forward evaluation

**Files:**
- Create: `ml/tests/test_corner_rank_prediction_by_section.py`

- [ ] **Step 1: Write the failing tests**

```python
import pandas as pd

from ml.prediction.corner_rank_prediction_by_section import (
    add_corner_prediction_features,
    assign_corner_top_targets,
    build_parser,
    build_walk_forward_folds,
    evaluate_prediction_frame,
)


def test_assign_corner_top_targets_marks_top_30_percent_as_positive():
    raw = pd.DataFrame(
        {
            "date": ["2026-06-04"] * 10,
            "section": ["501-522"] * 10,
            "machine_number": list(range(501, 511)),
            "machine_name": [f"M{i}" for i in range(10)],
            "last_digit": ["0"] * 10,
            "games_normalized": [120] * 10,
            "diff_coins_normalized": [5000, 3000, 1500, 500, -200, -800, -1200, -1500, -2000, -2500],
            "rank_from_aisle": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "is_corner": [1] + [0] * 9,
            "machine_type": ["jug"] * 10,
        }
    )

    out = assign_corner_top_targets(raw)
    corner_row = out.loc[out["is_corner"].eq(1)].iloc[0]
    assert corner_row["target_corner_top_flag"] == 1
    assert out["target_corner_top_flag"].sum() == 3


def test_add_corner_prediction_features_uses_shifted_history():
    raw = pd.DataFrame(
        {
            "date": ["2026-06-04", "2026-06-05", "2026-06-07"],
            "section": ["501-522"] * 3,
            "machine_number": [501, 501, 501],
            "machine_name": ["M0", "M0", "M0"],
            "last_digit": ["0"] * 3,
            "games_normalized": [120] * 3,
            "diff_coins_normalized": [10.0, 20.0, 30.0],
            "rank_from_aisle": [1, 1, 1],
            "is_corner": [1, 1, 1],
            "machine_type": ["jug"] * 3,
        }
    )

    out = add_corner_prediction_features(assign_corner_top_targets(raw)).sort_values("date").reset_index(drop=True)
    assert pd.isna(out.loc[0, "corner_rolling7_mean"])
    assert out.loc[1, "corner_rolling7_mean"] == 10.0
    assert out.loc[2, "prev_xday_corner_top_flag"] == 1


def test_build_walk_forward_folds_respects_window_sizes():
    dates = pd.date_range("2026-01-01", periods=8, freq="D")
    folds = build_walk_forward_folds(dates, train_days=3, val_days=2, step_days=2)
    assert len(folds) == 3
    assert folds[0].train_dates == tuple(dates[:3])
    assert folds[0].val_dates == tuple(dates[3:5])


def test_evaluate_prediction_frame_returns_classification_metrics():
    frame = pd.DataFrame(
        {
            "date": ["2026-06-04"] * 4,
            "section": ["501-522"] * 4,
            "target_corner_top_flag": [1, 1, 1, 0],
            "pred_corner_top_prob": [0.9, 0.8, 0.7, 0.1],
        }
    )
    out = evaluate_prediction_frame(frame)
    assert out["auc"] == 1.0
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0


def test_parser_exposes_corner_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.train_days == 72
    assert args.val_days == 30
    assert args.step_days == 30
    assert args.xday_only is False
    assert args.output_dir == "data/corner_rank_prediction_by_section"
```

- [ ] **Step 2: Run the new test file and confirm it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_corner_rank_prediction_by_section.py -v`
Expected: FAIL because the module does not exist yet.

### Task 2: Implement the corner prediction pipeline

**Files:**
- Create: `ml/prediction/corner_rank_prediction_by_section.py`

- [ ] **Step 1: Add the new module with the section-local binary target**

Implement:

```python
def assign_corner_top_targets(raw: pd.DataFrame) -> pd.DataFrame: ...
def add_corner_prediction_features(ranked: pd.DataFrame) -> pd.DataFrame: ...
def build_walk_forward_folds(...): ...
def predict_section_walk_forward(...): ...
def evaluate_prediction_frame(frame: pd.DataFrame) -> dict[str, float]: ...
def summarize_section_metrics(predictions: pd.DataFrame) -> pd.DataFrame: ...
def run_pipeline(...): ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

Target construction must:

```python
threshold_rank = max(1, math.ceil(len(section_day_rows) * 0.3))
target_corner_top_flag = 1 if corner_machine_rank <= threshold_rank else 0
```

Corner features must be leakage-safe and use `shift(1)`:

```python
work["corner_rolling7_mean"] = work.groupby(group_cols)["diff_coins_normalized"].transform(
    lambda s: s.shift(1).rolling(7, min_periods=1).mean()
)
work["corner_rolling30_mean"] = work.groupby(group_cols)["diff_coins_normalized"].transform(
    lambda s: s.shift(1).rolling(30, min_periods=1).mean()
)
work["corner_trend"] = work["corner_rolling7_mean"] - work["corner_rolling30_mean"]
work["_xday_flag"] = work["target_corner_top_flag"].where(work["is_xday"].eq(1))
work["prev_xday_corner_top_flag"] = work.groupby(group_cols)["_xday_flag"].transform(lambda s: s.shift(1).ffill())
```

The classifier should use CatBoostClassifier with the requested parameters, fall back to CPU when GPU is unavailable, and output `pred_corner_top_prob` plus a section/date-level ranking for inspection.

- [ ] **Step 2: Run a focused module smoke test**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_corner_rank_prediction_by_section.py -v`
Expected: PASS once the module is complete.

### Task 3: Wire CLI defaults and output files

**Files:**
- Modify: `ml/prediction/corner_rank_prediction_by_section.py`

- [ ] **Step 1: Ensure CLI defaults and output names match the request**

Use:

```python
--db-path db/みとや大森町店.db
--output-dir data/corner_rank_prediction_by_section
--train-days 72
--val-days 30
--step-days 30
--min-games 100
--xday-only false
--task-type GPU
--section-filter ""
```

Write:

```text
data/corner_rank_prediction_by_section/corner_rank_prediction_by_section_validation.csv
data/corner_rank_prediction_by_section/corner_rank_prediction_by_section_metrics.csv
```

Include section-level summary columns for `auc`, `precision`, `recall`, and `f1`.

- [ ] **Step 2: Run the CLI against the real DB path**

Run: `venv\Scripts\python.exe -m ml.prediction.corner_rank_prediction_by_section --db-path db/みとや大森町店.db --task-type CPU`
Expected: CSV outputs are generated and the script prints per-section metrics.

### Task 4: Verify the implementation end-to-end

**Files:**
- Modify: any files needed from the prior tasks

- [ ] **Step 1: Run the focused tests again**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_corner_rank_prediction_by_section.py -v`
Expected: PASS.

- [ ] **Step 2: Run a broader ML test slice if the new module shares helpers**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_tail_rank_prediction_by_section.py ml/tests/test_corner_rank_prediction_by_section.py -v`
Expected: PASS.

- [ ] **Step 3: Review the generated CSV columns**

Confirm the validation CSV contains at least:
`date`, `section`, `machine_number`, `machine_name`, `is_corner`, `target_corner_top_flag`, `pred_corner_top_prob`, `fold_id`.

