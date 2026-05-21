# Machine-Type ML Design

**Date:** 2026-05-21  
**Scope:** `ml/machine_type/` new implementation for machine-name-based forecasting in `2026project`

## Goal

Implement a machine-type forecasting workflow that follows the operational shape used in `ml/last_digit/`, but predicts at the `machine_name` level instead of `last_digit`.

The workflow must support:

- `is_rank_1`
- `is_top_2`
- `is_top_3`
- `is_top_5`
- next-day prediction output
- monthly reliability checking
- leakage-safe feature generation
- consolidated outputs under `ml/machine_type/reports/`
- a README with operational commands and artifact guidance

The first version should remain global across all machine names and report Thursday vs non-Thursday behavior separately without splitting the model by weekday.

## Constraints

- Do not break existing `ml/last_digit/` code or the compatibility wrappers under `ml/experiments/tail_ltr_*`.
- Preserve the existing wrapper contract for last-digit commands.
- Keep all training and prediction logic leakage-safe with `train_end < pred_date`.
- Run `--help` verification at minimum before completion.

## Problem Definition

The target entity is `machine_name` itself, based on `daily_machine_type_summary`.

Raw `avg_diff_coins` is not sufficient for rank labeling because machine counts vary heavily by machine name. A single-machine category can spike due to noise and dominate larger, more reliable categories if raw average difference is used directly.

Because of that, training labels will be created from a shrunk ranking score rather than raw average difference.

## Label Definition

### Shrunk ranking score

For each `(date, machine_name)` row, compute:

```python
shrunk_avg_diff = (
    (machine_count / (machine_count + alpha)) * avg_diff_coins
    + (alpha / (machine_count + alpha)) * daily_global_avg_diff
)
```

Where:

- `machine_count`: machine count for that machine name on that day
- `avg_diff_coins`: average difference for that machine name on that day
- `daily_global_avg_diff`: same-day average across all machine names
- `alpha`: shrinkage strength hyperparameter

Interpretation:

- large machine counts stay close to observed `avg_diff_coins`
- small machine counts are partially pulled back toward the daily global average
- labels become more robust against lucky one-machine spikes

### Rank labels

Within each day, rank machine names by `shrunk_avg_diff` descending and define:

- `is_rank_1`: rank == 1
- `is_top_2`: rank <= 2
- `is_top_3`: rank <= 3
- `is_top_5`: rank <= 5

For audit and reporting, also keep:

- `raw_avg_rank`
- `shrunk_rank`
- `avg_diff_coins`
- `shrunk_avg_diff`

### Initial alpha handling

Version 1 uses a fixed `alpha` value. This value is not tuned inside the first implementation loop. It should be exposed in the CLI/config so later ablation can compare alternatives without changing code structure.

## Data Sources

Primary tables:

- `daily_machine_type_summary`
- `machine_master`

Expected key columns from `daily_machine_type_summary`:

- `date`
- `machine_name`
- `machine_count`
- `total_games`
- `avg_games`
- `total_diff_coins`
- `avg_diff_coins`
- optional `win_rate`

Reference data from `machine_master` is used only when needed for enrichment or validation. The core entity remains `machine_name`, not a family grouping such as `jug/hana/oki/bt/other`.

## Data Audit Requirements

Before model training, create an explicit audit step that checks:

- duplicate `(date, machine_name)` rows
- date parsing consistency
- null or missing values in `machine_count`, `avg_diff_coins`, `total_games`
- join miss rate against `machine_master`
- gaps in machine-name history
- first-seen dates for new machine names
- machine-count change history by machine name
- type consistency for numeric columns
- suspicious future leakage from already-aggregated columns

Audit output must be written to JSON under `ml/machine_type/reports/`.

## Leakage Rules

The implementation must enforce the following:

- all rolling and expanding history uses prior-only values
- all rolling and expanding history must be based on `shift(1)` semantics
- no same-day realized values may be used to predict the same day
- next-day placeholder rows may inherit metadata but not realized target or realized performance values
- monthly and holdout evaluation must respect `train_end < pred_date`

Unit tests should include at least one regression case proving that shifted historical features do not use current-row target information.

## Evaluation Protocol

Evaluation design must be fixed before tuning.

### Main metrics

- `Hit@1`
- `Hit@2`
- `Hit@3`
- `Hit@5`
- threshold-based `F1`
- threshold-based `Recall`
- threshold-based `Precision`

### Operational metrics

- `skip_rate`
- `predicted_count`
- target base rate
- Thursday-only metrics
- non-Thursday metrics

### Baseline comparisons

Compare against at least:

- ranking by raw `avg_diff_coins`
- ranking by `machine_count`
- random baseline

