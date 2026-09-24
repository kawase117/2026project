# MDE Gate

> 本表は `games_normalized >= 1000` の台に条件づけた検出力である。
> この足切りは表示上の運用規約であって母集団の定義ではない。

MDEの生値は推定器固有の単位であり、異なる推定器間では比較しない。
推定器間は `detectability = reference_effect / MDE` の無次元量だけで比較する。
last_digit・section・machine_name・corner1 は position 参照クラス、dd_event・strong_zorome・weekday は calendar 参照クラスである。

## 検収

検収値の元データ截止日は `20260910`。全体マップは各DBの最新日まで使用。

| metric | expected | actual | tolerance | passed |
| --- | --- | --- | --- | --- |
| mean_effect | 0.137 | 0.13671 | 0.01 | True |
| daily_sd | 3.753 | 3.753106 | 0.01 | True |
| n_days | 615.0 | 615.0 | 0.0 | True |
| mde_7 | 3.972 | 3.971914 | 0.01 | True |
| mde_14 | 2.809 | 2.808567 | 0.01 | True |
| mde_28 | 1.986 | 1.985957 | 0.01 | True |
| mde_56 | 1.404 | 1.404284 | 0.01 | True |
| mde_180 | 0.783 | 0.783272 | 0.01 | True |

## 入力DB

| hall | db_path | rows_games_ge_1000 | date_min | date_max | n_dates | layout_missing | master_missing | daily_summary_flag_missing | any_event_days | strong_zorome_days | weekend_rate_before_20260601 | weekend_rate_from_20260601 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 楽園蒲田店 | db\楽園蒲田店.db | 249670 | 20250101 | 20260923 | 628 | 471 | 0 | 0 | 233 | 21 | 0.287378640776699 | 0.2782608695652174 |
| マルハンメガシティ2000-蒲田7 | db\マルハンメガシティ2000-蒲田7.db | 287345 | 20250707 | 20260923 | 435 | 0 | 0 | 0 | 216 | 15 | 0.28134556574923547 | 0.26851851851851855 |
| マルハンメガシティ2000-蒲田1 | db\マルハンメガシティ2000-蒲田1.db | 190155 | 20250101 | 20260923 | 614 | 10212 | 0 | 0 | 293 | 21 | 0.2868525896414343 | 0.2767857142857143 |
| みとや大森町店 | db\みとや大森町店.db | 141330 | 20250101 | 20260923 | 625 | 406 | 0 | 0 | 296 | 21 | 0.2840466926070039 | 0.27927927927927926 |
| ARROW池上店 | db\ARROW池上店.db | 186490 | 20250101 | 20260922 | 626 | 186490 | 0 | 0 | 274 | 21 | 0.28793774319066145 | 0.2857142857142857 |
| ヒロキ東口店 | db\ヒロキ東口店.db | 110436 | 20250101 | 20260923 | 622 | 110436 | 0 | 0 | 249 | 21 | 0.28599221789883267 | 0.28703703703703703 |
| レイトギャップ平和島 | db\レイトギャップ平和島.db | 183296 | 20250320 | 20260923 | 550 | 183296 | 0 | 0 | 219 | 18 | 0.2889908256880734 | 0.2719298245614035 |
| ザ-シティ-ベルシティ雑色店 | db\ザ-シティ-ベルシティ雑色店.db | 58401 | 20250101 | 20260923 | 626 | 58401 | 0 | 0 | 288 | 21 | 0.287378640776699 | 0.2702702702702703 |
| 金時京急蒲田店 | db\金時京急蒲田店.db | 66245 | 20250101 | 20260923 | 629 | 66245 | 0 | 0 | 259 | 21 | 0.28599221789883267 | 0.2782608695652174 |

## ホール別・推定器順位

28日窓、既存4軸、JUG・BT・判別可能の共通セルにおける detectability 中央値で順位づけ。

