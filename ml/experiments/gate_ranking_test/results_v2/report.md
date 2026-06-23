# Gate Ranking Connection Test Report

Output: `ml/experiments/gate_ranking_test/results_v2`
Test days: 195
CatBoost available: yes
ML fallback days: 0

## 1. Series Comparison (Active Days Only)

| series_id | event_type | precision_at_10 | precision_at_15 | lift_at_10 | lift_at_15 | avg_payout_at_10 | avg_payout_at_15 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | all | 0.204 | 0.212 | 0.999 | 1.040 | 100.409 | 100.796 | 195 | 0 |
| gate_v6a | all | 0.213 | 0.208 | 1.047 | 1.019 | 101.518 | 101.523 | 195 | 0 |
| gate_random | all | 0.203 | 0.203 | 0.994 | 0.995 | 101.307 | 101.559 | 195 | 0 |
| gate_v6b_rule | all | 0.215 | 0.209 | 1.055 | 1.027 | 101.409 | 101.392 | 195 | 0 |
| gate_ml_shadow | all | 0.210 | 0.218 | 1.032 | 1.069 | 100.748 | 101.357 | 195 | 0 |

## 2. Event vs Non-Event

| series_id | event_type | precision_at_10 | precision_at_15 | lift_at_10 | lift_at_15 | avg_payout_at_10 | avg_payout_at_15 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | event | 0.220 | 0.222 | 1.077 | 1.088 | 100.485 | 101.469 | 61 | 0 |
| nogate_v6a | non_event | 0.196 | 0.207 | 0.964 | 1.019 | 100.375 | 100.490 | 134 | 0 |
| gate_v6a | event | 0.220 | 0.212 | 1.078 | 1.040 | 102.078 | 101.780 | 61 | 0 |
| gate_v6a | non_event | 0.210 | 0.205 | 1.033 | 1.009 | 101.263 | 101.406 | 134 | 0 |
| gate_random | event | 0.213 | 0.203 | 1.046 | 0.998 | 102.104 | 101.939 | 61 | 0 |
| gate_random | non_event | 0.198 | 0.202 | 0.971 | 0.994 | 100.945 | 101.386 | 134 | 0 |
| gate_v6b_rule | event | 0.223 | 0.215 | 1.094 | 1.056 | 101.899 | 101.615 | 61 | 0 |
| gate_v6b_rule | non_event | 0.211 | 0.206 | 1.037 | 1.014 | 101.186 | 101.290 | 134 | 0 |
| gate_ml_shadow | event | 0.200 | 0.205 | 0.981 | 1.008 | 100.326 | 101.054 | 61 | 0 |
| gate_ml_shadow | non_event | 0.215 | 0.223 | 1.055 | 1.097 | 100.940 | 101.495 | 134 | 0 |

## 3. Front/Back Stability

| series_id | split_period | precision_at_10 | precision_at_15 | lift_at_10 | avg_payout_at_10 | n_test_days | n_days_active_lt_10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nogate_v6a | front | 0.194 | 0.205 | 0.952 | 100.977 | 97 | 0 |
| nogate_v6a | back | 0.213 | 0.218 | 1.046 | 99.848 | 98 | 0 |
| gate_v6a | front | 0.206 | 0.206 | 1.013 | 101.663 | 97 | 0 |
| gate_v6a | back | 0.220 | 0.209 | 1.081 | 101.374 | 98 | 0 |
| gate_random | front | 0.195 | 0.200 | 0.957 | 101.794 | 97 | 0 |
| gate_random | back | 0.210 | 0.205 | 1.031 | 100.825 | 98 | 0 |
| gate_v6b_rule | front | 0.207 | 0.202 | 1.018 | 101.559 | 97 | 0 |
| gate_v6b_rule | back | 0.222 | 0.216 | 1.091 | 101.260 | 98 | 0 |
| gate_ml_shadow | front | 0.206 | 0.215 | 1.013 | 101.254 | 97 | 0 |
| gate_ml_shadow | back | 0.214 | 0.220 | 1.051 | 100.247 | 98 | 0 |

