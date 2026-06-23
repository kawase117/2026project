# Gate Ranking Connection Test Report

Output: `C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/ml/experiments/gate_ranking_test/results`
Test days: 195
CatBoost available: yes
ML fallback days: 0

## 1. Series Comparison (Active Days Only)

| series_id | event_type | precision_at_10 | precision_at_15 | lift_at_10 | lift_at_15 | avg_payout_at_10 | avg_payout_at_15 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | all | 0.197 | 0.213 | 0.969 | 1.047 | 100.344 | 101.189 | 195 | 0 |
| gate_v6a | all | 0.216 | 0.210 | 1.062 | 1.032 | 101.437 | 101.289 | 195 | 0 |
| gate_random | all | 0.188 | 0.189 | 0.924 | 0.928 | 101.478 | 101.170 | 195 | 0 |
| gate_v6b_rule | all | 0.218 | 0.209 | 1.070 | 1.025 | 101.477 | 101.092 | 195 | 0 |
| gate_ml_shadow | all | 0.217 | 0.219 | 1.065 | 1.076 | 101.401 | 101.188 | 195 | 0 |

## 2. Event vs Non-Event

| series_id | event_type | precision_at_10 | precision_at_15 | lift_at_10 | lift_at_15 | avg_payout_at_10 | avg_payout_at_15 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | event | 0.213 | 0.230 | 1.046 | 1.126 | 100.738 | 102.659 | 61 | 0 |
| nogate_v6a | non_event | 0.190 | 0.206 | 0.934 | 1.011 | 100.164 | 100.520 | 134 | 0 |
| gate_v6a | event | 0.234 | 0.227 | 1.150 | 1.116 | 103.047 | 102.500 | 61 | 0 |
| gate_v6a | non_event | 0.208 | 0.202 | 1.022 | 0.994 | 100.704 | 100.738 | 134 | 0 |
| gate_random | event | 0.156 | 0.161 | 0.764 | 0.788 | 99.361 | 99.679 | 61 | 0 |
| gate_random | non_event | 0.203 | 0.202 | 0.997 | 0.992 | 102.442 | 101.848 | 134 | 0 |
| gate_v6b_rule | event | 0.236 | 0.227 | 1.159 | 1.116 | 103.054 | 102.838 | 61 | 0 |
| gate_v6b_rule | non_event | 0.210 | 0.200 | 1.030 | 0.984 | 100.759 | 100.297 | 134 | 0 |
| gate_ml_shadow | event | 0.205 | 0.205 | 1.006 | 1.008 | 100.996 | 100.990 | 61 | 0 |
| gate_ml_shadow | non_event | 0.222 | 0.225 | 1.092 | 1.107 | 101.585 | 101.279 | 134 | 0 |

## 3. Front/Back Stability

| series_id | split_period | precision_at_10 | precision_at_15 | lift_at_10 | avg_payout_at_10 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | front | 0.191 | 0.216 | 0.937 | 100.312 | 97 | 0 |
| nogate_v6a | back | 0.204 | 0.210 | 1.001 | 100.375 | 98 | 0 |
| gate_v6a | front | 0.218 | 0.214 | 1.068 | 102.331 | 97 | 0 |
| gate_v6a | back | 0.215 | 0.207 | 1.056 | 100.551 | 98 | 0 |
| gate_random | front | 0.193 | 0.192 | 0.947 | 102.599 | 97 | 0 |
| gate_random | back | 0.184 | 0.186 | 0.901 | 100.369 | 98 | 0 |
| gate_v6b_rule | front | 0.221 | 0.208 | 1.084 | 102.422 | 97 | 0 |
| gate_v6b_rule | back | 0.215 | 0.210 | 1.056 | 100.541 | 98 | 0 |
| gate_ml_shadow | front | 0.201 | 0.210 | 0.988 | 101.114 | 97 | 0 |
| gate_ml_shadow | back | 0.233 | 0.229 | 1.142 | 101.685 | 98 | 0 |

## 4. Gate Coverage

| series_id | n_active_machines | n_days_active_lt_10 | n_test_days |
| --- | --- | --- | --- |
| gate_ml_shadow | 189.342 | 0 | 257 |
| gate_random | 189.342 | 0 | 257 |
| gate_v6a | 189.342 | 0 | 257 |
| gate_v6b_rule | 189.342 | 0 | 257 |
| nogate_v6a | 701.210 | 0 | 257 |

