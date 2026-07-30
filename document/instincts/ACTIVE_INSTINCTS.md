# ACTIVE_INSTINCTS

- generated_at: 2026-07-31T01:19:35+09:00
- compiler_version: 1.3.0
- source_dir: `C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/document/instincts`
- total_records_scanned: 1476
- active_records: 120
- status_breakdown: unverified=1472, confirmed=1, refuted=0, superseded=2
- filters: `confidence >= 0.80` and `file_date within 21 days` (unless pinned by high confidence)

## Usage
- Start of work: run `venv\Scripts\python.exe scripts/compile_instincts.py` (or `python scripts/compile_instincts.py`).
- Long sessions: rerun before major decisions or every 15-20 minutes.
- Preferred source for Codex: `ACTIVE_INSTINCTS.jsonl` (machine-readable canonical).
- This Markdown is a quick view. Open raw YAML only when detail is missing.
- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed.

## Active List

### 1. `forward-scoring-needs-rb-perspective-not-just-diff`
- confidence: `0.85` | status: `unverified` | date: `2026-07-30` | file: `2026-07-30-forward-scoring-rb-perspective-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: RB確率(hist_mean_rb_prob / hist_mean_rb_prob_model_z / hist_hit104_rate)で台を選ぶジャグ・ハナハナ系フォワードテストの答え合わせをするとき
- summary: backtest/forward.py の score() は元々「diff(差枚) - 同日eligible平均」のedgeだけを答え合わせ指標にしていた。しかしRB確率ベースの選定ルールは「RBが多く出る台=高設定」という根拠で台を選んでおり、差枚は投資ペースやBB配分・短時間の出玉ムラにも左右されるため、d...

### 2. `split-half-consistency-is-not-holdout`
- confidence: `0.95` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 候補（DD・末尾・section等）を全期間から抽出したあとに、時系列前半/後半へ分割して『holdout検証した』と主張しようとするとき
- summary: `eda/rakuen_theory_revalidation.py` はジャグ・ハナハナ・技術介入・AT一般のカテゴリ別DD候補を 中央値日（2025-10-14）で前後半に割り、後半でBH補正付き permutation 検定を行い、通過分に `holdout_supported` という列名を与えた。しかし...

### 3. `model-confinement-causes-residual-degeneracy`
- confidence: `0.90` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-residual-methodology-and-section-retraction-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 機種内残差（同日×同機種平均からの残差）で、フロア・棟・特定セクション群など「機種を横断する広い単位」を比較しようとするとき
- summary: 楽園蒲田店で2回、同じ構造のバグ/罠に遭遇した。 (1) 「本館>新館」の建物単位勾配を機種内残差で測ろうとしたところ、ジャグ・ハナハナ・ 技術介入はカテゴリ内の全機種が本館↔新館のどちらか一方に完全に閉じ込められており （複数棟にまたがる機種が0件）、機種内残差では原理的に建物間の差を検出できなかった。 唯一A...

### 4. `rakuen-section-dd-swing-fully-retracted`
- confidence: `0.90` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-residual-methodology-and-section-retraction-insights.yaml`
- domain/source: `pachinko-domain-analysis` / `session-observation`
- trigger: 楽園蒲田店のセクション別DD狙い目/避け目（旧Type A/B、1130-1134・3117-3120・3113-3116・1209-1216等）を運用ルールとして参照しようとするとき
- summary: document/rakuen_theory.md §8（2026-07-12作成）は avg_diff（回転数交絡未処理）と 旧43 section定義に基づき、1130-1134を「31日全てマイナスの恒常回避区画」、 3117-3120を「DD11・DD29・DD30favorable/DD25・DD31・...

### 5. `hit104-and-diff-are-volume-confounded-not-setting-indicators`
- confidence: `0.90` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-event-day-category-decomposition-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: DD・曜日・イベント日などの日レベル軸を、差枚(diff)またはhit104率(P(機械割>104%))で判定しようとするとき
- summary: 機械割 = 100 + diff/(3*games)*100 なので Var(機械割) ∝ 1/games。回転数十分位で 実測すると平均機械割そのものが82.7%→106.2%と単調に動き、hit104率(P(機械割>104%)超え確率) は16.1%→54.6%と3.4倍動く（`eda/rakuen_hit1...

### 6. `omnibus-null-vs-walkforward-topk-positive`
- confidence: `0.90` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: section・軸・区画の主効果が omnibus 検定で非有意だったことを根拠に『構造なし』と結論しようとするとき
- summary: `rakuen_theory.md` §2.1c は「section主効果・section×DD交互作用は構造なし」と結論している。 一方、同じデータで直近90日を訓練窓とする walk-forward（当日games足切りなし・工事前・ ジャグp56）を回すと、top3 section の excess は通常...

### 7. `report-without-paired-ci-invites-misreading`
- confidence: `0.90` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `analysis-workflow` / `session-observation`
- trigger: モデルA と モデルB の比較結果を『Aは Bを上回らなかった』と報告する、または他エージェント（Codex等）からそう報告されたとき
- summary: Codex が生成した `eda/results/rakuen_theory_revalidation/report.md` は section walk-forward の 比較を点推定のみで示し、「category_calendar_split は all_history を上回らなかった」と結論した。 CS...

### 8. `layout-mapping-precedes-reanalysis`
- confidence: `0.90` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `hall-strategy` / `session-observation`
- trigger: 改装・レイアウト変更後のホールで、旧section名を含む分析を再実行しようとするとき
- summary: 楽園蒲田は 2026-07-06 に改装。`legacy_section_status.csv` は旧7区画 （1106-1115 / 1130-1134 / 1209-1216 / 3113-3116 / 3117-3120 / 2141-2162 / 1057-1059）すべてが `requires phys...

### 9. `debut-date-must-be-per-slot-not-per-model`
- confidence: `0.85` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-residual-methodology-and-section-retraction-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 経過日数・設置からの日数・「新台」判定など、機種の設置起点(debut)を扱う分析をするとき
- summary: `eda/core.py` の `compute_debut_features` は debut_date を `df.groupby("machine_name")["date"].min()` で計算していた——machine_name(機種名) 単位でホール全体での最古出現日。楽園蒲田店で実測したところ、5...

### 10. `rakuen-event-day-not-single-calendar`
- confidence: `0.85` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-event-day-category-decomposition-insights.yaml`
- domain/source: `pachinko-domain-analysis` / `session-observation`
- trigger: ホール単位で単一のevent_dds（イベント日リスト）を定義・使用しようとするとき
- summary: 楽園蒲田店を機種内機械割残差でカテゴリ別に割ると、DDごとに全く違う顔を見せる: | DD | ジャグ | 技術介入 | ハナハナ | AT一般 | |---|---|---|---|---| | 30 | +0.99 | +2.50(1位) | +4.56 | +2.41(1位) | | 22 | +2.19(...

### 11. `single-survivor-summary-hides-calendar-shift`
- confidence: `0.85` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `hall-strategy` / `session-observation`
- trigger: 複数候補DDを前後半で再検定し、『N個中1個だけ残った』と要約しようとするとき
- summary: 楽園ジャグのカテゴリ別DD候補を p56（設定5-6事後確率）で前後半比較すると、 `eda/results/rakuen_theory_revalidation/category_dd_temporal_validation.csv` は次を示す。 | DD | 前半effect | 後半effect | |-...

### 12. `machine-rate-metric-not-comparable-to-p56`
- confidence: `0.80` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: ジャグ以外のカテゴリ（ハナハナ・技術介入・AT一般）のDD効果を機械割ベースの rate で検定し、ジャグのp56結果と同じ表に並べようとするとき
- summary: `category_dd_temporal_validation.csv` の BH補正通過数はカテゴリで大きく偏る。 | category | metric | 31DD中の通過数 | |---|---|---| | ジャグ | p56 | 1 | | ハナハナ | rate | 7 | | 技術介入 | ra...

### 13. `rakuen-section-column-not-island`
- confidence: `0.95` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-rakuen-section-column-redefinition-and-edge-effect-insights.yaml`
- domain/source: `section-analysis` / `session-observation`
- trigger: 楽園のsectionをフロア座標・生成スクリプトから扱うとき
- summary: `Heatmap/generate_rakuen_kamata_coordinates.py`が、1122-1134・1135-1151・2100-2110・ 3107-3116・3176-3187の5箇所で、通路(柱)で物理的に分断された1本の列を`section`という 1つのラベルにまとめていた。既存の`m...

### 14. `pick-concentration-decomposition-before-trusting-score`
- confidence: `0.90` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-instincts.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: 新規に発見・提案したスコアリングルールのwalk-forward edgeが良好な数値を示したとき（prereg化する前）
- summary: 2026-07-28、蒲田7のk7_at_histdiff_top3ルール(rank1-3)を9ヶ月walk-forwardで 測ると+1,130枚/台(CI[+737,+1,619])と好成績だったが、選出頻度を見ると 台2026が227日中184日(81%)選ばれていた。台2026を除外すると+122.6枚...

### 15. `mean-averaging-denominator-shrink-bias`
- confidence: `0.90` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-instincts.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: walk-forwardで日次top-Nを選び、当日の実データと突き合わせてedgeを平均するとき（即席の分析スクリプトを書くとき）
- summary: 2026-07-29、Codexへの独立監査依頼(codex:rescueではなく直接コピペ依頼)で 発覚。k7_at_histdiff_top3のedge検証で、私の即席walk-forwardスクリプトは `sel = day[day.machine_number.isin(top)]` として当日のgame...

### 16. `whole-period-average-hides-regime-collapse`
- confidence: `0.90` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-instincts.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: ホールの店長交代・改装等の既知レジーム変化点があるルールについて、全期間プールのwalk-forward数値だけを見て判断しようとするとき
- summary: 2026-07-28、みとやのジャグRB機種内zスコア(hist_mean_rb_prob_model_z)の 全日walk-forward(2025-10-28〜2026-07-27, n=267日)は+206.0枚/台 CI[+113.2,+324.6]・勝日率60%で「盤面最強」に見えた。しかし2026-0...

### 17. `rakuen-clean-column-edge-effect-confirmed`
- confidence: `0.90` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-rakuen-section-column-redefinition-and-edge-effect-insights.yaml`
- domain/source: `hall-strategy` / `session-observation`
- trigger: 楽園の設定投入の位置法則性を検証・報告するとき
- summary: section定義を「2列facing pair islandの各列・通路breakなしの単列・S字」=clean(38列)、 「外周(frame, 22列)」「内部通路分断(interior_split, 6列)」「三角形・L字(special, 4列)」 に分類し、clean限定・同日×同機種残差・台単位クラ...

