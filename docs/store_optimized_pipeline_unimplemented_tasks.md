# Store Optimized Pipeline Unimplemented Tasks

更新日: 2026-05-13

このメモは、`より高度な feature selection` より上位で列挙されていた未実装タスクの退避先です。
今回の実装では以下を対象外として残しています。

## Remaining Tasks

- `corner_number` grouping の実装
- `machine_number_position` の追加特徴
  - `corner_distance`
  - `corner_flag`
  - `block_id`
  - `zone_id`
  - `adjacent_high_signal_count`
  - `left_right_edge_type`
  - `same_last_digit_position_bias`
  - `position_weekday_bias`
  - `machine_number_non_consecutive_rate`
  - `prior_worst_streak_length`
  - `local_cluster_rank_rate`
- `machine_number_position` 特化 anti-pattern の拡張
- 位置ベース近傍特徴の本格導入
- 配置の空間構造の導入
- `machine_number_position` 用の `win_rate` 相当設計
- `last_digit × weekday` 以外の複合特徴拡張