### Time split

Version 1 should use fixed time ordering with explicit train/valid/test separation. The implementation should centralize split logic so it can later support regime-specific experiments without rewriting feature code.

Thursday is treated as an analysis slice in v1, not as a separate model branch.

## Feature Strategy

Version 1 uses a focused feature set that combines periodicity and machine-specific lifecycle effects.

### Basic performance and activity features

- `machine_count`
- `total_games`
- `avg_games`
- `total_diff_coins`
- `avg_diff_coins`
- `efficiency`
- lag features for `1/7/14/21` days where meaningful
- rolling averages for `7/14/28` days

### History and recurrence features

- `prior_rank1_rate`
- `prior_top2_rate`
- `prior_top3_rate`
- `prior_top5_rate`
- `days_since_last_rank1`
- `days_since_last_top2`
- `days_since_last_top3`
- `days_since_last_top5`
- `same_weekday_rank1_rate`
- `same_weekday_top3_rate`
- `same_weekday_rolling_rank_sum_3`

### Machine lifecycle and count-change features

- `days_since_first_seen`
- `count_delta_1d`
- `count_delta_7d`
- `count_increase_flag`
- `count_decrease_flag`
- `days_since_last_count_increase`
- `days_since_last_count_decrease`
- count-change bins for recent increase/decrease behavior

These are important because machine-name entities can appear, disappear, increase, or decrease in count over time, unlike last-digit entities.

### Calendar and event features

- `day_of_week`
- `month_progress`
- `is_event_day`
- event distance or proximity signals if available from current repo logic
- `is_thursday`

`is_thursday` is included as a feature and must also be used for evaluation breakdowns. However, the first model remains a single global model.

### Binning policy

For exploratory machine lifecycle features, keep raw and binned variants together initially. Do not prematurely drop raw count deltas or raw recency features before importance or ablation confirms redundancy.

## Proposed Package Layout

Create:

- `ml/machine_type/__init__.py`
- `ml/machine_type/machine_type_common.py`
- `ml/machine_type/machine_type_nextday.py`
- `ml/machine_type/machine_type_monthly_check.py`
- `ml/machine_type/README.md`
- `ml/machine_type/reports/`
- `ml/tests/test_machine_type_common.py`
- `ml/tests/test_machine_type_cli.py`

Responsibilities:

- `machine_type_common.py`
  - data loading
  - audit helpers
  - shrinkage label generation
  - feature generation
  - split helpers
  - shared output formatting
- `machine_type_nextday.py`
  - next-day CLI entrypoint
  - forecast artifact generation
- `machine_type_monthly_check.py`
  - reliability CLI entrypoint
  - fixed-period evaluation and summary artifacts

## Outputs

All machine-type outputs should live under `ml/machine_type/reports/`.

Required artifacts:

- `*_nextday_prediction.json`
- `*_nextday_prediction.csv`
- `*_reliability_daily.csv`
- `*_reliability_monthly.csv`
- `*_audit_report.json`

Prediction outputs should include:

- `machine_name`
- ranking score
- per-target probabilities
- `raw_avg_rank`
- `shrunk_rank`
- supporting confidence fields if used

## README Scope

`ml/machine_type/README.md` must explain:

- operational purpose
- command lines for next-day prediction
- command lines for monthly checking
- meaning of major report files
- how to read Thursday vs non-Thursday reliability output
- the shrinkage-label rationale

## Validation Requirements

Minimum validation before calling the work complete:

1. unit tests for:
   - shrinkage label calculation
   - `shift(1)` leakage safety
   - new-machine detection
   - count-increase and count-decrease recency logic
2. CLI verification:
   - `python -m ml.machine_type.machine_type_nextday --help`
   - `python -m ml.machine_type.machine_type_monthly_check --help`
3. minimal execution path:
   - audit
   - next-day prediction
   - monthly check

## Operational Assumptions

Version 1 allows skipping low-confidence days rather than forcing a daily action. This is important because machine-name forecasting has a larger candidate universe and more unstable tails than last-digit forecasting.

The first operating mode should expose skip-related reporting rather than force a hard always-play strategy.

## Deferred Work

The following are intentionally deferred until after v1 is working:

- separate Thursday and non-Thursday models
- broader regime gating
- multi-stage decision policies beyond simple thresholding and skip logic
- aggressive hyperparameter tuning
- large-scale feature pruning before initial ablation evidence

## Recommended Implementation Order

1. confirm working area and current git status handling
2. implement audit step and audit artifact
3. implement shrunk label generation
4. implement shared feature generation
5. implement next-day CLI
6. implement monthly-check CLI
7. add tests
8. verify `--help`
9. run minimal execution path
10. write README