| hall | estimator | median_detectability_28d | rank |
| --- | --- | --- | --- |
| ARROW池上店 | bonus_rate | 0.779 | 1.0 |
| ARROW池上店 | payout | 0.618 | 2.0 |
| ARROW池上店 | payout_within_model | 0.618 | 3.0 |
| ARROW池上店 | rb_rate | 0.498 | 4.0 |
| みとや大森町店 | bonus_rate | 0.757 | 1.0 |
| みとや大森町店 | payout_within_model | 0.638 | 2.0 |
| みとや大森町店 | payout | 0.637 | 3.0 |
| みとや大森町店 | rb_rate | 0.555 | 4.0 |
| ザ-シティ-ベルシティ雑色店 | bonus_rate | 0.451 | 1.0 |
| ザ-シティ-ベルシティ雑色店 | payout_within_model | 0.361 | 2.0 |
| ザ-シティ-ベルシティ雑色店 | payout | 0.36 | 3.0 |
| ザ-シティ-ベルシティ雑色店 | rb_rate | 0.296 | 4.0 |
| ヒロキ東口店 | bonus_rate | 0.464 | 1.0 |
| ヒロキ東口店 | payout_within_model | 0.377 | 2.0 |
| ヒロキ東口店 | payout | 0.377 | 3.0 |
| ヒロキ東口店 | rb_rate | 0.315 | 4.0 |
| マルハンメガシティ2000-蒲田1 | bonus_rate | 0.751 | 1.0 |
| マルハンメガシティ2000-蒲田1 | payout_within_model | 0.665 | 2.0 |
| マルハンメガシティ2000-蒲田1 | payout | 0.664 | 3.0 |
| マルハンメガシティ2000-蒲田1 | rb_rate | 0.526 | 4.0 |
| マルハンメガシティ2000-蒲田7 | bonus_rate | 0.896 | 1.0 |
| マルハンメガシティ2000-蒲田7 | payout | 0.79 | 2.0 |
| マルハンメガシティ2000-蒲田7 | payout_within_model | 0.788 | 3.0 |
| マルハンメガシティ2000-蒲田7 | rb_rate | 0.61 | 4.0 |
| レイトギャップ平和島 | bonus_rate | 0.666 | 1.0 |
| レイトギャップ平和島 | payout_within_model | 0.562 | 2.0 |
| レイトギャップ平和島 | payout | 0.562 | 3.0 |
| レイトギャップ平和島 | rb_rate | 0.438 | 4.0 |
| 楽園蒲田店 | bonus_rate | 0.761 | 1.0 |
| 楽園蒲田店 | payout_within_model | 0.578 | 2.0 |
| 楽園蒲田店 | payout | 0.577 | 3.0 |
| 楽園蒲田店 | rb_rate | 0.496 | 4.0 |
| 金時京急蒲田店 | bonus_rate | 0.501 | 1.0 |
| 金時京急蒲田店 | payout_within_model | 0.395 | 2.0 |
| 金時京急蒲田店 | payout | 0.395 | 3.0 |
| 金時京急蒲田店 | rb_rate | 0.335 | 4.0 |

## 日付軸の暦日換算

日付軸では `base_rate = n_days_in_group / n_days`、暦C日での有効対象日数を `eff_n = base_rate * C` とする。`eff_n < 5` は `INSUFFICIENT_DATA`。

| contrast | calendar_days | base_rate_min | base_rate_median | base_rate_max | eff_n_min | eff_n_median | eff_n_max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dd_event | 28 | 0.371 | 0.438 | 0.497 | 10.389 | 12.256 | 13.903 |
| dd_event | 56 | 0.371 | 0.438 | 0.497 | 20.777 | 24.511 | 27.807 |
| dd_event | 180 | 0.371 | 0.438 | 0.497 | 66.783 | 78.786 | 89.379 |
| dd_event | 365 | 0.371 | 0.438 | 0.497 | 135.422 | 159.76 | 181.241 |
| strong_zorome | 28 | 0.033 | 0.034 | 0.034 | 0.916 | 0.939 | 0.966 |
| strong_zorome | 56 | 0.033 | 0.034 | 0.034 | 1.833 | 1.879 | 1.931 |
| strong_zorome | 180 | 0.033 | 0.034 | 0.034 | 5.891 | 6.038 | 6.207 |
| strong_zorome | 365 | 0.033 | 0.034 | 0.034 | 11.945 | 12.244 | 12.586 |
| weekday | 28 | 0.136 | 0.143 | 0.147 | 3.798 | 4.013 | 4.12 |
| weekday | 56 | 0.136 | 0.143 | 0.147 | 7.595 | 8.025 | 8.239 |
| weekday | 180 | 0.136 | 0.143 | 0.147 | 24.414 | 25.796 | 26.483 |
| weekday | 365 | 0.136 | 0.143 | 0.147 | 49.506 | 52.309 | 53.701 |

日付軸ごとのゲート件数（位置系とは合算しない）:

| contrast | calendar_days | DETECTABLE | INSUFFICIENT_DATA | MARGINAL | NOT_APPLICABLE | UNDETECTABLE |
| --- | --- | --- | --- | --- | --- | --- |
| dd_event | 28 | 93 | 0 | 43 | 36 | 8 |
| dd_event | 56 | 112 | 0 | 32 | 36 | 0 |
| dd_event | 180 | 138 | 0 | 6 | 36 | 0 |
| dd_event | 365 | 144 | 0 | 0 | 36 | 0 |
| strong_zorome | 28 | 0 | 144 | 0 | 36 | 0 |
| strong_zorome | 56 | 0 | 144 | 0 | 36 | 0 |
| strong_zorome | 180 | 56 | 0 | 76 | 36 | 12 |
| strong_zorome | 365 | 92 | 0 | 52 | 36 | 0 |
| weekday | 28 | 0 | 144 | 0 | 36 | 0 |
| weekday | 56 | 93 | 0 | 41 | 36 | 10 |
| weekday | 180 | 130 | 0 | 14 | 36 | 0 |
| weekday | 365 | 134 | 0 | 10 | 36 | 0 |

> ⚠️ **上表のgate列（DETECTABLE等）を日付軸(dd_event/strong_zorome/weekday)ではそのまま使わない。**
> reference_effect（calendar参照クラス）は rakuen_dd_jug という単一の確定済みclaimの効果量
> （payout +2.307pp等、`backtest/results/deathwatch/status.csv`）を3軸・9ホール全部に転用している。
> rakuen のイベントDDは確認済みの強い効果であり、まだ検証していない新しい仮説の目安には楽観的すぎる。
> 下表がその楽観度（configured_reference ÷ このマップ自身で観測されたmean_effectの中央値）を軸別に示す。
> ⚠️ **下表の`median_abs_observed`を新しいreference_effectとして使い回さないこと。**
> 同じ実行の観測データを閾値にして同じデータの検出力を測ると自己参照になる。日付軸で仮説を検定できるかは
> 個別に独立した参照効果量（他ホールの確定済みclaim等）を探して判断する。

| contrast | estimator | configured_reference | median_abs_observed | n_cells | optimism_ratio |
| --- | --- | --- | --- | --- | --- |
| weekday | bonus_rate | 0.424 | 0.0575 | 27 | 7.3766 |
| dd_event | bonus_rate | 0.424 | 0.0852 | 27 | 4.9778 |
| strong_zorome | bonus_rate | 0.424 | 0.1135 | 27 | 3.7352 |
| weekday | payout | 2.3 | 0.2288 | 45 | 10.0503 |
| dd_event | payout | 2.3 | 0.5987 | 45 | 3.8418 |
| strong_zorome | payout | 2.3 | 0.9052 | 45 | 2.5408 |
| weekday | payout_within_model | 2.3 | 0.2106 | 45 | 10.9206 |
| dd_event | payout_within_model | 2.3 | 0.577 | 45 | 3.986 |
| strong_zorome | payout_within_model | 2.3 | 0.9026 | 45 | 2.5482 |
| weekday | rb_rate | 0.271 | 0.0219 | 27 | 12.3671 |
| dd_event | rb_rate | 0.271 | 0.0437 | 27 | 6.1991 |
| strong_zorome | rb_rate | 0.271 | 0.0693 | 27 | 3.9085 |

## 暦28日で位置系が DETECTABLE の条件