### 18. `mediator-adjustment-trap-games-as-outcome-not-covariate`
- confidence: `0.90` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-rakuen-section-column-redefinition-and-edge-effect-insights.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: パチスロの位置・区画効果を検証する際にgames(回転数)を統制変数として使いたくなったとき
- summary: 楽園clean列の端番効果を検証中、「端の台はgamesが多い区分に偏っている」ことが分かり、 day×model内でgamesを線形統制(残差化)したところ、機械割ppだけでなくBB+RB(ボーナス確率、 遊技者の継続バイアスの影響を受けない指標)まで同じ大きさで符号反転した。ボーナス確率が 回転数統制で反転す...

### 19. `iron-seat-exclusion-in-forward-test-attribution`
- confidence: `0.85` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-instincts.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: 凍結済みprereg結果の実績を答え合わせするとき、鉄台（fixed-effect machine）が選択に含まれている場合
- summary: 2026-07-27の答え合わせで、蒲田7の台2026(+4,100枚)を「本命が当たった」と評価したが、 台2026は briefing_common.IRON_MACHINES に登録済みの鉄台であり、機種が3回変わっても 優遇が続く座席固有の効果である。鉄台の的中は選定アルゴリズムの精度と無関係に 高確率で...

### 20. `comovement-fails-for-single-hall-few-model-boundary-attribution`
- confidence: `0.85` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-rakuen-section-column-redefinition-and-edge-effect-insights.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: 単一ホールで、隣接する2区画/列が同一の投入単位かどうかを日次残差の相関(連動性)で判定しようとするとき
- summary: 楽園のfram/interior_splitセクションが「柱の分断を投入単位として扱っているか」を、 2列の日次残差(同日×同機種平均からの残差)の相関で判定しようとした。素朴な同日×同機種 残差は、同じ機種が比較対象の2列にしか設置されていない場合、残差のゼロ和制約により 片方が上がればもう片方が必ず下がるとい...

### 21. `mitoya-manager-change-regime-confirmed-2026-05`
- confidence: `0.90` | status: `unverified` | date: `2026-07-27` | file: `2026-07-27-mitoya-manager-change-regime-confirmed.yaml`
- domain/source: `hall-strategy` / `session-observation`
- trigger: みとや大森町の推薦・イベントDD分析・過去のバックテスト数値を参照するとき

### 22. `hall-regime-external-event-calendar-methodology`
- confidence: `0.85` | status: `unverified` | date: `2026-07-27` | file: `2026-07-27-hall-regime-external-event-calendar-methodology.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: ホール推薦を出す前、または既存の凍結バックテストルールの根拠が古くなっていないか確認するとき

### 23. `single-day-answercheck-cannot-separate-signal-from-selection-failure`
- confidence: `0.90` | status: `unverified` | date: `2026-07-26` | file: `2026-07-26-mitoya-dd24-answercheck-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 1日分の推薦結果を答え合わせして「シグナルが効かなかった」と結論しそうになったとき
- summary: 2026-07-24のみとや答え合わせで、推薦TOP7は明確に負けた(lift -1330)。 ここで「h_nonjug角1シグナルは効かない」と結論するのは誤り。 バスケット全体(候補となった8台全部)を見ると平均+402でホール平均+70を上回っており、 **信号自体は機能し、TOP-N絞り込みの銘柄選択だけ...

### 24. `mitoya-dd24-recommend-tiebreak-selected-losing-half`
- confidence: `0.85` | status: `unverified` | date: `2026-07-26` | file: `2026-07-26-mitoya-dd24-answercheck-insights.yaml`
- domain/source: `pachinko-visit-strategy` / `session-observation`
- trigger: みとや大森町 h_nonjug 角1バスケット(全8台同点)から台別履歴でtie-breakして推薦するとき
- summary: 2026-07-24(DD24、X_DDS日)のみとや推薦で、h_nonjug角1の8台(全て800点で同点)を 直近X_DDS履歴でtie-breakし、574(東京喰種)・607(SAOⅡ)を最上位に置いた。 実績は574=-5,814(266台中264位)、607=-4,644(260位)で、266台中ワー...

### 25. `rb-probability-decimal-null-on-zero-count`
- confidence: `0.98` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: rb_probability_decimal または bb_probability_decimal / total_probability_decimal に notna() / IS NOT NULL / > 0 のフィルタをかけようとするとき
- summary: `rb_probability_decimal` は `rb_count / games_normalized` から作られる派生列だが、 `rb_count == 0` の行では NULL になる（9ホール全てでNaN率とRB0回率が完全一致、 rb_count>0でNULLの行は0件）。`bb_probabi...

### 26. `machine-layout-single-snapshot-breaks-across-renovation`
- confidence: `0.97` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: machine_layoutを使って過去データに位置(section/rank_from_*)を結合するとき、または改装・島配列変更があったホールの位置分析を行うとき
- summary: machine_layoutは日付次元を持たないため、改装で位置定義が変わると新しい位置が 過去データに遡って適用される。楽園蒲田の2026-07-06の改装でsection定義が 書き換わり(2223-2240→2225-2242等)、技術介入の端番効果が+1.127pp→+0.211pp(ns)に 変化した。...

### 27. `uniform-physical-threshold-across-categories-produces-false-anomalies`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-rakuen-column-merge-and-games-corruption-audit-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: 確率・機械割等に「物理的にありえない」閾値を設定して、複数の機種カテゴリを横断して異常値/破損データを検出しようとするとき
- summary: 本セッションで2回、同じ失敗パターンが起きた。(1) 機械割>200%かつdiff>1000で 「破損」を検出→14,554行のうち89%がAT機で、AT機のボーナス/AT当選確率(1/15〜150)は ジャグ/ハナ/沖スロ(1/300+)と2桁違うため単に正常な高分散日だった。(2) ボーナス確率 >1/20で...

### 28. `diff-coins-confounds-setting-with-turnover`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 差枚(diff_coins_normalized)ベースで位置・人気度など回転数に影響しうる変数の効果を測るとき
- summary: diff = 3 * G * (payout - 1) なので、機械割が同じでもG(回転数)が違えば差枚は動く。 蒲田7角番1の検証で、差枚ベースの-162枚のほぼ全部(-124枚が共分散差、-37枚がG数差、 機械割の寄与はわずか-0.5枚)が「角1は+624G多く回されている」という回転数差の 帰結だった。角...

### 29. `games-filter-is-selection-on-setting`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: games_normalized >= N / min_games フィルタを集計前にかけて、区画・軸・カテゴリの成績や設定シグナルを測るとき
- summary: 「低設定→早く見切られる／高設定→長く回される」という基本法則により、games は 設定の下流にある（独立指標RBで確認: 台レベル相関 ハナ+0.94/ジャグ+0.69、 日レベルでジャグの稼働帯別RBz が -1.33→+0.97 と単調）。したがって `games >= N` のフィルタは低設定の日を選択...

### 30. `mwu-cannot-detect-tail-only-edges`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-mwu-tail-edge-and-weight-desync-insights.yaml`
- domain/source: `analysis-methodology` / `session-analysis`
- trigger: 台×日の差枚でグループAとBを比較し、MWU/Kruskal-Wallisが非有意だったとき。特に平均差はあるのにp値が大きいとき
- summary: 2026-07-24、みとや大森町の h_nonjug 角番1（X_DDS日）を post-regime で評価した際、 MWU が p=0.522 で非有意だったため「角番効果は消えた/解像できない」と一度結論した。 これは**誤りだった**。同じデータを分位点と裾確率で測り直すと明確な差が出た。 | X_DD...

