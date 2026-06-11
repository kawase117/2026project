# 2026-06-07 individual machine diff prediction plan

## Goal

Build a leakage-safe walk-forward classifier for individual machine `diff_coins_normalized >= 0`, and compare:

- baseline: 36 features from `ml/prediction/mitoya_daily_prediction.py`
- with_corner: the same 36 features plus `pred_corner_top_prob`

## Data flow

1. Load `machine_detailed_results`, `machine_layout`, and `machine_master` from SQLite.
2. Recreate the 36 numeric features used in `mitoya_daily_prediction.py`.
3. Load precomputed corner predictions from `data/corner_rank_prediction_by_section`.
4. Aggregate corner output to `date + section` and use the mean corner probability from corner rows as `pred_corner_top_prob`.
5. Merge the corner feature into the individual-machine frame, then run the same walk-forward folds for both models.

## Outputs

- `data/individual_machine_diff_prediction/individual_machine_diff_plus_validation.csv`
- `data/individual_machine_diff_prediction/individual_machine_diff_plus_metrics.csv`
- `data/individual_machine_diff_prediction/individual_machine_diff_plus_feature_importance.csv`

## Validation

- Verify the feature list is 36 without corner and 37 with corner.
- Verify missing corner predictions fall back to 0.5.
- Verify both models use the same fold list.
- Verify metrics are computed for baseline, with_corner, and improvement rows.

