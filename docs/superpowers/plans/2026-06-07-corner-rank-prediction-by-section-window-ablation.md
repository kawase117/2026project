# Corner Rank Prediction By Section Window Ablation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a window ablation mode for the corner-by-section model that compares rolling and expanding history definitions and writes metrics plus pairwise significance CSVs.

**Architecture:** Keep the existing corner prediction pipeline and add a separate window-ablation scenario family with its own feature builder, significance summary, and output filenames. Reuse the same walk-forward training loop and CatBoost classifier so only the history-window definition changes across scenarios.

**Tech Stack:** Python, pandas, NumPy, CatBoost, scikit-learn, SciPy optional for paired significance tests, pytest.

---

### Task 1: Add window-ablation feature scenarios and summaries

**Files:**
- Modify: `ml/prediction/corner_rank_prediction_by_section.py`
- Test: `ml/tests/test_corner_rank_prediction_by_section.py`

- [ ] **Step 1: Write the failing test**

Add tests that assert the parser exposes `--window-ablation`, the window scenario feature columns include `all_days_rolling7`, `xday_expanding_mean`, `xday_rolling30_mean`, and `all_days_expanding_mean`, and the window summary helpers return the requested CSV shapes.

- [ ] **Step 2: Run the targeted test subset to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_corner_rank_prediction_by_section.py -v`
Expected: fail because the window-ablation parser flag and summary helpers are not yet implemented.

- [ ] **Step 3: Implement the minimal window-ablation plumbing**

Add the new scenario constants, history-window feature builder, fold-pair significance helpers, window metrics summary, and pairwise comparison summary.

- [ ] **Step 4: Run the targeted test subset to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_corner_rank_prediction_by_section.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add ml/prediction/corner_rank_prediction_by_section.py ml/tests/test_corner_rank_prediction_by_section.py docs/superpowers/plans/2026-06-07-corner-rank-prediction-by-section-window-ablation.md
git commit -m "feat: add corner window ablation"
```

