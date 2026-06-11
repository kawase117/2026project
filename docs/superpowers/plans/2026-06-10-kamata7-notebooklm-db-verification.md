# Kamata7 NotebookLM DB Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable `ml.last_digit` CLI that turns the NotebookLM-derived Kamata7 hypotheses into DB-backed summary tables and markdown reports.

**Architecture:** Build one focused analysis runner that reads `machine_detailed_results`, `daily_hall_summary`, and `machine_master`, derives common machine/date aggregates once, and then emits one report section per hypothesis task. Keep the implementation data-first: no model training, no new schema, only deterministic summary statistics and CSV/MD outputs.

**Tech Stack:** Python, pandas, sqlite3, numpy, argparse, pathlib, pytest.

---

### Task 1: Add the Kamata7 verification runner

**Files:**
- Create: `ml/last_digit/kamata7_notebooklm_verification.py`
- Modify: `ml/last_digit/README.md`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from ml.last_digit.kamata7_notebooklm_verification import build_report, load_sources


def test_build_report_emits_all_task_sections(tmp_path: Path):
    db_path = Path("tests/fixtures/kamata7_small.db")
    sources = load_sources(db_path)
    report = build_report(sources=sources, min_games=0)
    assert "Task 1" in report.markdown
    assert "Task 2" in report.markdown
    assert "Task 3" in report.markdown
    assert "Task 4" in report.markdown
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\\Scripts\\python.exe -m pytest ml/tests/test_kamata7_notebooklm_verification.py -q`
Expected: import error because the runner does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement:
- a `load_sources(db_path)` helper that reads the needed tables and normalizes dates
- a `build_report(...)` function that computes the four hypothesis summaries
- a CLI entrypoint that writes one markdown file plus CSV outputs under `ml/last_digit/reports/kamata7_notebooklm_verification/`

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\\Scripts\\python.exe -m pytest ml/tests/test_kamata7_notebooklm_verification.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml/last_digit/kamata7_notebooklm_verification.py ml/last_digit/README.md ml/tests/test_kamata7_notebooklm_verification.py
git commit -m "feat: add kamata7 notebooklm verification runner"
```

### Task 2: Add focused summaries for the four hypothesis buckets

**Files:**
- Modify: `ml/last_digit/kamata7_notebooklm_verification.py`
- Modify: `ml/tests/test_kamata7_notebooklm_verification.py`

- [ ] **Step 1: Write the failing test**

```python
def test_task_2_new_machine_summary_uses_days_since_debut():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\\Scripts\\python.exe -m pytest ml/tests/test_kamata7_notebooklm_verification.py -q`
Expected: the bucket summary assertions fail until the debut logic is implemented.

- [ ] **Step 3: Write minimal implementation**

Add deterministic summaries for:
- Task 1: pre/post `2026-05-30` regime comparison
- Task 2: debut-window comparison
- Task 3: high-variance machine comparison
- Task 4: monthly/half-month reproducibility comparison

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\\Scripts\\python.exe -m pytest ml/tests/test_kamata7_notebooklm_verification.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml/last_digit/kamata7_notebooklm_verification.py ml/tests/test_kamata7_notebooklm_verification.py
git commit -m "feat: add kamata7 hypothesis summaries"
```

### Task 3: Validate the CLI output contract

**Files:**
- Modify: `ml/tests/test_kamata7_notebooklm_verification.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_writes_markdown_and_csv(tmp_path: Path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\\Scripts\\python.exe -m pytest ml/tests/test_kamata7_notebooklm_verification.py -q`
Expected: file-output assertion fails until the CLI wiring is present.

- [ ] **Step 3: Write minimal implementation**

Write the markdown report and a small set of CSV artifacts, and keep all file paths configurable by `--output-dir`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\\Scripts\\python.exe -m pytest ml/tests/test_kamata7_notebooklm_verification.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ml/tests/test_kamata7_notebooklm_verification.py
git commit -m "test: cover kamata7 notebooklm verification cli"
```

---

### Coverage Check

- Task 1: pre/post `2026-05-30` regime comparison
- Task 2: debut-window comparison
- Task 3: high-variance machine comparison
- Task 4: reproducibility comparison

All four hypotheses are covered by the planned runner and its tests.
