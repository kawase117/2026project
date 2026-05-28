# Next 10h Plan Results (threshold=30 fixed)

## Success Criteria
- combined_hit@1 >= 0.40: FAIL (actual=0.3888888888888889)
- 2F_N lift@3 >= 1.0: PASS (actual=1.0767799770451727)

## Phase B
- missing rate raw join: 0.15172054223149115
- missing rate normalized join: 0.15172054223149115
- missing rate after fix: 0.0

## Phase C
- 2F_A: hit@1=0.3888888888888889, lift@1=0.9765819631290481, hit@3=0.8666666666666667, lift@3=1.0204653770675638
- 2F_N: hit@1=0.12222222222222222, lift@1=1.0929375419898317, hit@3=0.3333333333333333, lift@3=1.0767799770451727
- 3F_A: hit@1=0.28888888888888886, lift@1=1.4398734177215193, hit@3=0.6222222222222222, lift@3=1.2016033954256071
- 3F_N: hit@1=0.26666666666666666, lift@1=1.260433273937916, hit@3=0.5333333333333333, lift@3=0.9876189632789492
- weakest_segment_by_lift_at_1: 2F_A

## Phase D
- is_top3_current: {'n_machines_2fn': 34, 'base_rate': 0.11061040557148709, 'lift_at_3': 1.0767799770451727, 'lift_at_5': 1.021392223753768, 'combined_hit_at_1': 0.3888888888888889}
- is_top5_2fn: {'n_machines_2fn': 34, 'base_rate': 0.1843506759524785, 'lift_at_5': 1.021392223753768, 'combined_hit_at_1': 0.3888888888888889}

## Phase E
- ML: {'hit_at_1': 0.12222222222222222, 'lift_at_3': 1.0767799770451727}
- Rule: {'hit_at_1': 0.13333333333333333, 'hit_at_3': 0.3, 'random_baseline_at_3': 0.3095649440362406, 'lift_at_3': 0.9691019793406555}

## Phase F
- baseline: {'combined_hit_at_1': 0.3888888888888889, 'combined_auc': 0.654964321938541, 'weak_segment_lift_at_1': 0.9765819631290481, 'weak_segment_lift_at_3': 1.0204653770675638}
- games_vs_segment_mean_7d_only: {'combined_hit_at_1': 0.34444444444444444, 'combined_auc': 0.6576909895560944, 'weak_segment_lift_at_1': 0.8649725959142998, 'weak_segment_lift_at_3': 1.0335482665171478}
- delta_combined_hit_at_1: -0.04444444444444445