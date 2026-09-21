# ACTIVE_INSTINCTS

- generated_at: 2026-09-21T15:32:12+09:00
- compiler_version: 1.3.0
- source_dir: `C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/document/instincts`
- total_records_scanned: 1608
- active_records: 120
- status_breakdown: unverified=1600, confirmed=1, refuted=0, superseded=6
- filters: `confidence >= 0.80` and `file_date within 21 days` (unless pinned by high confidence)

## Usage
- Start of work: run `venv\Scripts\python.exe scripts/compile_instincts.py` (or `python scripts/compile_instincts.py`).
- Long sessions: rerun before major decisions or every 15-20 minutes.
- Preferred source for Codex: `ACTIVE_INSTINCTS.jsonl` (machine-readable canonical).
- This Markdown is a quick view. Open raw YAML only when detail is missing.
- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed.

## Active List

### 1. `spec-lookup-none-is-name-mismatch-not-unregistered`
- confidence: `0.90` | status: `unverified` | date: `2026-09-21` | file: `2026-09-21-spec-lookup-none-is-name-mismatch-not-unregistered.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: site777のブリーフや推定器で、BT・A+AT・ノーマル機（LBクレアの秘宝伝ボーナストリガーver.、ＳＬＯＴマッピー、LBタコスロ、LBサンダーV、異世界かるてっと）の設定推定が出ないとき。『スペックが未登録』『推定対象外』と言おうとするとき。backtest.bo...
- summary: 2026-09-20 楽園蒲田で、LBタコスロの設定推定がブリーフに出なかった。 `setting_estimator.annotate_setting_estimates` が None を返したので「スペック未登録」と書いたが誤りだった。 実際は次の2点だった。 1. `scraper/site777/set...

### 2. `event-days-are-per-hall-never-borrowed`
- confidence: `0.90` | status: `unverified` | date: `2026-09-20` | file: `2026-09-20-event-days-are-per-hall-never-borrowed.yaml`
- domain/source: `hall-strategy` / `user-correction`
- trigger: 蒲田1と蒲田7のように近い店を並べて、合同企画・収録来店・周年・取材などのイベント日の効果を測ろうとするとき。『カマタに集合』『W来店コラボ』『回胴エムワンバトル』の開催日を別ホールに当てはめようとするとき。予告ツイートの日付をイベント日として使う前
- summary: 2026-09-19 に蒲田1・蒲田7の「カマタに集合」の開催日平均差枚を比べたとき、過去の開催日を両店に同じ5日で当てはめた。 実際は、カマタに集合は両店同日（6/13・7/25・8/30・9/19）だが、蒲田1の回胴エムワンバトル収録（6/28・7/26）は別イベントで蒲田1のみだった。 収録日を蒲田7の開催...

### 3. `single-event-dummy-se-collapses-use-permutation`
- confidence: `0.85` | status: `unverified` | date: `2026-09-20` | file: `2026-09-20-single-event-dummy-se-collapses-use-permutation.yaml`
- domain/source: `methodology` / `empirical-measurement`
- trigger: イベント日が1〜5日しかない日をダミー変数にして回帰し、『t値が大きい』『有意』と結論しようとするとき。周年・新台入替・カマタに集合・取材など、少数日のイベントの効果を測るとき
- summary: 2026-09-20 に蒲田7のイベント日効果を、曜日・1/7の付く日・30日・ゾロ目を統制した回帰（HC標準誤差）で測った。 周年（7/7の1日）が t=+13.5、新台入替（7/6の1日）が t=-8.3 と出たが、1日だけのダミーは残差がほぼ0になり、標準誤差が構造的に小さくなる。 カマタに集合（4日）も勝...

### 4. `same-day-snapshots-are-not-replications`
- confidence: `0.85` | status: `unverified` | date: `2026-09-19` | file: `2026-09-19-same-day-snapshots-are-not-replications.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: site777を同じ日に何度も再収集して、『5回連続で負』『時刻をまたいで同じ方向』『zが強まっている』と、角番・末尾・列・機種の偏りを『安定したシグナル』と言おうとするとき。AT角番1の冷遇などを収集回数で裏づけようとするとき
- summary: 2026-09-19 楽園蒲田で site777 を13:55・14:55・15:55・18:55・21:56に5回収集した。 AT機の角番1の差枚残差は -1.5 → -2.2 → -2.7 → -2.8 → -2.4（z）と一貫して負だったため、 「5回連続で負。最も信頼できるシグナル」と報告した。 しかし各...

### 5. `model-rank-hides-eligible-machine-count`
- confidence: `0.85` | status: `unverified` | date: `2026-09-19` | file: `2026-09-19-model-rank-hides-eligible-machine-count.yaml`
- domain/source: `prediction-evaluation` / `empirical-measurement`
- trigger: site777のブリーフで機種を『自己ベースライン上位◯%』『平均差枚+◯』で推そうとするとき。設置台数が多いのに判定できる台が少ない機種（スマスロハナビ等）を機種として評価しようとするとき。『この機種は強い』と言う前
- summary: 2026-09-18 楽園蒲田の site777 ブリーフ（19:25）で、スマスロハナビが判別可能機種の最上位に出た （自己ベースライン上位4%・設定5以上63%・平均差枚+1280）。これを「機種として強い」と報告したが、 ユーザーに「差枚が出ている台自体が少ないのでは」と指摘され、機種の中身を見ると次の通り...

### 6. `axis-sweep-star-is-today-only`
- confidence: `0.80` | status: `unverified` | date: `2026-09-17` | file: `2026-09-17-axis-sweep-star-is-today-only.yaml`
- domain/source: `prediction-strategy` / `empirical-measurement`
- trigger: 軸スイープ（site777_live_brief.md の『今日どの切り口に構造が出ているか』）で★が出たとき。『今日は末尾5が熱い』『この角番が来ている』を翌日の予測に使おうとしたとき。機種・列・末尾・角番のどれかで見つけた構造をルール化しようとしたとき
- summary: 2026-09-17、楽園蒲田の88日（20260617〜20260915、1,000G以上、配置替えは日付ごとに machine_layout_history で解決）に対し、軸スイープ（機種/列/末尾/角番/フロア＋機種×各軸、 指標は差枚残差・差枚ホール比・回転数残差、最大統計量の並べ替え検定200回）を全...

### 7. `kamata7-tuesday-kakuban-is-section-end-minmax`
- confidence: `0.80` | status: `unverified` | date: `2026-09-16` | file: `2026-09-16-kamata7-kakuban-definition-and-midday-rb.yaml`
- domain/source: `pachinko-domain-knowledge` / `empirical-measurement`
- trigger: 蒲田7の火曜『角◯仕掛け』を採点・推定するとき。999999Q9Q メガなな速報の公表角番（AT角◯・ノーマル角◯）をDBと照合するとき。蒲田7で角番別の残差を集計するとき。rank_from_aisle（通路角番）で角番を採点しようとしたとき
- summary: 999999Q9Q（GALAXYウスイのメガなな速報）が火曜の翌未明に公表する角番は、 2026-09-16 時点で5火曜分（7/14 AT4・ノーマル7 / 7/28 AT7・N3 / 8/4 AT8・N4 / 8/18 AT6・N3 / 8/25 AT5・N8）が残っている。 この10件を正解ラベルとして、台...

### 8. `realtime-field-observation-is-not-blind-prediction`
- confidence: `0.80` | status: `unverified` | date: `2026-09-14` | file: `2026-09-14-realtime-field-observation-is-not-prediction.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: ユーザーが現地で気づいたこと（『末尾Xに仕掛けがある』『この機種は全っぽい』等）を予測材料として記録・採点するとき。リアルタイム取得できないホール（蒲田1・蒲田7）の主張を『完全な事前予測』として凍結しようとしたとき。当方が当日データを見ていないことを根拠に事前予測と判定し...

### 9. `machine-level-highsetting-estimator-validity`
- confidence: `0.88` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-mitoya-regime-and-highsetting-estimator-insights.yaml`
- domain/source: `methodology` / `empirical-validation`
- trigger: 台単位で「この台は高設定か」を推定しようとするとき。勝率・差枚・出率・ボーナス確率のどれかを高設定の代理指標にしようとするとき。AT機に設定が入ったかを判定しようとするとき
- summary: 2026-09-11 に楽園蒲田・蒲田1・みとやで台単位の高設定推定を組むにあたり、 代理指標を4つ試して**全部壊れることを実データで確認した**。 | 指標 | 壊れ方 | |---|---| | 勝率（差枚>0） | 設定6のAT機でも4割は負ける。分解能が足りない | | 絶対差枚 | 名指し機種・人気機...

### 10. `whole-period-aggregates-hide-regime-changes`
- confidence: `0.85` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-whole-period-aggregates-lie.yaml`
- domain/source: `prediction-evaluation` / `empirical-measurement`
- trigger: 全期間や前半後半で集計した数字を根拠に使おうとしたとき。前半と後半で符号が反転したものを棄却しようとしたとき。設置が1台しかない機種を候補から外そうとしたとき。撤去済みの機種を含む集計を読むとき。『この条件は効く』と結論する直前