| hall | segment | contrast | estimator | calendar_days | window_days | n_days | n_days_in_group | n_per_day | mde | reference_effect | detectability | rb0_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ARROW池上店 | bonus_judgeable | last_digit | bonus_rate | 28 | 28.0 | 626 |  | 10.0 | 0.2345 | 0.245 | 1.0447 | 0.0126 |
| みとや大森町店 | bonus_judgeable | corner1 | bonus_rate | 28 | 28.0 | 625 |  | 16.0 | 0.2002 | 0.245 | 1.2239 | 0.0299 |
| みとや大森町店 | JUG | corner1 | bonus_rate | 28 | 28.0 | 625 |  | 13.0 | 0.2173 | 0.245 | 1.1277 | 0.0073 |
| みとや大森町店 | bonus_judgeable | corner1 | payout_within_model | 28 | 28.0 | 625 |  | 16.0 | 1.2731 | 1.35 | 1.0604 | 0.0299 |
| みとや大森町店 | bonus_judgeable | corner1 | payout | 28 | 28.0 | 625 |  | 16.0 | 1.2752 | 1.35 | 1.0586 | 0.0299 |
| みとや大森町店 | JUG | corner1 | payout_within_model | 28 | 28.0 | 625 |  | 13.0 | 1.3393 | 1.35 | 1.008 | 0.0073 |
| みとや大森町店 | JUG | corner1 | payout | 28 | 28.0 | 625 |  | 13.0 | 1.3394 | 1.35 | 1.0079 | 0.0073 |
| マルハンメガシティ2000-蒲田1 | JUG | corner1 | bonus_rate | 28 | 28.0 | 613 |  | 14.0 | 0.2313 | 0.245 | 1.0594 | 0.0073 |
| マルハンメガシティ2000-蒲田1 | JUG | corner1 | payout_within_model | 28 | 28.0 | 613 |  | 14.0 | 1.3078 | 1.35 | 1.0323 | 0.0073 |
| マルハンメガシティ2000-蒲田1 | JUG | corner1 | payout | 28 | 28.0 | 613 |  | 14.0 | 1.3104 | 1.35 | 1.0302 | 0.0073 |
| マルハンメガシティ2000-蒲田1 | bonus_judgeable | corner1 | bonus_rate | 28 | 28.0 | 613 |  | 18.0 | 0.2383 | 0.245 | 1.028 | 0.0091 |
| マルハンメガシティ2000-蒲田1 | bonus_judgeable | corner1 | payout | 28 | 28.0 | 613 |  | 18.0 | 1.3488 | 1.35 | 1.0009 | 0.0091 |
| マルハンメガシティ2000-蒲田7 | bonus_judgeable | corner1 | payout_within_model | 28 | 28.0 | 435 |  | 38.0 | 1.0381 | 1.35 | 1.3005 | 0.0085 |
| マルハンメガシティ2000-蒲田7 | JUG | corner1 | bonus_rate | 28 | 28.0 | 435 |  | 24.0 | 0.1885 | 0.245 | 1.3001 | 0.0082 |
| マルハンメガシティ2000-蒲田7 | bonus_judgeable | corner1 | payout | 28 | 28.0 | 435 |  | 38.0 | 1.0512 | 1.35 | 1.2842 | 0.0085 |
| マルハンメガシティ2000-蒲田7 | bonus_judgeable | corner1 | bonus_rate | 28 | 28.0 | 435 |  | 38.0 | 0.2025 | 0.245 | 1.2097 | 0.0085 |
| マルハンメガシティ2000-蒲田7 | bonus_judgeable | last_digit | bonus_rate | 28 | 28.0 | 435 |  | 23.0 | 0.2034 | 0.245 | 1.2047 | 0.0085 |
| マルハンメガシティ2000-蒲田7 | JUG | corner1 | payout | 28 | 28.0 | 435 |  | 24.0 | 1.1455 | 1.35 | 1.1785 | 0.0082 |
| マルハンメガシティ2000-蒲田7 | JUG | corner1 | payout_within_model | 28 | 28.0 | 435 |  | 24.0 | 1.1475 | 1.35 | 1.1764 | 0.0082 |
| マルハンメガシティ2000-蒲田7 | bonus_judgeable | last_digit | payout_within_model | 28 | 28.0 | 435 |  | 23.0 | 1.2047 | 1.35 | 1.1206 | 0.0085 |
| マルハンメガシティ2000-蒲田7 | bonus_judgeable | last_digit | payout | 28 | 28.0 | 435 |  | 24.0 | 1.2055 | 1.35 | 1.1199 | 0.0085 |
| マルハンメガシティ2000-蒲田7 | JUG | last_digit | bonus_rate | 28 | 28.0 | 435 |  | 18.0 | 0.2241 | 0.245 | 1.0935 | 0.0082 |
| マルハンメガシティ2000-蒲田7 | JUG | section | bonus_rate | 28 | 28.0 | 435 |  | 13.0 | 0.2368 | 0.245 | 1.0347 | 0.0082 |
| マルハンメガシティ2000-蒲田7 | JUG | last_digit | payout_within_model | 28 | 28.0 | 435 |  | 16.0 | 1.3427 | 1.35 | 1.0055 | 0.0082 |
| マルハンメガシティ2000-蒲田7 | JUG | last_digit | payout | 28 | 28.0 | 435 |  | 16.0 | 1.3429 | 1.35 | 1.0053 | 0.0082 |
| 楽園蒲田店 | bonus_judgeable | corner1 | bonus_rate | 28 | 28.0 | 627 |  | 39.0 | 0.1587 | 0.245 | 1.5437 | 0.1432 |
| 楽園蒲田店 | bonus_judgeable | corner1 | payout | 28 | 28.0 | 627 |  | 39.0 | 1.0925 | 1.35 | 1.2357 | 0.1432 |
| 楽園蒲田店 | bonus_judgeable | corner1 | payout_within_model | 28 | 28.0 | 627 |  | 39.0 | 1.0955 | 1.35 | 1.2323 | 0.1432 |
| 楽園蒲田店 | JUG | corner1 | bonus_rate | 28 | 28.0 | 627 |  | 18.0 | 0.2097 | 0.245 | 1.1684 | 0.0089 |
| 楽園蒲田店 | bonus_judgeable | last_digit | bonus_rate | 28 | 28.0 | 628 |  | 17.0 | 0.2245 | 0.245 | 1.0913 | 0.1432 |
| 楽園蒲田店 | bonus_judgeable | corner1 | rb_rate | 28 | 28.0 | 627 |  | 39.0 | 0.1068 | 0.108 | 1.0115 | 0.1432 |

