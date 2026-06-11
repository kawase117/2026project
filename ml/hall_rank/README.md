# Hall Rank

Hall prediction entrypoints are canonical under `ml/hall_rank/`.

Examples:

```powershell
venv\Scripts\python.exe -m ml.hall_rank.hall_gpu_model_zoo `
  --grid-profile small `
  --output-prefix ml/hall_rank/reports/hall_gpu_model_zoo_full
```

```powershell
venv\Scripts\python.exe -m ml.hall_rank.hall_practical_strategy_analysis `
  --output-root db/experiments/hall_rank/hall_practical_strategy_followup_20260601
```