### 11. `absolute-and-relative-coins-answer-different-questions`
- confidence: `0.85` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-absolute-vs-relative-coins.yaml`
- domain/source: `prediction-evaluation` / `empirical-measurement`
- trigger: 差枚で効果を測るとき。『ホール平均との差』を指標に選ぼうとしたとき。ボーナス確率の上振れと差枚を並べて比べるとき。『設定は入っているのに勝てない』と結論したくなったとき。イベント日に行くかどうかを判断するとき

### 12. `hall-mean-residual-flips-sign-on-high-injection-days`
- confidence: `0.85` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-mitoya-regime-and-highsetting-estimator-insights.yaml`
- domain/source: `methodology` / `empirical-validation`
- trigger: 当日ホール平均を引いた残差でセグメント・島・末尾を比較するとき。イベント日・取材日・予告日など、ホール全体が動く日の分析をするとき。「この区分は締められている」と結論したくなったとき
- summary: 当日ホール平均を引いた残差は日効果を消す標準手法だが、**比較の基準線そのものが日によって 動く**ことを見落とすと結論が反転する。 2026-09-11 にみとやで実際に誤読した。イベント日のノーマル機を残差で見ると ノーマル 残差: イベント日 -32.5枚 vs 通常日 +57.0枚（差 -89枚、**p<...

### 13. `rule-scores-must-be-decomposed-by-machine`
- confidence: `0.85` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-fixed-machine-echo.yaml`
- domain/source: `prediction-evaluation` / `empirical-measurement`
- trigger: フォワードテストや検証のスコアで『このルールは効いている』と言おうとしたとき。蒲田7のAT系ルール（k7_at_histdiff）の成績を引用するとき。台2026を候補に見たとき。上位ルールを運用に載せる判断をするとき

### 14. `hall-raises-a-subset-not-everything`
- confidence: `0.80` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-hall-raises-a-subset.yaml`
- domain/source: `hall-strategy` / `empirical-measurement`
- trigger: イベント日の効果を平均差枚で測ったとき。『ボーナスは上がったが平均が動かない』と感じたとき。設定判別やめどきの価値を見積もるとき。条件日の効き幅をユーザーに伝えるとき

### 15. `date-conditions-choose-the-day-not-the-model`
- confidence: `0.80` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-date-conditions-pick-days-not-models.yaml`
- domain/source: `hall-strategy` / `empirical-measurement`
- trigger: ゾロ目・7のつく日・月末・土日などの日付条件を検証するとき。日数の少ない条件を差枚で測ろうとしたとき。『この機種はこの日に強い』という条件付きルールを作ろうとしたとき。イベント日の効果を測る指標を選ぶとき

### 16. `model-strength-persists-by-term-not-by-day`
- confidence: `0.80` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-model-strength-persists-by-term.yaml`
- domain/source: `hall-strategy` / `empirical-measurement`
- trigger: 『過去の成績から選ぶルールは効かない』『日次の投入は読めないから機種選択は無理』と結論したくなったとき。機種の持続性・自己相関を測るとき。機種の恒常的な強さを交絡・雑音として除去しようとしたとき。どの機種を打つか決めるとき

### 17. `mitoya-xday-effect-decays-after-manager-change`
- confidence: `0.80` | status: `unverified` | date: `2026-09-11` | file: `2026-09-11-mitoya-regime-and-highsetting-estimator-insights.yaml`
- domain/source: `hall-regime` / `empirical-validation`
- trigger: みとやのイベント日（x_day / DD 4,7,14,17,24,27,30）で台を選ぶとき。みとやの既存 x_day プレイブックや DD 優先順位を使おうとするとき。みとやのイベント日が最近効かないと感じたとき
- summary: ホール平均差枚で、既知のレジーム境界（店長交代 2026-04末、2026-08 の +11台増設）に沿って 3分割した。イベント日 = DD{4,7,14,17,24,27,30}、通常日は DD1 を除いたもの。 | 期間 | 営業日 | 通常日 | イベント日 | 効果 | p | |---|---|---...

### 18. `label-position-must-split-by-granularity`
- confidence: `0.85` | status: `unverified` | date: `2026-09-10` | file: `2026-09-10-position-labels-confounded-by-narabi.yaml`
- domain/source: `hall-strategy` / `empirical-measurement`
- trigger: 結果発表の台単位ラベル(external_result_machines)で角番・末尾の偏りを測るとき。『角1は該当台になりにくい』を外部ラベルの裏付けとして引用しようとしたとき。並びラベルと全台系ラベルをまとめて位置分析にかけようとしたとき

### 19. `external-result-corpus-gives-ground-truth-labels`
- confidence: `0.80` | status: `unverified` | date: `2026-09-10` | file: `2026-09-10-external-result-labels.yaml`
- domain/source: `prediction-evaluation` / `empirical-measurement`
- trigger: 全台系スコアの閾値(+1800)超え/未達を『設定が入っていたか』の判定に使うとき。予告の的中率のベースレートが要るとき。『正解ラベルが数十件しかない』と感じたとき。楽園蒲田で台単位の正解ラベルが欲しいとき

### 20. `2026-09-07-social-collector-silent-truncation`
- confidence: `0.95` | status: `unverified` | date: `2026-09-07` | file: `2026-09-07-social-collector-silent-truncation.yaml`
- domain/source: `data-collection` / `session-observation`
- trigger: Twitter/Xの収集結果を『N件取得』『EXIT=0』で正常と判断しようとしたとき。スクレイプ済みツイートの期間網羅性を前提に分析を始めるとき。tweet_text から予告・仕掛けの内容を読み取ろうとしたとき
- summary: twitter_monitor の収集は、失敗を例外にせず**成功報告の形で欠落を返す**。 件数・終了コード・ログの警告はいずれも欠落を検出しない。検証は (a) 日付のカバレッジ (b) 取れた文字列の末尾 の2点で行う。 n_observations: 3（いずれも独立に発生し、いずれも EXIT=0・警告...

### 21. `2026-09-07-announce-verification-prerequisites`
- confidence: `0.90` | status: `unverified` | date: `2026-09-07` | file: `2026-09-07-announce-verification-prerequisites.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: ホール予告の的中率を検証しようとしたとき。backtest/announce.py の register / score を回す前。画像抽出の完了を待って予告分析を始めようとしたとき。答え合わせの計画を立てるとき
- summary: 予告検証を始める前に確認すべきは画像抽出の進捗ではなく、 (1) 予告本文が完全に取れているか (2) 対象日のホールDBが存在するか (3) 登録と取込の順序 の3点である。この3つを外すと、抽出を何枚進めても 採点は1件もできない。 data scope: backtest/announce/、db/*.db...

### 22. `2026-09-07-multihall-account-extraction-targeting`
- confidence: `0.90` | status: `unverified` | date: `2026-09-07` | file: `2026-09-07-multihall-account-extraction-targeting.yaml`
- domain/source: `data-collection` / `session-observation`
- trigger: Twitter画像の抽出クォータ（Codex等）をどの投稿に使うか決めるとき。kawasakislot・sloneko222・999999Q9Q を対象ホールの情報源として扱うとき。抽出を『新しい順』で回そうとしたとき。あるアカウントについて『対象ホールが取れない』と結論し...
- summary: 監視している8アカウントのうち複数は特定ホール専属ではなく**広域アカウント**で、 投稿の大半は対象外ホールを扱っている。抽出を「新しい順」で回すと、 クォータ（Codex 約140枚/日）が対象外の画像に消える。 抽出前に**本文語で絞る**こと。 data scope: scraper/twitter_mo...

### 23. `2026-08-01-do-not-use-briefing-common-is-event-dd`
- confidence: `0.95` | status: `unverified` | date: `2026-08-01` | file: `2026-08-01-eventday-audit-methodology.yaml`
- domain/source: `data-pipeline` / `session-observation`
- trigger: eda/briefing_common.py の load_hall_frame を使ってイベント日別の集計をするとき。is_event_dd 列を使おうとしたとき。HALL_EVENT_DIGITS を参照するとき。イベント日 vs 非イベント日の比較をするとき

### 24. `split-half-consistency-is-not-holdout`
- confidence: `0.95` | status: `unverified` | date: `2026-07-29` | file: `2026-07-29-rakuen-theory-revalidation-audit-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 候補（DD・末尾・section等）を全期間から抽出したあとに、時系列前半/後半へ分割して『holdout検証した』と主張しようとするとき
- summary: `eda/rakuen_theory_revalidation.py` はジャグ・ハナハナ・技術介入・AT一般のカテゴリ別DD候補を 中央値日（2025-10-14）で前後半に割り、後半でBH補正付き permutation 検定を行い、通過分に `holdout_supported` という列名を与えた。しかし...

### 25. `rakuen-section-column-not-island`
- confidence: `0.95` | status: `unverified` | date: `2026-07-28` | file: `2026-07-28-rakuen-section-column-redefinition-and-edge-effect-insights.yaml`
- domain/source: `section-analysis` / `session-observation`
- trigger: 楽園のsectionをフロア座標・生成スクリプトから扱うとき
- summary: `Heatmap/generate_rakuen_kamata_coordinates.py`が、1122-1134・1135-1151・2100-2110・ 3107-3116・3176-3187の5箇所で、通路(柱)で物理的に分断された1本の列を`section`という 1つのラベルにまとめていた。既存の`m...

### 26. `rb-probability-decimal-null-on-zero-count`
- confidence: `0.98` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: rb_probability_decimal または bb_probability_decimal / total_probability_decimal に notna() / IS NOT NULL / > 0 のフィルタをかけようとするとき
- summary: `rb_probability_decimal` は `rb_count / games_normalized` から作られる派生列だが、 `rb_count == 0` の行では NULL になる（9ホール全てでNaN率とRB0回率が完全一致、 rb_count>0でNULLの行は0件）。`bb_probabi...

