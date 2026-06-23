# Kamata7 section-relative digit report

- Data source: `load_hall_df("蒲田7")`
- Filter: `date != 20260707` and `games >= 400`
- Scope: segment `N` only
- Digit types: `raw_digit`, `pos_from_left`, `pos_from_right`

## Section 1: 12パターンの比較表
| floor | side | digit_type | H_stat | p_value | effect_range | n |
| --- | --- | --- | --- | --- | --- | --- |
| 2F | L | raw_digit | 17.760 | 0.038 | 247.700 | 23991 |
| 2F | L | pos_from_left | 6.855 | 0.652 | 199.400 | 23991 |
| 2F | L | pos_from_right | 9.564 | 0.387 | 196.900 | 23991 |
| 2F | R | raw_digit | 9.408 | 0.400 | 134.400 | 93024 |
| 2F | R | pos_from_left | 10.779 | 0.291 | 91.800 | 93024 |
| 2F | R | pos_from_right | 14.250 | 0.114 | 147.400 | 93024 |
| 3F | L | raw_digit | 38.518 | 0.000 | 443.800 | 12519 |
| 3F | L | pos_from_left | 27.982 | 0.001 | 428.800 | 12519 |
| 3F | L | pos_from_right | 17.378 | 0.043 | 335.400 | 12519 |
| 3F | R | raw_digit | 20.544 | 0.015 | 212.200 | 42625 |
| 3F | R | pos_from_left | 15.573 | 0.076 | 189.300 | 42625 |
| 3F | R | pos_from_right | 12.720 | 0.176 | 141.600 | 42625 |

## Section 2: R側の信号回復度
| digit_type | H_stat | p_value | effect_range | n |
| --- | --- | --- | --- | --- |
| raw_digit | 19.431 | 0.022 | 139.600 | 135649 |
| pos_from_left | 15.292 | 0.083 | 78.000 | 135649 |
| pos_from_right | 12.538 | 0.185 | 102.000 | 135649 |
- R側の最良digit_type: `raw_digit`

## Section 3: L側の一貫性確認
| comparison | spearman_rho |
| --- | --- |
| raw vs pos_from_left | 0.345 |
| raw vs pos_from_right | 0.055 |

## Section 4: R側の修正digitランキング
- selected digit_type: `pos_from_left`
| digit | n | avg_diff |
| --- | --- | --- |
| 0 | 12484 | 141.9 |
| 1 | 14552 | 198.7 |
| 2 | 14175 | 219.9 |
| 3 | 14229 | 161.8 |
| 4 | 13858 | 171.1 |
| 5 | 13583 | 181.5 |
| 6 | 13305 | 204.1 |
| 7 | 13282 | 206.2 |
| 8 | 12959 | 203.1 |
| 9 | 13222 | 148.9 |

## Section 5: 結論
- R側の最良digit_typeは `raw_digit` (p=0.022)
- L側の最良digit_typeは `pos_from_right` (p=0.009)
- L側 Spearman(raw, left) = 0.345
- R側 Spearman(raw, left) = 0.224
- R側 Spearman(raw, right) = -0.188
- R側の修正digitによる回復は弱いか、定義依存
- L側は raw_digit が依然として主信号である可能性が高い
