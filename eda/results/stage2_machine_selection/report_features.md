# Stage 2 Machine Selection Feature Report

- DB: `C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\db\マルハンメガシティ2000-蒲田7.db`
- Source date range: `2025-07-08` to `2026-06-28`
- Evaluation dates: `2026-04-28` to `2026-06-28` (60 days)
- Filters: `games_normalized >= 1500`, `0707` excluded, machine `2026` excluded
- Stage 1: top `5` sections per day
- Stage 2: top `5` machines per selected section

| feature | rho_in_section | p_value | delta_pp | signal_flag |
| --- | --- | --- | --- | --- |
| debut_days | 0.0301 | 0.0840 | 2.7273 | 1 |
| kakuban_group | 0.0056 | 0.7470 | 2.5758 | 0 |
| kakuban_raw | 0.0048 | 0.7828 | 1.0606 | 0 |
| momentum | -0.0116 | 0.5072 | -2.1212 | 0 |
| trail_14d_hit | -0.0136 | 0.4340 | -3.6364 | 0 |
| trail_7d_hit | -0.0138 | 0.4285 | -1.0606 | 0 |
| trail_diff_7d | -0.0152 | 0.3816 | -1.9697 | 0 |
| kakuban_edge | -0.0384 | 0.0275 | 0.0848 | 0 |
| debut_phase |  |  | 0.0000 | 0 |