### 27. `machine-layout-single-snapshot-breaks-across-renovation`
- confidence: `0.97` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: machine_layoutを使って過去データに位置(section/rank_from_*)を結合するとき、または改装・島配列変更があったホールの位置分析を行うとき
- summary: machine_layoutは日付次元を持たないため、改装で位置定義が変わると新しい位置が 過去データに遡って適用される。楽園蒲田の2026-07-06の改装でsection定義が 書き換わり(2223-2240→2225-2242等)、技術介入の端番効果が+1.127pp→+0.211pp(ns)に 変化した。...

### 28. `uniform-physical-threshold-across-categories-produces-false-anomalies`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-rakuen-column-merge-and-games-corruption-audit-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: 確率・機械割等に「物理的にありえない」閾値を設定して、複数の機種カテゴリを横断して異常値/破損データを検出しようとするとき
- summary: 本セッションで2回、同じ失敗パターンが起きた。(1) 機械割>200%かつdiff>1000で 「破損」を検出→14,554行のうち89%がAT機で、AT機のボーナス/AT当選確率(1/15〜150)は ジャグ/ハナ/沖スロ(1/300+)と2桁違うため単に正常な高分散日だった。(2) ボーナス確率 >1/20で...

### 29. `games-filter-is-selection-on-setting`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: games_normalized >= N / min_games フィルタを集計前にかけて、区画・軸・カテゴリの成績や設定シグナルを測るとき
- summary: 「低設定→早く見切られる／高設定→長く回される」という基本法則により、games は 設定の下流にある（独立指標RBで確認: 台レベル相関 ハナ+0.94/ジャグ+0.69、 日レベルでジャグの稼働帯別RBz が -1.33→+0.97 と単調）。したがって `games >= N` のフィルタは低設定の日を選択...

### 30. `diff-coins-confounds-setting-with-turnover`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `statistical-methodology` / `session-observation`
- trigger: 差枚(diff_coins_normalized)ベースで位置・人気度など回転数に影響しうる変数の効果を測るとき
- summary: diff = 3 * G * (payout - 1) なので、機械割が同じでもG(回転数)が違えば差枚は動く。 蒲田7角番1の検証で、差枚ベースの-162枚のほぼ全部(-124枚が共分散差、-37枚がG数差、 機械割の寄与はわずか-0.5枚)が「角1は+624G多く回されている」という回転数差の 帰結だった。角...

### 31. `mwu-cannot-detect-tail-only-edges`
- confidence: `0.95` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-mwu-tail-edge-and-weight-desync-insights.yaml`
- domain/source: `analysis-methodology` / `session-analysis`
- trigger: 台×日の差枚でグループAとBを比較し、MWU/Kruskal-Wallisが非有意だったとき。特に平均差はあるのにp値が大きいとき
- summary: 2026-07-24、みとや大森町の h_nonjug 角番1（X_DDS日）を post-regime で評価した際、 MWU が p=0.522 で非有意だったため「角番効果は消えた/解像できない」と一度結論した。 これは**誤りだった**。同じデータを分位点と裾確率で測り直すと明確な差が出た。 | X_DD...

### 32. `null-result-requires-power-measurement`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-analysis`
- trigger: 検定が帰無を棄却しなかったとき。『効果なし』『レジームなし』と結論したくなったとき
- summary: 「棄却できない」は「効果が無い」ではなく「あっても見えない」かもしれない。区別するには検出力が要る。実データの日次系列（＝本物のノイズ）に振幅±A・周期75日の矩形波を人工的に注入し、p<0.05 になる最小振幅を測ればよい。 2026-07-23の検証では、この測定で判定が分かれた。蒲田7・雑色は±150枚以上...

### 33. `null-hypothesis-must-preserve-serial-correlation`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-implementation`
- trigger: 時系列の非定常性・変化点・レジームを検定するとき。帰無分布をシャッフルで作ろうとしたとき
- summary: 台選択ルールの日次エッジには正の系列相関がある（同じ台が連日選ばれ続けるため）。この相関だけでローリング窓平均は勝手に振れる。帰無分布をiidシャッフルで作ると相関が消えて分布が狭くなりすぎ、**ただの自己相関がレジーム変化として有意に出る**。 検定したいのは「窓平均の振れがノイズを超えるか」なので、帰無仮説側...

### 34. `metric-choice-decides-what-signal-is-visible`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-regime-nonstationarity-and-changepoint-insights.yaml`
- domain/source: `analysis-methodology` / `session-analysis`
- trigger: 台×日のシグナルを検定・比較するとき。差枚(diff_coins_normalized)を指標に選ぼうとしたとき
- summary: 2026-07-23、非定常性検定を全9ホールで回した際、系列を全て差枚ベースのエッジで作っていた。差枚 = G数 × 3 × (機械割 - 1) なので、当日どれだけ回ったかという設定と無関係な分散が丸ごと混入する。スロットは6段階設定であり、見るべきは設定差。 同一の選択ルールに対し指標だけを差枚 / 機械割...

### 35. `signal-existence-does-not-imply-predictability`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-methodology` / `session-analysis`
- trigger: 分散分解や台×日シグナルの大きさを見て『予測できるはず』と判断しそうになったとき
- summary: eda/variance_decomposition.py の分散分解で、蒲田7は9ホール中最大の台×日シグナル(2.89pp≈400枚/日相当)を持つのに、その蒲田7で組んだ複数の履歴ベース事前登録ルール(RB確率上位・hit104率上位)はすべて負エッジ(-17.9〜-58.6枚/台、289日・867選択)だ...

### 36. `preregistration-breaks-in-sample-self-reference`
- confidence: `0.95` | status: `unverified` | date: `2026-07-23` | file: `2026-07-23-prereg-backtest-harness-and-signal-ceiling-insights.yaml`
- domain/source: `ml-methodology` / `session-implementation`
- trigger: instinct/仮説を検証したいとき。バックテストの結果を『確証』として扱いたくなったとき
- summary: document/instincts/ が1400本近くありながら confirmed=0 だった原因は、「過去データを見て見つけたルールを同じ過去データで確認する」自己参照ループから一度も抜けていなかったこと。バックテストは「未来データに効かないルールを実弾の前に落とすフィルタ」としてのみ価値があり、それ自体は...

### 37. `emulator-arm64-translation-requires-api34-plus`
- confidence: `0.97` | status: `unverified` | date: `2026-07-19` | file: `2026-07-19-maruhan-frida-arm64-translation-and-play-integrity-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: x86_64エミュレーターでarm64専用ネイティブライブラリを含む商用アプリを動かそうとするとき
- summary: API 33 (r17) google_apis x86_64は abilist=x86_64のみ、native.bridge=0で、arm64専用アプリは INSTALL_FAILED_NO_MATCHING_ABIS で弾かれる。API 34 (r14) は abilist=x86_64,arm64-v8a、...

### 38. `frida-incompatible-with-arm-translation-layer`
- confidence: `0.95` | status: `unverified` | date: `2026-07-19` | file: `2026-07-19-maruhan-frida-arm64-translation-and-play-integrity-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: ARM変換(libndk_translation)エミュ上でFridaによる動的計装・SSLアンピンを試みるとき
- summary: x86_64エミュ上でarm64アプリを動かすため libndk_translation で変換実行させると、 Fridaは3つとも失敗する: 1. x86_64 frida-server は変換実行中のarm64プロセスにアタッチ不可("need Gadget"エラー)。 2. arm64 frida-serv...

### 39. `codex-resume-must-go-through-rescue-subagent-not-raw-cli`
- confidence: `0.95` | status: `unverified` | date: `2026-07-13` | file: `2026-07-13-kamata1-dd14-section-streak-and-codex-resume-insights.yaml`
- domain/source: `workflow-codex-handoff` / `session-observation`
- trigger: Codexへの委任セッションを--resumeで再開しようとするとき
- summary: Codexへの委任タスクが確認質問(閾値選択)で止まった後、再開のために `node codex-companion.mjs task "--resume-last <指示文>"` をBashから直接叩いたところ、 "--resume-last"という文字列がCLIフラグではなくCodexへの生プロンプトテキスト...

