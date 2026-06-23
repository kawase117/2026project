# Gate Ranking Connection Test Report

Output: `ml/experiments/gate_ranking_test/results_v2_opt`
Test days: 8
CatBoost available: yes
ML fallback days: 0

## 1. Series Comparison (Active Days Only)

| series_id | event_type | precision_at_10 | precision_at_15 | lift_at_10 | lift_at_15 | avg_payout_at_10 | avg_payout_at_15 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | all | 0.150 | 0.192 | 0.735 | 0.940 | 97.867 | 99.549 | 8 | 0 |
| gate_v6a | all | 0.138 | 0.142 | 0.675 | 0.695 | 99.772 | 98.255 | 8 | 0 |
| gate_random | all | 0.188 | 0.167 | 0.919 | 0.817 | 100.631 | 103.320 | 8 | 0 |
| gate_v6b_rule | all | 0.138 | 0.142 | 0.675 | 0.695 | 100.101 | 98.627 | 8 | 0 |
| gate_ml_shadow | all | 0.212 | 0.267 | 1.043 | 1.309 | 101.657 | 108.363 | 8 | 0 |

## 2. Event vs Non-Event

| series_id | event_type | precision_at_10 | precision_at_15 | lift_at_10 | lift_at_15 | avg_payout_at_10 | avg_payout_at_15 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | event | 0.100 | 0.200 | 0.492 | 0.983 | 93.188 | 97.787 | 2 | 0 |
| nogate_v6a | non_event | 0.167 | 0.189 | 0.817 | 0.926 | 99.426 | 100.136 | 6 | 0 |
| gate_v6a | event | 0.050 | 0.067 | 0.246 | 0.328 | 90.884 | 92.504 | 2 | 0 |
| gate_v6a | non_event | 0.167 | 0.167 | 0.818 | 0.818 | 102.735 | 100.172 | 6 | 0 |
| gate_random | event | 0.050 | 0.067 | 0.246 | 0.328 | 87.285 | 91.865 | 2 | 0 |
| gate_random | non_event | 0.233 | 0.200 | 1.144 | 0.981 | 105.079 | 107.138 | 6 | 0 |
| gate_v6b_rule | event | 0.050 | 0.067 | 0.246 | 0.328 | 90.468 | 92.504 | 2 | 0 |
| gate_v6b_rule | non_event | 0.167 | 0.167 | 0.818 | 0.818 | 103.312 | 100.668 | 6 | 0 |
| gate_ml_shadow | event | 0.250 | 0.267 | 1.229 | 1.311 | 106.735 | 106.455 | 2 | 0 |
| gate_ml_shadow | non_event | 0.200 | 0.267 | 0.981 | 1.308 | 99.964 | 108.999 | 6 | 0 |

## 3. Front/Back Stability

| series_id | split_period | precision_at_10 | precision_at_15 | lift_at_10 | avg_payout_at_10 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | front | 0.125 | 0.150 | 0.613 | 96.965 | 4 | 0 |
| nogate_v6a | back | 0.175 | 0.233 | 0.857 | 98.769 | 4 | 0 |
| gate_v6a | front | 0.125 | 0.100 | 0.614 | 102.273 | 4 | 0 |
| gate_v6a | back | 0.150 | 0.183 | 0.737 | 97.272 | 4 | 0 |
| gate_random | front | 0.175 | 0.183 | 0.858 | 100.471 | 4 | 0 |
| gate_random | back | 0.200 | 0.150 | 0.980 | 100.791 | 4 | 0 |
| gate_v6b_rule | front | 0.125 | 0.100 | 0.614 | 101.655 | 4 | 0 |
| gate_v6b_rule | back | 0.150 | 0.183 | 0.736 | 98.546 | 4 | 0 |
| gate_ml_shadow | front | 0.275 | 0.300 | 1.350 | 109.726 | 4 | 0 |
| gate_ml_shadow | back | 0.150 | 0.233 | 0.737 | 93.588 | 4 | 0 |

## 4. Gate Coverage