## 推定器変更と窓延長の比較

既存4軸の対応可能な物理セル 312 件で、推定器間はdetectability比だけを比較した。

| estimator | matched_cells | median_ratio_vs_payout | mean_ratio_vs_payout | win_rate_vs_payout |
| --- | --- | --- | --- | --- |
| bonus_rate | 312 | 1.209 | 1.258 | 0.987 |
| rb_rate | 312 | 0.823 | 0.866 | 0.192 |
| payout_within_model | 312 | 1.0 | 1.001 | 0.641 |

bonus_rateへの変更による中央値改善は 1.209 倍。窓を2倍にした1.414倍は実測発見ではなく、MDEが1/sqrt(W)に比例する定義上の恒等式である。
両者は乗算的に効き、bonus_rateと窓2倍を組み合わせた倍率は 1.710 倍。
指標変更は追加の日数を必要としないが、窓延長は法則がその期間だけ定常であることを仮定する。したがって運用上は指標変更を先に検討する。
修正後の312対応セルではrb_rate単体のpayout比中央値は 0.823、勝率は 19.2% で、検出力の優位はない。bonus_rateの上昇はBB追加と整合するが、設定感応度の優劣や因果的な寄与分解は本分析の対象外。
payout_within_modelのpayout比中央値は 1.000。MDEが改善しないのは仕様どおりで、機種構成の定数バイアスを除く正しさの道具であり、分散低減の道具ではない。

参考：同一推定器内で窓を延ばした場合の定義上の倍率:

| calendar_window_change | detectability_multiplier |
| --- | --- |
| 28→56 | 1.414 |
| 56→180 | 1.793 |
| 180→365 | 1.424 |

## ゲート定義

- DETECTABLE: detectability >= 1.0
- MARGINAL: 0.4 <= detectability < 1.0
- UNDETECTABLE: detectability < 0.4
- NOT_APPLICABLE: rb_rate / bonus_rate を設定判別不能または混在セグメントへ適用しない
- INSUFFICIENT_DATA: 日次効果系列を構成できない、またはcalendar軸の暦窓内eff_nが5日未満

## 計算していないこと・近似

- 新しい法則、相関、投入パターンの探索は行っていない。
- レジーム分割、ルール探索、パラメータ探索、walk-forward再実装は行っていない。
- MDEは `2.8 * daily_sd / sqrt(W)` の正規近似。
- 複数グループを持つ対比軸は、各グループの二群差SDを並べた中央グループを代表系列としている。
- calendar軸は群内平均 − 群外平均の二群差。Wを対象群日数として、群外側も観測された日数比で分散へ加えている。
- dd_eventは `is_any_event = 祝日 OR 週末 OR X日` であり、ホール固有のイベントDDではない。weekdayと重なる軸なので、両者を独立証拠として合算しない。
- bootstrapはcalendar軸では対象群W日と群外側を観測日数比で別々に7日ブロック再標本化し、その平均差の95%CI半幅を出した。
- payout_within_modelの機種平均は、各DBの全対象期間かつgames>=1000の行から計算した。
- 参照効果量はユーザー指定のdeathwatch中央値を固定値として使用し、この処理では再推定していない。
