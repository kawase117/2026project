# 2026-06-07 individual-machine diff prediction by section

## Goal
Build a section-specific individual-machine CatBoost pipeline that compares:
- baseline: existing 36 features
- with_corner: existing 36 features + `pred_corner_top_prob`

## Data flow
1. Load raw machine rows from the SQLite DB.
2. Build the existing individual-machine feature frame.
3. Load corner prediction outputs from `corner_rank_prediction_by_section_window_ablation_validation.csv`.
4. Filter the corner data to the selected scenario `xday_7mean`.
5. Merge corner probabilities into the machine-level frame.
6. Split the data by `section`, then run walk-forward folds independently inside each section.
7. Train baseline and with-corner CatBoost models for every section/fold.

## Outputs
- `individual_machine_diff_prediction_by_section_validation.csv`
- `individual_machine_diff_prediction_by_section_metrics.csv`
- `individual_machine_diff_prediction_by_section_feature_importance.csv`

## Validation
- Confirm per-section metrics are emitted for both model types.
- Confirm `pred_corner_top_prob` appears in with-corner feature importance.
- Confirm the validation CSV uses the expected columns and section-specific model IDs.