### 40. `rakuen-diff-unit-is-coins-not-yen`
- confidence: `0.95` | status: `unverified` | date: `2026-07-13` | file: `2026-07-13-rakuen-weekday-metrics-insights.yaml`
- domain/source: `terminology` / `user-feedback`
- trigger: diff_coins_normalized（差枚）の数値を報告・記述するとき
- summary: `document/rakuen_theory.md`全体で`diff_coins_normalized`由来の数値を「円」と誤記していた（約45箇所）。ユーザー指摘を受けて文書全体を「枚」に一括修正した。 `diff_coins_normalized`・`avg_diff`・`excess_diff`・`dif...

### 41. `rakuen-section-type-a-avoid-always`
- confidence: `0.95` | status: `unverified` | date: `2026-07-12` | file: `2026-07-12-rakuen-section-dd-swing-insights.yaml`
- domain/source: `section-analysis` / `session-observation`
- trigger: 楽園の1106-1115・1130-1134セクションの扱いを判断するとき
- summary: `eda/rakuen_section_dd_swing_analysis.py`でセクション×DD(1-31)のavg_diffを分解した結果、この2区画は31DD全てでマイナス（符号一致率100%）という、Type A(恒常型)の中でも極端な例だった。「強い日だけ狙う」戦略の前提として、まず「日で変わらず常に...

### 42. `rakuen-honkan-floor-simpson-paradox`
- confidence: `0.95` | status: `unverified` | date: `2026-07-12` | file: `2026-07-12-rakuen-eda-session-insights.yaml`
- domain/source: `floor-layout-analysis` / `session-observation`
- trigger: 楽園のセグメント定義・フロア構成を参照するとき
- summary: `dashboard/config/hall_configs/rakuen.yaml`のsegment_scheme初版は「本館_N」として本館1F/2F/3Fを1セグメントに統合していた。実データでは本館1F(N)だけ極端に悪く(avg_diff -997.9円, hit率26.2%)、本館2F/3F(N)は良...

### 43. `rakuen-event-day-definition-corrected`
- confidence: `0.95` | status: `unverified` | date: `2026-07-12` | file: `2026-07-12-rakuen-eda-session-insights.yaml`
- domain/source: `event-day-analysis` / `session-observation`
- trigger: 楽園のイベント日定義を参照・使用するとき
- summary: `document/rakuen_theory.md`の旧記載は「HALL_EVENT_DIGITS=[11,22]」、`eda/section_lateral_expansion.py`のHALL_CONFIGSは「{1,4,7,14,17,24,27,30}」（みとやの定義を誤って転用）と、2つの矛盾する定義...

### 44. `prior-distribution-echo-in-self-evaluated-selection-models`
- confidence: `0.95` | status: `unverified` | date: `2026-07-11` | file: `2026-07-11-latent-setting-inference-and-prior-echo-insights.yaml`
- domain/source: `ml-evaluation` / `session-observation`
- trigger: 台・商品等の選択ロジックの評価指標が、選択ロジック自体が使った事前分布・変換テーブルに依存しているとき
- summary: 蒲田7ジャグラー日次選択（`jug_rb_setting_prediction`裁定#13）で、B1の評価指標 （p_high・e_payoutという「モデル通貨」）は+2.5ppのエッジを示していたが、これは 選択ロジック（family別の設定事後分布）と評価指標（同じ事後分布からの期待機械割 換算）が同じ計算...

### 45. `kakuban-vs-hanaban-terminology-redefinition`
- confidence: `0.95` | status: `unverified` | date: `2026-07-11` | file: `2026-07-11-dd11-kakuban-hanaban-row-effect-insights.yaml`
- domain/source: `pachinko-domain-terminology` / `session-observation`
- trigger: 蒲田7で「角番」という言葉を使った分析・議論を始めるとき
- summary: これまで「角番(kakuban)」という一語で、(a) `rank_from_min`/`rank_from_max`（列の両端からの距離、台1台につき2つの値を持つ）と (b) メイン通路からの距離、という異なる2概念を混同したまま分析していた。 さらに`dashboard/utils/theory_engin...

### 46. `dataframe-apply-axis1-plus-per-row-series-is-slow`
- confidence: `0.95` | status: `unverified` | date: `2026-07-10` | file: `2026-07-10-dashboard-refactoring-codex-delegation-insights.yaml`
- domain/source: `performance` / `session-observation`
- trigger: DataFrameの各行に分類・判定関数を適用するコードを書くとき
- summary: セオリー検証エンジンの一般化（Phase 2）で、YAML駆動のセグメント判定を `work.apply(lambda row: classify_theory_segment(...), axis=1)` で実装したところ、 蒲田7の実DB（259,545行）で`load_theory_frame`が90秒以上...

### 47. `codex-desktop-agmsg-monitor-requires-cli-shim-not-desktop-app`
- confidence: `0.98` | status: `unverified` | date: `2026-07-09` | file: `2026-07-09-codex-desktop-agmsg-monitor-limitations.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: when expecting agmsg monitor-mode real-time delivery inside the Codex desktop app
- summary: Setting `agmsg` delivery mode to `monitor` for `codex` is not sufficient when the session is running inside the Codex desktop app. The monitor bridge only be...

### 48. `agmsg-history-vs-inbox-must-not-be-confused-during-debugging`
- confidence: `0.96` | status: `unverified` | date: `2026-07-09` | file: `2026-07-09-codex-desktop-agmsg-monitor-limitations.yaml`
- domain/source: `agent-coordination` / `session-observation`
- trigger: when debugging whether a Codex or Claude agmsg message was actually delivered
- summary: `inbox.sh` showing `No new messages.` does not mean a message was never sent. Delivery debugging must distinguish unread inbox state from persistent message...

### 49. `kamata7-dashboard-theory-visualization-gaps`
- confidence: `0.95` | status: `unverified` | date: `2026-07-09` | file: `2026-07-09-kamata7-dashboard-extension-plan.yaml`
- domain/source: `visualization-feature-design` / `session-analysis`
- trigger: when extending dashboard to visualize all kamata7_theory.md law patterns
- summary: 現在のダッシュボード19ページは、セオリーの主要法則性（15項目）のうち6項目のみ実装済み。 残り9項目を段階的に追加することで、全法則性をダッシュボードから可視化可能にする。 n_observations: 1 data scope: kamata7_theory.md（セオリー文書）vs dashboard/...

### 50. `codex-agmsg-must-use-git-bash-on-windows`
- confidence: `0.99` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-agmsg-kamata7-dashboard-insights.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: Codex Desktop on WindowsからagmsgでClaude Codeと連絡するとき
- summary: Kamata7 dashboard計画でClaude Codeとagmsg連携した際、Codex側で `bash ...` をそのまま実行すると `C:\Users\apto117\AppData\Local\Microsoft\WindowsApps\bash.exe` 経由のWSL bashに流れ、`$HOM...

### 51. `agmsg-on-windows-use-git-bash-not-windowsapps-bash`
- confidence: `0.98` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: when sending agmsg messages from Codex Desktop on Windows
- summary: Using the WindowsApps `bash.exe` path can route the command into the wrong shell and produce empty or misleading agmsg sends. n_observations: 1 data scope: t...

### 52. `kamata7-theory-dashboard-needs-japanese-tabs-and-fallbacks`
- confidence: `0.97` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `dashboard-ui-patterns` / `session-observation`
- trigger: when building or revising the Kamata7 theory dashboard
- summary: The Kamata7 theory page is only useful when each tab explains its purpose in Japanese and falls back gracefully when a sample threshold removes all cells. n_...

### 53. `cross-agent-dashboard-workflow-claude-design-codex-implementation`
- confidence: `0.97` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-agmsg-kamata7-dashboard-insights.yaml`
- domain/source: `agent-coordination` / `session-observation`
- trigger: Claude CodeとCodexでdashboard機能を共同設計・実装するとき
- summary: Kamata7 dashboard拡張では、初期状態でCodexからClaudeへの相談文が届いたか不明になり、 ユーザーが両画面を中継して状況確認した。通信経路をGit Bashに固定した後、 Claude側が「Claude=設計・仕様・テスト戦略、Codex=実装」と役割を明示し、 `document/pla...

### 54. `kamata7-dashboard-routing-must-stay-in-sync-across-main-entrypoints`
- confidence: `0.96` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `dashboard-ui-patterns` / `session-observation`
- trigger: when adding, renaming, or moving Kamata7 dashboard pages
- summary: The Kamata7 dashboard only resolves new page keys reliably when `main_app.py` and `dashboard/main.py` are kept in sync; updating one router alone can still p...

### 55. `kamata7-event-kind-summary-should-be-machine-count-weighted`
- confidence: `0.95` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `dashboard-analysis` / `session-observation`
- trigger: when summarizing Kamata7 event kinds, DD buckets, or other day-level aggregates
- summary: Kamata7 event-kind and DD summaries should use `machine_count`-weighted averages for rate-like columns so small cohorts do not distort the aggregate view. n_...

### 56. `kamata7-dashboard-initial-scope-safe-top5`
- confidence: `0.95` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-agmsg-kamata7-dashboard-insights.yaml`
- domain/source: `dashboard-ui-patterns` / `session-observation`
- trigger: 蒲田7セオリーをdashboardで可視化・検証する初期実装を設計するとき
- summary: 蒲田7セオリーのdashboard化では、最初に全論点を対象にすると GATED/NOGATE、debut age/regime、machine-specific DD/weekdayなど、 ライブ表示にはデータ品質・誤読リスクが高い項目まで混ざる。 Claudeレビューでは初期Top5として Six physi...

### 57. `mitoya-recommend-optimized-weights-never-synced-to-production`
- confidence: `0.95` | status: `unverified` | date: `2026-07-04` | file: `2026-07-04-mitoya-kamata7-recommend-flow-audit-insights.yaml`
- domain/source: `pachinko-domain-analysis` / `session-observation`
- trigger: みとやの台選びスクリプト(eda/mitoya_recommend.py, eda/mitoya_recommend_backtest.py)を実行・修正する時、または『台選びフローが古くないか確認して』と依頼された時
- summary: ユーザーから「台選びフローが古い形式になっていないか確認して、更新できるフローがあれば更新して」という依頼を受けた。調査の結果、`eda/mitoya_recommend_optimize.py`によるwalk-forward最適化が既に実行済みで、結果が`eda/results/mitoya_optimize_...

