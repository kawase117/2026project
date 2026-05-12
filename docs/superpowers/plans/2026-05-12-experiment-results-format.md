# Experiment Results Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize ML experiment outputs around per-run folders with `run.json`, `summary.html`, and root-level `index.jsonl`, while replacing human-facing Markdown reports with HTML.

**Architecture:** Add a shared helper module under `ml/experiments` for writing structured result bundles and simple HTML reports. Update `ExperimentRunner` and representative report-generating scripts to call the helper, while keeping JSON outputs machine-readable and updating tests to lock the behavior.

**Tech Stack:** Python, `pathlib`, `json`, existing `pytest` tests, existing ML experiment scripts

---

### Task 1: Add regression tests for result bundles

**Files:**
- Modify: `ml/tests/test_experiment_runner.py`
- Test: `ml/tests/test_experiment_runner.py`

- [ ] **Step 1: Write failing tests for bundle layout**
- [ ] **Step 2: Run targeted `pytest` to confirm the new assertions fail**
- [ ] **Step 3: Implement the minimal production changes needed for the bundle layout**
- [ ] **Step 4: Run targeted `pytest` to confirm the tests pass**

### Task 2: Add shared result-format helpers

**Files:**
- Create: `ml/experiments/result_format.py`
- Modify: `ml/experiments/experiment_runner.py`

- [ ] **Step 1: Introduce helpers for run directory creation, `run.json`, `summary.html`, and `index.jsonl`**
- [ ] **Step 2: Update `ExperimentRunner` to emit the shared format without breaking existing callers**
- [ ] **Step 3: Re-run the focused test file**

### Task 3: Switch representative reports from Markdown to HTML

**Files:**
- Modify: `ml/experiments/phase9_02_model_training.py`
- Modify: `ml/experiments/phase9_04_evaluation_report.py`
- Modify: `ml/experiments/phase9_05_last_digit_evaluation_report.py`
- Modify: `ml/experiments/phase10_hyperparameter_tuning.py`

- [ ] **Step 1: Replace direct Markdown report generation with HTML report generation**
- [ ] **Step 2: Keep machine-readable JSON outputs untouched except for added bundle/index metadata where useful**
- [ ] **Step 3: Verify filenames and console summaries match the new HTML outputs**

### Task 4: Verify and summarize

**Files:**
- Test: `ml/tests/test_experiment_runner.py`

- [ ] **Step 1: Run the focused verification command**
- [ ] **Step 2: Inspect the generated diff for accidental scope creep**
- [ ] **Step 3: Report the behavioral change and any remaining migration gaps**
