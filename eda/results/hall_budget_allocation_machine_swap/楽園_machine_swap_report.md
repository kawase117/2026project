# 楽園 Machine Residual and Swap Check

- target bins: 10
- no_clear_swap_in_window: 4/10 (40.0%)

## Machine Residual
| hall | axis_value | t_full_original | t_full_residual | residual_verdict |
| --- | --- | --- | --- | --- |
| 楽園 | 1031-1040 | 5.639 | -1.616 | explained_by_machine_identity |
| 楽園 | 1041-1050 | 4.631 | -0.513 | explained_by_machine_identity |
| 楽園 | 1051-1060 | 3.762 | -0.955 | explained_by_machine_identity |
| 楽園 | 1101-1110 | -4.274 | -0.743 | explained_by_machine_identity |
| 楽園 | 1131-1140 | -6.624 | -0.774 | explained_by_machine_identity |
| 楽園 | 1151-1160 | -4.359 | -2.775 | band_effect_survives_residualization |
| 楽園 | 1191-1200 | -3.812 | -1.622 | explained_by_machine_identity |
| 楽園 | 1201-1210 | -5.353 | -1.874 | explained_by_machine_identity |
| 楽園 | 2131-2140 | 4.020 | -2.435 | band_effect_survives_residualization |
| 楽園 | 3221-3230 | 4.133 | -2.018 | explained_by_machine_identity |

## Swap Stability
| hall | axis_value | swap_date | n_days_before | t_before | n_days_after | t_after | swap_verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 楽園 | 1031-1040 | 20260105 | 367 | 5.615 | 181 | 2.347 | persists_across_swap |
| 楽園 | 1041-1050 | 20260105 | 367 | 3.679 | 181 | 2.874 | persists_across_swap |
| 楽園 | 1051-1060 | 20250303 | 61 | -1.634 | 487 | 4.649 | weakens_after_swap |
| 楽園 | 1101-1110 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| 楽園 | 1131-1140 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| 楽園 | 1151-1160 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| 楽園 | 1191-1200 | 20250929 | 269 | -2.708 | 279 | -2.681 | persists_across_swap |
| 楽園 | 1201-1210 |  | 0 | 0.000 | 0 | 0.000 | no_clear_swap_in_window |
| 楽園 | 2131-2140 | 20260303 | 421 | 3.383 | 123 | 2.407 | persists_across_swap |
| 楽園 | 3221-3230 | 20250804 | 213 | 1.372 | 335 | 4.226 | persists_across_swap |

## Machine Names Around Swap
| axis_value | swap_date | n_machines_in_band | n_machines_swapped_on_date | machine_names_before | machine_names_after |
| --- | --- | --- | --- | --- | --- |
| 1031-1040 | 20260105 | 10 | 10 | スマスロ北斗の拳 | 北斗の拳 転生の章2 |
| 1041-1050 | 20260105 | 10 | 10 |  サラリーマン金太郎, サラリーマン金太郎～MAX～, スマスロ北斗の拳, 聖戦士ダンバイン | 北斗の拳 転生の章2, 東京喰種 |
| 1051-1060 | 20250303 | 9 | 9 |  サラリーマン金太郎, にゃんこ大戦争 超神速, サラリーマン金太郎～MAX～, スマスロ真・北斗無双, マクロスフロンティア4, ルパン三世 大航海者の秘宝, 東京喰種, 聖戦士ダンバイン, 頭文字D 2nd | スマスロ北斗の拳, 北斗の拳 転生の章2, 東京喰種 |
| 1101-1110 |  | 10 | 5 | キングハナハナ-30, スマート沖スロ スターハナハナ, 南国育ち, 沖ドキ!BLACK, 沖ドキ!DUO アンコール | キングハナハナ-30, スマート沖スロ スターハナハナ, 南国育ち, 沖ドキ!BLACK, 沖ドキ!DUO アンコール |
| 1131-1140 |  | 10 | 4 | ジャグラーガールズ, ファンキージャグラー2, 沖ドキ!BLACK, 沖ドキ!DUO アンコール, 沖ドキ!GOLD‐30 | ジャグラーガールズ, ファンキージャグラー2, 沖ドキ!BLACK, 沖ドキ!DUO アンコール, 沖ドキ!GOLD‐30 |
| 1151-1160 |  | 10 | 5 | アイムジャグラーEX-TP, ゴーゴージャグラー3, ハッピージャグラーVIII | アイムジャグラーEX-TP, ゴーゴージャグラー3, ハッピージャグラーVIII |
| 1191-1200 | 20250929 | 10 | 6 | アイムジャグラーEX-TP, マイジャグラーV | ネオアイムジャグラーEX, マイジャグラーV |
| 1201-1210 |  | 10 | 0 | マイジャグラーV | マイジャグラーV |
| 2131-2140 | 20260303 | 10 | 10 | クランキークレスト, バーサスリヴァイズ, ファミスタ回胴版!!, 新ハナビ | プリズムナナ, マギアレコード 魔法少女まどか☆マギカ外伝 |
| 3221-3230 | 20250804 | 10 | 10 | OVERLORD絶対支配者光臨II, ダンジョンに出会いを求めるのは間違っているだろうか2, マクロスデルタ, 新鬼武者2, 甲鉄城のカバネリ | 交響詩篇エウレカセブン HI-EVOLUTION ZERO TYPE‐ART, 新鬼武者2, 甲鉄城のカバネリ |
