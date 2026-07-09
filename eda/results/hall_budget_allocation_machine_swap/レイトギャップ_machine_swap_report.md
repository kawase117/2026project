# レイトギャップ Machine Residual and Swap Check

- target bins: 6
- no_clear_swap_in_window: 4/6 (66.7%)

## Machine Residual
| hall | axis_value | t_full_original | t_full_residual | residual_verdict |
| --- | --- | --- | --- | --- |
| レイトギャップ | 571-580 | 4.168 | -1.713 | explained_by_machine_identity |
| レイトギャップ | 711-720 | 4.923 | -1.761 | explained_by_machine_identity |
| レイトギャップ | 721-730 | 3.871 | -2.222 | band_effect_survives_residualization |
| レイトギャップ | 731-740 | 5.354 | -1.492 | explained_by_machine_identity |
| レイトギャップ | 741-750 | 3.832 | -1.641 | explained_by_machine_identity |
| レイトギャップ | 861-870 | -7.114 | -0.818 | explained_by_machine_identity |

## Swap Stability
| hall | axis_value | swap_date | n_days_before | t_before | n_days_after | t_after | swap_verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| レイトギャップ | 571-580 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| レイトギャップ | 711-720 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| レイトギャップ | 721-730 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| レイトギャップ | 731-740 | 20251006 | 198 | 5.062 | 270 | 2.573 | persists_across_swap |
| レイトギャップ | 741-750 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| レイトギャップ | 861-870 | 20260202 | 316 | -5.970 | 152 | -3.866 | persists_across_swap |

## Machine Names Around Swap
| axis_value | swap_date | n_machines_in_band | n_machines_swapped_on_date | machine_names_before | machine_names_after |
| --- | --- | --- | --- | --- | --- |
| 571-580 |  | 10 | 0 | モンキーターンV, 東京喰種 | モンキーターンV, 東京喰種 |
| 711-720 |  | 10 | 0 | ウルトラミラクルジャグラー, ゴーゴージャグラー3, ジャグラーガールズ | ウルトラミラクルジャグラー, ゴーゴージャグラー3, ジャグラーガールズ |
| 721-730 |  | 10 | 2 | アイムジャグラーEX-TP, ウルトラミラクルジャグラー, ネオアイムジャグラーEX, ハッピージャグラーVIII | アイムジャグラーEX-TP, ウルトラミラクルジャグラー, ネオアイムジャグラーEX, ハッピージャグラーVIII |
| 731-740 | 20251006 | 10 | 8 | アイムジャグラーEX-TP | アイムジャグラーEX-TP, ネオアイムジャグラーEX |
| 741-750 |  | 10 | 5 | アイムジャグラーEX-TP, ネオアイムジャグラーEX | アイムジャグラーEX-TP, ネオアイムジャグラーEX |
| 861-870 | 20260202 | 10 | 6 | Re:ゼロから始める異世界生活 season2, いざ!番長, いざ！番長, スマスロ真・北斗無双, ダンベル何キロ持てる？, 化物語, 吉宗, 咲‐Saki‐ 頂上決戦, 東京喰種, 革命機ヴァルヴレイヴ, 頭文字D 2nd | BIRDIE WING ‐Golf Girls' Story‐, いざ！番長, からくりサーカス, バイオハザード5, モンスターハンターライズ, ヨルムンガンド, 吉宗, 新鬼武者3 |