## 5. ML Shadow vs Rule-Based

| metric | gate_v6b_rule | gate_ml_shadow | delta |
|--------|---------------|----------------|-------|
| p@10 (all) | 0.218 | 0.217 | -0.001 |
| p@10 (front) | 0.221 | 0.201 | -0.020 |
| p@10 (back) | 0.215 | 0.233 | 0.017 |
| AUC (all) | N/A | 0.539 | N/A |

## 6. Segment-Level Detail

| series_id | active_segments | precision_at_10 | precision_at_15 | lift_at_10 | n_test_days |
| --- | --- | --- | --- | --- | --- |
| gate_ml_shadow | 2F_L_N | 0.154 | 0.200 | 0.755 | 13 |
| gate_ml_shadow | 2F_L_N,2F_R_N | 0.175 | 0.200 | 0.859 | 4 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.200 | 0.133 | 0.978 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.133 | 0.490 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.982 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.175 | 0.200 | 0.862 | 4 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.217 | 0.256 | 1.066 | 6 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_N | 0.550 | 0.433 | 2.717 | 2 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.350 | 0.333 | 1.721 | 2 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.100 | 0.133 | 0.495 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_R_A | 0.150 | 0.200 | 0.735 | 2 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.333 | 0.289 | 1.634 | 3 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_R_N | 0.200 | 0.133 | 0.983 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_L_N | 0.200 | 0.133 | 0.975 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.200 | 0.156 | 0.983 | 3 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_R_A | 0.200 | 0.222 | 0.980 | 3 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.067 | 0.156 | 0.327 | 3 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_R_N | 0.100 | 0.200 | 0.488 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_N | 0.250 | 0.233 | 1.226 | 2 |
| gate_ml_shadow | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.471 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_N,3F_R_N | 0.150 | 0.200 | 0.736 | 2 |
| gate_ml_shadow | 2F_L_N,3F_R_A | 0.150 | 0.133 | 0.739 | 2 |
| gate_ml_shadow | 2F_L_N,3F_R_N | 0.200 | 0.210 | 0.979 | 7 |
| gate_ml_shadow | 2F_R_N | 0.150 | 0.171 | 0.737 | 14 |
| gate_ml_shadow | 2F_R_N,3F_L_A | 0.200 | 0.267 | 0.978 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N | 0.100 | 0.200 | 0.490 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.267 | 0.489 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.233 | 0.200 | 1.147 | 3 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.300 | 0.267 | 1.471 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_R_A | 0.150 | 0.167 | 0.737 | 2 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.475 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_N | 0.300 | 0.274 | 1.474 | 9 |
| gate_ml_shadow | 2F_R_N,3F_L_N,3F_R_N | 0.100 | 0.200 | 0.491 | 2 |
| gate_ml_shadow | 2F_R_N,3F_R_A | 0.300 | 0.333 | 1.473 | 1 |
| gate_ml_shadow | 2F_R_N,3F_R_A,3F_R_N | 0.000 | 0.067 | 0.000 | 1 |
| gate_ml_shadow | 2F_R_N,3F_R_N | 0.400 | 0.333 | 1.961 | 2 |
| gate_ml_shadow | 3F_L_A | 0.188 | 0.192 | 0.920 | 8 |
| gate_ml_shadow | 3F_L_A,3F_L_N | 0.333 | 0.244 | 1.636 | 3 |
| gate_ml_shadow | 3F_L_A,3F_L_N,3F_R_A | 0.400 | 0.400 | 1.964 | 1 |
| gate_ml_shadow | 3F_L_A,3F_R_A | 0.160 | 0.167 | 0.785 | 10 |
| gate_ml_shadow | 3F_L_A,3F_R_A,3F_R_N | 0.000 | 0.067 | 0.000 | 1 |
| gate_ml_shadow | 3F_L_A,3F_R_N | 0.333 | 0.289 | 1.637 | 3 |
| gate_ml_shadow | 3F_L_N | 0.256 | 0.237 | 1.255 | 18 |
| gate_ml_shadow | 3F_L_N,3F_R_A | 0.125 | 0.150 | 0.613 | 4 |
| gate_ml_shadow | 3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.233 | 0.985 | 2 |
| gate_ml_shadow | 3F_L_N,3F_R_N | 0.309 | 0.267 | 1.518 | 11 |
| gate_ml_shadow | 3F_R_A | 0.256 | 0.237 | 1.255 | 9 |
| gate_ml_shadow | 3F_R_N | 0.216 | 0.221 | 1.059 | 19 |
| gate_random | 2F_L_N | 0.177 | 0.185 | 0.868 | 13 |
| gate_random | 2F_L_N,2F_R_N | 0.200 | 0.150 | 0.984 | 4 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.490 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.000 | 0.000 | 0.000 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.275 | 0.267 | 1.347 | 4 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.183 | 0.189 | 0.902 | 6 |
| gate_random | 2F_L_N,2F_R_N,3F_L_N | 0.250 | 0.167 | 1.235 | 2 |
| gate_random | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.100 | 0.100 | 0.491 | 2 |
| gate_random | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.133 | 0.990 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_R_A | 0.200 | 0.200 | 0.981 | 2 |
| gate_random | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.167 | 0.178 | 0.818 | 3 |
| gate_random | 2F_L_N,2F_R_N,3F_R_N | 0.100 | 0.067 | 0.492 | 1 |
| gate_random | 2F_L_N,3F_L_A,3F_L_N | 0.200 | 0.333 | 0.975 | 1 |
| gate_random | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.111 | 0.491 | 3 |
| gate_random | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_random | 2F_L_N,3F_L_A,3F_R_A | 0.167 | 0.178 | 0.818 | 3 |
| gate_random | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.167 | 0.222 | 0.817 | 3 |
| gate_random | 2F_L_N,3F_L_A,3F_R_N | 0.200 | 0.200 | 0.977 | 1 |
| gate_random | 2F_L_N,3F_L_N | 0.250 | 0.267 | 1.226 | 2 |
| gate_random | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.100 | 0.200 | 0.490 | 1 |
| gate_random | 2F_L_N,3F_L_N,3F_R_N | 0.200 | 0.233 | 0.983 | 2 |
| gate_random | 2F_L_N,3F_R_A | 0.250 | 0.267 | 1.231 | 2 |
| gate_random | 2F_L_N,3F_R_N | 0.200 | 0.210 | 0.980 | 7 |
| gate_random | 2F_R_N | 0.179 | 0.195 | 0.877 | 14 |
| gate_random | 2F_R_N,3F_L_A | 0.100 | 0.067 | 0.489 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N | 0.200 | 0.200 | 0.980 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.500 | 0.400 | 2.445 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.333 | 0.222 | 1.636 | 3 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.000 | 0.067 | 0.000 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_R_A | 0.100 | 0.133 | 0.491 | 2 |
| gate_random | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.400 | 0.267 | 1.967 | 1 |
| gate_random | 2F_R_N,3F_L_N | 0.222 | 0.200 | 1.093 | 9 |
| gate_random | 2F_R_N,3F_L_N,3F_R_N | 0.150 | 0.133 | 0.737 | 2 |
| gate_random | 2F_R_N,3F_R_A | 0.200 | 0.200 | 0.982 | 1 |
| gate_random | 2F_R_N,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.981 | 1 |
| gate_random | 2F_R_N,3F_R_N | 0.200 | 0.200 | 0.981 | 2 |
| gate_random | 3F_L_A | 0.175 | 0.192 | 0.858 | 8 |
| gate_random | 3F_L_A,3F_L_N | 0.367 | 0.289 | 1.802 | 3 |
| gate_random | 3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.133 | 0.491 | 1 |
| gate_random | 3F_L_A,3F_R_A | 0.150 | 0.187 | 0.736 | 10 |
| gate_random | 3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.200 | 1.467 | 1 |
| gate_random | 3F_L_A,3F_R_N | 0.233 | 0.200 | 1.144 | 3 |
| gate_random | 3F_L_N | 0.167 | 0.189 | 0.819 | 18 |
| gate_random | 3F_L_N,3F_R_A | 0.150 | 0.167 | 0.737 | 4 |
| gate_random | 3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.233 | 1.479 | 2 |
| gate_random | 3F_L_N,3F_R_N | 0.173 | 0.182 | 0.849 | 11 |
| gate_random | 3F_R_A | 0.122 | 0.133 | 0.600 | 9 |
| gate_random | 3F_R_N | 0.205 | 0.196 | 1.008 | 19 |
| gate_v6a | 2F_L_N | 0.223 | 0.185 | 1.093 | 13 |
| gate_v6a | 2F_L_N,2F_R_N | 0.300 | 0.250 | 1.474 | 4 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.100 | 0.133 | 0.489 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.133 | 0.490 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.982 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.200 | 0.233 | 0.983 | 4 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.344 | 1.474 | 6 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_N | 0.150 | 0.100 | 0.741 | 2 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.968 | 2 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.100 | 0.133 | 0.495 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_R_A | 0.300 | 0.333 | 1.467 | 2 |
| gate_v6a | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.267 | 0.244 | 1.308 | 3 |
| gate_v6a | 2F_L_N,2F_R_N,3F_R_N | 0.100 | 0.133 | 0.492 | 1 |
| gate_v6a | 2F_L_N,3F_L_A,3F_L_N | 0.100 | 0.067 | 0.488 | 1 |
| gate_v6a | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.400 | 0.356 | 1.966 | 3 |
| gate_v6a | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.978 | 1 |
| gate_v6a | 2F_L_N,3F_L_A,3F_R_A | 0.233 | 0.267 | 1.144 | 3 |
| gate_v6a | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.167 | 0.222 | 0.818 | 3 |
| gate_v6a | 2F_L_N,3F_L_A,3F_R_N | 0.300 | 0.200 | 1.465 | 1 |
| gate_v6a | 2F_L_N,3F_L_N | 0.350 | 0.267 | 1.714 | 2 |
| gate_v6a | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.267 | 1.961 | 1 |
| gate_v6a | 2F_L_N,3F_L_N,3F_R_N | 0.150 | 0.167 | 0.739 | 2 |
| gate_v6a | 2F_L_N,3F_R_A | 0.200 | 0.200 | 0.984 | 2 |
| gate_v6a | 2F_L_N,3F_R_N | 0.229 | 0.200 | 1.119 | 7 |
| gate_v6a | 2F_R_N | 0.171 | 0.176 | 0.844 | 14 |
| gate_v6a | 2F_R_N,3F_L_A | 0.300 | 0.200 | 1.467 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N | 0.300 | 0.267 | 1.471 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.489 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.233 | 0.244 | 1.144 | 3 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.300 | 0.267 | 1.471 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_R_A | 0.100 | 0.167 | 0.491 | 2 |
| gate_v6a | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.100 | 0.133 | 0.492 | 1 |
| gate_v6a | 2F_R_N,3F_L_N | 0.200 | 0.185 | 0.982 | 9 |
| gate_v6a | 2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.200 | 0.983 | 2 |
| gate_v6a | 2F_R_N,3F_R_A | 0.500 | 0.400 | 2.455 | 1 |
| gate_v6a | 2F_R_N,3F_R_A,3F_R_N | 0.200 | 0.267 | 0.981 | 1 |
| gate_v6a | 2F_R_N,3F_R_N | 0.150 | 0.267 | 0.735 | 2 |
| gate_v6a | 3F_L_A | 0.225 | 0.217 | 1.102 | 8 |
| gate_v6a | 3F_L_A,3F_L_N | 0.133 | 0.178 | 0.656 | 3 |
| gate_v6a | 3F_L_A,3F_L_N,3F_R_A | 0.200 | 0.200 | 0.982 | 1 |
| gate_v6a | 3F_L_A,3F_R_A | 0.240 | 0.220 | 1.179 | 10 |
| gate_v6a | 3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6a | 3F_L_A,3F_R_N | 0.133 | 0.200 | 0.656 | 3 |
| gate_v6a | 3F_L_N | 0.178 | 0.185 | 0.873 | 18 |
| gate_v6a | 3F_L_N,3F_R_A | 0.225 | 0.183 | 1.106 | 4 |
| gate_v6a | 3F_L_N,3F_R_A,3F_R_N | 0.150 | 0.200 | 0.738 | 2 |
| gate_v6a | 3F_L_N,3F_R_N | 0.191 | 0.182 | 0.935 | 11 |
| gate_v6a | 3F_R_A | 0.256 | 0.267 | 1.255 | 9 |
| gate_v6a | 3F_R_N | 0.216 | 0.189 | 1.060 | 19 |
| gate_v6b_rule | 2F_L_N | 0.200 | 0.179 | 0.980 | 13 |
| gate_v6b_rule | 2F_L_N,2F_R_N | 0.275 | 0.267 | 1.351 | 4 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.100 | 0.133 | 0.489 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.490 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.982 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.200 | 0.250 | 0.983 | 4 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.317 | 0.344 | 1.556 | 6 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_N | 0.150 | 0.133 | 0.741 | 2 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.968 | 2 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.100 | 0.133 | 0.495 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_R_A | 0.300 | 0.367 | 1.467 | 2 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.267 | 0.222 | 1.308 | 3 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_R_N | 0.100 | 0.067 | 0.492 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_L_N | 0.100 | 0.067 | 0.488 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.433 | 0.378 | 2.130 | 3 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.978 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_R_A | 0.233 | 0.267 | 1.144 | 3 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.981 | 3 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_R_N | 0.300 | 0.200 | 1.465 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_N | 0.350 | 0.267 | 1.714 | 2 |
| gate_v6b_rule | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.267 | 1.961 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_N,3F_R_N | 0.150 | 0.133 | 0.739 | 2 |
| gate_v6b_rule | 2F_L_N,3F_R_A | 0.250 | 0.200 | 1.231 | 2 |
| gate_v6b_rule | 2F_L_N,3F_R_N | 0.243 | 0.200 | 1.189 | 7 |
| gate_v6b_rule | 2F_R_N | 0.143 | 0.162 | 0.704 | 14 |
| gate_v6b_rule | 2F_R_N,3F_L_A | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N | 0.300 | 0.267 | 1.471 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.489 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.233 | 0.244 | 1.145 | 3 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.300 | 0.267 | 1.471 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_R_A | 0.100 | 0.167 | 0.491 | 2 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.100 | 0.133 | 0.492 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_N | 0.200 | 0.200 | 0.982 | 9 |
| gate_v6b_rule | 2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.200 | 0.983 | 2 |
| gate_v6b_rule | 2F_R_N,3F_R_A | 0.400 | 0.400 | 1.964 | 1 |
| gate_v6b_rule | 2F_R_N,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.981 | 1 |
| gate_v6b_rule | 2F_R_N,3F_R_N | 0.150 | 0.267 | 0.735 | 2 |
| gate_v6b_rule | 3F_L_A | 0.237 | 0.208 | 1.164 | 8 |
| gate_v6b_rule | 3F_L_A,3F_L_N | 0.133 | 0.178 | 0.656 | 3 |
| gate_v6b_rule | 3F_L_A,3F_L_N,3F_R_A | 0.200 | 0.200 | 0.982 | 1 |
| gate_v6b_rule | 3F_L_A,3F_R_A | 0.240 | 0.207 | 1.180 | 10 |
| gate_v6b_rule | 3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6b_rule | 3F_L_A,3F_R_N | 0.167 | 0.200 | 0.821 | 3 |
| gate_v6b_rule | 3F_L_N | 0.200 | 0.185 | 0.982 | 18 |
| gate_v6b_rule | 3F_L_N,3F_R_A | 0.225 | 0.183 | 1.106 | 4 |
| gate_v6b_rule | 3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.985 | 2 |
| gate_v6b_rule | 3F_L_N,3F_R_N | 0.164 | 0.188 | 0.802 | 11 |
| gate_v6b_rule | 3F_R_A | 0.278 | 0.252 | 1.364 | 9 |
| gate_v6b_rule | 3F_R_N | 0.221 | 0.196 | 1.085 | 19 |
| nogate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.197 | 0.213 | 0.969 | 195 |

## 7. Pass/Fail Judgment

- [x] gate_v6a precision@10 > nogate_v6a precision@10 (all)
- [x] gate_v6a precision@10 > nogate_v6a precision@10 (front)
- [x] gate_v6a precision@10 > nogate_v6a precision@10 (back)
- [x] gate_v6a precision@10 > gate_random precision@10
- [x] gate_v6b_rule precision@10 > gate_v6a precision@10 (all)
- [x] gate_v6b_rule precision@10 > gate_v6a precision@10 (front)
- [ ] gate_v6b_rule precision@10 > gate_v6a precision@10 (back)
- [ ] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 + 0.05 (all)
- [ ] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (front)
- [x] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (back)
- [x] gate_ml_shadow precision@10 > gate_random precision@10

Overall verdict: PASS / FAIL / PARTIAL -> **PARTIAL**
