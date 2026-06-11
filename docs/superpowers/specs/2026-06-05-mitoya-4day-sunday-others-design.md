# Mitoya 4day Sunday Others Design

**Context:** `ml/last_digit/tail_ltr_mitoya_wf.py` currently reuses the shared Wednesday-vs-non-Wednesday walk-forward split from `tail_ltr_split_rule_wf.py`. For Mitoya Omorimachi, that split is domain-wrong: Wednesday is not a special event day, while `4/14/24` and Sunday matter more operationally.

## Goal

Change the Mitoya walk-forward runner so it trains and evaluates three mutually exclusive day buckets:

- `4day`
- `Sunday`
- `others`

`4day` has priority over `Sunday`. A Sunday that falls on the 4th/14th/24th is treated as `4day`.

## Scope

In scope:

- `ml/last_digit/tail_ltr_mitoya_wf.py`
- new/updated tests under `ml/tests/`

Out of scope:

- `signal_existence_mitoya.py`
- shared `tail_ltr_split_rule_wf.py`
- other halls or pooled logic

## Approach

Keep the shared base module as a source of reusable primitives only: model training, feature extraction helpers, CSV parsing, logging, and evaluation helpers. Implement Mitoya-specific bucket selection locally inside `tail_ltr_mitoya_wf.py` instead of trying to generalize the shared Wednesday runner.

This avoids accidental behavior drift in other halls and makes the Mitoya logic explicit.

## Data Rules

- `4day`: calendar day in `{4, 14, 24}`
- `Sunday`: weekday is Sunday and not already classified as `4day`
- `others`: every remaining date

The walk-forward split remains leakage-safe:

- train/test windows are still time-based
- bucket filtering happens after date-window selection
- existing model/evaluation helpers remain unchanged

## Interface Changes

Replace the Wednesday-specific CLI options with bucket-specific options:

- `--min-train-days-4day`
- `--min-train-days-sunday`
- `--min-train-days-other`
- `--windows-4day`
- `--lambdas-4day`
- `--q-grid-4day`
- `--windows-sunday`
- `--lambdas-sunday`
- `--q-grid-sunday`
- `--windows-other`
- `--lambdas-other`
- `--q-grid-other`

The output summaries should no longer emit `wednesday_only` / `non_wednesday`. They should emit:

- `fourday_only`
- `sunday_only`
- `other_days`

Daily output CSVs should include a `day_bucket` column.

## Testing

Add regression tests for:

- bucket classification priority: `4day` overrides `Sunday`
- parser wiring for the new bucket CLI options
- summary bucket names and counts from a minimal synthetic day table

## Verification

Required verification after implementation:

- targeted pytest for the new Mitoya runner tests
- `python -m ml.last_digit.tail_ltr_mitoya_wf --help`
- a short smoke run with reduced blocks to confirm the runner completes and writes JSON/CSV artifacts
