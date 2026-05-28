# Last Digit Rerank And Ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the current `v2` last-digit model as the stable baseline, then add lightweight post-ranking logic and operator-facing outputs that can improve practical use without destabilizing core `hit@2`.

**Architecture:** The existing LTR model remains the first-stage scorer. A second-stage lightweight reranker and risk layer consume first-stage outputs plus weekday/domain signals, then produce adjusted priority, avoid-candidates, and confidence bands. Validation stays anchored to the current test-period split so we can reject changes that harm `2F_N`.

**Tech Stack:** Python 3.10+, pandas, xgboost/lightgbm/catboost artifacts already in repo, existing `ml.last_digit` pipeline and report CSV/JSON outputs.

---

## File Map

- Modify: `ml/last_digit/tail_ltr_split_rule_nextday_gpu.py`
  - Add optional post-ranking hooks and richer output columns.
- Modify: `ml/last_digit/tail_ltr_split_rule_wf.py`
  - Revert temporary `v4b` feature state back to `v2` baseline before new work starts.
- Create: `ml/last_digit/post_rerank.py`
  - Lightweight reranking utilities using non-boost logic.
- Create: `ml/last_digit/post_rerank_eval.py`
  - Offline evaluator for rerank, avoid-list, and confidence outputs.
- Create: `ml/last_digit/reports/` artifacts from the evaluator
  - Comparison CSV/JSON for baseline vs rerank.
- Test: `test/ml/last_digit/test_post_rerank.py`
  - Unit tests for rerank scoring, confidence labels, and avoid-candidate logic.

---

### Task 1: Restore Stable `v2` Baseline In Code

**Files:**
- Modify: `ml/last_digit/tail_ltr_split_rule_wf.py`
- Test: `python -m py_compile ml/last_digit/tail_ltr_split_rule_wf.py`

- [ ] **Step 1: Remove temporary `v4b`-only feature block**

Delete the `pctrank_*` block currently left at the end of `add_simple_features()` and restore the `v2` feature set exactly: no `cluster_*`, no `weekday_roll4_*`, no `znorm_*`, no `pctrank_*`.

- [ ] **Step 2: Run syntax check**

Run:

```bash
python -m py_compile ml/last_digit/tail_ltr_split_rule_wf.py
```

Expected: command exits with no output.

- [ ] **Step 3: Commit baseline restoration**

```bash
git add ml/last_digit/tail_ltr_split_rule_wf.py
git commit -m "chore: restore last digit v2 baseline features"
```

---

### Task 2: Add Lightweight Post-Rerank Module

**Files:**
- Create: `ml/last_digit/post_rerank.py`
- Test: `test/ml/last_digit/test_post_rerank.py`

- [ ] **Step 1: Write failing tests for rerank utilities**

Add tests covering:

```python
import pandas as pd

from ml.last_digit.post_rerank import (
    build_confidence_band,
    compute_rerank_score,
    mark_avoid_candidates,
)


def test_compute_rerank_score_orders_by_penalty_and_bonus():
    df = pd.DataFrame(
        [
            {"last_digit": "1", "pred": 0.9, "pred_span_top12": 0.6, "weekday": "Thursday", "distance_top2": 5, "agreement": 3},
            {"last_digit": "2", "pred": 0.8, "pred_span_top12": 0.2, "weekday": "Thursday", "distance_top2": 2, "agreement": 1},
        ]
    )
    out = compute_rerank_score(df)
    assert out.loc[out["last_digit"] == "1", "rerank_score"].item() > out.loc[out["last_digit"] == "2", "rerank_score"].item()


def test_mark_avoid_candidates_flags_bottom_ranked_rows():
    df = pd.DataFrame(
        [
            {"last_digit": "1", "pred": 0.9},
            {"last_digit": "2", "pred": 0.7},
            {"last_digit": "3", "pred": 0.2},
            {"last_digit": "4", "pred": 0.1},
        ]
    )
    out = mark_avoid_candidates(df, avoid_k=2)
    assert set(out.loc[out["is_avoid_candidate"] == 1, "last_digit"]) == {"3", "4"}


def test_build_confidence_band_uses_span_and_agreement():
    row = {"pred_span_top12": 0.55, "agreement": 3}
    assert build_confidence_band(row) == "high"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
pytest test/ml/last_digit/test_post_rerank.py -v
```