| series_id | n_active_machines | n_days_active_lt_10 | n_test_days |
| --- | --- | --- | --- |
| gate_ml_shadow | 132.500 | 0 | 10 |
| gate_random | 132.500 | 0 | 10 |
| gate_v6a | 132.500 | 0 | 10 |
| gate_v6b_rule | 132.500 | 0 | 10 |
| nogate_v6a | 702.700 | 0 | 10 |

## 5. ML Shadow vs Rule-Based

| metric | gate_v6b_rule | gate_ml_shadow | delta |
|--------|---------------|----------------|-------|
| p@10 (all) | 0.138 | 0.212 | 0.075 |
| p@10 (front) | 0.125 | 0.275 | 0.150 |
| p@10 (back) | 0.150 | 0.150 | -0.000 |
| AUC (all) | N/A | 0.594 | N/A |

## 6. Segment-Level Detail

| series_id | active_segments | precision_at_10 | precision_at_15 | lift_at_10 | n_test_days |
| --- | --- | --- | --- | --- | --- |
| gate_ml_shadow | 2F_L_N,3F_R_N | 0.200 | 0.200 | 0.982 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_N | 0.400 | 0.333 | 1.964 | 1 |
| gate_ml_shadow | 3F_L_N | 0.300 | 0.333 | 1.472 | 2 |
| gate_ml_shadow | 3F_L_N,3F_R_N | 0.100 | 0.200 | 0.491 | 3 |
| gate_ml_shadow | 3F_R_N | 0.200 | 0.333 | 0.984 | 1 |
| gate_random | 2F_L_N,3F_R_N | 0.000 | 0.067 | 0.000 | 1 |
| gate_random | 2F_R_N,3F_L_N | 0.200 | 0.133 | 0.982 | 1 |
| gate_random | 3F_L_N | 0.250 | 0.200 | 1.225 | 2 |
| gate_random | 3F_L_N,3F_R_N | 0.233 | 0.178 | 1.143 | 3 |
| gate_random | 3F_R_N | 0.100 | 0.200 | 0.492 | 1 |
| gate_v6a | 2F_L_N,3F_R_N | 0.400 | 0.333 | 1.964 | 1 |
| gate_v6a | 2F_R_N,3F_L_N | 0.200 | 0.133 | 0.982 | 1 |
| gate_v6a | 3F_L_N | 0.100 | 0.067 | 0.491 | 2 |
| gate_v6a | 3F_L_N,3F_R_N | 0.033 | 0.133 | 0.163 | 3 |
| gate_v6a | 3F_R_N | 0.200 | 0.133 | 0.984 | 1 |
| gate_v6b_rule | 2F_L_N,3F_R_N | 0.400 | 0.400 | 1.964 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_N | 0.200 | 0.133 | 0.982 | 1 |
| gate_v6b_rule | 3F_L_N | 0.100 | 0.067 | 0.491 | 2 |
| gate_v6b_rule | 3F_L_N,3F_R_N | 0.033 | 0.111 | 0.163 | 3 |
| gate_v6b_rule | 3F_R_N | 0.200 | 0.133 | 0.984 | 1 |
| nogate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.150 | 0.192 | 0.735 | 8 |

## 7. Pass/Fail Judgment

- [ ] gate_v6a precision@10 > nogate_v6a precision@10 (all)
- [ ] gate_v6a precision@10 > nogate_v6a precision@10 (front)
- [ ] gate_v6a precision@10 > nogate_v6a precision@10 (back)
- [ ] gate_v6a precision@10 > gate_random precision@10
- [ ] gate_v6b_rule precision@10 > gate_v6a precision@10 (all)
- [ ] gate_v6b_rule precision@10 > gate_v6a precision@10 (front)
- [x] gate_v6b_rule precision@10 > gate_v6a precision@10 (back)
- [x] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 + 0.05 (all)
- [x] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (front)
- [ ] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (back)
- [x] gate_ml_shadow precision@10 > gate_random precision@10

Overall verdict: PASS / FAIL / PARTIAL -> **PARTIAL**