### 31. `deathwatch-tests-drift-from-baseline-not-zero-effect`
- confidence: `0.92` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 既に確認済みのセオリー(角番・端番等の位置効果、DD効果など)が今も有効か継続監視する仕組みを設計するとき
- summary: みとやの角番1シグナルは16か月間+0.327z(RB確率z)で安定し、2026-04-27に一度きり 終わった(店長交代と一致)。これは「2-3ヶ月で入れ替わる循環レジーム」ではなく 「長く効く法則がある日死ぬ」という形。循環モデルなら常時レジーム推定が必要だが (60日窓でも検出まで時間がかかり、2-3ヶ月の...

### 32. `verify-grouping-unit-via-leave-group-out-correlation`
- confidence: `0.90` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-rakuen-column-merge-and-games-corruption-audit-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 分析の集計単位（島・区画・カテゴリ等）を統合すべきか分割すべきか判断に迷うとき
- summary: 楽園のsectionは背中合わせ2列を1つに統合していた欠陥が見つかり63列に分割したが、 「まとめることで物理配置ではない真の設定投入単位が見えるのでは」という対立仮説が 出た（ユーザー指摘）。これをleave-island-out残差の相関で検定した。単純な同日×同機種 残差は、その機種が島内を独占していると...

### 33. `check-existing-per-machine-spec-validator-before-flagging-anomaly`
- confidence: `0.90` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-rakuen-column-merge-and-games-corruption-audit-insights.yaml`
- domain/source: `feedback-methodology` / `session-observation`
- trigger: 特定機種のボーナス/AT確率が異常に高い/低いと感じ、独自にデータ品質問題や物理故障の調査を始めようとするとき
- summary: ゴッドイーター リザレクションとスマスロ北斗の拳のボーナス確率がホール間で 食い違って見えたため、「台番号への物理的な結線ミス」という仮説を立てて 1ラウンド分の検証（台番号の連続日数・機種入替をまたぐ継続性の検定）を 丸ごと消費した。実際には eda/at_semantics_validator.py に両機種...

### 34. `bb-rb-column-can-be-duplicate-not-just-mismatched`
- confidence: `0.90` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-rakuen-column-merge-and-games-corruption-audit-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: bb_count/rb_countのどちらかがat_semantics_validatorでPASS、もう片方がfailと判定された機種で、ホールごとに観測確率が大きく食い違うとき
- summary: ゴッドイーター リザレクションでbb+rb合算のボーナス確率がホール間で最大9倍 食い違い、「ホールごとに違う当選種別をbb/rbに記録している」という複雑な 仮説を立てた。実際にrb_countを単独で見ると全9ホールが1/334〜540とスペック 範囲にほぼ収まって一致し、bb_countだけが原因だった：5...

### 35. `hit-rate-measures-volatility-not-setting`
- confidence: `0.90` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: hit率・勝率（P(差枚>0)や104%率）で区画・機種・軸の設定の良さを比較しようとするとき
- summary: hit率 = P(差枚>0) は平均だけでなく分布の歪みに依存する。AT機は「多くの日は小さく 負け、稀に大きく勝つ」右歪み分布なので、同じ期待値でも P(差枚>0) が低く出る。 ジャグ・ハナハナは対称に近く高く出る。楽園§1のHot/Coldを63列で測り直すと hit差 vs 差枚SD = -0.490、h...

### 36. `scoring-weights-must-have-single-source-of-truth`
- confidence: `0.90` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-mwu-tail-edge-and-weight-desync-insights.yaml`
- domain/source: `implementation` / `session-analysis`
- trigger: 推薦スコアラとそのバックテストが別ファイルにあるとき。重みや係数を変更しようとしたとき
- summary: `eda/mitoya_recommend.py` の `_score_machine`（if分岐で逐次加算）と `eda/mitoya_recommend_backtest.py` の `CURRENT_WEIGHTS`（特徴量ベクトル×重みの内積）に **同じ数値が別々にハードコード**されていた。 実害が2...

### 37. `known-duplicate-fix-does-not-rule-out-a-third-copy`
- confidence: `0.85` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-mwu-tail-edge-and-weight-desync-insights.yaml`
- domain/source: `implementation` / `session-analysis`
- trigger: 同じ値/ロジックが2箇所に重複していたバグを直したあと。特に「重み一本化」「single source of truth化」を完了したと思ったとき
- summary: `_score_machine`(recommend.py) と `CURRENT_WEIGHTS`(backtest.py) の重み二重定義を 一本化し、実データ218行×DD5パターンでスコア一致を自分で数値検証して0件不一致を確認した。 「直った」と判断してCodexに read-only レビューを依頼し...

### 38. `metric-choice-decides-what-signal-is-visible`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-analysis`
- trigger: 台×日のシグナルを検定・比較するとき。差枚(diff_coins_normalized)を指標に選ぼうとしたとき
- summary: 2026-07-23、非定常性検定を全9ホールで回した際、系列を全て差枚ベースのエッジで作っていた。差枚 = G数 × 3 × (機械割 - 1) なので、当日どれだけ回ったかという設定と無関係な分散が丸ごと混入する。スロットは6段階設定であり、見るべきは設定差。 同一の選択ルールに対し指標だけを差枚 / 機械割...

### 39. `null-hypothesis-must-preserve-serial-correlation`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-implementation`
- trigger: 時系列の非定常性・変化点・レジームを検定するとき。帰無分布をシャッフルで作ろうとしたとき
- summary: 台選択ルールの日次エッジには正の系列相関がある（同じ台が連日選ばれ続けるため）。この相関だけでローリング窓平均は勝手に振れる。帰無分布をiidシャッフルで作ると相関が消えて分布が狭くなりすぎ、**ただの自己相関がレジーム変化として有意に出る**。 検定したいのは「窓平均の振れがノイズを超えるか」なので、帰無仮説側...

### 40. `null-result-requires-power-measurement`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-analysis`
- trigger: 検定が帰無を棄却しなかったとき。『効果なし』『レジームなし』と結論したくなったとき
- summary: 「棄却できない」は「効果が無い」ではなく「あっても見えない」かもしれない。区別するには検出力が要る。実データの日次系列（＝本物のノイズ）に振幅±A・周期75日の矩形波を人工的に注入し、p<0.05 になる最小振幅を測ればよい。 2026-07-23の検証では、この測定で判定が分かれた。蒲田7・雑色は±150枚以上...

### 41. `preregistration-breaks-in-sample-self-reference`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-methodology` / `session-implementation`
- trigger: instinct/仮説を検証したいとき。バックテストの結果を『確証』として扱いたくなったとき
- summary: document/instincts/ が1400本近くありながら confirmed=0 だった原因は、「過去データを見て見つけたルールを同じ過去データで確認する」自己参照ループから一度も抜けていなかったこと。バックテストは「未来データに効かないルールを実弾の前に落とすフィルタ」としてのみ価値があり、それ自体は...

### 42. `signal-existence-does-not-imply-predictability`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-methodology` / `session-analysis`
- trigger: 分散分解や台×日シグナルの大きさを見て『予測できるはず』と判断しそうになったとき
- summary: eda/variance_decomposition.py の分散分解で、蒲田7は9ホール中最大の台×日シグナル(2.89pp≈400枚/日相当)を持つのに、その蒲田7で組んだ複数の履歴ベース事前登録ルール(RB確率上位・hit104率上位)はすべて負エッジ(-17.9〜-58.6枚/台、289日・867選択)だ...

### 43. `pooled-null-does-not-imply-segment-null`
- confidence: `0.90` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-mistake`
- trigger: 全期間・全セグメントをプールした平均で効果が出ず、『この軸は効かない』と結論しそうになったとき
- summary: 2026-07-23、蒲田1のセクション端効果が全カテゴリで null だったことから「蒲田1は位置軸そのものが効かない」と書いたが、これは誤りだった。測ったのは全期間・全セクション・全日をプールした平均に過ぎない。セグメントで符号が逆なら（例: イベント日プラス、通常日マイナス）プール平均はゼロになる。 これは...

### 44. `within-model-residual-controls-lineup-confound`
- confidence: `0.90` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-implementation`
- trigger: 位置効果・末尾効果などを機種が不均質なカテゴリ（AT一般など）で測るとき
- summary: AT一般は機種構成が不均質（蒲田7で58機種、楽園で134機種）。同日・同カテゴリ平均からの残差では「角に置かれている機種がそもそも機械割の低い機種だった」という交絡を除去できない。同日**かつ同機種**の平均を引けば機種差が消える。 また差枚だとカテゴリ間で分散スケールが5倍近く違い（蒲田7: AT一般 SD=...

### 45. `machine-layout-is-undated-snapshot`
- confidence: `0.90` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `data-quality` / `session-analysis`
- trigger: machine_layout の位置データ（section / rank_from_*）を使った分析をするとき。ホールの工事・リニューアルを把握したとき
- summary: machine_layout の列は machine_number / hall_name / x / y / display_y / section / section_min / section_max / rank_from_min / rank_from_max / rank_from_aisle で、*...

### 46. `cross-model-raw-value-ranking-conflates-spec-and-setting`
- confidence: `0.90` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-bug-discovery`
- trigger: ジャグラーシリーズなど複数機種にまたがるRB確率/BB確率の生値でランキング・スコアリングするとき
- summary: mitoya_jug_eventdd_rb_top3(生値でRB確率上位3台を選ぶルール)をバックテストするとedge+63.3枚(CI [-95.1,+219.3])止まりだったが、同一機種内で標準化してから順位付ける版(hist_mean_rb_prob_model_z)に直すとedge+212.5枚(CI...

### 47. `baseline-including-picks-shrinks-observed-edge`
- confidence: `0.90` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-methodology` / `session-bug-discovery`
- trigger: 選択台の実績を同一母集団の平均と比較してエッジを測るとき。特に選択比率(pick_share)が母集団の大半を占めるルールで
- summary: 角番1回避ルール(k7_jug_kakuban1_avoid、universeの93%を選ぶほぼ全選択)で、baseline(universe平均)に対するedgeは+10.8枚(事前基準+50未達で破棄)だったが、pickされなかった台(角1のみ)との対比であるedge_vs_excludedを計算すると+15...

### 48. `codex-rescue-cannot-execute-arbitrary-inline-instructions`
- confidence: `0.90` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: codex:codex-rescue subagent に読み取り専用レビュー以外の柔軟な指示(『今すぐ自分で読んで』等)を送ろうとするとき
- summary: Codexエージェントがバックグラウンドタスクの完了を待つだけで最初の応答を終えたため、SendMessageで「今すぐ自分でファイルを読んでレビューしろ」と再指示したが、「自分はCodex task呼び出し1回に限定されたラッパーであり、リポジトリファイルを直接読むことも自分でレビューすることも指示では変更でき...

### 49. `position-policy-is-hall-and-category-specific`
- confidence: `0.85` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `hall-strategy` / `session-analysis`
- trigger: 「機種が変わっても共通する法則があるはず」と考えたとき。位置ポリシーをホール横断で仮定したくなったとき
- summary: 「店側が日々変化する機種に合わせて毎回設定を考えるのは労力が大きすぎる。だから機種が変わっても共通する法則があるはず」という労力コスト論を検証した。この論拠が支持するのは機種個別のスコアリングではなく**機種を問わない配置ポリシー**なので、位置効果をカテゴリ横断で測れば直接検証できる。 結果はホールで分かれた。...

### 50. `regime-breaks-come-from-hall-events-not-cycles`
- confidence: `0.85` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `hall-strategy` / `session-analysis`
- trigger: 「ホールが2〜3ヶ月周期で法則を入れ替えている」と仮定したとき。レジーム追随の仕組みを作ろうとしたとき
- summary: 当初の仮説は「ホールは2〜3ヶ月の短いスパンで法則を入れ替えている」だった。実際に観測されたのは違う形だった。 みとやジャグの角番1優位は **2025-01 から 2026-04 まで16か月間 +0.327z [+0.296, +0.360] で安定**し、2026-04-27 に消失した（後期 +0.013...

### 51. `hall-data-coverage-must-be-checked-before-comparison`
- confidence: `0.85` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `data-quality` / `session-mistake`
- trigger: 複数ホールの結果を並べて比較するとき。分析期間を --start で指定するとき
- summary: 2026-07-23の検証で --start 20240101 を指定していたが、実際のデータは全ホール2025年以降だった。特に**蒲田7は2025-07-07開始で375日しかなく**、他ホール（550日前後）より検出力が約3割低い条件で測っていた。結論は変わらなかったが、蒲田7の null は他ホールの n...

### 52. `bootstrap-ci-must-block-for-repeated-machine-selection`
- confidence: `0.85` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-methodology` / `session-bug-discovery`
- trigger: 同一台/同一エンティティが複数日にまたがって繰り返し選ばれるバックテストの信頼区間を計算するとき
- summary: Codexレビュー(セカンドオピニオン)で指摘。scoreベースのルールでは、履歴が良い台は複数日連続で選ばれやすく、日次エッジの系列には正の相関がある。iidな日単位bootstrapはこの相関を無視して有効サンプル数を過大評価し、CIが実際より狭くなる。7日moving block bootstrapに変更し...

### 53. `forward-test-plan-needs-append-only-ledger-not-just-hash`
- confidence: `0.85` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `development-workflow` / `session-bug-discovery`
- trigger: 未来日の選択を事前に確定させ、後から改ざんされていないことを保証したいとき
- summary: Codexレビューで指摘(HIGH)。PreRegistration.freeze_hash()はルール定義(hypothesis, score, top_n等のパラメータ)の同一性しか保証しない。plan(実際に選ばれた台番号のリスト)を結果を見た後に書き換えても、参照している事前登録ファイル自体が変わっていな...

### 54. `machine-number-history-must-be-restricted-to-current-machine-name`
- confidence: `0.85` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `data-engineering` / `session-bug-discovery`
- trigger: 台番号(machine_number)を集計キーにして履歴のスコアを計算するとき。長期lookback窓を使うほど注意
- summary: Codexレビューで指摘。実データで検証したところ、みとや大森町店で直近30日窓に2機種以上入った台番号が266台中39台、蒲田7で715台中104台存在した。さらにジャグ機同士(スコアリング対象の同一フラグ内)の入替に絞っても、みとや58件・蒲田7 110件(台×窓の延べ数)が確認された。台番号のみのgroup...

### 55. `mitoya-kakuban1-signal-died-20260427`
- confidence: `0.80` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `hall-strategy` / `session-analysis`
- trigger: みとや大森町店のジャグ角番セオリーを使おうとしたとき。みとやの推奨台を出すとき
- summary: みとやジャグの角番1（rank_from_aisle=1、実運用上は横列2台のセオリー）は、選択ルールと無関係に台そのものの残差で見ても長期に安定していた。 前期 2025-01〜2026-04（485日）: RB z残差 +0.327z [+0.296, +0.360] / 機械割残差 +2.261pp [+2...

### 56. `rb-vs-bb-setting-sensitivity-by-machine-type`
- confidence: `0.90` | status: `unverified` | date: `2026-07-21` | file: `2026-07-21-thunder-v-dd-weekday-null-and-rb-vs-bb-methodology-insights.yaml`
- domain/source: `setting-inference-methodology` / `user-feedback`
- trigger: Aタイプ・技術介入機で設定判別の指標(RB確率/BB確率/合算確率)を選ぶとき
- summary: サンダーVのスペック表で検証: BB確率は設定1(1/277.7)→設定6(1/264.3)で変動幅わずか5.1%、RB確率は設定1(1/434.0)→設定6(1/313.6)で変動幅38.4%。BBはほぼ設定不問(純ノイズに近い)。合算確率(BB+RB)にBBを混ぜることはサンプル数を稼ぐ一方で、本来RBが持つ...

### 57. `umineko2-payout-rate-skill-contamination-methodology`
- confidence: `0.85` | status: `unverified` | date: `2026-07-21` | file: `2026-07-21-umineko2-multihall-dd-weekday-and-monthly-trend-insights.yaml`
- domain/source: `setting-inference-methodology` / `user-feedback`
- trigger: A+ARTタイプ・技術介入機で機械割の変化を設定投入シグナルとして解釈するとき
- summary: うみねこのなく頃に2はA+ARTタイプのスマスロ(技術介入機)。ユーザー指摘: 「うちての技術によって機械割が数%増減する」。実際、楽園蒲田の直近1ヶ月分析でRB(z=+1.83)/BB(z=+0.80)という弱い改善に対し、機械割は+2.1ptという大きな上昇を示し、乖離が観測された([[umineko2-ra...

### 58. `umineko2-games-residual-not-setting-signal`
- confidence: `0.85` | status: `unverified` | date: `2026-07-21` | file: `2026-07-21-umineko2-multihall-dd-weekday-and-monthly-trend-insights.yaml`
- domain/source: `setting-inference-methodology` / `session-observation`
- trigger: 回転数(games_normalized)のDD別・曜日別残差を高設定投入シグナルとして解釈しそうになったとき
- summary: うみねこのなく頃に2、蒲田7の曜日別回転数z検定で水(z=-3.91)・金(z=-3.41)・木(z=-2.53)が強い負の逸脱を示したが、これは単に平日の来店客数が少ないという稼働構造を反映しているだけで、高設定/低設定投入とは無関係。差枚・機械割・RB・BB・合算の残差分析と回転数の残差分析を同列の「設定シグ...

### 59. `umineko2-hall-baseline-per-hall-methodology`
- confidence: `0.85` | status: `unverified` | date: `2026-07-21` | file: `2026-07-21-umineko2-multihall-dd-weekday-and-monthly-trend-insights.yaml`
- domain/source: `setting-inference-methodology` / `user-feedback`
- trigger: 複数ホールでベースライン(RB/BB/合算/機械割等)を比較・集計するとき
- summary: うみねこのなく頃に2、8ホールのRB/BB/合算ベースライン比較で、ベルシティ雑色がRBでは中〜下位(93.9%、公称設定1相当比)なのにBB(97.8%、8ホール中1位)・合算(95.9%)では単独トップという順位の逆転が見つかった。ユーザー指摘: 「データカウンターの集計方法によって、計算が微妙に異なっている...

### 60. `thunder-v-dd-weekday-high-setting-negative-4halls`
- confidence: `0.85` | status: `unverified` | date: `2026-07-21` | file: `2026-07-21-thunder-v-dd-weekday-null-and-rb-vs-bb-methodology-insights.yaml`
- domain/source: `multi-hall-machine-dd-weekday-analysis` / `session-observation`
- trigger: サンダーV(または他Aタイプ機)でDD別・曜日別の高設定投入日を検討するとき
- summary: みとや・楽園蒲田・蒲田7・蒲田1の4ホール、サンダーV(2026/3/2導入〜7/20、総計789万G)についてRB確率・合算確率(BB+RB)の両方でDD別・曜日別z検定を実施。全152回検定(DD31×4ホール+曜日7×4ホール)で|z|>=2.0となったのは8件、ランダム期待値7.6件(152×0.05)と...

### 61. `codex-agmsg-must-use-git-bash-on-windows`
- confidence: `0.99` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-agmsg-kamata7-dashboard-insights.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: Codex Desktop on WindowsからagmsgでClaude Codeと連絡するとき
- summary: Kamata7 dashboard計画でClaude Codeとagmsg連携した際、Codex側で `bash ...` をそのまま実行すると `C:\Users\apto117\AppData\Local\Microsoft\WindowsApps\bash.exe` 経由のWSL bashに流れ、`$HOM...

### 62. `agmsg-on-windows-use-git-bash-not-windowsapps-bash`
- confidence: `0.98` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: when sending agmsg messages from Codex Desktop on Windows
- summary: Using the WindowsApps `bash.exe` path can route the command into the wrong shell and produce empty or misleading agmsg sends. n_observations: 1 data scope: t...

### 63. `v12b-composite-score-no-calibration`
- confidence: `0.98` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-v12b-calibration-failure-insights.yaml`
- domain/source: `ml-evaluation` / `walk-forward-calibration-60days`
- trigger: スコアリングモデルの予測結果をTop-Nで絞り込むとき、またはcompositeスコアに基づく台選択推薦を行うとき
- summary: v12b_debut_multiplier_halfのcompositeスコアと実際の104%超え確率の対応関係を、60日間のwalk-forward評価（42,840行）で検証した。 スコア十分位別の104%超え率はD0=32.9%からD9=32.8%まで実質フラットで、スコアの高低が的中確率をほぼ予測しない。...

### 64. `mitoya-section-was-two-rows-merged`
- confidence: `1.00` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-section-split-and-corner-effect-insights.yaml`
- domain/source: `data-infrastructure` / `session-discovery`
- trigger: みとやのセクション定義・角番分析・rank_from_aisle を扱うとき
- summary: Heatmap/mitoya_omorimachi_floor_coordinates.csv で 557-590 のような34台セクションが、実際には2つの物理列（y=29: 557-573, y=28: 574-590）を1セクションにまとめていた。これにより rank_from_aisle が列単位ではなく...

### 65. `segment-determination-must-come-first`
- confidence: `0.98` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `analysis-methodology` / `session-design`
- trigger: 新ホールでEDAを開始するとき / セグメント未確定の状態で変数効果を分析しようとするとき
- summary: 蒲田7で全体集計のA機Top3(d3/d4)とN機Top3(d6/d8)が逆相関(ρ=-0.418)になるSimpson's Paradoxが発生。 セグメント未分割の状態で「末尾Xが強い」と主張しても、フロア/機種タイプ/セクションサイズの交絡で無意味になる。 1. フロア分割（複数フロアなら必須） 2. A/...

### 66. `lookahead-detection-by-reimplementation`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-lookahead-and-pipeline-insights.yaml`
- domain/source: `ml-evaluation` / `bug-fix`
- trigger: walk-forward検証で有望な結果が出たとき / リランキングやフィルタの効果を検証するとき / scored DataFrameの列を後処理で使うとき
- summary: 2026-06-26 Track D。seg_percentileリランキングの初回検証で+108枚/日（p=0.000003）という 高度に有意な結果が出た。しかしpool_n sweepで別実装を走らせたところ結果が再現せず、 原因を追ったらstrength_weightの計算に当日の `diff_coins...

### 67. `v12-debut-multiplier-machine-name-not-number`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-v12-debut-multiplier-walkforward-insights.yaml`
- domain/source: `implementation` / `bug-fix`
- trigger: debut_dateやpre_existingを計算するとき / 機種の初出日をgroupbyで算出するとき
- summary: 2026-06-26 V12実装時のバグ。初回walk-forwardでV11/V12a/V12bの全指標が完全一致。 `train.groupby("machine_number")["date_dt"].min()` でdebut_dateを計算していた。 同じ台番号に異なる機種が入れ替わっても（新台入替）、...

### 68. `debut-181plus-definition-caveat`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-grouping-debut-event-insights.yaml`
- domain/source: `data-definition` / `session-observation`
- trigger: 181日+フェーズの分析結果を解釈するとき / 定番台の定義を確認するとき
- summary: 2026-06-26 セッションで確認。debut_phase分析ではpre_existing=Trueの機種を除外している。 181日+ = DB開始日（蒲田7: 2025-07-07）以降に導入され、181日以上経過した機種 pre_existing（DB開始日に既に存在していた機種）は除外済み 蒲田7の場合...

### 69. `infer-lr-must-use-x-coordinate`
- confidence: `0.99` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-lr-reversal-bug-and-v7-revalidation-insights.yaml`
- domain/source: `data-engineering` / `bug-discovery-and-fix`
- trigger: LR分割ロジックを実装・修正・レビューするとき
- summary: `_infer_lr()` は台番号の中央値でLRを分割していた（小さい方=L、大きい方=R）。 しかし蒲田7では島ごとに台番号の並び方向が反転する（奇数列は左→右、偶数列は右→左）。 結果として2Fの55.6%、3Fの57.7%のセクションで物理的な左右が逆転していた。 修正: X座標の中央値でLRを判定する。...

### 70. `walkforward-scoring-is-rule-based-not-ml`
- confidence: `0.99` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-classify-seg-db-flag-insights.yaml`
- domain/source: `ml-methodology` / `session-discussion`
- trigger: Walk-forward scoringモデルの位置づけを説明するとき
- summary: v1-v6のWalk-forward scoringモデルは手動設計のコンポーネント（c1-c6, hist特徴量）を 手動設定のウェイトで線形結合するルールベースのスコアリングシステム。 学習アルゴリズム・損失関数・パラメータ最適化プロセスが存在しない。 Walk-forwardは評価フレームワークであり、学習...

### 71. `hit100-equals-winrate-redundancy`
- confidence: `0.99` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-walkforward-v6-threshold-segment-insights.yaml`
- domain/source: `ml-feature-engineering` / `mathematical-identity`
- trigger: payout閾値100%を特徴量候補に含めるとき
- summary: `payout >= 100%` は `(games*3 + diff) / (games*3) >= 1.0` すなわち `diff >= 0` と等価。 これは勝率（winrate = (diff > 0).mean()）と同一の指標であり、独立した情報を持たない。 Walk-forwardで hist_wi...

### 72. `recommendation-powershell-encoding-required`
- confidence: `0.99` | status: `unverified` | date: `2026-06-21` | file: `2026-06-21-recommendation-top50-workflow-insights.yaml`
- domain/source: `development-workflow` / `session-observation`
- trigger: 日本語を含むPythonスクリプトの出力をターミナルで確認するとき
- summary: Bash toolで日本語を含むPythonスクリプトを実行すると、出力がmojibake（文字化け）になる。 PowerShellで `$env:PYTHONIOENCODING = "utf-8"` を設定してから実行すると正常に表示される。 日本語出力を含むPythonスクリプトは以下で実行: $env:P...

### 73. `recommendation-machine-master-schema`
- confidence: `0.99` | status: `unverified` | date: `2026-06-21` | file: `2026-06-21-recommendation-top50-workflow-insights.yaml`
- domain/source: `data-pipeline` / `session-observation`
- trigger: machine_masterテーブルからA機種フラグを取得するとき
- summary: machine_masterテーブルのカラム構成: machine_name_normalized（キー） jug_flag, hana_flag, oki_flag, bt_flag display_names, official_name, created_at, updated_at machine_num...

### 74. `recommendation-db-path-kamata7-actual`
- confidence: `0.99` | status: `unverified` | date: `2026-06-21` | file: `2026-06-21-recommendation-top50-workflow-insights.yaml`
- domain/source: `data-pipeline` / `session-observation`
- trigger: 蒲田7のDBを読み込むとき
- summary: db/kamata7.db は0Bの空ファイル。実データは db/マルハンメガシティ2000-蒲田7.db（55.73MB）に格納されている。 前回セッションでも同じミスが発生しており、kamata7.dbを開いてテーブルが見つからないエラーが出た。 蒲田7のデータを読む場合は必ず `db/マルハンメガシティ20...

### 75. `kakuban-alternating-section-reversal-bug`
- confidence: `0.99` | status: `unverified` | date: `2026-06-20` | file: `2026-06-20-recommendation-scoring-insights.yaml`
- domain/source: `data-pipeline` / `user-correction`
- trigger: 蒲田7の角番（kakuban）を計算・使用するとき
- summary: 蒲田7の島はメイン通路から見て順方向・逆方向が交互に並んでいる。 物理座標（generate_kamata7_coordinates.py）のstep_xで確認: step_x=+1の島: 台番号min側が通路側 → rank_from_min = 角番（正しい） step_x=-1の島: 台番号min側が奥側...

### 76. `dd-band-priority-categorization`
- confidence: `0.98` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-kakuban-dd-band-analysis-findings.yaml`
- domain/source: `data-categorization-design` / `session-implementation-requirement`
- trigger: DD値が複数のカテゴリに該当するとき、優先順位で一意ラベル化
- summary: dd_band 分類で event（1, 10, 20, 30）が他帯と重複。 集計キーの一意性のため、優先順位で単一ラベル化。 1. 優先順位の定義 Tier 1: event（dd in [1, 10, 20, 30]） Tier 2: early（dd in 1-10） Tier 3: mid（dd in...

### 77. `normalize-segment-frame-essential-columns`
- confidence: `0.98` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-kakuban-section-lr-analysis-insights.yaml`
- domain/source: `eda-implementation-pattern` / `session-debugging`
- trigger: セグメント別フレームを作成時、必ず dd, rank_from_min, section_size_group を生成
- summary: 蒲田7分析時、_build_segment_views() で返すフレームに `dd` カラムが存在せず、後続処理で KeyError が発生。 _normalize_segment_frame() を呼び出して、日付から dd を生成し、section_size から section_size_group を導...

### 78. `kamata7-event-day-complete-definition`
- confidence: `0.98` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-kamata7-theory-doc-and-eventday-fix-insights.yaml`
- domain/source: `pachinko-data-engineering` / `user-correction`
- trigger: 蒲田7または蒲田1のイベント日を定義・参照・計算するとき
- summary: `eda/core.py` の `HALL_EVENT_DIGITS` にDD21が欠落、月末がハードコード(30,31)、 強ゾロ目(MM=DD)が `is_x_day` に未統合だった。ユーザーが複数回指摘しても 繰り返し不完全な定義が使われていた。2026-06-19に修正。 正しい定義: 7のつく日: D...

### 79. `kakuban-colsize-eda-pending-rerun`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-correction-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 今日（2026-06-17）の colsize EDA 結果（short/medium/long のbin別kakubanパターン）を選台や特徴量設計に使おうとするとき
- summary: 2026-06-17 午前: kamata7_kakuban_colsize_eda.py の column_size 計算が X座標集計ベースで定義されており、section 角番の colsize 分類としては軸がずれていた。 → 再実行を宣言（use-禁止ブロック）。 2026-06-17 同日: sect...

### 80. `kakuban-colsize-pending-rerun-resolved`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-newresults-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 2026-06-17 の colsize EDA 再実行ブロック（kakuban-colsize-eda-pending-rerun）の状態を確認するとき
- summary: 2026-06-17 午前: `kamata7_kakuban_colsize_eda.py` の column_size が **X軸集計ベース（誤り）** で定義されており、bin の境界も台集合も実態と異なっていた。 → `2026-06-17-kakuban-colsize-correction-insi...

### 81. `mitmweb-exe-path`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: python -m mitmweb でモジュールが見つからないエラーが出るとき
- summary: `python -m mitmweb`は`No module named mitmweb`エラーになる。 mitmproxyのエントリーポイントは`Scripts/mitmweb.exe`として提供される。 C:\Users\<user>\AppData\Local\Python\pythoncore-3.14-...

### 82. `arm64-apk-x86-emulator-incompatible`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: x86_64エミュレーターにarm64ネイティブライブラリを使うアプリを動かそうとするとき
- summary: `split_config.arm64_v8a.apk`をx86_64エミュレーターに含めると `INSTALL_FAILED_NO_MATCHING_ABIS`エラー。 除外すると`GifInfoHandle.<clinit>`でクラッシュ（ネイティブライブラリが見つからない）。 x86_64エミュレーターでは...

### 83. `floor-column-size-definition-correction`
- confidence: `0.98` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-correction-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 列の台数でグルーピングする分析を設計・実装するとき、または座標CSVからセクションサイズを計算するとき
- summary: 2026-06-17: kamata7_kakuban_colsize_eda.py で column_size を 「同じX座標を持つ台数（coords.groupby("X").size()）」で定義していたが誤り。 例：X=1 に12台いても、2001-2010（10台）と別セクションの2台が 同じX位置に...

### 84. `android-user-cert-app-trust`
- confidence: `0.98` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: Androidアプリのhttps通信をmitmproxyで傍受しようとするとき
- summary: mitmproxyのCA証明書をAndroidにインストールしてもChromeブラウザの通信しか傍受できない。 Android 7以降、ネイティブアプリはユーザーインストールのCA証明書を無視する仕様になっている。 ブラウザ通信は傍受できるが、アプリは傍受できないと認識する 解決策は3択：(1)エミュレーターにシ...

### 85. `goal-prompt-4000char-limit`
- confidence: `0.99` | status: `unverified` | date: `2026-06-16` | file: `2026-06-16-when-which-backtest-insights.yaml`
- domain/source: `workflow-codex-handoff` / `user-instruction`
- trigger: Codexへの/goalプロンプトを作成するとき
- summary: 2026-06-16セッションでユーザーから明示的に指示。 初稿は不要な詳細（バリデーションリスト・例外ケース列挙）が多かった。 既存ファイルから流用する関数名を明示すれば実装詳細の記述を省略でき、 1500〜1800文字程度に圧縮しても Codex が迷わず実装できる。 既存流用関数名を明示して詳細記述を省く...

### 86. `daily-hall-summary-date-features-null-bug`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda` / `session-observation`
- trigger: daily_hall_summary の day_of_week / last_digit / is_x_day を使った分析をするとき
- summary: `date_info_calculator.py` は全日付で実行されておらず、`daily_hall_summary` の `day_of_week`, `last_digit`, `is_x_day` 等は443日中わずか3日分しか入っていない。 例：レイトギャップ 土曜 n=422（修正前）→ 24,850...

### 87. `rb-probability-juggler-hokuto-spec`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-rb-probability-analysis-insights.yaml`
- domain/source: `machine-spec` / `user-provided`
- trigger: スマスロ北斗の拳・モンキーターンV・ジャグラー各種のRB確率(rb_probability_decimal)から設定推定を行うとき
- summary: 2026-06-10セッションでユーザーから提供された、ジャグラーシリーズ以外の RB確率ベース設定判別が可能な機種のスペック表。 以下のスペックをRB確率(1/X)から設定推定する際の基準値として使う。 | 設定 | AT初当り確率 | 出玉率 | |---|---|---| | L | ※下パネルが常に点滅...

### 88. `kabaneri-s-and-l-version-distinction`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-machine-hall-fixedeffect-and-banchou4-insights.yaml`
- domain/source: `machine-naming` / `user-clarification`
- trigger: カバネリ・甲鉄城のカバネリについて分析するとき / 「カバネリ海門」という呼称が出てきたとき
- summary: 蒲田7では以下の2機種が両方とも現役（last_date=20260607）で稼働している: | machine_name | n(games>=1000) | baseline hit104 | |---|---|---| | 甲鉄城のカバネリ（無印・S版） | 1648 | 45.8% | | 甲鉄城のカバネ...

### 89. `juggler-series-bonus-probability-spec`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-juggler-spec-and-debut-curve-insights.yaml`
- domain/source: `machine-spec` / `user-provided`
- trigger: ジャグラーシリーズ機種の設定別出玉率・ボーナス確率を参照するとき / kaiwari近似値の精度を機種別に検証するとき
- summary: 2026-06-10セッションでユーザーから提供されたジャグラーシリーズの公称スペック。 hit104%（機械割104%以上）の解釈や、機種ごとの設定推定の基礎データとして使う。 以下のスペック表を機種別の設定推定・閾値較正に使用する。 | 設定 | BIG | REG | 合算 | 出玉率 | |---|---...

### 90. `weekday-digit-nth-single-dim-all-null`
- confidence: `0.99` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: 曜日・台番号末尾・第N曜日を単独次元でスキャンするとき
- summary: daily_hall_summaryのJOINバグを修正した後、21次元 × 9ホールの全スキャンを実施。 以下の単独次元は全ホール・全パターンでTier A/B が1件も出なかった。 以下の単独次元に基づく台選択・設定投入予測は無効として扱う： `day_of_week`（曜日単独） `machine_digi...

### 91. `rb-threshold-monkey-hokuto-confirmed`
- confidence: `0.99` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `rb-signal` / `instinct-confirmed`
- trigger: モンキーターンV・スマスロ北斗の拳のRBシグナルを使うとき
- summary: 旧閾値 1/300=0.003333 ではモンキーターンV設定1（1/299=0.003344）が 閾値を突き抜けて全台シグナル扱いになり、発動率83.7%という汚染が発生した。 北斗の拳設定3（1/297=0.003367）も同様に捕捉されていた（設定3は低設定）。 設定4以上を識別する正しい閾値 = 1/25...

### 92. `firstday-analysis-implementation`
- confidence: `0.99` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-new-machine-firstday-hall-insights.yaml`
- domain/source: `eda-implementation` / `implementation`
- trigger: 新台初日のホール別・機種別パフォーマンスを集計するスクリプトを書くとき / debut_dateを計算するとき
- summary: `machine_detailed_results` に導入初日フラグは存在しないため、 「機種ごとの最古date = debut_date」として計算する。 pre_existing（DBスタート日に既に存在した機種）を除外する必要がある。 実装済みファイル: `eda/hall_firstday_analys...

### 93. `pre-existing-machine-debut-detection`
- confidence: `0.98` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `implementation`
- trigger: days_since_debutを計算するとき / compute_debut_features を使うとき
- summary: `compute_debut_features(df, db_start_grace_days=0)` で実装済み。 蒲田7の検証結果: DB期間: 2025-07-07 〜 2026-06-07 pre_existing 60機種: 全て debut_date == 2025-07-07（DB初日に集中） DB...

### 94. `dd-individual-x-day-confirmation`
- confidence: `0.98` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: DD個別（1-31）スキャンの結果を解釈するとき
- summary: DD個別（1-31）スキャン結果： みとや: DD4=+280, DD14=+234, DD24=+213（全Tier B）→ 4系x_dayと完全一致 蒲田7: DD7=+425 → 7系x_dayと一致 蒲田1: DD7=+194 → 7系の弱い反応 レイトギャップ: DD6=+219 → 6系x_dayと一...

### 95. `anomaly-next-day-mean-reversion`
- confidence: `0.98` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: ANOMALYを翌日の台選択シグナルとして使おうとするとき
- summary: 全ホール合算・翌日1000G以上でのANOMATY後続検証: | 条件 | 翌日avg | 翌日plus率 | |------|---------|----------| | ANOMALY日（score≥2） | +43 | 39.8% | | 通常日（score<2） | +60 | 40.6% | ANOM...

### 96. `mitoya-bari-island-nonexistent`
- confidence: `0.99` | status: `unverified` | date: `2026-06-09` | file: `2026-06-09-mitoya-lag-feature-island-section-insights.yaml`
- domain/source: `data-model` / `session-observation`
- trigger: みとや大森町店で assign_island() を使うとき / island カテゴリ数を確認するとき
- summary: assign_island() の定義: machine_num >= 832 を 'bari' に分類。 みとや大森町店の machine_detailed_results における machine_number の実際の範囲: MIN=501, MAX=815, n=266台 → 815 < 832 のため、...

### 97. `python-windows-encoding-japanese-output`
- confidence: `0.99` | status: `unverified` | date: `2026-06-07` | file: `2026-06-07-island-digit-stability-insights.yaml`
- domain/source: `data-pipeline` / `empirical-validation`
- trigger: WindowsのPython分析スクリプトで日本語を含む出力を行うとき、または機種名・ホール名を表示するスクリプトを書くとき
- summary: Windows環境ではPythonのデフォルトstdoutエンコーディングがCP932（Shift-JIS）のため、 UTF-8で保存された日本語文字列をprintすると文字化けする。 分析スクリプトで機種名・ホール名が文字化けすると誤った名称を正しい名称と誤認し 分析結果の解釈を誤る危険がある。 実害の例： 機...

### 98. `kakuban-not-rank-terminology`
- confidence: `0.99` | status: `unverified` | date: `2026-06-07` | file: `2026-06-07-mitoya-corner-aisle-eda-insights.yaml`
- domain/source: `terminology` / `user-correction`
- trigger: 台配置位置の順位を表現するとき
- summary: ユーザーからの明示的な指摘: 「ランクだと成績順位と混同する。角番という言い方に統一してください」。 本プロジェクトでは: **角番**（kakuban）: メイン通路からの距離による位置順位（rank_from_aisle, rank_from_min） **ランク**: 機械ランキング（machine_ran...

### 99. `machine-name-contamination-in-ml-training`
- confidence: `0.98` | status: `unverified` | date: `2026-06-07` | file: `2026-06-07-mitoya-ml-prediction-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `empirical-validation`
- trigger: みとや（または他ホール）でCatBoostにmachine_nameをCAT_FEATUREとして使うとき
- summary: みとや大森町店 266台中 **204台（76%）** で機種名が変わっていた（515日分データ）。 例: 台501-522は「ダンベル何キロ持てる？」→「バンドリ！」→「甲鉄城のカバネリ 海門(うなと)決戦」のように変遷。 CatBoostに`machine_name`をCAT_FEATUREとして使うとき、...

### 100. `full-2025-window-boundary-safety`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-leakage-audit-insights.yaml`
- domain/source: `methodology` / `code-audit`
- trigger: walk-forward の学習窓 full_2025 が holdout と重複しないか確認するとき、または新しい window_name を追加するとき
- summary: `build_train_window("full_2025", test_start)` は `(REGIME_1_START="2025-07-07", REGIME_2_END="2025-12-31")` を返す。 holdout 期間は `REGIME_3_START="2026-01-01"` 以降。...

### 101. `xday-equals-is-xday-flag`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `hall-specific` / `db-exploration`
- trigger: みとやの x_day bucket を定義または実装するとき
- summary: みとや大森町 DB で is_x_day=1 の日と「day % 10 in {4,7}（4/7/14/17/24/27日）」は 514日間で完全一致（n=102、重複率100%）。 x_day ONLY: 0件、ld4/7 ONLY: 0件。 x_day 判定は `day % 10 in {4, 7}` で計算...

### 102. `poco-diff-is-db-derived`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-analysis-db-insights.yaml`
- domain/source: `poco-data-quality` / `empirical-measurement`
- trigger: ぽこデータの差枚精度を疑うとき・ぽこCSVとDBの差枚を比較するとき
- summary: poco_data_v5.csv の `kamata7_diff` / `kamata1_diff` がアナスロデータと一致するか全期間検証した結果、 K7: 282件中1件不一致、K1: 210件中3件不一致（ほぼ完全一致）。 ぽこの差枚欄はアナスロDB（machine_detailed_results の S...

### 103. `catboost-gpu-ndcg-not-implemented`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-allhall-model-architecture-insights.yaml`
- domain/source: `ml-infrastructure` / `empirical-20260605`
- trigger: when using CatBoostRanker with GPU backend and NDCG objective
- summary: CatBoostRanker に --use-gpu を指定した場合、NDCG 目標が GPU 未実装という警告が出て 計算継続するが、精度が崩壊した： CPU: avg_diff=111.81 GPU: avg_diff=34.73（壊滅的な低下） GPU 経路では CatBoostRanker を除外する。...

### 104. `walrus-operator-parameter-overwrite`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `python-bugs` / `session-observation`
- trigger: Pythonのwalrus演算子 := をif条件の中で使うとき
- summary: `feature_engineering.py` の Feature 8 で以下のコードがあった： if is_train := False: # Placeholder: always use stored stats pass walrus演算子は関数パラメータ `is_train` をローカル変数として `...

### 105. `poco-is-post-hoc-not-realtime`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-forward-strategy-insights.yaml`
- domain/source: `poco-analysis-fundamentals` / `user-correction`
- trigger: ぽこデータを使った戦略・予測を立てるとき
- summary: ぽこ（poco）のデータは「その日の結果が出た後」に発表される事後記録である。 当日朝にぽこを確認して「今日発表された機種を打ちに行く」という使い方は不可能。 | 用途 | 可否 | |------|------| | 当日の台選択 | NG（事後発表のため不可） | | 過去パターンの統計分析 | OK（11ヶ...

### 106. `poco-hall-separation-rule`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-hall-analysis-insights.yaml`
- domain/source: `poco-analysis-workflow` / `user-instruction`
- trigger: ぽこデータをK7・K1両ホールで分析・出力するとき
- summary: 蒲田七（K7）と蒲田一（K1）は戦略・規模・データ品質が根本的に異なる： 規模: K7 月平均69.7機種発表 vs K1 44.9機種（K7の約65%） K7: アニメ系スマスロを幅広く・平日も機種名明示 K1: 戦国乙女4・カバネリ海門などに集中・平日は機種全が「不明」多数 同一機種でもK7とK1で実績が真逆...

### 107. `instinct-contamination-two-types`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-instinct-management-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク修正後に過去のinstinctを評価するとき、または古いinstinctを参照しようとするとき
- summary: 2026-05-31のリーク修正後、過去のinstinctを精査した結果、 汚染の種類によって処置が異なることが判明した（2026-06-01）。 種類1「MLモデル性能値が主体」→ contaminated/ へアーカイブ（無効化） AUC=0.8140、hit@2=98%、precision@2=83% 等の...

### 108. `instinct-scope-taxonomy-rule`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-hall-independence-principle.yaml`
- domain/source: `ml-architecture` / `user-instruction`
- trigger: 新しいinstinctを作成するとき、または既存instinctをインポートするとき
- summary: ホール固有の発見と普遍的な方法論が混在することで、 別ホール分析時に誤った前提が持ち込まれる問題が発生した（2026-06-01）。 add_instinct_scope.py で既存70件に一括追加済み。 新しいinstinctを作成するとき、必ず以下のフィールドを追加する： confidence: 0.XX...

### 109. `hall-specific-findings-never-transfer-to-other-halls`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-hall-independence-principle.yaml`
- domain/source: `domain-strategy` / `user-instruction`
- trigger: 別のホールの分析を始めるとき、または複数ホールにまたがる提案をするとき、または蒲田7の数値を引用するとき
- summary: ユーザーから繰り返し指摘された最重要ルール（2026-06-01 確立）： 「ホール固有ルールが強い。他ホールと比較することに意味がない。」 パチンコホールは独立した経営主体であり、設定投入戦略を共有する理由がない。 他業種でも経営戦略は共有しない（例：A社の販売戦略がB社でも有効とは限らない）。 蒲田7で確認さ...

### 110. `signal-existence-must-precede-ml-design`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-signal-existence-insights.yaml`
- domain/source: `ml-architecture` / `data-analysis`
- trigger: MLモデルの設計・特徴量追加を検討するとき
- summary: signal_existence_plan.py を蒲田7（holdout 150日）で実行した結果： 反復回避：P(top1_{t+1}|top1_t) = 0.098 vs 基準0.10（非有意） ランク自己相関：max |rho|≈0.035（実質ゼロ） (DD,末尾)セル：Bonferroni補正後有意0...

### 111. `grid-search-exposes-narrow-space-artifacts`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: 限定的な探索で見つかったシグナルを全空間に拡張するとき
- summary: lag=14 × 2F_N × digit=8 の発見経緯： 1. is_positive autocorr で raw hit → p_raw=0.00066 2. lag=14 に絞った検定 → FDR=0.026 で有意 3. 全 expert × 全 digit × 複数 lag のグリッド探索 → FD...

### 112. `leakage-check-direction-must-be-inclusion-not-exclusion`
- confidence: `0.99` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-leakage-protocol-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク確認を依頼されたとき、またはget_numeric_features()の出力を確認するとき
- summary: total_diff_coins_focus のリークを複数回の確認依頼にもかかわらず見逃した。 原因は「除外リストに target 列が含まれているか」をチェックしていたこと。 しかし本当に必要なのは「get_numeric_features() が返す全列の生成元を追跡すること」。 間違ったチェック方向： e...

### 113. `total-diff-coins-focus-leakage-root-cause`
- confidence: `0.99` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテストのhit@2が95%超のとき、またはget_numeric_featuresで特徴量セットを変更するとき
- summary: clean holdout監査（2025選定→2026評価）でも hit@2=98-99% が継続したことで調査。 以下の手順でリークを特定した： 1. ナイーブ基準（過去固定Top2）: hit@2=37.8% ≈ ランダム → Top2は日次で変動しており単純暗記ではない 2. 全lag特徴量のSpearma...

### 114. `dd-value-missing-from-features`
- confidence: `0.99` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-evaluation-feature-insights.yaml`
- domain/source: `ml-architecture` / `code-inspection`
- trigger: 特徴量セットを確認・拡張するとき、またはdd_valueを実装するとき
- summary: add_simple_features()（tail_ltr_split_rule_wf.py line 167）の実際の特徴量： 既存（曜日系、追加不要）: weekday（0-6）, weekday_sin, weekday_cos, is_wed weekday_prior_top2_rate, weekd...

### 115. `adjusted-lift-denominator-10-not-9`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_multi_tail_2fn の hit_rate をランダムベースラインと比較するとき
- summary: 蒲田七の末尾は 0-9 の10種類（北斗は末尾4欠番で9台だが、末尾数は10）。 summary.json の `baseline_random = 0.1` がこれを示している。 分母を 9 にすると diff・OR が「baseline 以下」に見えるが、10 にすると「baseline 水準」になる。 |...

### 116. `signal-correlation-json-output-keys`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: signal_machine_correlation_summary.jsonを読み込んで解釈するとき
- summary: 実際の出力JSONのキーは `overall_stats` や `weekday_stats` ではなく、 `signal_or`, `diff_signal_only`, `rb_signal_only`, `fake_tail_check` など。 間違ったキーでアクセスすると None が返って解釈を誤る。...

### 117. `kamata7-floor-classification`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `data-processing` / `session-observation`
- trigger: 蒲田七（マルハンメガシティ2000-蒲田7）のデータをセグメント分類するとき
- summary: machine_detailed_resultsにはフロア情報が直接ないが、台番号でフロアを判定できる。 Heatmap/2F_floor_coordinates_kamata7.csvで確認済み。 machine_number < 3000 → 2F（2001〜2351付近） machine_number >=...

### 118. `correct-segment-classification-floor-atype4`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `data-processing` / `codex-correction`
- trigger: 蒲田七の機台をセグメント分類（2F_N/3F_N/3F_A/2F_A）するとき
- summary: 台番号の先頭桁（2xxx=2F / 3xxx=3F）だけで分類していたのは不正確。 正しい定義は ml/last_digit/tail_ltr_split_rule_wf.py の floor_atype4 モードにあり、 jug_flag/hana_flag/bt_flag を使ってA/N型を判定する。 df[...

### 119. `is-top2-must-be-within-expert`
- confidence: `0.99` | status: `unverified` | date: `2026-05-25` | file: `2026-05-25-within-expert-target-fix.yaml`
- domain/source: `ml-pipeline-configuration` / `session-breakthrough`
- trigger: when defining LTR ranking target for multi-expert pachinko prediction
- summary: 末尾別LTRパイプラインでは複数のエキスパート（2F_N / 3F_N / 3F_A / 2F_A）が それぞれ独立したモデルを持つ。 評価指標 hit@2 は「エキスパート内10アイテム中、予測top2が実績top2を含むか」で定義。 （metrics_ops.py: true_top2 = actual_ra...

### 120. `window-name-vs-feature-name-confusion`
- confidence: `0.99` | status: `unverified` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-pipeline-configuration` / `session-error`
- trigger: when specifying --windows-wed or --windows-nonwed arguments for tail_ltr_split_rule_nextday_gpu
- summary: ACF/PACFで「roll28が最適」という知見を得た後、 `--windows-wed "roll28"` を指定したところ全candidateが "unavailable" になった。 `roll28` は特徴量名（`roll28_total_diff_coins`）であり、 training window...
