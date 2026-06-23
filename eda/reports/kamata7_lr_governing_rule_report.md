# Kamata7 L/R governing rule report

- Data source: `load_hall_df("蒲田7")`
- Filter: `date != 20260707` and `games >= 400`
- Scope: segment `N` only
- Axis definitions: `digit` = machine tail digit, `kakuban` = section corner rank

## Section 1: L側 末尾効果 vs 角番効果の比較表
| floor | digit_H | digit_p | digit_range | digit_n | kakuban_H | kakuban_p | kakuban_range | kakuban_n | winner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2F | 19.019 | 0.025 | 238.000 | 62805 | 32.377 | 0.000 | 224.000 | 62805 | kakuban |
| 3F | 20.260 | 0.016 | 257.300 | 39108 | 26.918 | 0.000 | 258.300 | 39108 | kakuban |

## Section 2: R側 末尾効果 vs 角番効果の比較表
| floor | digit_H | digit_p | digit_range | digit_n | kakuban_H | kakuban_p | kakuban_range | kakuban_n | winner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2F | 10.969 | 0.278 | 126.600 | 55571 | 21.532 | 0.000 | 201.200 | 55571 | kakuban |
| 3F | 7.527 | 0.582 | 298.500 | 18940 | 26.630 | 0.000 | 457.400 | 18940 | kakuban |

## Section 3: 2F/3F × L/R × {末尾, 角番} の8パターンまとめ
| floor | side | axis | H_stat | p_value | effect_range | n |
| --- | --- | --- | --- | --- | --- | --- |
| 2F | L | digit | 19.019 | 0.025 | 238.000 | 62805 |
| 2F | L | kakuban | 32.377 | 0.000 | 224.000 | 62805 |
| 2F | R | digit | 10.969 | 0.278 | 126.600 | 55571 |
| 2F | R | kakuban | 21.532 | 0.000 | 201.200 | 55571 |
| 3F | L | digit | 20.260 | 0.016 | 257.300 | 39108 |
| 3F | L | kakuban | 26.918 | 0.000 | 258.300 | 39108 |
| 3F | R | digit | 7.527 | 0.582 | 298.500 | 18940 |
| 3F | R | kakuban | 26.630 | 0.000 | 457.400 | 18940 |

## Section 4: 結論
- 2F: winner=kakuban; digit p=0.025, kakuban p=0.000; effect_range digit=238.0, kakuban=224.0
- 3F: winner=kakuban; digit p=0.016, kakuban p=0.000; effect_range digit=257.3, kakuban=258.3
- 全体平均では角番効果がやや優勢
- 仮説「L=末尾支配 / R=角番支配」は不成立寄り（L=角番優勢, R=角番優勢）
