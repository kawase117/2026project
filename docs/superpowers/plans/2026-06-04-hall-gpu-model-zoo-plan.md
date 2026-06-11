# Hall GPU Model Zoo Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate GPU-backed hall ranking experiment path that compares `XGBRanker`, `LGBMRanker`, and `CatBoostRanker` without modifying the existing CPU hall strategy pipeline.

**Architecture:** Keep the current `hall_practical_strategy_analysis.py` unchanged and introduce a new GPU-focused runner with shared feature preparation, a small model registry, and a common evaluation harness. The new runner will train rankers per split, write a normalized comparison table, and preserve the existing practical metrics (`chosen_avg_diff_mean`, `top1_hit_rate`, `top2_inclusion_rate`, `spearman_daily_mean`, `regret_mean`). Each backend gets its own GPU parameters and a CPU fallback so the code can still smoke-test on machines without CUDA.

**Tech Stack:** Python, pandas, numpy, xgboost, lightgbm, catboost, pytest.

---

### Task 1: Create a shared hall GPU experiment harness

**Files:**
- Create: `ml/last_digit/hall_gpu_model_zoo.py`
- Create: `ml/tests/test_hall_gpu_model_zoo.py`
- Modify: `ml/last_digit/README.md`

- [ ] **Step 1: Write the failing test**

```python
def test_hall_gpu_model_zoo_module_exposes_registry():
    from ml.last_digit import hall_gpu_model_zoo as zoo

    names = [spec.name for spec in zoo.build_model_specs(use_gpu=False)]
    assert names == ["xgb_ranker", "lgbm_ranker", "catboost_ranker"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_gpu_model_zoo.py -v`
Expected: FAIL because the new module does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class ModelSpec:
    name: str
    family: str
    kind: str
    create_fn: Callable[[int], Any]

def build_model_specs(*, use_gpu: bool, gpu_backend: str = "cuda") -> list[ModelSpec]:
    return [
        ModelSpec(
            name="xgb_ranker",
            family="xgboost",
            kind="ranker",
            create_fn=lambda seed: make_xgb_ranker(seed=seed, use_gpu=use_gpu, gpu_backend=gpu_backend),
        ),
        ModelSpec(
            name="lgbm_ranker",
            family="lightgbm",
            kind="ranker",
            create_fn=lambda seed: make_lgbm_ranker(seed=seed, use_gpu=use_gpu),
        ),
        ModelSpec(
            name="catboost_ranker",
            family="catboost",
            kind="ranker",
            create_fn=lambda seed: make_catboost_ranker(seed=seed, use_gpu=use_gpu),
        ),
    ]
```

Add a small `main()` entrypoint that:
- loads the hall dataset,
- trains each model in the registry,
- evaluates the same metrics as the current practical pipeline,
- writes `hall_gpu_model_zoo_summary.csv` and `hall_gpu_model_zoo_detailed.csv`.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_gpu_model_zoo.py -v`
Expected: PASS.

- [ ] **Step 5: Update the README**

Add a short entry for the new runner:

```md
- `hall_gpu_model_zoo.py`
  - GPU-backed hall ranking benchmark comparing XGBRanker, LightGBM, and CatBoost.
```

- [ ] **Step 6: Commit**

```bash
git add ml/last_digit/hall_gpu_model_zoo.py ml/tests/test_hall_gpu_model_zoo.py ml/last_digit/README.md
git commit -m "feat: add hall gpu model zoo harness"
```

### Task 2: Implement backend-specific GPU rankers with CPU fallback

**Files:**
- Modify: `ml/last_digit/hall_gpu_model_zoo.py`
- Modify: `ml/tests/test_hall_gpu_model_zoo.py`

- [ ] **Step 1: Write the failing test**

```python
def test_backend_gpu_params_are_mapped():
    from ml.last_digit import hall_gpu_model_zoo as zoo

    xgb = zoo.build_model_specs(use_gpu=True, gpu_backend="cuda")[0].create_fn(42)
    params = xgb.get_params()
    assert params["device"] == "cuda"
    assert params["tree_method"] == "hist"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_gpu_model_zoo.py -k gpu_params -v`
Expected: FAIL until the backend constructors exist.

- [ ] **Step 3: Write minimal implementation**

