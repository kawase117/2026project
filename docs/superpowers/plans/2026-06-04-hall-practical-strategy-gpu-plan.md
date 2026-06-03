# Hall Practical Strategy GPU Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `hall_practical_strategy_analysis.py` to a practical GPU-backed training path so repeated sweeps run faster without changing the evaluation semantics.

**Architecture:** Keep the existing experiment outputs and policy evaluation logic, but swap the CPU-only learner stack to an XGBoost-based backend that can run on CUDA when available. Preserve a CPU fallback for environments without a working GPU so smoke tests and CI remain usable. Reduce runtime further by shrinking the policy grid once the GPU learner is in place, since the policy sweep is still the dominant hot path.

**Tech Stack:** Python, pandas, numpy, xgboost, scikit-learn compatibility wrappers, pytest.

---

### Task 1: Add a GPU-capable learner backend

**Files:**
- Modify: `ml/last_digit/hall_practical_strategy_analysis.py`
- Modify: `ml/tests/test_hall_practical_strategy_analysis.py`

- [ ] **Step 1: Write the failing test**

```python
def test_gpu_backend_flag_wires_xgboost_params():
    params = build_model_params(use_gpu=True, gpu_backend="cuda")
    assert params["device"] == "cuda"
    assert params["tree_method"] == "hist"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_practical_strategy_analysis.py -k gpu_backend -v`
Expected: FAIL because the current hall strategy analysis code does not expose a GPU backend adapter.

- [ ] **Step 3: Write minimal implementation**

```python
from xgboost import XGBClassifier, XGBRegressor

def build_model_params(*, use_gpu: bool, gpu_backend: str) -> dict[str, Any]:
    if not use_gpu:
        return {"device": "cpu"}
    if gpu_backend == "cuda":
        return {"tree_method": "hist", "device": "cuda"}
    return {"tree_method": "gpu_hist"}

def make_binary_model(*, c: float, use_gpu: bool, gpu_backend: str) -> XGBClassifier:
    params = build_model_params(use_gpu=use_gpu, gpu_backend=gpu_backend)
    return XGBClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.9,
        colsample_bytree=0.9,
        reg_alpha=0.0,
        reg_lambda=1.0,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
        **params,
    )

def make_regressor(*, use_gpu: bool, gpu_backend: str) -> XGBRegressor:
    params = build_model_params(use_gpu=use_gpu, gpu_backend=gpu_backend)
    return XGBRegressor(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        random_state=42,
        **params,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_practical_strategy_analysis.py -k gpu_backend -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ml/last_digit/hall_practical_strategy_analysis.py ml/tests/test_hall_practical_strategy_analysis.py
git commit -m "feat: add gpu-capable learners to hall strategy analysis"
```

### Task 2: Wire GPU flags through the experiment runner

**Files:**
- Modify: `ml/last_digit/hall_practical_strategy_analysis.py`
- Modify: `ml/tests/test_hall_practical_strategy_analysis.py`

- [ ] **Step 1: Write the failing test**

```python
def test_parser_exposes_gpu_flags():
    parser = build_parser()
    args = parser.parse_args(["--use-gpu", "--gpu-backend", "cuda"])
    assert args.use_gpu is True
    assert args.gpu_backend == "cuda"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_practical_strategy_analysis.py -k gpu_flags -v`
Expected: FAIL until CLI flags are added to the parser.

- [ ] **Step 3: Write minimal implementation**

```python
p.add_argument("--use-gpu", action="store_true", help="Enable GPU learners when available")
p.add_argument("--gpu-backend", choices=["cuda", "gpu_hist"], default="cuda")
```

Use the new flags in the pooled, per-hall, and hybrid training paths so each learner is created through the GPU-aware helpers.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_practical_strategy_analysis.py -k gpu_flags -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ml/last_digit/hall_practical_strategy_analysis.py ml/tests/test_hall_practical_strategy_analysis.py
git commit -m "feat: wire gpu flags through hall strategy analysis"
```

### Task 3: Shrink the policy sweep and verify the speedup

**Files:**
- Modify: `ml/last_digit/hall_practical_strategy_analysis.py`
- Modify: `ml/tests/test_hall_practical_strategy_analysis.py`
- Add: `db/experiments/...` output from a smoke run

- [ ] **Step 1: Write the failing test**

```python
def test_policy_grid_can_be_smaller_for_gpu_runs():
    grid = build_policy_grid(use_gpu=True)
    assert len(grid) < 7680
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_practical_strategy_analysis.py -k policy_grid_can_be_smaller -v`
Expected: FAIL until the grid builder exposes a smaller GPU-specific sweep.

- [ ] **Step 3: Write minimal implementation**

```python
def build_policy_grid(*, use_gpu: bool) -> list[dict[str, float]]:
    edge_grid = [0.0, 0.08, 0.16] if use_gpu else [0.0, 0.04, 0.08, 0.12, 0.16, 0.2]
    weight_grid = [(1.0, 1.0, 1.0), (1.0, 1.5, 2.0), (1.0, 2.0, 3.0)]
```

Use a reduced grid only when `--use-gpu` is on. Keep the non-GPU path unchanged so existing comparisons remain valid.
This assumes an XGBoost build with CUDA support is installed in the active venv.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python.exe -m pytest ml/tests/test_hall_practical_strategy_analysis.py -k policy_grid_can_be_smaller -v`
Expected: PASS.

- [ ] **Step 5: Run a smoke benchmark**

Run:
`venv\Scripts\python.exe -m ml.last_digit.hall_practical_strategy_analysis --use-gpu --gpu-backend cuda --hybrid-logreg-c-grid 0.1 --output-root db/experiments/hall_practical_strategy_gpu_smoke`

Expected:
- The run completes successfully on a CUDA-capable machine.
- `run_summary.json` is produced.
- The total wall time is lower than the current CPU run on the same data slice.

- [ ] **Step 6: Commit**

```bash
git add ml/last_digit/hall_practical_strategy_analysis.py ml/tests/test_hall_practical_strategy_analysis.py
git commit -m "perf: reduce hall strategy sweep for gpu runs"
```