Expected: import failure for `ml.last_digit.post_rerank`.

- [ ] **Step 3: Implement minimal rerank module**

Create `ml/last_digit/post_rerank.py` with:

```python
from __future__ import annotations

import pandas as pd


DISTANCE5_WEEKDAYS = {"Thursday", "Sunday"}


def build_confidence_band(row: dict | pd.Series) -> str:
    span = float(row.get("pred_span_top12", 0.0))
    agreement = int(row.get("agreement", 0))
    if span >= 0.4 and agreement >= 3:
        return "high"
    if span >= 0.25 and agreement >= 2:
        return "medium"
    return "low"


def compute_rerank_score(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    span = pd.to_numeric(out.get("pred_span_top12", 0.0), errors="coerce").fillna(0.0)
    agreement = pd.to_numeric(out.get("agreement", 0), errors="coerce").fillna(0.0)
    pred = pd.to_numeric(out["pred"], errors="coerce").fillna(0.0)
    weekday_bonus = (
        out.get("weekday", pd.Series("", index=out.index)).isin(DISTANCE5_WEEKDAYS)
        & (pd.to_numeric(out.get("distance_top2", 0), errors="coerce").fillna(0.0) == 5.0)
    ).astype(float) * 0.02
    out["rerank_score"] = pred + (span * 0.10) + (agreement * 0.03) + weekday_bonus
    return out


def mark_avoid_candidates(df: pd.DataFrame, avoid_k: int = 3) -> pd.DataFrame:
    out = df.sort_values("pred", ascending=False).reset_index(drop=True).copy()
    out["is_avoid_candidate"] = 0
    if avoid_k > 0:
        out.loc[out.index >= max(len(out) - avoid_k, 0), "is_avoid_candidate"] = 1
    return out
```

- [ ] **Step 4: Run tests and confirm pass**

Run:

```bash
pytest test/ml/last_digit/test_post_rerank.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit rerank module**

```bash
git add ml/last_digit/post_rerank.py test/ml/last_digit/test_post_rerank.py
git commit -m "feat: add lightweight last digit post reranker"
```

---

### Task 3: Add Operator-Facing Output Fields

**Files:**
- Modify: `ml/last_digit/tail_ltr_split_rule_nextday_gpu.py`
- Test: existing script `--help` and one short smoke run

- [ ] **Step 1: Add output-only rerank integration**

Inside the path that builds latest-test and next-day expert rankings:
- compute `pred_span_top12`
- compute `distance_top2`
- compute `agreement` if combined expert outputs are available
- call `compute_rerank_score()`
- call `mark_avoid_candidates()`
- append columns:
  - `rerank_score`
  - `confidence_band`
  - `is_avoid_candidate`

Do not replace the baseline ranking yet. Output both `pred` and `rerank_score`.

- [ ] **Step 2: Verify CLI still works**

Run:

```bash
python -m ml.last_digit.tail_ltr_split_rule_nextday_gpu --help
```

Expected: command prints help successfully.

- [ ] **Step 3: Run one short smoke**

Run a short smoke command using the existing baseline model and output prefix `ml/last_digit/reports/tmp_post_rerank_smoke`.

Expected:
- JSON and CSV files are written
- output rows contain `rerank_score`, `confidence_band`, `is_avoid_candidate`

- [ ] **Step 4: Commit output enrichment**

```bash
git add ml/last_digit/tail_ltr_split_rule_nextday_gpu.py
git commit -m "feat: add last digit rerank and avoid output fields"
```

---

### Task 4: Build Offline Evaluator For Rerank And Avoid Logic

**Files:**
- Create: `ml/last_digit/post_rerank_eval.py`
- Test: direct module run

- [ ] **Step 1: Create evaluator script**

Create `ml/last_digit/post_rerank_eval.py` that:
- reads an existing `*_testperiod_topk.csv`
- recomputes `rerank_score`
- compares:
  - baseline top2 hit rate
  - reranked top2 hit rate
  - avoid-candidate negative rate
  - confidence-band breakdown (`high/medium/low`)

Core output shape:

```python
{
    "baseline_hit_at_2": 0.0,
    "rerank_hit_at_2": 0.0,
    "avoid_negative_rate": 0.0,
    "confidence_band_summary": [
        {"band": "high", "n_days": 0, "hit_at_2": 0.0},
        {"band": "medium", "n_days": 0, "hit_at_2": 0.0},
        {"band": "low", "n_days": 0, "hit_at_2": 0.0},
    ],
}
```

- [ ] **Step 2: Run evaluator on current `v2` artifacts**

Run:

```bash
python -m ml.last_digit.post_rerank_eval --input ml/last_digit/reports/digit_lag_v2_withinexpert_xgb_ranker_ndcg_testperiod_topk.csv --output ml/last_digit/reports/post_rerank_eval_v2.json
```

Expected: JSON report is written.

- [ ] **Step 3: Commit evaluator**

```bash
git add ml/last_digit/post_rerank_eval.py
git commit -m "feat: add last digit post rerank evaluator"
```

---

### Task 5: Validate Weekday-Aware Candidate Control

**Files:**
- Modify: `ml/last_digit/post_rerank.py`
- Test: `test/ml/last_digit/test_post_rerank.py`

- [ ] **Step 1: Add explicit weekday candidate penalty rules**

Add penalties instead of hard exclusions:
- Monday: cluster-distance bonus disabled
- Thursday/Sunday: distance-5 bonus enabled
- Wednesday: allow tail-day bonus for high-agreement rows only

Use small bounded adjustments only, for example `±0.01` to `±0.03`.

- [ ] **Step 2: Add failing tests for weekday-specific adjustments**

Add tests that prove:
- Monday rows do not get distance-5 bonus
- Thursday/Sunday rows do
- Wednesday low-agreement rows do not get tail-day bonus

- [ ] **Step 3: Implement minimal rule changes and rerun tests**

Run:

```bash
pytest test/ml/last_digit/test_post_rerank.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Re-run offline evaluator**

