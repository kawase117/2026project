# run.json Schema

Each experiment is stored as `results/{experiment_id}/run.json` with the following structure.

## Root Level

```json
{
  "run_id": "string (unique identifier, e.g., '2026-05-09_rank1_is-other-flag_vs_onehot')",
  "experiment_id": "string (for backward compat, same as run_id)",
  "timestamp": "ISO 8601 datetime string (when the experiment was run)",
  "status": "string ('completed' | 'failed' | 'cancelled')",
  "decision": "string ('adopt' | 'inconclusive' | 'low_value' | 'invalid' | 'unreviewed')",
  
  // Core experiment metadata
  "question": "string (hypothesis being tested, required for decision making)",
  "phase": "integer (1-10+, which phase of ML pipeline)",
  "task": "string (e.g., 'rank_1', 'top_3', 'last_digit')",
  "ml_model": "string (model name, e.g., 'xgboost_md3_lr0.01_n200')",
  "groupby_strategy": "string (grouping approach, e.g., 'machine_type', 'tail', 'dd')",
  
  // Relationship to other runs
  "baseline_run_id": "string or null (run_id of baseline for comparison)",
  "changed_factors": ["array of strings (what was intentionally changed)"],
  "fixed_factors": { "object (what was held constant)" },
  
  // Data and split information
  "data": {
    "source_table": "string (e.g., 'daily_machine_type_summary')",
    "date_range": "string (e.g., '2026-01-01..2026-04-30')",
    "train_days": "integer (number of training days)",
    "test_days": "integer (number of test days)",
    "split_method": "string (e.g., 'time_series_last_57_days')"
  },
  
  // Main results
  "result": {
    "primary_metric": "string (e.g., 'auc')",
    "primary_value": "float (primary metric value)",
    "baseline_value": "float or null (baseline primary metric for comparison)",
    "delta": "float or null (primary_value - baseline_value)",
    "metrics": {
      "object with arbitrary keys, e.g.": {
        "auc": 0.7002,
        "accuracy": 0.8125,
        "precision": 0.7333,
        "recall": 0.55,
        "f1": 0.6274
      }
    }
  },
  
  // Interpretation
  "interpretation": "string (human explanation of what happened, can be multi-line)",
  "conclusion": "string (summary conclusion based on the metrics and interpretation)",
  "next_step": "string (what to try next, or why this is a dead end)",
  
  // Decision aids
  "retest_if": [
    "array of strings (conditions that would justify revisiting this run)"
  ],
  "tags": [
    "array of strings (searchable tags, e.g., 'feature_engineering', 'hyperparameter', 'baseline')"
  ],
  
  // Artifacts (for reference)
  "artifacts": [
    "array of paths relative to {experiment_id}/ (e.g., 'summary.html', 'metrics.json', 'artifacts/roc_curves.html')"
  ]
}
```

## Field Definitions

### `decision`
- **adopt** — This result is good enough to keep; implement this approach going forward
- **inconclusive** — Results don't clearly say yes/no; need more data or conditions to decide
- **low_value** — Small improvement (delta ≤ threshold); not worth the complexity or cost
- **invalid** — Broken experiment, data leak, or methodological flaw; discard the result
- **unreviewed** — Default; awaiting human review

### `changed_factors`
List of specific parameters/strategies that differ from the baseline. Examples:
- `"feature_encoding"` (e.g., one-hot → is_other_flag)
- `"model_hyperparameters"` (e.g., max_depth 3 → 5)
- `"feature_set"` (e.g., 16d baseline → 20d enhanced)
- `"split_strategy"` (e.g., random_split → time_series_split)

### `fixed_factors`
Object where each key is a factor name and the value is its constant value. Examples:
```json
{
  "hall": "マルハン蒲田7",
  "target": "rank_1",
  "split": "time_series_last_57_days",
  "model_base": "xgboost"
}
```