### 58. `mitoya-theory-partial-autogeneration-gotcha`
- confidence: `0.95` | status: `unverified` | date: `2026-07-02` | file: `2026-07-02-theory-doc-architecture-and-okf-insights.yaml`
- domain/source: `documentation-architecture` / `session-observation`
- trigger: document/*_theory.md や、それを生成するeda/*_theory.pyスクリプトを扱うとき、または長大なtheory文書が自動生成か手動作成か判断するとき
- summary: document/mitoya_theory.md を調査した際、最初の100行程度（Phase3の生データ羅列部分）だけを見て「ファイル全体が自動生成の産物」と誤判断した。 実際には eda/mitoya_phase5b_theory.py の build_theory_document() が生成するのはPh...

### 59. `significance-csv-duplicate-rows-by-outcome`
- confidence: `0.95` | status: `unverified` | date: `2026-07-02` | file: `2026-07-02-recent-window-trend-analysis-insights.yaml`
- domain/source: `tooling` / `session-observation`
- trigger: 全機種スキャンのCSVで同じホール×機種名の行が複数出て重複バグに見えるとき
- summary: machine_axis_pattern_scan.py系のpattern_summary.csvは1機種につきdiff(Kruskal-Wallis)/plus(カイ二乗)/hit104(カイ二乗)の3種の検定を独立行として出力する。p<0.05かつ効果量≥0.1でフィルタしたCSVで同じhall×machin...

### 60. `dashboard-page-registration-four-files`
- confidence: `0.95` | status: `unverified` | date: `2026-07-01` | file: `2026-07-01-daily-hall-report-page-insights.yaml`
- domain/source: `dashboard-ui-patterns` / `session-observation`
- trigger: ダッシュボードに新規ページを追加するとき
- summary: ダッシュボードのページルーティングは `dashboard/pages/__init__.py`（import + `__all__`）、`dashboard/config/constants.py`（`PAGES`リスト）、`dashboard/main.py`（import + `PAGE_ROUTER`）、...

### 61. `dd30-heatmap-export-tool-available`
- confidence: `0.95` | status: `unverified` | date: `2026-06-30` | file: `2026-06-30-dd30-three-hall-comparison-insights.yaml`
- domain/source: `tooling` / `session-implementation`
- trigger: DD別の候補台を視覚的に確認したいとき
- summary: 2026-06-30セッションで設計、Codexが実装。平均差枚（背景色7段階: 赤→グレー→緑→金）×勝率（枠線4段階: 金太枠→緑→なし→赤点線）の二軸でフロアマップ上に候補台をハイライト表示するHTMLを生成する。 python Heatmap/export_dd_candidates.py --dd 30...

### 62. `v12b-composite-score-no-calibration`
- confidence: `0.98` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-v12b-calibration-failure-insights.yaml`
- domain/source: `ml-evaluation` / `walk-forward-calibration-60days`
- trigger: スコアリングモデルの予測結果をTop-Nで絞り込むとき、またはcompositeスコアに基づく台選択推薦を行うとき
- summary: v12b_debut_multiplier_halfのcompositeスコアと実際の104%超え確率の対応関係を、60日間のwalk-forward評価（42,840行）で検証した。 スコア十分位別の104%超え率はD0=32.9%からD9=32.8%まで実質フラットで、スコアの高低が的中確率をほぼ予測しない。...

### 63. `v11-segment-weight-concentration-artifact`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-v12b-calibration-failure-insights.yaml`
- domain/source: `ml-model-design` / `session-analysis`
- trigger: v11のセグメント別重みを使用するとき、または特定機種・セクションがTop-Nを支配するとき
- summary: SEGMENT_WEIGHTS_V11で3F_R_Nはc1=0.50, c4=0.50（2成分のみで100%）、2F_L_Nはc2=0.47（末尾が47%を支配）。 この極端な集中により、DD28×日曜のような特定コンテキストで東京喰種セクション（3209-3217）がTop5を独占する一方、2F_L_N（182...

### 64. `top-n-coverage-vs-precision-tradeoff`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-v12b-calibration-failure-insights.yaml`
- domain/source: `recommendation-design` / `walk-forward-calibration-60days`
- trigger: 推薦台数（Top-N）の設定を決めるとき、またはスコアモデルの出力をユーザーに提示するとき
- summary: Top50のhit率32.7%はベースライン31.1%と+1.6ppしか差がなく、Top50は全104%+台の7.4%しか捕捉しない。 セグメント別では3F_R_Aが0.8%、2F_L_Nが3.7%の捕捉率で、特定セグメントの高設定台を体系的に見逃している。 問題は「高スコア台が高設定でない」ことではなく、「低ス...

### 65. `component-calibration-hist-only-signal`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-v12b-calibration-failure-insights.yaml`
- domain/source: `ml-evaluation` / `component-level-calibration-v6a-60days`
- trigger: スコアリングモデルのコンポーネント設計を見直すとき、または新バリアントの重み配分を検討するとき
- summary: v6aの6コンポーネント＋hist_metricを個別にSpearman相関で検証した結果: hist_metric: rho=+0.037, p<0.0001 (D0=28.9%→D9=35.0%, +6.1pp) — 唯一の実効的シグナル c2（角番距離）: rho=+0.015, p=0.002 — 有意だ...

### 66. `kamata1-section-structure-30sec-350machines`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-kamata1-eda-step1-3-insights.yaml`
- domain/source: `floor-layout-analysis` / `session-observation`
- trigger: 蒲田1のセクション定義・フロア構成を参照するとき
- summary: 座標CSV (Heatmap/2F_floor_coordinates_kamata1.csv) から全セクションを確認。 2331-2340（10台、Y=68-77の孤立ゾーン）は2025-08-17に撤去されておりCSVから削除済み。 1631-1633は厳密には1Fだが同一フロア扱い。 有効セクション: 3...

### 67. `kamata1-residual-analysis-no-signal`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-kamata1-eda-step1-3-insights.yaml`
- domain/source: `residual-analysis` / `session-observation`
- trigger: 蒲田1の曜日・末尾・角番効果を検討するとき
- summary: 手順書Step 3に従い、セクション当日平均→DD×セクション×イベント効果を階層的に除去した resid2に対して、曜日・末尾・角番の効果量を検出。アクション閾値3ppを超える要素はゼロ。 **曜日**: 完全にフラット（≈0.00pp）。曜日×イベント交互作用もなし **末尾**: レンジ1.2pp（末尾5が...

### 68. `rakuen-event-dd-not-validated`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-rakuen-2004-2007-deep-dive-insights.yaml`
- domain/source: `data-quality` / `user-correction`
- trigger: 楽園蒲田のイベントDD定義を使おうとするとき
- summary: 分析で使用したis_event_ddフラグはみとや由来の定義で、楽園に適合するか未検証。実際にイベントDD(avg_diff -53.1)が非イベントDD(+49.6)を下回る逆転現象が発生し、ユーザーから「楽園はまだ精査していないので無視」と指示。 楽園蒲田のDD分析ではis_event_ddフラグを参照しない...

### 69. `rakuen-2004-2007-bimodal-distribution`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-rakuen-2004-2007-deep-dive-insights.yaml`
- domain/source: `statistical-interpretation` / `session-observation`
- trigger: 楽園蒲田のセクション差枚が微プラスの場合にその構造を解釈するとき
- summary: 鏡期間(2026-01~)の日別分析で、全体avg_diff +96の構造を分解。日の66%はマイナス（中央値-238）。5k+G日（全体の17%）だけがavg_diff +1,709で全体を引き上げている極端な二峰分布。 セクションのavg_diffが微プラスの場合、平均値だけで判断せず必ずG数バケット別に分解...

### 70. `section-ranking-pipeline-final-spec`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-stage2-and-final-pipeline-insights.yaml`
- domain/source: `ml-operations` / `session-cumulative`
- trigger: predict_section.pyの最終仕様を確認するとき
- summary: セッションで確立した最終仕様: Stage 1: section_avg_hist（60日窓）でセクションランキング Stage 2: hist_metric（60日窓）でセクション内台ランキング 推奨: Top5セクション × 5台 = 25台/日 検証済みパラメータ: 窓幅60日（90日より+73枚/台、6期...

### 71. `mitoya-coords-section-already-split`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-section-score-refinement-insights.yaml`
- domain/source: `data-processing` / `session-verification`
- trigger: みとやの座標データでsection×y分割を検討するとき
- summary: mitoya_theoryの instinct (mitoya-section-y-split-correct-granularity) では 「section×yの複合キーを分析単位として使用する」と指示している。 しかしこれは machine_layout テーブルの旧定義への注意であり、 Heatmap/m...

### 72. `predict-daily-pipeline-integrated`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-backtest-and-pipeline-integration-insights.yaml`
- domain/source: `ml-operations` / `implementation`
- trigger: predict_daily.pyのパイプラインを実行するとき
- summary: predict_daily.pyのパイプラインにpredict_sectionを統合。 実行順序: scrape → DB update → predict_section → predict_gated。 predict_sectionが主力、predict_gatedは後方互換。 predict_sectio...

### 73. `section-daily-pipeline-validated`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-section-daily-pipeline-insights.yaml`
- domain/source: `ml-model-design` / `walk-forward-eval-60days-predict-section`
- trigger: 蒲田7の予測・推薦パイプラインを設計するとき、またはpredict_section.pyの結果を解釈するとき
- summary: predict_section.pyの60日walk-forward評価で検証: Stage 1（セクション選択）: section_avg_hist rho=+0.172, p<0.0001 Stage 1+2（セクション選択＋台選び）: Top1sec×5台で104%超え率39.6%（baseline 31....

### 74. `granularity-shift-section-wins-weekly-loses`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-section-daily-pipeline-insights.yaml`
- domain/source: `ml-model-design` / `granularity-shift-experiments`
- trigger: 予測粒度（台×日/セクション×日/台×週）の選択を議論するとき
- summary: 台×日のhist_metric（rho=+0.038, D0→D9=+6.0pp）をベンチマークに2つの粒度シフトを検証: セクション×日: section_avg_hist rho=+0.195, D0→D9=+10.1pp → ベンチマークの5倍 台×週: hist_metric rho=+0.043, D0...

### 75. `mitoya-segment-is-section-not-lr-an`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-mitoya-calibration-insights.yaml`
- domain/source: `ml-model-design` / `session-analysis`
- trigger: みとやのデータをセグメント分割するとき、または蒲田7のモデルをみとやに移植するとき
- summary: 蒲田7はフロア×LR×A/Nで6セグメントに分割し、セグメント別に戦略を変えることが有効だった。 みとやは全台2F（フロア分割なし）、18セクション（島）が分析の基本粒度。 LR×A/Nで分割（2F_L_A, 2F_L_N, 2F_R_A, 2F_R_N）すると、セクション構造が無視され、 同じ島内でL側とR側で...

### 76. `mitoya-hist-metric-strongest-signal`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-mitoya-calibration-insights.yaml`
- domain/source: `ml-evaluation` / `walk-forward-calibration-mitoya-60days`
- trigger: みとや大森町の台選択・予測モデルを設計するとき
- summary: 60日walk-forward（n=15,960）でみとやのコンポーネント別キャリブレーションを検証。 hist_metric: rho=+0.042, p<0.0001, D0=26.0%→D9=33.4%（+7.4pp）。 c_dd_sec: rho=+0.017, p=0.036（弱い正）。 c_dow_s...

### 77. `segment-ranking-eval-results`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-segment-ranking-eval-insights.yaml`
- domain/source: `ml-evaluation` / `walk-forward-segment-eval-60days`
- trigger: セグメント別予測の出力形式や戦略を設計するとき、またはcomposite vs hist_metricの使い分けを決めるとき
- summary: 60日walk-forwardでセグメントごとにcomposite Top10とhist_metric Top10の的中率（104%超え）をベースラインと比較した。 統計的に有意な差があるのは3F_L_Nのみ（hist_only +8.8pp, Wilcoxon p=0.002）。 他5セグメントではcompos...

### 78. `3fln-composite-harmful`
- confidence: `0.95` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-segment-ranking-eval-insights.yaml`
- domain/source: `ml-model-design` / `walk-forward-segment-eval-60days`
- trigger: 3F_L_Nセグメントの予測やスコアリングを行うとき
- summary: 3F_L_NのcompositeスコアTop10のhit率は29.8%で、ベースライン32.0%より低い（-2.1pp）。 一方hist_metric Top10は38.7%でベースラインを+6.7pp上回る。 Wilcoxon検定でhist-comp差は+8.8pp, p=0.002（有意）。 差枚でもcomp...

### 79. `segment-discovery-not-physical-gap`
- confidence: `0.95` | status: `unverified` | date: `2026-06-28` | file: `2026-06-28-multi-hall-segment-discovery-insights.yaml`
- domain/source: `hall-analysis-methodology` / `session-correction`
- trigger: 新ホールのセグメント判別を開始するとき
- summary: 台番号の連番ギャップ（gap検出）でフロア・島を自動推定するアプローチを試みたが、 ユーザーの意図するセグメント判別とは根本的に異なることが判明。 セグメントとは「ホールが設定投入戦略を変える集団の境界」であり、 差枚データから統計的に検出すべきもの。蒲田7のL/R分割のように、 物理的配置とは独立に戦略が変化す...

### 80. `mitoya-section-was-two-rows-merged`
- confidence: `1.00` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-section-split-and-corner-effect-insights.yaml`
- domain/source: `data-infrastructure` / `session-discovery`
- trigger: みとやのセクション定義・角番分析・rank_from_aisle を扱うとき
- summary: Heatmap/mitoya_omorimachi_floor_coordinates.csv で 557-590 のような34台セクションが、実際には2つの物理列（y=29: 557-573, y=28: 574-590）を1セクションにまとめていた。これにより rank_from_aisle が列単位ではなく...

### 81. `segment-determination-must-come-first`
- confidence: `0.98` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `analysis-methodology` / `session-design`
- trigger: 新ホールでEDAを開始するとき / セグメント未確定の状態で変数効果を分析しようとするとき
- summary: 蒲田7で全体集計のA機Top3(d3/d4)とN機Top3(d6/d8)が逆相関(ρ=-0.418)になるSimpson's Paradoxが発生。 セグメント未分割の状態で「末尾Xが強い」と主張しても、フロア/機種タイプ/セクションサイズの交絡で無意味になる。 1. フロア分割（複数フロアなら必須） 2. A/...

### 82. `kamata7-findings-not-transferable-procedure-is`
- confidence: `0.97` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `methodology` / `session-design`
- trigger: 蒲田7の知見を他ホールに適用しようとするとき / 他ホールで「末尾Xが強い」と主張するとき
- summary: 蒲田7と蒲田1（同系列マルハン）で曜日効果が完全に逆転している実証例がある: 蒲田7: 水曜最強(+1.5pp) / 金曜最弱(-4.2pp) 蒲田1: 火曜最強(+3.4pp) / 水曜弱い(-2.0pp) 末尾、DD、イベント日の法則もすべてホール固有。 移植可能なもの: 分析手順（KW検定→耐久性検証→th...

### 83. `kakuban-definition-requires-epsilon-comparison`
- confidence: `0.96` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `analysis-methodology` / `session-design`
- trigger: 新ホールで角番の定義を決めるとき / rank_from_min vs rank_from_max vs rank_from_aisle を選ぶとき
- summary: みとや大森町店で rank_from_aisle のε²=0.002482 vs rank_from_min のε²=0.000488 で5.1倍の差。 台番号の並び方向が島ごとに交互に逆転するホール（みとやなど）では、rank_from_minだけでは通路からの距離を正しく表せない。 1. 座標CSVがあれば、...

### 84. `add-debut-phase-index-alignment-bug`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-phase10efgh-deep-dive-insights.yaml`
- domain/source: `implementation-bug` / `session-observation`
- trigger: add_debut_phase の出力で debut_days が NaN になるとき
- summary: mitoya_prompt_common.py line 246 で pd.Series(debut_days, dtype=object) が group のインデックスと不整合を起こし、debut/growth/mature 行の debut_days が全行 NaN になっていた。Phase10e Step...

### 85. `mitoya-h-nonjug-oddeven-rank-noise-confirmed`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-corner-segment-effect-insights.yaml`
- domain/source: `hall-strategy-analysis` / `session-observation`
- trigger: みとやh_nonjugのrank偶奇パターンを検討するとき
- summary: Phase 10dでh_nonjug X_DDS日のfine rank分析でrank2,4がrank1,3,5を上回る偶奇パターンが見えたが、追加検証でノイズと確定。Odd vs Even MWU p=0.258。11セクション個別にdelta(even-odd)を計算すると+539～-209で符号がバラバラ。物...

### 86. `mitoya-no-pure-digit-effect`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-digit-durability-insights.yaml`
- domain/source: `hall-strategy` / `durability-test`
- trigger: みとやの台番号末尾を台選びに使おうとするとき
- summary: Phase 10b で h_jug の非イベント日末尾 KW が p=6.2e-7 と強有意だったが、Phase 10c の耐久性検証で machine_dependency が FAIL（d4 の top2_share=96.0%）。台674（658-674の角番1、マイジャグラーV）が d4 全体の avg_...

### 87. `mitoya-v-nonjug-avoid-segment`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-segment-validation-insights.yaml`
- domain/source: `hall-strategy` / `segment-validation`
- trigger: みとやの台選び・推薦リストを作成するとき
- summary: v_nonjug（692-700, 701-711, 745-755）はavg_diff=-119で全角番帯マイナス（corner1=-282, corner2-4=-107, corner5-9=-115, corner10+=-32）。バラエティ島で設定投入が薄い。5セグメント分割の交互作用検証でこのセグメン...

### 88. `mitoya-shortlist-min-n-and-existence-check`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-section-split-and-corner-effect-insights.yaml`
- domain/source: `ml-methodology` / `session-debugging`
- trigger: みとやのshortlist・バックテスト・機種選定を実装するとき
- summary: Phase 7 shortlist バックテストで、学習窓の avg_diff 上位機種がテスト窓に存在しないケース（撤去済み機種）が大量発生。犬夜叉2（n=37, pre_existing, 撤去済み）が学習窓で1位を取りテスト窓で空振りし、591-623 で X_DDS=-1017 の壊滅的結果を出した。また...

### 89. `hall-analysis-procedure-six-phases`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `methodology` / `session-design`
- trigger: 新しいホールの分析を開始するとき / 蒲田7以外のホールにMLモデルを適用するとき
- summary: 2026-06-27 蒲田7で確立した分析手順を一般化し、document/plans/hall-analysis-procedure.mdとして手順書化。 蒲田7での地雷（Simpson's Paradox、角番定義誤り、イベント日流用、鉄台除外忘れ等）を回避する構造化されたフローを設計。 Phase 0(デー...

### 90. `kakuban-is-model-backbone-not-auxiliary`
- confidence: `0.95` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-kakuban-ablation-and-dd-boost-insights.yaml`
- domain/source: `ml-feature-importance` / `walk-forward-ablation`
- trigger: 角番特徴量の重要度を評価するとき、または角番を補助特徴量として扱おうとするとき
- summary: 角番（kakuban）が「あると少し良くなる補助特徴量」か「モデルの根幹」かを判定するため、v12b_debut_multiplier_half から角番依存を完全に除去した v12b_no_kakuban との対称ablation実験を実施。c1/c2/c3/c4の全4コンポーネントから角番を除去。 角番を外す...

### 91. `lookahead-detection-by-reimplementation`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-lookahead-and-pipeline-insights.yaml`
- domain/source: `ml-evaluation` / `bug-fix`
- trigger: walk-forward検証で有望な結果が出たとき / リランキングやフィルタの効果を検証するとき / scored DataFrameの列を後処理で使うとき
- summary: 2026-06-26 Track D。seg_percentileリランキングの初回検証で+108枚/日（p=0.000003）という 高度に有意な結果が出た。しかしpool_n sweepで別実装を走らせたところ結果が再現せず、 原因を追ったらstrength_weightの計算に当日の `diff_coins...

### 92. `v12-debut-multiplier-machine-name-not-number`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-v12-debut-multiplier-walkforward-insights.yaml`
- domain/source: `implementation` / `bug-fix`
- trigger: debut_dateやpre_existingを計算するとき / 機種の初出日をgroupbyで算出するとき
- summary: 2026-06-26 V12実装時のバグ。初回walk-forwardでV11/V12a/V12bの全指標が完全一致。 `train.groupby("machine_number")["date_dt"].min()` でdebut_dateを計算していた。 同じ台番号に異なる機種が入れ替わっても（新台入替）、...

### 93. `debut-181plus-definition-caveat`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-grouping-debut-event-insights.yaml`
- domain/source: `data-definition` / `session-observation`
- trigger: 181日+フェーズの分析結果を解釈するとき / 定番台の定義を確認するとき
- summary: 2026-06-26 セッションで確認。debut_phase分析ではpre_existing=Trueの機種を除外している。 181日+ = DB開始日（蒲田7: 2025-07-07）以降に導入され、181日以上経過した機種 pre_existing（DB開始日に既に存在していた機種）は除外済み 蒲田7の場合...

### 94. `model-vs-random-segment-divergence`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-significance-test-design-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: MLモデルのセグメント別実用性を評価するとき
- summary: v6a/v9cの有意性検定で、モデル間比較（v6a vs v9c）よりも本質的な問いとして「そもそもモデルはランダムより良い台を選べているか」を検定した。結果、セグメントごとにモデルの実用性が劇的に異なることが判明。 モデル評価では必ず vs ランダム検定（H0: avg_diff_vs_other = 0）をセ...

### 95. `insample-cv-overfitting-guard`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-significance-test-design-insights.yaml`
- domain/source: `ml-methodology` / `session-analysis`
- trigger: 重み最適化やモデル改善をインサンプルで評価するとき
- summary: セグメント別重みをインサンプルで検証したところ、2F_R_N非イベント日が+114(p=0.008)で「ADOPT」判定。しかし4-fold temporal CVでは-2に崩壊し、完全な過学習だった。3F_L_Nイベント日も+208(in-sample) → -38(CV)で同様。 重み最適化は必ず4-fold...

### 96. `3fln-3frn-subtype-composition-divergence`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-significance-test-design-insights.yaml`
- domain/source: `segment-structure` / `session-analysis`
- trigger: 3F_L_Nまたは3F_R_Nのモデル性能を分析・改善するとき
- summary: 3F_L_Nでモデルが機能しない原因を調査。3F_L_Nと3F_R_Nの機種構成を比較した結果、決定的な構造差が判明。 3F_L_Nでのモデル改善は、セグメント内の機種異質性を解消する方向で行うべき。選択肢: 1. 沖ドキ/GODをサブセグメントとして分離し、別ルールを適用 2. 機種サブタイプをスコアリング特徴...

### 97. `v12b-near-random-performance-10day`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-predict-gated-10day-operational-test-insights.yaml`
- domain/source: `ml-evaluation` / `session-observation`
- trigger: predict_gated実運用評価・モデル性能議論時
- summary: 2026-06-16〜06-25の10日間でpredict_gated(v12b_debut_multiplier_half)を実行し、 Top50推奨台の実績を検証した。hit@50 rate=8.2%（ランダム期待値≈8.5%）、 勝率=40.8%、平均percentile=53.1%と、統計的にランダム選択...

### 98. `scored-pool-streaming-csv-fix`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-lookahead-and-pipeline-insights.yaml`
- domain/source: `implementation` / `bug-fix`
- trigger: walk-forward backtestを長時間実行するとき / メモリエラーが発生するとき
- summary: 2026-06-26 修正。walk-forward backtestがscored_poolをリスト蓄積してメモリ枯渇していた問題を修正。 scored_poolの各DataFrameを scored_pool.csv に都度追記（mode="a"） メモリには直近10日分（scored_pool_tail）の...

### 99. `predict-daily-pipeline-created`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-lookahead-and-pipeline-insights.yaml`
- domain/source: `implementation` / `implementation`
- trigger: 蒲田7の日次予測を実行するとき / predict_gated.pyを手動で実行するとき
- summary: 2026-06-26 実装。3ステップの手動実行を1コマンドに統合。 python -m ml.experiments.walkforward_scoring.predict_daily --skip-scrape --skip-db python -m ml.experiments.walkforward_sc...

### 100. `seg-percentile-reranking-verified`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-track-d-seg-percentile-reranking-insights.yaml`
- domain/source: `ml-evaluation` / `full-walkforward-validation`
- trigger: Top50選抜方法を検討するとき / リランキング戦略を比較するとき / predict_gated.pyの出力を改善するとき
- summary: 2026-06-26 Track D。V12bのTop50選抜後にseg_percentileリランキングを適用する効果を検証。 strength_weightに `scored["diff_coins_normalized"]`（当日実績）を使用。 結果: +108枚/日, p=0.000003。**ルックアヘ...

### 101. `walkforward-memory-limit-scored-pool-accumulation`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-track-b-a1-evaluation-insights.yaml`
- domain/source: `implementation` / `bug-encounter`
- trigger: walk-forward backtestがメモリエラーで落ちるとき / scored_poolのサイズが問題になるとき
- summary: 2026-06-26 Track A1実行時。V11+V12b（2バリアント, window=90, 260日）のwalk-forwardが 100タスク目付近でMemoryError。scored_poolがDataFrameリストとして蓄積される。 1. scored_pool を都度CSVに追記し、メモリか...

### 102. `payout-rate-weighted-avg-mandatory`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-track-b-a1-evaluation-insights.yaml`
- domain/source: `ml-evaluation` / `implementation-fix`
- trigger: payout_rateを計算するとき / walk-forward評価指標を追加・修正するとき / 台別meanで集計しようとするとき
- summary: 2026-06-26 Track B実装。従来のpayout_rate計算は台別に `(games*3+diff)/(games*3)*100` を計算してから `.mean()` を取っていた。 これはgames=100の台（payout 200%）とgames=8000の台（payout 101%）を同じ重み...

### 103. `grouping-hall-strategy-heterogeneity-confirmed`
- confidence: `0.95` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-grouping-debut-event-insights.yaml`
- domain/source: `hall-behavior` / `empirical-analysis`
- trigger: 全ホール横断の汎化法則を探索しようとするとき / ホール間比較で共通パターンを前提とするとき
- summary: 2026-06-26 全9ホール横断EDA（経過日数/設置台数/区間成績の3軸検証）。 経過日数が進むほどavg_diffが改善する単調パターンは全9ホールで再現 全ホールでKruskal-Wallis p<0.01 1. **プラス圏到達**: 好設定ホール（蒲田7/蒲田1/楽園/ARROW/みとや）は61-1...

### 104. `single-day-dependency-leave-one-out-required`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-significance-test-design-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: avg_diffやavg_diff_vs_otherの平均ベース検定を行うとき
- summary: 2F_L_N std=3003はDD07の+12,920が、3F_L_NはDD28の+6,126が平均を正に見せている。 ブートストラップやt検定の平均ベース結論は、この1日に支配される。 Wilcoxon（中央値）や符号検定（勝敗0/1）は外れ値に頑健だが、 平均系の指標を使う場合はleave-one-day-...

### 105. `significance-test-unit-is-day-not-machine`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-significance-test-design-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: v6a/v9b/v9cのモデル間比較を統計的に検定するとき
- summary: 同一日内の台は独立でない。v9cは特定台番号を連日選択する（リピート台）。 台を1標本にすると独立性仮定が崩れ、p値が過小（偽陽性率上昇）になる。 各日に全variantが同じ台プールをスコアリングするため、日単位でモデルがペアになる。 ペア化で「当たり日/外れ日」の共通変動が相殺され検出力が上がる。 ブートスト...

### 106. `lift-daily-mean-is-statistically-wrong`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-significance-test-design-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: lift_t指標を日次で平均して集約するとき
- summary: lift = hit/expected の比率を日次で出して平均するのは数学的に不正確。 正しい集約量はプール比 Σhit/Σexpected。 現状 _aggregate_daily_results および segment_daily は日次liftの .mean() を取っている。 これはレポート用の概算とし...

### 107. `event-day-subset-underpowered`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-significance-test-design-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: イベント日サブセットでモデル比較を行うとき
- summary: 28日間バックテストでイベント日はわずか6日。256日間でも30-40日程度。 符号検定で勝率83%(5/6)をp<0.05にするにはN≥6でちょうどギリギリ（片側p=0.109）。 つまり「イベント日はv6aが強い」はサンプル数的に確定不能。 イベント日サブセットの結論は「定性的傾向」に留め、「有意に優れている...

### 108. `claude-code-background-task-timeout-10min`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-catboost-v2-optimization-insights.yaml`
- domain/source: `tooling` / `session-observation`
- trigger: Claude Codeのバックグラウンドタスクで長時間ジョブを実行しようとするとき
- summary: CatBoost v2フル実行（257日、推定104分）をClaude Codeのrun_in_backgroundで起動したところ、 70/257日（27%）の時点でタイムアウトにより強制終了された。 Bashツールのrun_in_backgroundパラメータは最大600秒（10分）の制限がある。 ML実験な...

### 109. `segment-baseline-comparison-required`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-high-rotation-evaluation-and-machine-bias-insights.yaml`
- domain/source: `ml-evaluation` / `user-correction`
- trigger: Top50の高回転率をセグメント間で比較するとき
- summary: Top50中の5000G+率だけでは、それがモデルの選別力なのかセグメント自体の特性なのか区別できない。 ベースライン（全台の5000G+率）との比較で初めてliftが計算できる。 実測ベースライン: 3F_R_A=46.8%, 3F_L_A=45.2%, 3F_R_N=34.5%, 2F_L_N=27.2% A...

### 110. `ntype-high-rotation-three-factors`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-high-rotation-evaluation-and-machine-bias-insights.yaml`
- domain/source: `pachinko-domain` / `user-domain-knowledge`
- trigger: N-type（AT機）の高回転台を評価指標に使おうとするとき
- summary: AT機の高回転は3つの要因で発生する: 1. 新台 — 打ちたいだけで座る（例: 戦国乙女5, avg_diff=-1,184で回されている） 2. 人気台 — 設定不問で回る機種（例: カバネリ海門, avg_diff=-1,466） 3. 高設定 — 実際に設定が入っている 7日間のサンプルではこれらの分離が...

### 111. `high-rotation-lift-all-models-below-1`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-high-rotation-evaluation-and-machine-bias-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: 高回転台の捕捉率でモデル評価するとき
- summary: v6a/v9b/v9cいずれもTop50の5000G+率はランダム期待以下（lift 0.74〜0.998）。 差枚ベースでスコアリングしている以上、高回転台が上位に集中する保証はない。 ただしv9cだけは6000G+でlift=0.998（ほぼランダム同等）まで維持。 v6a/v9bは0.74まで落ちる。v9c...

### 112. `v9c-percentile-eliminates-weak-segments`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-threshold-evaluation-and-model-comparison-insights.yaml`
- domain/source: `ml-model-design` / `session-analysis`
- trigger: v9c_percentileモデルの台配分を確認するとき
- summary: v9cの最終スコア = seg_percentile × seg_weight。 seg_weightは訓練データのセグメント別平均diffから算出（強=1.0, 弱=0.5）。 3F_R_N（avg_diff≈-9）はweight≈0.5なので、セグメント内1位でも スコア=1.0×0.5=0.5にしかならず、...

### 113. `top50-border-exceeds-setting6-ceiling`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-threshold-evaluation-and-model-comparison-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: lift@50やhit@50でモデル評価を行うとき
- summary: 実際のTop50ボーダー（50番目に差枚が高い台）は平均+4,100枚、最低日でも+3,100枚。 設定6の最高機械割114.9%で実質8000G回して約+3,500枚が現実的上限。 つまりTop50に入るには「高設定＋上振れ」が必要で、設定6を普通に回しただけでは届かない。 +3,100（最低日）こそ真の設定6...

### 114. `threshold-lift-increases-with-stricter-threshold`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-threshold-evaluation-and-model-comparison-insights.yaml`
- domain/source: `ml-evaluation` / `session-analysis`
- trigger: 閾値ベースliftの結果を解釈するとき
- summary: lift_t2500 < lift_t3500 < lift_t4500 という結果は直感に反するが正常。 liftはランダム比であり、閾値を上げるとランダム期待hitは比例して減るが、 モデルの当たり台は差枚分布の上位に集中しているため減り方が緩やか。 結果として相対優位（lift）は閾値が厳しいほど拡大する。...

### 115. `atype-vs-at-evaluation-must-separate`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-threshold-evaluation-and-model-comparison-insights.yaml`
- domain/source: `ml-evaluation` / `session-observation`
- trigger: Aタイプ（ジャグラー・ハナハナ）とATタイプを含むモデル評価時
- summary: ATもAタイプも最高機械割は114.9%で同じ。しかしAタイプは設定6の機械割が低めに設定される ケースが多く、差枚で+2,500に届きにくい。全体Top50で評価するとATの大当たり台に 正解ラベルが偏り、Aタイプの高設定台を正しく拾っても「外れ」扱いになる。 Aタイプのlift_t指標は全閾値で1.0以下だが...

### 116. `atype-high-games-is-hall-level-signal`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-threshold-evaluation-and-model-comparison-insights.yaml`
- domain/source: `pachinko-domain` / `user-domain-knowledge`
- trigger: Aタイプの回転数（games_normalized）を解釈するとき
- summary: Aタイプ（ジャグラー・ハナハナ）は遊技中の設定示唆がほぼ無い。 個別の台が高回転なのは「その台を高設定と判断した」からではなく、 「この店がAタイプに設定を入れている」という店全体への信頼で打ち続ける人が多いため。 設定判別ができない打ち手のだらだらプレイも回転を押し上げる。 設定が入っていない店のジャグラーの回...

### 117. `daily-hall-summary-weekday-nth-mostly-null`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-sat-triplet-window-eda-insights.yaml`
- domain/source: `data-engineering` / `session-observation`
- trigger: daily_hall_summaryのweekday_nthを使って曜日フィルタをかけるとき
- summary: Codexが土曜フィルタを実装した際に発見。 蒲田7の daily_hall_summary で weekday_nth は大半がNULL。 値が入っている行でも形式は 'Sat1'/'Sat2'等の英語表記で、'土1'等の日本語表記ではない。 weekday_nth LIKE '土%' をそのまま使うとほぼ全行...

### 118. `v10-dow-kakuban-boost-monotonic-failure`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-v10-boost-scaling-failure-insights.yaml`
- domain/source: `ml-feature-engineering` / `empirical-backtest`
- trigger: 残差分析で有意な交互作用をスコアリングファクターに変換しようとするとき
- summary: 残差法で3F_L_Aの曜日×角番交互作用が高度に有意（木q=1e-13、火q=2.6e-12）であることを確認。 これをc1に乗数ブーストとして実装（v10a: scale=1.0, v10d: scale=0.25, v10e: scale=0.50）。 結果: ブースト倍率を小さくするほどv6aに近づくが決し...

### 119. `wed-digit-top-identity-random`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-wed-digit-event-deepdive-insights.yaml`
- domain/source: `kamata7-event-pattern` / `session-eda-2026-06-23`
- trigger: 水曜のトップ末尾を事前予測しようとするとき
- summary: 346日のカイ二乗検定で2F_L_A（末尾7, p<0.0001）と2F_R_A（末尾4, p=0.001）に偏りがあるが、 これはAT機の物理的配置要因であり、水曜固有ではない。 水曜限定の前半vs後半安定性は0/8（完全不一致）。 水曜のトップ末尾を事前予測するモデルは構築しない 全体avg_diffでのトッ...

### 120. `analysis-granularity-changes-conclusions`
- confidence: `0.95` | status: `unverified` | date: `2026-06-23` | file: `2026-06-23-residual-weekday-segment-kakuban-insights.yaml`
- domain/source: `analysis-methodology` / `empirical-analysis`
- trigger: 角番・セグメント・曜日の分析で結論を出すとき
- summary: 2026-06-17: A/N 2分割の残差分析 → 「曜日×角番はセクション効果の混入で消える」 2026-06-23: 6セグメント分解の残差分析 → 「3F_L_Aの曜日×角番交互作用は有意に残る(q=1e-13)」 A/N分割では3F_L_Aの強いシグナルが他のA機サブセグメントのノイズで希釈された。 角...