Run the evaluator again and compare to the previous JSON.

- [ ] **Step 5: Commit weekday-aware control**

```bash
git add ml/last_digit/post_rerank.py test/ml/last_digit/test_post_rerank.py
git commit -m "feat: add weekday aware candidate control"
```

---

### Task 6: Produce Operator Summary And Go/No-Go Decision

**Files:**
- Create: `ml/last_digit/reports/post_rerank_eval_summary.md`

- [ ] **Step 1: Summarize the practical outcome**

Write a short markdown summary with:
- baseline vs rerank `hit@2`
- confidence band quality
- avoid-candidate negative rate
- whether rerank should stay output-only or become ranking-active

- [ ] **Step 2: Define adoption rule**

Use this acceptance rule:
- keep baseline ranking as primary if rerank hurts `2F_N`
- allow rerank as optional secondary display if it improves `3F_A` or avoid-rate without harming `2F_N`

- [ ] **Step 3: Commit summary**

```bash
git add ml/last_digit/reports/post_rerank_eval_summary.md
git commit -m "docs: summarize last digit rerank evaluation"
```

---

## Self-Review

- Spec coverage:
  - `v2` baseline preservation: covered in Task 1
  - non-boost second-stage idea: covered in Task 2
  - ranking/avoid/confidence outputs: covered in Task 3 and Task 4
  - weekday-aware operation idea: covered in Task 5
  - practical go/no-go judgment: covered in Task 6
- Placeholder scan:
  - no `TODO`, `TBD`, or unspecified commands left
- Type consistency:
  - rerank fields consistently named `rerank_score`, `confidence_band`, `is_avoid_candidate`

## Estimated 6-Hour Timeline

1. `0.5h` Restore `v2` baseline and verify syntax
2. `1.0h` Add post-rerank module and tests
3. `1.0h` Wire output fields into nextday pipeline
4. `1.0h` Build offline evaluator
5. `1.0h` Add weekday-aware penalties and re-evaluate
6. `1.5h` Summarize results, compare baseline vs rerank, decide adoption

**Plan complete and saved to `docs/superpowers/plans/2026-05-25-last-digit-rerank-ops-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