```python
def make_xgb_ranker(*, seed: int, use_gpu: bool, gpu_backend: str) -> XGBRanker:
    params = {"objective": "rank:ndcg", "n_estimators": 300, "learning_rate": 0.05, "max_depth": 4}
    if use_gpu:
        params.update({"tree_method": "hist", "device": "cuda" if gpu_backend == "cuda" else "cuda:0"})
    else:
        params.update({"tree_method": "hist", "device": "cpu"})
    return XGBRanker(**params, random_state=seed, verbosity=0)

def make_lgbm_ranker(*, seed: int, use_gpu: bool) -> LGBMRanker:
    params = {"objective": "lambdarank", "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 63}
    if use_gpu:
        params.update({"device_type": "gpu"})
    return LGBMRanker(**params, random_state=seed, verbosity=-1)

def make_catboost_ranker(*, seed: int, use_gpu: bool) -> CatBoostRanker:
    params = {"loss_function": "YetiRank", "iterations": 300, "depth": 6, "learning_rate": 0.05}
    if use_gpu:
        params.update({"task_type": "GPU"})
    else:
        params.update({"task_type": "CPU"})
    return CatBoostRanker(**params, random_seed=seed, verbose=False)
```

Use `use_gpu=False` as an explicit fallback path so the same code can run on CPU-only machines.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_gpu_model_zoo.py -k gpu_params -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ml/last_digit/hall_gpu_model_zoo.py ml/tests/test_hall_gpu_model_zoo.py
git commit -m "feat: add gpu ranker backends to hall model zoo"
```

### Task 3: Add evaluation and comparison output

**Files:**
- Modify: `ml/last_digit/hall_gpu_model_zoo.py`
- Modify: `ml/tests/test_hall_gpu_model_zoo.py`

- [ ] **Step 1: Write the failing test**

```python
def test_comparison_table_has_expected_metrics():
    rows = [
        {
            "model_name": "xgb_ranker",
            "backend": "xgboost",
            "use_gpu": True,
            "chosen_avg_diff_mean": 123.4,
            "top1_hit_rate": 0.31,
            "top2_inclusion_rate": 0.50,
            "spearman_daily_mean": 0.42,
            "regret_mean": 138.5,
            "wall_time_seconds": 99.0,
        }
    ]
    df = zoo.build_comparison_frame(rows)
    assert {"chosen_avg_diff_mean", "spearman_daily_mean", "top1_hit_rate"}.issubset(df.columns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_gpu_model_zoo.py -k comparison_table -v`
Expected: FAIL until the comparison builder exists.

- [ ] **Step 3: Write minimal implementation**

```python
def build_comparison_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    wanted = [
        "model_name",
        "backend",
        "use_gpu",
        "chosen_avg_diff_mean",
        "top1_hit_rate",
        "top2_inclusion_rate",
        "spearman_daily_mean",
        "regret_mean",
        "wall_time_seconds",
    ]
    df = df.loc[:, wanted].copy()
    return df.sort_values(
        ["chosen_avg_diff_mean", "spearman_daily_mean", "regret_mean"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
```

The comparison frame should include:
- `strategy` / `model_name`
- `chosen_avg_diff_mean`
- `top1_hit_rate`
- `top2_inclusion_rate`
- `spearman_daily_mean`
- `regret_mean`
- `wall_time_seconds`
- `backend` and `use_gpu`

Add a smoke CLI run that writes:
- `hall_gpu_model_zoo_summary.csv`
- `hall_gpu_model_zoo_detailed.csv`
- `hall_gpu_model_zoo.json`

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_gpu_model_zoo.py -k comparison_table -v`
Expected: PASS.

- [ ] **Step 5: Run a smoke benchmark**

Run:
`venv\Scripts\python.exe -m ml.last_digit.hall_gpu_model_zoo --use-gpu --gpu-backend cuda --output-root db/experiments/hall_gpu_model_zoo_smoke`

Expected:
- The three rankers complete on a CUDA-capable machine.
- The output CSV/JSON files are produced.
- The comparison table can be read side-by-side with the existing CPU strategy results.

- [ ] **Step 6: Commit**

```bash
git add ml/last_digit/hall_gpu_model_zoo.py ml/tests/test_hall_gpu_model_zoo.py
git commit -m "feat: add hall gpu model zoo evaluation"
```
