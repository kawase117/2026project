# Last-Digit ML

`ml/last_digit` contains the production-focused pipeline for last-digit prediction and related evaluation utilities.

## Main Scripts

- `tail_ltr_split_rule_nextday_gpu.py`
  - Daily next-day prediction (split4 experts, GPU-friendly).
- `tail_ltr_split_rule_wf.py`
  - Walk-forward evaluation for split-rule strategies.
- `tail_ltr_split_rule_monthly_check_gpu.py`
  - Monthly check/report wrapper.
- `tail_time_adaptive_ltr_poc_improved.py`
  - Core time-adaptive LTR experiments.
- `tail_ltr_full_walkforward_ops.py`
  - Full walk-forward ops utilities.
- `tail_ltr_profit_ops.py`
  - Profit-oriented evaluation utilities.
- `model_zoo_benchmark.py`
  - One-shot multi-model benchmark (XGBoost/CatBoost/LightGBM/sklearn + optional deep/RL-style baselines).

## Quick Help

```powershell
venv\Scripts\python.exe -m ml.last_digit.tail_ltr_split_rule_nextday_gpu --help
venv\Scripts\python.exe -m ml.last_digit.tail_ltr_split_rule_monthly_check_gpu --help
venv\Scripts\python.exe -m ml.last_digit.model_zoo_benchmark --help
```

## Model Zoo Benchmark

Run broad benchmarking in one command:

```powershell
venv\Scripts\python.exe -m ml.last_digit.model_zoo_benchmark `
  --include-deep --include-rl `
  --seeds 42,77,123,202,303,404,505,606 `
  --output-prefix ml/last_digit/reports/model_zoo_benchmark_full `
  --log-level INFO
```

Artifacts:

- `..._summary.csv`: averaged metrics per model
- `..._detailed.csv`: per-seed metrics
- `... .json`: execution config, failures, and top ranking snapshot

## Notes

- `2F_A` can be indeterminate (flat predictions) depending on data availability/quality.
- `--enable-test-period-report` in nextday flow is intentionally heavier than daily prediction.
