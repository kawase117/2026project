# Mitoya 4day Sunday Others Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Mitoya walk-forward runner's Wednesday split with three mutually exclusive buckets: `4day`, `Sunday`, and `others`.

**Architecture:** Keep shared training/evaluation primitives from `tail_ltr_split_rule_wf.py`, but move the day-bucket split logic into `tail_ltr_mitoya_wf.py`. Add focused tests for bucket priority, parser wiring, and summary output shape before changing the runner.

**Tech Stack:** Python, pandas, pytest.

---

### Task 1: Add regression tests for Mitoya day buckets

**Files:**
- Create: `ml/tests/test_tail_ltr_mitoya_wf.py`
- Modify: `ml/last_digit/tail_ltr_mitoya_wf.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_classify_mitoya_day_bucket_prioritizes_4day_over_sunday():
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-06-14")) == "4day"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-06-07")) == "Sunday"
    assert classify_mitoya_day_bucket(pd.Timestamp("2026-06-08")) == "others"


def test_parser_exposes_three_bucket_cli_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "--min-train-days-4day", "8",
            "--min-train-days-sunday", "10",
            "--min-train-days-other", "30",
        ]
    )
    assert args.min_train_days_4day == 8
    assert args.min_train_days_sunday == 10
    assert args.min_train_days_other == 30


def test_summarize_bucketed_days_returns_expected_sections():
    df = pd.DataFrame(
        {
            "date": ["2026-06-04", "2026-06-07", "2026-06-08"],
            "weekday": ["Thursday", "Sunday", "Monday"],
            "day_bucket": ["4day", "Sunday", "others"],
            "excess": [100.0, 50.0, -10.0],
        }
    )
    out = summarize_bucketed_days(df, n_boot=10)
    assert set(out) == {"overall", "fourday_only", "sunday_only", "other_days"}
    assert out["fourday_only"]["n_days"] == 1
    assert out["sunday_only"]["n_days"] == 1
    assert out["other_days"]["n_days"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_tail_ltr_mitoya_wf.py -v`
Expected: FAIL because the helper functions and parser options do not exist yet.

- [ ] **Step 3: Implement the minimal bucket helpers**

Add:

```python
def classify_mitoya_day_bucket(value: pd.Timestamp) -> str:
    ts = pd.Timestamp(value)
    day = int(ts.day)
    if day in {4, 14, 24}:
        return "4day"
    if int(ts.weekday()) == 6:
        return "Sunday"
    return "others"
```

and a `summarize_bucketed_days()` helper that emits `overall`, `fourday_only`, `sunday_only`, `other_days`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_tail_ltr_mitoya_wf.py -v`
Expected: PASS.

### Task 2: Replace the Wednesday runner with a Mitoya-local three-bucket runner

**Files:**
- Modify: `ml/last_digit/tail_ltr_mitoya_wf.py`

- [ ] **Step 1: Write the failing parser expectations into implementation**

Replace the Wednesday-specific CLI options with:

```python
p.add_argument("--min-train-days-4day", type=int, default=10)
p.add_argument("--min-train-days-sunday", type=int, default=14)
p.add_argument("--min-train-days-other", type=int, default=42)
p.add_argument("--windows-4day", default="full_2025")
p.add_argument("--lambdas-4day", default="0.75,1.0,1.25")
p.add_argument("--q-grid-4day", default="0.0,0.1,0.2,0.3,0.4")
p.add_argument("--windows-sunday", default="full_2025")
p.add_argument("--lambdas-sunday", default="0.75,1.0,1.25")
p.add_argument("--q-grid-sunday", default="0.0,0.1,0.2,0.3,0.4")
p.add_argument("--windows-other", default="recent_60d,full_2025")
p.add_argument("--lambdas-other", default="0.75,1.0,1.25")
p.add_argument("--q-grid-other", default="0.0,0.1,0.2,0.3,0.4,0.5,0.6")
```

- [ ] **Step 2: Implement the bucketed walk-forward loop**

Add local helpers equivalent to the Wednesday functions, but bucket-based:

```python
def eval_candidate_for_bucket(..., bucket_name: str, ...) -> dict[str, Any] | None: ...
def select_best_bucket_candidates(..., bucket_configs: dict[str, BucketConfig], ...) -> dict[str, dict[str, Any]] | None: ...
def run_mode_bucketed(..., bucket_configs: dict[str, BucketConfig], ...) -> tuple[pd.DataFrame, dict[str, Any]]: ...
```

Each test block should:

- choose the best candidate independently for `4day`, `Sunday`, `others`
- concatenate their `test_day` frames
- add `day_bucket`
- summarize by the three bucket labels

- [ ] **Step 3: Wire `_evaluate_one_mode()` and ranking to the new summary fields**

Use the new bucketed runner for both:

```python
diff_col="total_diff_coins"
diff_col="total_diff_coins_focus"
```

Update ranking to include:

```python
"focus_fourday_mean"
"focus_sunday_mean"
"focus_other_mean"
```

- [ ] **Step 4: Run the targeted tests**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_tail_ltr_mitoya_wf.py -v`
Expected: PASS.

### Task 3: Verify the Mitoya runner end to end

**Files:**
- Modify: `ml/last_digit/tail_ltr_mitoya_wf.py`
- Output: `db/experiments/tail_ltr_mitoya_wf*`

- [ ] **Step 1: Verify CLI help**

Run: `venv\Scripts\python.exe -m ml.last_digit.tail_ltr_mitoya_wf --help`
Expected: help shows `4day`, `Sunday`, `other` options and no Wednesday-specific train-grid flags.

- [ ] **Step 2: Run a short smoke execution**

Run: `venv\Scripts\python.exe -m ml.last_digit.tail_ltr_mitoya_wf --max-blocks 1 --n-boot 100`
Expected: command exits 0 and writes fresh JSON/CSV outputs.

- [ ] **Step 3: Run the full targeted pytest set**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_tail_ltr_mitoya_wf.py ml/tests/test_mitoya_segmentation.py -v`
Expected: PASS.