### `retest_if`
Conditions that **would justify revisiting** this experiment. These are constraints/conditions, not actions. If any become true, the experiment is worth re-running. Examples:
- `"hall_count >= 3"` (if we get more halls, retry)
- `"feature_set changed"` (if underlying features change, re-validate)
- `"delta > 0.02"` (if baseline improves significantly, re-measure)
- `"split_method != 'time_series'"` (if we change splits, re-evaluate)

### `tags`
Searchable categorical labels for filtering and grouping. Examples:
- `"baseline"` (is this a baseline model?)
- `"feature_engineering"` (primary focus of this run)
- `"hyperparameter_tuning"` (primary focus)
- `"baseline_vs_candidate"` (comparison run)
- `"all_halls"` (tested on all halls)
- `"single_hall"` (tested on one hall)
- `"rank_1"` (target: rank 1 prediction)
- `"top_3"` (target: top 3)

## Example: Feature Encoding Comparison

```json
{
  "run_id": "2026-05-09_rank1_is-other-flag_vs_onehot",
  "experiment_id": "2026-05-09_rank1_is-other-flag_vs_onehot",
  "timestamp": "2026-05-09T14:32:15.123456",
  "status": "completed",
  "decision": "low_value",
  
  "question": "Does replacing one-hot machine_type encoding with is_other 1-bit flag improve AUC?",
  "phase": 9,
  "task": "rank_1",
  "ml_model": "xgboost_md3_lr0.01_n200",
  "groupby_strategy": "machine_type",
  
  "baseline_run_id": "2026-05-08_phase9_onehot_baseline",
  "changed_factors": ["feature_encoding"],
  "fixed_factors": {
    "hall": "マルハン蒲田7",
    "target": "rank_1",
    "split": "time_series_last_57_days",
    "model": "xgboost_md3_lr0.01_n200"
  },
  
  "data": {
    "source_table": "daily_machine_type_summary",
    "date_range": "2026-01-01..2026-04-30",
    "train_days": 240,
    "test_days": 57,
    "split_method": "time_series_last_57_days"
  },
  
  "result": {
    "primary_metric": "auc",
    "primary_value": 0.7002,
    "baseline_value": 0.6959,
    "delta": 0.0043,
    "metrics": {
      "auc": 0.7002,
      "accuracy": 0.7895,
      "precision": 0.6667,
      "recall": 0.55,
      "f1": 0.6034
    }
  },
  
  "interpretation": "The is_other flag encoding marginally improves AUC (+0.43%), but the absolute improvement is small and likely within noise. The model still struggles with recall (55%), indicating the feature set lacks discriminative power for rank_1 prediction.",
  "conclusion": "改善は小さく (delta=+0.43%), 再現優先度は低い。このアプローチの複雑度と利益が釣り合わない。",
  "next_step": "target_encodingやカテゴリエンボーディング等の別手法を試す前に、feature_setそのものの拡張を優先すること。",
  
  "retest_if": [
    "hall count >= 3",
    "feature_set expanded beyond machine_type",
    "split method changes from time_series"
  ],
  "tags": ["baseline_vs_candidate", "feature_encoding", "rank_1", "single_hall"],
  "artifacts": ["summary.html", "artifacts/roc_curves.html", "metrics.json"]
}
```

## Usage in Index Records

When creating `index.jsonl` entries, extract a minimal projection:

```json
{
  "run_id": "2026-05-09_rank1_is-other-flag_vs_onehot",
  "timestamp": "2026-05-09T14:32:15.123456",
  "phase": 9,
  "task": "rank_1",
  "ml_model": "xgboost_md3_lr0.01_n200",
  "groupby_strategy": "machine_type",
  "decision": "low_value",
  "primary_metric": "auc",
  "primary_value": 0.7002,
  "delta": 0.0043,
  "tags": ["baseline_vs_candidate", "feature_encoding", "rank_1"],
  "path": "2026-05-09_rank1_is-other-flag_vs_onehot/run.json"
}
```