## 4. Gate Coverage

| series_id | n_active_machines | n_days_active_lt_10 | n_test_days |
| --- | --- | --- | --- |
| gate_ml_shadow | 189.377 | 0 | 257 |
| gate_random | 189.377 | 0 | 257 |
| gate_v6a | 189.377 | 0 | 257 |
| gate_v6b_rule | 189.377 | 0 | 257 |
| nogate_v6a | 701.210 | 0 | 257 |

## 5. ML Shadow vs Rule-Based

| metric | gate_v6b_rule | gate_ml_shadow | delta |
|--------|---------------|----------------|-------|
| p@10 (all) | 0.215 | 0.210 | -0.005 |
| p@10 (front) | 0.207 | 0.206 | -0.001 |
| p@10 (back) | 0.222 | 0.214 | -0.008 |
| AUC (all) | N/A | 0.545 | N/A |

## 6. Segment-Level Detail

| series_id | active_segments | precision_at_10 | precision_at_15 | lift_at_10 | n_test_days |
| --- | --- | --- | --- | --- | --- |
| gate_ml_shadow | 2F_L_N | 0.200 | 0.200 | 0.981 | 13 |
| gate_ml_shadow | 2F_L_N,2F_R_N | 0.200 | 0.167 | 0.982 | 4 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.200 | 0.200 | 0.978 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.490 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.964 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.150 | 0.183 | 0.735 | 4 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.289 | 1.473 | 6 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_N | 0.300 | 0.367 | 1.471 | 2 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.350 | 0.267 | 1.722 | 2 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.333 | 0.983 | 1 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_R_A | 0.250 | 0.267 | 1.218 | 2 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.133 | 0.200 | 0.654 | 3 |
| gate_ml_shadow | 2F_L_N,2F_R_N,3F_R_N | 0.200 | 0.200 | 0.977 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_L_N | 0.200 | 0.133 | 0.982 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.233 | 0.200 | 1.143 | 3 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.956 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_R_A | 0.200 | 0.244 | 0.985 | 3 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.233 | 0.222 | 1.144 | 3 |
| gate_ml_shadow | 2F_L_N,3F_L_A,3F_R_N | 0.100 | 0.200 | 0.492 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_N | 0.300 | 0.267 | 1.481 | 2 |
| gate_ml_shadow | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.200 | 0.981 | 1 |
| gate_ml_shadow | 2F_L_N,3F_L_N,3F_R_N | 0.200 | 0.200 | 0.979 | 2 |
| gate_ml_shadow | 2F_L_N,3F_R_A | 0.100 | 0.133 | 0.490 | 2 |
| gate_ml_shadow | 2F_L_N,3F_R_N | 0.186 | 0.200 | 0.913 | 7 |
| gate_ml_shadow | 2F_R_N | 0.107 | 0.148 | 0.528 | 14 |
| gate_ml_shadow | 2F_R_N,3F_L_A | 0.200 | 0.200 | 0.978 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N | 0.100 | 0.133 | 0.490 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.500 | 0.467 | 2.445 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.244 | 0.985 | 3 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.200 | 0.333 | 0.974 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_R_A | 0.400 | 0.333 | 1.961 | 2 |
| gate_ml_shadow | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.333 | 1.475 | 1 |
| gate_ml_shadow | 2F_R_N,3F_L_N | 0.189 | 0.207 | 0.926 | 9 |
| gate_ml_shadow | 2F_R_N,3F_L_N,3F_R_N | 0.400 | 0.267 | 1.970 | 2 |
| gate_ml_shadow | 2F_R_N,3F_R_A | 0.600 | 0.467 | 2.946 | 1 |
| gate_ml_shadow | 2F_R_N,3F_R_A,3F_R_N | 0.000 | 0.067 | 0.000 | 1 |
| gate_ml_shadow | 2F_R_N,3F_R_N | 0.200 | 0.267 | 0.984 | 2 |
| gate_ml_shadow | 3F_L_A | 0.175 | 0.192 | 0.857 | 8 |
| gate_ml_shadow | 3F_L_A,3F_L_N | 0.233 | 0.289 | 1.145 | 3 |
| gate_ml_shadow | 3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.200 | 0.491 | 1 |
| gate_ml_shadow | 3F_L_A,3F_R_A | 0.150 | 0.153 | 0.737 | 10 |
| gate_ml_shadow | 3F_L_A,3F_R_A,3F_R_N | 0.100 | 0.067 | 0.489 | 1 |
| gate_ml_shadow | 3F_L_A,3F_R_N | 0.200 | 0.267 | 0.985 | 3 |
| gate_ml_shadow | 3F_L_N | 0.233 | 0.233 | 1.145 | 18 |
| gate_ml_shadow | 3F_L_N,3F_R_A | 0.225 | 0.183 | 1.104 | 4 |
| gate_ml_shadow | 3F_L_N,3F_R_A,3F_R_N | 0.100 | 0.100 | 0.490 | 2 |
| gate_ml_shadow | 3F_L_N,3F_R_N | 0.227 | 0.230 | 1.117 | 11 |
| gate_ml_shadow | 3F_R_A | 0.200 | 0.193 | 0.980 | 9 |
| gate_ml_shadow | 3F_R_N | 0.253 | 0.260 | 1.242 | 19 |
| gate_random | 2F_L_N | 0.146 | 0.169 | 0.717 | 13 |
| gate_random | 2F_L_N,2F_R_N | 0.200 | 0.217 | 0.982 | 4 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.100 | 0.067 | 0.489 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.400 | 0.333 | 1.959 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.467 | 1.964 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.225 | 0.167 | 1.105 | 4 |
| gate_random | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.200 | 0.167 | 0.982 | 6 |
| gate_random | 2F_L_N,2F_R_N,3F_L_N | 0.350 | 0.300 | 1.716 | 2 |
| gate_random | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.250 | 0.300 | 1.230 | 2 |
| gate_random | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.300 | 0.267 | 1.475 | 1 |
| gate_random | 2F_L_N,2F_R_N,3F_R_A | 0.150 | 0.100 | 0.733 | 2 |
| gate_random | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.267 | 0.244 | 1.308 | 3 |
| gate_random | 2F_L_N,2F_R_N,3F_R_N | 0.000 | 0.000 | 0.000 | 1 |
| gate_random | 2F_L_N,3F_L_A,3F_L_N | 0.100 | 0.133 | 0.491 | 1 |
| gate_random | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.300 | 0.222 | 1.470 | 3 |
| gate_random | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.978 | 1 |
| gate_random | 2F_L_N,3F_L_A,3F_R_A | 0.167 | 0.178 | 0.820 | 3 |
| gate_random | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.300 | 0.289 | 1.469 | 3 |
| gate_random | 2F_L_N,3F_L_A,3F_R_N | 0.400 | 0.267 | 1.967 | 1 |
| gate_random | 2F_L_N,3F_L_N | 0.100 | 0.133 | 0.493 | 2 |
| gate_random | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.981 | 1 |
| gate_random | 2F_L_N,3F_L_N,3F_R_N | 0.200 | 0.167 | 0.980 | 2 |
| gate_random | 2F_L_N,3F_R_A | 0.300 | 0.267 | 1.471 | 2 |
| gate_random | 2F_L_N,3F_R_N | 0.171 | 0.200 | 0.844 | 7 |
| gate_random | 2F_R_N | 0.221 | 0.252 | 1.090 | 14 |
| gate_random | 2F_R_N,3F_L_A | 0.200 | 0.133 | 0.978 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N | 0.200 | 0.133 | 0.980 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.200 | 0.133 | 0.978 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.233 | 0.289 | 1.148 | 3 |
| gate_random | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.400 | 0.267 | 1.948 | 1 |
| gate_random | 2F_R_N,3F_L_A,3F_R_A | 0.400 | 0.367 | 1.954 | 2 |
| gate_random | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.200 | 0.267 | 0.983 | 1 |
| gate_random | 2F_R_N,3F_L_N | 0.233 | 0.200 | 1.146 | 9 |
| gate_random | 2F_R_N,3F_L_N,3F_R_N | 0.250 | 0.267 | 1.230 | 2 |
| gate_random | 2F_R_N,3F_R_A | 0.300 | 0.333 | 1.473 | 1 |
| gate_random | 2F_R_N,3F_R_A,3F_R_N | 0.300 | 0.333 | 1.471 | 1 |
| gate_random | 2F_R_N,3F_R_N | 0.250 | 0.233 | 1.226 | 2 |
| gate_random | 3F_L_A | 0.200 | 0.192 | 0.979 | 8 |
| gate_random | 3F_L_A,3F_L_N | 0.267 | 0.244 | 1.310 | 3 |
| gate_random | 3F_L_A,3F_L_N,3F_R_A | 0.200 | 0.200 | 0.982 | 1 |
| gate_random | 3F_L_A,3F_R_A | 0.170 | 0.193 | 0.832 | 10 |
| gate_random | 3F_L_A,3F_R_A,3F_R_N | 0.100 | 0.133 | 0.489 | 1 |
| gate_random | 3F_L_A,3F_R_N | 0.167 | 0.222 | 0.824 | 3 |
| gate_random | 3F_L_N | 0.206 | 0.193 | 1.011 | 18 |
| gate_random | 3F_L_N,3F_R_A | 0.200 | 0.217 | 0.980 | 4 |
| gate_random | 3F_L_N,3F_R_A,3F_R_N | 0.150 | 0.167 | 0.740 | 2 |
| gate_random | 3F_L_N,3F_R_N | 0.191 | 0.206 | 0.936 | 11 |
| gate_random | 3F_R_A | 0.122 | 0.133 | 0.599 | 9 |
| gate_random | 3F_R_N | 0.168 | 0.179 | 0.827 | 19 |
| gate_v6a | 2F_L_N | 0.223 | 0.205 | 1.096 | 13 |
| gate_v6a | 2F_L_N,2F_R_N | 0.300 | 0.300 | 1.472 | 4 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.133 | 0.490 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.473 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.200 | 0.233 | 0.981 | 4 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.317 | 0.322 | 1.557 | 6 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_N | 0.050 | 0.133 | 0.245 | 2 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.250 | 0.233 | 1.230 | 2 |
| gate_v6a | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.133 | 0.983 | 1 |
| gate_v6a | 2F_L_N,2F_R_N,3F_R_A | 0.200 | 0.267 | 0.977 | 2 |
| gate_v6a | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.167 | 0.178 | 0.817 | 3 |
| gate_v6a | 2F_L_N,2F_R_N,3F_R_N | 0.200 | 0.267 | 0.977 | 1 |
| gate_v6a | 2F_L_N,3F_L_A,3F_L_N | 0.200 | 0.200 | 0.982 | 1 |
| gate_v6a | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.367 | 0.311 | 1.796 | 3 |
| gate_v6a | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6a | 2F_L_N,3F_L_A,3F_R_A | 0.167 | 0.178 | 0.819 | 3 |
| gate_v6a | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.133 | 0.178 | 0.653 | 3 |
| gate_v6a | 2F_L_N,3F_L_A,3F_R_N | 0.400 | 0.267 | 1.967 | 1 |
| gate_v6a | 2F_L_N,3F_L_N | 0.300 | 0.267 | 1.480 | 2 |
| gate_v6a | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.267 | 1.961 | 1 |
| gate_v6a | 2F_L_N,3F_L_N,3F_R_N | 0.100 | 0.133 | 0.491 | 2 |
| gate_v6a | 2F_L_N,3F_R_A | 0.050 | 0.100 | 0.245 | 2 |
| gate_v6a | 2F_L_N,3F_R_N | 0.214 | 0.219 | 1.053 | 7 |
| gate_v6a | 2F_R_N | 0.186 | 0.167 | 0.914 | 14 |
| gate_v6a | 2F_R_N,3F_L_A | 0.500 | 0.333 | 2.445 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N | 0.200 | 0.133 | 0.980 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.133 | 0.489 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.333 | 0.267 | 1.636 | 3 |
| gate_v6a | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.400 | 0.333 | 1.948 | 1 |
| gate_v6a | 2F_R_N,3F_L_A,3F_R_A | 0.050 | 0.100 | 0.244 | 2 |
| gate_v6a | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.983 | 1 |
| gate_v6a | 2F_R_N,3F_L_N | 0.178 | 0.163 | 0.872 | 9 |
| gate_v6a | 2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.267 | 0.988 | 2 |
| gate_v6a | 2F_R_N,3F_R_A | 0.400 | 0.400 | 1.964 | 1 |
| gate_v6a | 2F_R_N,3F_R_A,3F_R_N | 0.100 | 0.200 | 0.490 | 1 |
| gate_v6a | 2F_R_N,3F_R_N | 0.200 | 0.267 | 0.981 | 2 |
| gate_v6a | 3F_L_A | 0.225 | 0.217 | 1.102 | 8 |
| gate_v6a | 3F_L_A,3F_L_N | 0.133 | 0.200 | 0.656 | 3 |
| gate_v6a | 3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.133 | 0.491 | 1 |
| gate_v6a | 3F_L_A,3F_R_A | 0.240 | 0.213 | 1.176 | 10 |
| gate_v6a | 3F_L_A,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.956 | 1 |
| gate_v6a | 3F_L_A,3F_R_N | 0.167 | 0.178 | 0.823 | 3 |
| gate_v6a | 3F_L_N | 0.178 | 0.170 | 0.874 | 18 |
| gate_v6a | 3F_L_N,3F_R_A | 0.200 | 0.183 | 0.980 | 4 |
| gate_v6a | 3F_L_N,3F_R_A,3F_R_N | 0.150 | 0.167 | 0.738 | 2 |
| gate_v6a | 3F_L_N,3F_R_N | 0.118 | 0.145 | 0.580 | 11 |
| gate_v6a | 3F_R_A | 0.256 | 0.267 | 1.252 | 9 |
| gate_v6a | 3F_R_N | 0.263 | 0.221 | 1.292 | 19 |
| gate_v6b_rule | 2F_L_N | 0.231 | 0.210 | 1.134 | 13 |
| gate_v6b_rule | 2F_L_N,2F_R_N | 0.300 | 0.300 | 1.472 | 4 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_L_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.490 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.473 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_R_A | 0.175 | 0.267 | 0.861 | 4 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.317 | 0.322 | 1.557 | 6 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_N | 0.100 | 0.167 | 0.490 | 2 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_N,3F_R_A,3F_R_N | 0.250 | 0.233 | 1.230 | 2 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_L_N,3F_R_N | 0.200 | 0.133 | 0.983 | 1 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_R_A | 0.200 | 0.267 | 0.977 | 2 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_R_A,3F_R_N | 0.167 | 0.178 | 0.817 | 3 |
| gate_v6b_rule | 2F_L_N,2F_R_N,3F_R_N | 0.200 | 0.200 | 0.977 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_L_N | 0.200 | 0.200 | 0.982 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_L_N,3F_R_A | 0.400 | 0.311 | 1.960 | 3 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.300 | 0.267 | 1.467 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_R_A | 0.167 | 0.200 | 0.819 | 3 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_R_A,3F_R_N | 0.133 | 0.133 | 0.653 | 3 |
| gate_v6b_rule | 2F_L_N,3F_L_A,3F_R_N | 0.400 | 0.267 | 1.967 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_N | 0.300 | 0.300 | 1.480 | 2 |
| gate_v6b_rule | 2F_L_N,3F_L_N,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.961 | 1 |
| gate_v6b_rule | 2F_L_N,3F_L_N,3F_R_N | 0.100 | 0.100 | 0.491 | 2 |
| gate_v6b_rule | 2F_L_N,3F_R_A | 0.050 | 0.100 | 0.245 | 2 |
| gate_v6b_rule | 2F_L_N,3F_R_N | 0.200 | 0.229 | 0.982 | 7 |
| gate_v6b_rule | 2F_R_N | 0.157 | 0.181 | 0.773 | 14 |
| gate_v6b_rule | 2F_R_N,3F_L_A | 0.500 | 0.333 | 2.445 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N | 0.200 | 0.200 | 0.980 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.067 | 0.489 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.333 | 0.289 | 1.636 | 3 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_L_N,3F_R_N | 0.400 | 0.333 | 1.948 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_R_A | 0.000 | 0.133 | 0.000 | 2 |
| gate_v6b_rule | 2F_R_N,3F_L_A,3F_R_A,3F_R_N | 0.200 | 0.133 | 0.983 | 1 |
| gate_v6b_rule | 2F_R_N,3F_L_N | 0.156 | 0.170 | 0.763 | 9 |
| gate_v6b_rule | 2F_R_N,3F_L_N,3F_R_N | 0.250 | 0.267 | 1.235 | 2 |
| gate_v6b_rule | 2F_R_N,3F_R_A | 0.400 | 0.400 | 1.964 | 1 |
| gate_v6b_rule | 2F_R_N,3F_R_A,3F_R_N | 0.100 | 0.200 | 0.490 | 1 |
| gate_v6b_rule | 2F_R_N,3F_R_N | 0.200 | 0.267 | 0.981 | 2 |
| gate_v6b_rule | 3F_L_A | 0.237 | 0.208 | 1.163 | 8 |
| gate_v6b_rule | 3F_L_A,3F_L_N | 0.167 | 0.200 | 0.820 | 3 |
| gate_v6b_rule | 3F_L_A,3F_L_N,3F_R_A | 0.100 | 0.200 | 0.491 | 1 |
| gate_v6b_rule | 3F_L_A,3F_R_A | 0.240 | 0.200 | 1.177 | 10 |
| gate_v6b_rule | 3F_L_A,3F_R_A,3F_R_N | 0.400 | 0.333 | 1.956 | 1 |
| gate_v6b_rule | 3F_L_A,3F_R_N | 0.200 | 0.178 | 0.987 | 3 |
| gate_v6b_rule | 3F_L_N | 0.206 | 0.174 | 1.010 | 18 |
| gate_v6b_rule | 3F_L_N,3F_R_A | 0.200 | 0.183 | 0.980 | 4 |
| gate_v6b_rule | 3F_L_N,3F_R_A,3F_R_N | 0.150 | 0.167 | 0.738 | 2 |
| gate_v6b_rule | 3F_L_N,3F_R_N | 0.118 | 0.145 | 0.580 | 11 |
| gate_v6b_rule | 3F_R_A | 0.278 | 0.252 | 1.362 | 9 |
| gate_v6b_rule | 3F_R_N | 0.253 | 0.218 | 1.241 | 19 |
| nogate_v6a | 2F_L_N,2F_R_N,3F_L_A,3F_L_N,3F_R_A,3F_R_N | 0.204 | 0.212 | 0.999 | 195 |

## 7. Pass/Fail Judgment

- [x] gate_v6a precision@10 > nogate_v6a precision@10 (all)
- [x] gate_v6a precision@10 > nogate_v6a precision@10 (front)
- [x] gate_v6a precision@10 > nogate_v6a precision@10 (back)
- [x] gate_v6a precision@10 > gate_random precision@10
- [x] gate_v6b_rule precision@10 > gate_v6a precision@10 (all)
- [x] gate_v6b_rule precision@10 > gate_v6a precision@10 (front)
- [x] gate_v6b_rule precision@10 > gate_v6a precision@10 (back)
- [ ] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 + 0.05 (all)
- [ ] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (front)
- [ ] gate_ml_shadow precision@10 > gate_v6b_rule precision@10 (back)
- [x] gate_ml_shadow precision@10 > gate_random precision@10

Overall verdict: PASS / FAIL / PARTIAL -> **PARTIAL**
