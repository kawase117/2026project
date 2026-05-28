# 10h Plan Results

## Success Criteria Check
- 2F_N lift@3 >= 1.0: PASS (best=1.1410)
- combined hit@1 >= 0.500: FAIL (best=0.3889)
- Layer0 JOIN?? <= 5%: PASS (after=0.0000)

## Phase A: Active Filter + 2F_N Concentration
| threshold | 2F_N machines | 2F_N lift@3 | combined hit@1 | AUC |
|---|---:|---:|---:|---:|
| 0 | 63 | 0.9745 | 0.3889 | 0.6555 |
| 60 | 30 | 1.1146 | 0.2889 | 0.6086 |
| 90 | 29 | 1.1410 | 0.2667 | 0.6120 |
| 120 | 27 | 1.0254 | 0.2444 | 0.6060 |
- recommended_threshold: 60
- holdout HHI: 0.084444 (random baseline 0.027778)

## Phase B: Layer0 JOIN Fix
- missing_layer0_proba_rate: 0.1501 -> 0.0000
- lambda sweep (hit@1 / hit@3):
  - lambda=0.1: hit@1=0.2889, hit@3=0.6556, missing=0.0000
  - lambda=0.2: hit@1=0.2889, hit@3=0.6556, missing=0.0000
  - lambda=0.3: hit@1=0.2889, hit@3=0.6444, missing=0.0000
  - lambda=0.4: hit@1=0.2778, hit@3=0.6444, missing=0.0000
  - lambda=0.5: hit@1=0.2778, hit@3=0.6444, missing=0.0000

## Phase C: 2F_N Target Redesign
| setting | 2F_N machines | base_rate | lift@3 | lift@5 |
|---|---:|---:|---:|---:|
| is_top3_current | 30 | 0.1192 | 1.1146 | 1.0865 |
| is_top5_2fn | 30 | 0.1987 | - | 1.0865 |
| hist120_is_top3 | 27 | 0.1351 | 1.0254 | 0.9925 |
| hist120_is_top5_2fn | 27 | 0.2251 | - | 0.9925 |

## Phase D: Games Features Ablation
| mode | combined hit@1 | combined AUC | 2F_N lift@3 | delta hit@1 vs none |
|---|---:|---:|---:|---:|
| none | 0.2889 | 0.6086 | 1.1146 | - |
| vs_seg | 0.2222 | 0.6086 | 1.1146 | -0.0667 |
| vs_seg_and_trend | 0.2333 | 0.6062 | 0.9457 | -0.0556 |

## Phase E: Rule vs ML (2F_N)
| metric | ML | Rule | Random |
|---|---:|---:|---:|
| hit@1 | 0.1222 | 0.1111 | 0.0333 |
| lift@3 | 1.1146 | 1.0132 | 1.0000 |

## Recommended Next Setting
- active filter threshold: 60 days
- target policy: default (2F_N top3??)
- games feature mode: none (??????????)
- combined lambda: 0.1 or 0.2 (????)