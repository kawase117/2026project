# ACTIVE_INSTINCTS

- generated_at: 2026-10-29T08:13:36+09:00
- compiler_version: 1.3.0
- source_dir: `C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/document/instincts`
- total_records_scanned: 1693
- active_records: 120
- status_breakdown: unverified=1682, confirmed=2, refuted=0, superseded=8
- filters: `confidence >= 0.80` and `file_date within 21 days` (unless pinned by high confidence)

## Usage
- Start of work: run `venv\Scripts\python.exe scripts/compile_instincts.py` (or `python scripts/compile_instincts.py`).
- Long sessions: rerun before major decisions or every 15-20 minutes.
- Preferred source for Codex: `ACTIVE_INSTINCTS.jsonl` (machine-readable canonical).
- This Markdown is a quick view. Open raw YAML only when detail is missing.
- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed.

## Active List

### 1. `quick-scrape-check-observed-at-per-hall-before-reporting`
- confidence: `0.80` | status: `unverified` | date: `2026-10-23` | file: `2026-10-23-quick-scrape-stale-and-small-sample-date-rule.yaml`
- domain/source: `realtime-scraping` / `session-2026-10-22-quick-scrape`
- trigger: クイックスクレイピング（scraper.realtime.run --mode quick）を実行した直後に、ランキングや列の合算RBを報告しようとするとき。楽園蒲田（サイトセブン）の結果を報告するとき。『収集は完走した』と書きたくなったとき

### 2. `prediction-autodraft-claims-must-be-rechecked-against-raw-announce`
- confidence: `0.80` | status: `unverified` | date: `2026-10-22` | file: `2026-10-22-prediction-autodraft-review.yaml`
- domain/source: `prediction-workflow` / `session-2026-10-21-prediction-and-answercheck`
- trigger: output/morning_docs や document/reviews の予測下書き（auto-morning-docs）を、人が読んで直すとき。蒲田1・蒲田7・楽園の予告が下書きに載っていて、そのまま根拠に使いたくなったとき。下書きが『避ける』『0の付く日』『前日に...

### 3. `external-site-scraper-needs-real-html-and-live-run-before-done`
- confidence: `0.80` | status: `unverified` | date: `2026-10-21` | file: `2026-10-21-instincts.yaml`
- domain/source: `scraper-verification` / `session-2026-10-21-dmm-model-page`
- trigger: ヒロキ東口・MAX・西口のDMM収集(scraper/dmm_goraggio/collector.py)、ana-slo、サイトセブン、ダイデータなど外部サイトの収集コードをCodexに委任して直したとき。単体テストが全部通ったので『完了』と報告したくなったとき。Code...
- summary: 2026-10-20〜21、DMM(ヒロキ3店舗)のクイック収集で、AT機の累計回転数が欠損していた。累計回転数は機種ページ(unit_list)にあるので、Codexに機種ページから取る実装を委任した。 Codexのテストは自作のHTML断片で、62→68→72→77件と通り続けたが、実収集では3回続けて失敗し...

### 4. `score-share-claims-by-high-setting-share-not-diff-threshold`
- confidence: `0.80` | status: `unverified` | date: `2026-10-20` | file: `2026-10-20-announce-share-claims-and-avoid-rule.yaml`
- domain/source: `announce-scoring` / `session-2026-10-17-answercheck-eureka-jug20`
- trigger: 予告の『ジャグ20%⑤⑥』『エウレカが1/3』『◯機種の1/2』など、台のうち何割が高設定(456)という主張を採点・答え合わせするとき。announce score の category_share や model_named_ratio で『外れ』と出たとき。機械割が低...
- summary: 2026-10-17の答え合わせで、楽園の予告「ジャグ20%⑤⑥」と「エウレカが1/3」が、従来の判定で「外れ」になった。ユーザーに「ジャグ20%はジャグラーの20%が高設定(456)という意味」「エウレカの1/3が高設定という意味で、機械割が低めの機種はこの測り方では実態をつかめない」と指摘された。 従来のジャ...

### 5. `aggregate-rb-by-section-before-reading-units`
- confidence: `0.80` | status: `unverified` | date: `2026-10-20` | file: `2026-10-20-section-rb-and-unstated-pledge-scoring.yaml`
- domain/source: `realtime-scan` / `session-2026-10-18-higashiguchi-warikiri`
- trigger: 営業中のクイックスキャンで、台ごとの設定5以上の確率(補正なし、4設定機は0.5前後)を見て『目立つ台がない』『補正なしの表は割り引いて混ぜない』と流しそうなとき。予告の『列全体』『半列』『島』を営業中データで探すとき。ヒロキ東口・MAX・西口の取材日に、その日が強い日かを...
- summary: 2026-10-18(日)のヒロキ東口(割／切リサーチ来店取材)で、13:31の最初のスキャンに答えが出ていたのに、見落とした。 マイジャグラーVの列(2053〜2067、12台): 合算23,184GでRB113(1/205)。設定平均なら期待約75回で、偶然に起きる確率は3.4×10⁻⁵。台ごとの事後確率は0...

### 6. `model-mean-outlier-check-median`
- confidence: `0.80` | status: `unverified` | date: `2026-10-20` | file: `2026-10-20-mean-vs-median-and-new-machine-day.yaml`
- domain/source: `scoring` / `answercheck-2026-10-19`
- trigger: 機種単位の平均差枚で『当たり』『列仕掛け』『台数の多い機種に投入』と判定するとき。答え合わせで推した機種の平均がホール平均を上回ったとき

### 7. `check-spec-judgeable-before-saying-unjudgeable`
- confidence: `0.90` | status: `unverified` | date: `2026-10-18` | file: `2026-10-18-judgeable-check-and-target-existence.yaml`
- domain/source: `setting-estimation` / `session-2026-10-16-rakuen-3135-thunder-v`
- trigger: AT機・BT機・スマスロ(サンダーV、スマスロハナビ、北斗など)の設定を、ボーナス確率やRBで判別できるか答えるとき。『ボーナス確率では判別できない』『判別不能』と言いたくなったとき。台の設定推定を機種ごとに出すとき
- summary: 2026-10-16、楽園3135(スマスロ サンダーV)で、ユーザーが「BB中のバラけ目が出たのでほぼ設定5・6」と申告した。私は台データ(440G、BB1・RB1)を見て「サンダーVはボーナス確率で判別できる機種ではない」と断言したが、これは確認せずに書いた誤りだった。ユーザーに「サンダーはボーナス確率で判別...

### 8. `at-rb-audit-regenerate-changes-other-halls`
- confidence: `0.90` | status: `unverified` | date: `2026-10-16` | file: `2026-10-16-togoshi-rb-games-confound-audit-append.yaml`
- domain/source: `data-integrity` / `togoshi-at-rb-audit-append-20261016`
- trigger: 新しいホールをDBに追加して、backtest.at_rb_audit を実行するとき。AT_RB_AUDIT.csv を再生成・上書きしたくなったとき。他ホールのAT機判定が急に変わったとき
- summary: 2026-10-16、戸越銀座をDBに追加したあと `python -m backtest.at_rb_audit` を実行すると、全ホールの行が書き直された。ホール間のばらつき(across_ratio)に新ホールが加わるため、他ホール4件の判定が変わった: 楽園蒲田のからくりサーカス・禁書目録2が A→B、A...

### 9. `anaslo-closed-day-page-all-same-diff`
- confidence: `0.85` | status: `unverified` | date: `2026-10-16` | file: `2026-10-16-scoreboard-and-closed-days.yaml`
- domain/source: `data-quality` / `data-audit-closed-days-20261016`
- trigger: ana-sloのデータで全台のG数が0、差枚が全台同じ値(-6,142など)の日を見つけたとき。ホールの休業日・改装日・入替日を扱うとき。日別の平均差枚に異常な落ち込みがあるとき
- summary: 楽園蒲田の 2025-04-21(入替)・2026-07-06(改装)は、全台 G数0・BB/RB なし・差枚が全台 -6,142(ホール平均らしき値)のページが取り込まれていて、1日あたり約-350万枚の偽の差枚がホール・機種・末尾の集計に混ざっていた。G数0のフィルタでは差枚が残るので救えない。 増分取り込み...

### 10. `rb-deviation-rises-with-games-show-raw-and-controlled`
- confidence: `0.80` | status: `unverified` | date: `2026-10-16` | file: `2026-10-16-togoshi-rb-games-confound-audit-append.yaml`
- domain/source: `statistics` / `togoshi-rb-weekday-games-confound-20261016`
- trigger: RB確率やボーナス確率の標準化残差(z)を、曜日・土日・日付・イベント日で比べるとき。『日曜はRBが良い』『土日に高設定が入る』と読みたくなったとき。回転数が多い日ほどRBが高く見えるとき
- summary: 2026-10-16、BIGディッパー戸越銀座のRB判別可能機種で、機種ごとのプールRB率からの標準化残差を曜日別に見ると、日曜が最大(ANOVA p=0.001)で、土日−平日は +0.12(日単位 p=0.003)と出た。しかし行を回転数の四分位で分けると、zは -0.65(約2,200G)→ -0.38 →...

### 11. `daidata-rb-column-zero-gap-by-machine`
- confidence: `0.80` | status: `unverified` | date: `2026-10-15` | file: `2026-10-15-mitoya-rb-gap-and-template-days.yaml`
- domain/source: `data-quality` / `mitoya-disc-up-745-rb-gap-20261014`
- trigger: みとやなどダイデータ由来のDBで、特定の台のRBが数日連続で0になっているのを見つけたとき。ディスクアップ745のRBが異常に少ないとき。設定推定・RB確率で台を評価する前
- summary: 2026-10-14、みとやのディスクアップ745の設定推定で、10/4のRBが5,729Gで0回と出た。ユーザーが「設定1でも少なすぎる、データエラーでは」と指摘し、確認すると745は9/28〜10/4の7日連続(9/2にも1日)でRB=0、BBは10〜33回あり、RB列だけが欠けていた。他の台のRB=0は通常...

### 12. `first-time-event-hypothesis-dont-count-annual-events`
- confidence: `0.90` | status: `unverified` | date: `2026-10-13` | file: `2026-10-13-first-time-event-dont-count-annual-events.yaml`
- domain/source: `event-hypothesis-ledger` / `user-correction`
- trigger: 『初取材・初イベント日はホールが力を入れる』の観測を数えるとき。kawasakislotなどの予告に『初』『🔰』『周年煽りは初』とあるとき。周年・記念日・毎年恒例のイベントを初イベントの観測として台帳に加算しようとしたとき

### 13. `pooled-lift-across-models-is-composition-use-within-group-baseline`
- confidence: `0.90` | status: `unverified` | date: `2026-10-13` | file: `2026-10-13-pooled-lift-is-composition-use-within-group.yaml`
- domain/source: `statistical-method` / `session-observation`
- trigger: ホール全体や複数機種を混ぜて、前日の条件（RB良・差枚・過去7日）ごとの翌日の高設定確率の上乗せを集計するとき。『全体比』『ホール全体で+0.0X』という数字を持ち越し・据え置きの証拠にしようとしたとき。蒲田7・蒲田1・楽園・みとやのジャグラーで群別集計をするとき

### 14. `spec-source-mismatch-check-with-payout-rate`
- confidence: `0.90` | status: `unverified` | date: `2026-10-13` | file: `2026-10-13-spec-source-mismatch-payout-check.yaml`
- domain/source: `bonus-spec-validation` / `session-observation`
- trigger: ジャグラーなど機種のBB・RBスペック（bonus_specs / find_spec / machine_master.csv / JUGGLER_FAMILY_SPECS）を使う推定の絶対水準が他機種と比べて不自然に高い・低いとき。スペックを追加・修正するとき。コメント...

### 15. `carryover-test-use-likelihood-model-not-daily-correlation`
- confidence: `0.85` | status: `unverified` | date: `2026-10-13` | file: `2026-10-13-carryover-test-use-likelihood-not-correlation.yaml`
- domain/source: `statistical-method` / `session-observation`
- trigger: 台や機種の設定の据え置き・持ち越し・連続日の相関を検定して『効果なし』『確認できない』と結論したくなったとき。1日のBB・RB・差枚の日別相関（lag1）や、前日の強い台の翌日の平均で据え置きを判定しようとしたとき。ジャグラーの据え置き分析をするとき

### 16. `announce-wrong-binding-void-never-delete`
- confidence: `0.90` | status: `unverified` | date: `2026-10-12` | file: `2026-10-12-announce-wrong-binding-void-not-delete.yaml`
- domain/source: `announce-ledger` / `session-observation`
- trigger: 予告の下書き（announce_autodraft）が別店・別日・結果発表に紐付いていたとき。予告JSONを削除・改名したくなったとき。登録済みの予告の日付やホールを直したいとき

### 17. `pachibo-pcb-has-machine-number-csv-does-not`
- confidence: `0.85` | status: `unverified` | date: `2026-10-12` | file: `2026-10-12-pachibo-pcb-machine-number.yaml`
- domain/source: `data-source` / `session-observation`
- trigger: ユーザーの遊技履歴（ぱち簿）から台番号が要るとき。ぱち簿のCSVに台番号が無いと気づいたとき。.pcbファイルを渡されたとき。自分の打った台と日別・直近の実績を突き合わせるとき

### 18. `shinhanabi-payout-interpolate-by-miss-rate`
- confidence: `0.80` | status: `unverified` | date: `2026-10-12` | file: `2026-10-12-shinhanabi-payout-by-miss-rate.yaml`
- domain/source: `machine-spec` / `user-explanation`
- trigger: 新ハナビの期待値・機械割を計算するとき。97.7%と102.0%のどちらを使うか迷ったとき。『設定1でも機械割100超えのはずなのに負ける』と言われたとき。台全体の差枚/Gを機械割に換算して設定を読もうとするとき

### 19. `axis-tables-must-share-event-exclusion`
- confidence: `0.85` | status: `unverified` | date: `2026-10-09` | file: `2026-10-09-axis-tables-must-share-event-exclusion.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: 曜日別とDD別など、複数の軸の表を同じ分析で並べるとき。『イベント日を除いて』と言われたとき。イベントDD集合(1・4・7・14・17・24・27・30)だけで周年日や取材日を除いたつもりになるとき(みとや・楽園)

### 20. `poisson-chi2-overstates-weekday-difference`
- confidence: `0.80` | status: `unverified` | date: `2026-10-09` | file: `2026-10-09-poisson-chi2-overstates-weekday-difference.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: 曜日別やDD別のRB確率の差を、総GとRB回数のPoissonカイ二乗で検定して『有意』と書きたくなったとき。日ごとに設定が動く機種(ディスクアップ等)の軸比較で、有意性を報告するとき

### 21. `discup-diff-and-winrate-follow-games-not-setting`
- confidence: `0.80` | status: `unverified` | date: `2026-10-09` | file: `2026-10-09-discup-diff-and-winrate-follow-games-not-setting.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: ディスクアップ(A+AT。完全攻略の機械割が設定1でも100%超)の強い曜日・DD・台を探すとき。みとやや楽園のディスクアップで、差枚・勝率・出率が良い日を『設定が高い日』と書きたくなったとき

### 22. `2026-10-07-spec-source-mismatch-versus`
- confidence: `0.85` | status: `unverified` | date: `2026-10-07` | file: `2026-10-07-spec-source-mismatch-versus.yaml`
- domain/source: `setting-estimation` / `user-confirmed-20261006`
- trigger: バーサスリヴァイズなど、同じ機種のスペックが一撃の複数ページ(スペックページと設定判別ページ)や、プロジェクトのスペック(bonus_specs、config.py)と食い違うとき。ユニメモの設定推測と、当方の事後確率が合わないとき。4設定機(設定1・2・5・6)の設定近似...
- summary: バーサスリヴァイズのBB・RBは、一撃のスペックページ(マスターCSV由来、旧スペック)と、設定判別ページ(/s_versus_rexse/0/)で約10%違う。 設定1→6のBBは、設定判別ページが1/292.6→1/264.3、旧スペックが1/264.3→1/237.4。RBは、1/374.5→1/292.6...

### 23. `rb-probability-decimal-null-on-zero-count`
- confidence: `0.98` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: rb_probability_decimal または bb_probability_decimal / total_probability_decimal に notna() / IS NOT NULL / > 0 のフィルタをかけようとするとき
- summary: `rb_probability_decimal` は `rb_count / games_normalized` から作られる派生列だが、 `rb_count == 0` の行では NULL になる（9ホール全てでNaN率とRB0回率が完全一致、 rb_count>0でNULLの行は0件）。`bb_probabi...

### 24. `machine-layout-single-snapshot-breaks-across-renovation`
- confidence: `0.97` | status: `unverified` | date: `2026-07-24` | file: `2026-07-24-deathwatch-rb-null-bug-and-layout-history-insights.yaml`
- domain/source: `data-quality` / `session-observation`
- trigger: machine_layoutを使って過去データに位置(section/rank_from_*)を結合するとき、または改装・島配列変更があったホールの位置分析を行うとき
- summary: machine_layoutは日付次元を持たないため、改装で位置定義が変わると新しい位置が 過去データに遡って適用される。楽園蒲田の2026-07-06の改装でsection定義が 書き換わり(2223-2240→2225-2242等)、技術介入の端番効果が+1.127pp→+0.211pp(ns)に 変化した。...

### 25. `emulator-arm64-translation-requires-api34-plus`
- confidence: `0.97` | status: `unverified` | date: `2026-07-19` | file: `2026-07-19-maruhan-frida-arm64-translation-and-play-integrity-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: x86_64エミュレーターでarm64専用ネイティブライブラリを含む商用アプリを動かそうとするとき
- summary: API 33 (r17) google_apis x86_64は abilist=x86_64のみ、native.bridge=0で、arm64専用アプリは INSTALL_FAILED_NO_MATCHING_ABIS で弾かれる。API 34 (r14) は abilist=x86_64,arm64-v8a、...

### 26. `codex-desktop-agmsg-monitor-requires-cli-shim-not-desktop-app`
- confidence: `0.98` | status: `unverified` | date: `2026-07-09` | file: `2026-07-09-codex-desktop-agmsg-monitor-limitations.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: when expecting agmsg monitor-mode real-time delivery inside the Codex desktop app
- summary: Setting `agmsg` delivery mode to `monitor` for `codex` is not sufficient when the session is running inside the Codex desktop app. The monitor bridge only be...

### 27. `codex-agmsg-must-use-git-bash-on-windows`
- confidence: `0.99` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-agmsg-kamata7-dashboard-insights.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: Codex Desktop on WindowsからagmsgでClaude Codeと連絡するとき
- summary: Kamata7 dashboard計画でClaude Codeとagmsg連携した際、Codex側で `bash ...` をそのまま実行すると `C:\Users\apto117\AppData\Local\Microsoft\WindowsApps\bash.exe` 経由のWSL bashに流れ、`$HOM...

### 28. `agmsg-on-windows-use-git-bash-not-windowsapps-bash`
- confidence: `0.98` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `tooling-environment` / `session-observation`
- trigger: when sending agmsg messages from Codex Desktop on Windows
- summary: Using the WindowsApps `bash.exe` path can route the command into the wrong shell and produce empty or misleading agmsg sends. n_observations: 1 data scope: t...

### 29. `kamata7-theory-dashboard-needs-japanese-tabs-and-fallbacks`
- confidence: `0.97` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-instincts.yaml`
- domain/source: `dashboard-ui-patterns` / `session-observation`
- trigger: when building or revising the Kamata7 theory dashboard
- summary: The Kamata7 theory page is only useful when each tab explains its purpose in Japanese and falls back gracefully when a sample threshold removes all cells. n_...

### 30. `cross-agent-dashboard-workflow-claude-design-codex-implementation`
- confidence: `0.97` | status: `unverified` | date: `2026-07-08` | file: `2026-07-08-agmsg-kamata7-dashboard-insights.yaml`
- domain/source: `agent-coordination` / `session-observation`
- trigger: Claude CodeとCodexでdashboard機能を共同設計・実装するとき
- summary: Kamata7 dashboard拡張では、初期状態でCodexからClaudeへの相談文が届いたか不明になり、 ユーザーが両画面を中継して状況確認した。通信経路をGit Bashに固定した後、 Claude側が「Claude=設計・仕様・テスト戦略、Codex=実装」と役割を明示し、 `document/pla...

### 31. `v12b-composite-score-no-calibration`
- confidence: `0.98` | status: `unverified` | date: `2026-06-29` | file: `2026-06-29-v12b-calibration-failure-insights.yaml`
- domain/source: `ml-evaluation` / `walk-forward-calibration-60days`
- trigger: スコアリングモデルの予測結果をTop-Nで絞り込むとき、またはcompositeスコアに基づく台選択推薦を行うとき
- summary: v12b_debut_multiplier_halfのcompositeスコアと実際の104%超え確率の対応関係を、60日間のwalk-forward評価（42,840行）で検証した。 スコア十分位別の104%超え率はD0=32.9%からD9=32.8%まで実質フラットで、スコアの高低が的中確率をほぼ予測しない。...

### 32. `mitoya-section-was-two-rows-merged`
- confidence: `1.00` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-mitoya-section-split-and-corner-effect-insights.yaml`
- domain/source: `data-infrastructure` / `session-discovery`
- trigger: みとやのセクション定義・角番分析・rank_from_aisle を扱うとき
- summary: Heatmap/mitoya_omorimachi_floor_coordinates.csv で 557-590 のような34台セクションが、実際には2つの物理列（y=29: 557-573, y=28: 574-590）を1セクションにまとめていた。これにより rank_from_aisle が列単位ではなく...

### 33. `segment-determination-must-come-first`
- confidence: `0.98` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `analysis-methodology` / `session-design`
- trigger: 新ホールでEDAを開始するとき / セグメント未確定の状態で変数効果を分析しようとするとき
- summary: 蒲田7で全体集計のA機Top3(d3/d4)とN機Top3(d6/d8)が逆相関(ρ=-0.418)になるSimpson's Paradoxが発生。 セグメント未分割の状態で「末尾Xが強い」と主張しても、フロア/機種タイプ/セクションサイズの交絡で無意味になる。 1. フロア分割（複数フロアなら必須） 2. A/...

### 34. `kamata7-findings-not-transferable-procedure-is`
- confidence: `0.97` | status: `unverified` | date: `2026-06-27` | file: `2026-06-27-hall-analysis-procedure-and-evolve-insights.yaml`
- domain/source: `methodology` / `session-design`
- trigger: 蒲田7の知見を他ホールに適用しようとするとき / 他ホールで「末尾Xが強い」と主張するとき
- summary: 蒲田7と蒲田1（同系列マルハン）で曜日効果が完全に逆転している実証例がある: 蒲田7: 水曜最強(+1.5pp) / 金曜最弱(-4.2pp) 蒲田1: 火曜最強(+3.4pp) / 水曜弱い(-2.0pp) 末尾、DD、イベント日の法則もすべてホール固有。 移植可能なもの: 分析手順（KW検定→耐久性検証→th...

### 35. `lookahead-detection-by-reimplementation`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-lookahead-and-pipeline-insights.yaml`
- domain/source: `ml-evaluation` / `bug-fix`
- trigger: walk-forward検証で有望な結果が出たとき / リランキングやフィルタの効果を検証するとき / scored DataFrameの列を後処理で使うとき
- summary: 2026-06-26 Track D。seg_percentileリランキングの初回検証で+108枚/日（p=0.000003）という 高度に有意な結果が出た。しかしpool_n sweepで別実装を走らせたところ結果が再現せず、 原因を追ったらstrength_weightの計算に当日の `diff_coins...

### 36. `v12-debut-multiplier-machine-name-not-number`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-v12-debut-multiplier-walkforward-insights.yaml`
- domain/source: `implementation` / `bug-fix`
- trigger: debut_dateやpre_existingを計算するとき / 機種の初出日をgroupbyで算出するとき
- summary: 2026-06-26 V12実装時のバグ。初回walk-forwardでV11/V12a/V12bの全指標が完全一致。 `train.groupby("machine_number")["date_dt"].min()` でdebut_dateを計算していた。 同じ台番号に異なる機種が入れ替わっても（新台入替）、...

### 37. `debut-181plus-definition-caveat`
- confidence: `0.98` | status: `unverified` | date: `2026-06-26` | file: `2026-06-26-grouping-debut-event-insights.yaml`
- domain/source: `data-definition` / `session-observation`
- trigger: 181日+フェーズの分析結果を解釈するとき / 定番台の定義を確認するとき
- summary: 2026-06-26 セッションで確認。debut_phase分析ではpre_existing=Trueの機種を除外している。 181日+ = DB開始日（蒲田7: 2025-07-07）以降に導入され、181日以上経過した機種 pre_existing（DB開始日に既に存在していた機種）は除外済み 蒲田7の場合...

### 38. `infer-lr-must-use-x-coordinate`
- confidence: `0.99` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-lr-reversal-bug-and-v7-revalidation-insights.yaml`
- domain/source: `data-engineering` / `bug-discovery-and-fix`
- trigger: LR分割ロジックを実装・修正・レビューするとき
- summary: `_infer_lr()` は台番号の中央値でLRを分割していた（小さい方=L、大きい方=R）。 しかし蒲田7では島ごとに台番号の並び方向が反転する（奇数列は左→右、偶数列は右→左）。 結果として2Fの55.6%、3Fの57.7%のセクションで物理的な左右が逆転していた。 修正: X座標の中央値でLRを判定する。...

### 39. `walkforward-scoring-is-rule-based-not-ml`
- confidence: `0.99` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-classify-seg-db-flag-insights.yaml`
- domain/source: `ml-methodology` / `session-discussion`
- trigger: Walk-forward scoringモデルの位置づけを説明するとき
- summary: v1-v6のWalk-forward scoringモデルは手動設計のコンポーネント（c1-c6, hist特徴量）を 手動設定のウェイトで線形結合するルールベースのスコアリングシステム。 学習アルゴリズム・損失関数・パラメータ最適化プロセスが存在しない。 Walk-forwardは評価フレームワークであり、学習...

### 40. `hit100-equals-winrate-redundancy`
- confidence: `0.99` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-walkforward-v6-threshold-segment-insights.yaml`
- domain/source: `ml-feature-engineering` / `mathematical-identity`
- trigger: payout閾値100%を特徴量候補に含めるとき
- summary: `payout >= 100%` は `(games*3 + diff) / (games*3) >= 1.0` すなわち `diff >= 0` と等価。 これは勝率（winrate = (diff > 0).mean()）と同一の指標であり、独立した情報を持たない。 Walk-forwardで hist_wi...

### 41. `top50-is-delivery-format-not-target`
- confidence: `0.97` | status: `unverified` | date: `2026-06-22` | file: `2026-06-22-multi-tier-recommendation-architecture-insights.yaml`
- domain/source: `ml-target-design` / `three-way-discussion-claude-codex-user`
- trigger: 予測モデルのターゲットを設計するとき
- summary: Walk-forward scoringのTop50は元々朝一チートシート用の候補生成だった。 しかし「全台を差枚で一列に並べてTop50を切る」ことを学習ターゲットにしていたため、 ATの高ボラ台がAの高設定を飲み込み、セグメント間の公平な評価ができなかった。 3者（ユーザー・Claude・Codex）の議論で...

### 42. `recommendation-powershell-encoding-required`
- confidence: `0.99` | status: `unverified` | date: `2026-06-21` | file: `2026-06-21-recommendation-top50-workflow-insights.yaml`
- domain/source: `development-workflow` / `session-observation`
- trigger: 日本語を含むPythonスクリプトの出力をターミナルで確認するとき
- summary: Bash toolで日本語を含むPythonスクリプトを実行すると、出力がmojibake（文字化け）になる。 PowerShellで `$env:PYTHONIOENCODING = "utf-8"` を設定してから実行すると正常に表示される。 日本語出力を含むPythonスクリプトは以下で実行: $env:P...

### 43. `recommendation-machine-master-schema`
- confidence: `0.99` | status: `unverified` | date: `2026-06-21` | file: `2026-06-21-recommendation-top50-workflow-insights.yaml`
- domain/source: `data-pipeline` / `session-observation`
- trigger: machine_masterテーブルからA機種フラグを取得するとき
- summary: machine_masterテーブルのカラム構成: machine_name_normalized（キー） jug_flag, hana_flag, oki_flag, bt_flag display_names, official_name, created_at, updated_at machine_num...

### 44. `recommendation-db-path-kamata7-actual`
- confidence: `0.99` | status: `unverified` | date: `2026-06-21` | file: `2026-06-21-recommendation-top50-workflow-insights.yaml`
- domain/source: `data-pipeline` / `session-observation`
- trigger: 蒲田7のDBを読み込むとき
- summary: db/kamata7.db は0Bの空ファイル。実データは db/マルハンメガシティ2000-蒲田7.db（55.73MB）に格納されている。 前回セッションでも同じミスが発生しており、kamata7.dbを開いてテーブルが見つからないエラーが出た。 蒲田7のデータを読む場合は必ず `db/マルハンメガシティ20...

### 45. `kakuban-alternating-section-reversal-bug`
- confidence: `0.99` | status: `unverified` | date: `2026-06-20` | file: `2026-06-20-recommendation-scoring-insights.yaml`
- domain/source: `data-pipeline` / `user-correction`
- trigger: 蒲田7の角番（kakuban）を計算・使用するとき
- summary: 蒲田7の島はメイン通路から見て順方向・逆方向が交互に並んでいる。 物理座標（generate_kamata7_coordinates.py）のstep_xで確認: step_x=+1の島: 台番号min側が通路側 → rank_from_min = 角番（正しい） step_x=-1の島: 台番号min側が奥側...

### 46. `dd-band-priority-categorization`
- confidence: `0.98` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-kakuban-dd-band-analysis-findings.yaml`
- domain/source: `data-categorization-design` / `session-implementation-requirement`
- trigger: DD値が複数のカテゴリに該当するとき、優先順位で一意ラベル化
- summary: dd_band 分類で event（1, 10, 20, 30）が他帯と重複。 集計キーの一意性のため、優先順位で単一ラベル化。 1. 優先順位の定義 Tier 1: event（dd in [1, 10, 20, 30]） Tier 2: early（dd in 1-10） Tier 3: mid（dd in...

### 47. `normalize-segment-frame-essential-columns`
- confidence: `0.98` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-kakuban-section-lr-analysis-insights.yaml`
- domain/source: `eda-implementation-pattern` / `session-debugging`
- trigger: セグメント別フレームを作成時、必ず dd, rank_from_min, section_size_group を生成
- summary: 蒲田7分析時、_build_segment_views() で返すフレームに `dd` カラムが存在せず、後続処理で KeyError が発生。 _normalize_segment_frame() を呼び出して、日付から dd を生成し、section_size から section_size_group を導...

### 48. `kamata7-event-day-complete-definition`
- confidence: `0.98` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-kamata7-theory-doc-and-eventday-fix-insights.yaml`
- domain/source: `pachinko-data-engineering` / `user-correction`
- trigger: 蒲田7または蒲田1のイベント日を定義・参照・計算するとき
- summary: `eda/core.py` の `HALL_EVENT_DIGITS` にDD21が欠落、月末がハードコード(30,31)、 強ゾロ目(MM=DD)が `is_x_day` に未統合だった。ユーザーが複数回指摘しても 繰り返し不完全な定義が使われていた。2026-06-19に修正。 正しい定義: 7のつく日: D...

### 49. `kakuban-strongest-structural-signal`
- confidence: `0.97` | status: `unverified` | date: `2026-06-19` | file: `2026-06-19-durability-verification-insights.yaml`
- domain/source: `kamata7-theory` / `session-eda-verification`
- trigger: 蒲田7で最も信頼できる変数を選択するとき
- summary: 台固有性定量化で角番中間台優位（C3）のtop1_machine_share=0.7%, top2_machine_share=1.4%であり、6法則中圧倒的に低い。特定台への依存がゼロに近い。かつ3テストすべてで堅牢。前半+130.1、後半+93.1で効果量は縮小しているが方向は一貫。 角番は蒲田7で最も信頼で...

### 50. `x-kakuban-rank-must-be-per-machine-not-per-row`
- confidence: `0.97` | status: `unverified` | date: `2026-06-18` | file: `2026-06-18-x-kakuban-eda-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: X角番（x_kakuban）をDataFrameに付与する実装を書くとき、またはGroupBy.rank()を使う類似の実装をするとき
- summary: 2026-06-18: `kamata7_x_kakuban_eda.py` の初版で、1台×342日のフレームに直接 `groupby(["floor","X"])["Y"].rank(method="first")` をかけたことで、 同一台の342行が全て異なるx_kakuban値（1〜342）を持つバグが...

### 51. `kakuban-colsize-eda-pending-rerun`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-correction-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 今日（2026-06-17）の colsize EDA 結果（short/medium/long のbin別kakubanパターン）を選台や特徴量設計に使おうとするとき
- summary: 2026-06-17 午前: kamata7_kakuban_colsize_eda.py の column_size 計算が X座標集計ベースで定義されており、section 角番の colsize 分類としては軸がずれていた。 → 再実行を宣言（use-禁止ブロック）。 2026-06-17 同日: sect...

### 52. `kakuban-colsize-pending-rerun-resolved`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-newresults-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 2026-06-17 の colsize EDA 再実行ブロック（kakuban-colsize-eda-pending-rerun）の状態を確認するとき
- summary: 2026-06-17 午前: `kamata7_kakuban_colsize_eda.py` の column_size が **X軸集計ベース（誤り）** で定義されており、bin の境界も台集合も実態と異なっていた。 → `2026-06-17-kakuban-colsize-correction-insi...

### 53. `mitmweb-exe-path`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: python -m mitmweb でモジュールが見つからないエラーが出るとき
- summary: `python -m mitmweb`は`No module named mitmweb`エラーになる。 mitmproxyのエントリーポイントは`Scripts/mitmweb.exe`として提供される。 C:\Users\<user>\AppData\Local\Python\pythoncore-3.14-...

### 54. `arm64-apk-x86-emulator-incompatible`
- confidence: `0.99` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: x86_64エミュレーターにarm64ネイティブライブラリを使うアプリを動かそうとするとき
- summary: `split_config.arm64_v8a.apk`をx86_64エミュレーターに含めると `INSTALL_FAILED_NO_MATCHING_ABIS`エラー。 除外すると`GifInfoHandle.<clinit>`でクラッシュ（ネイティブライブラリが見つからない）。 x86_64エミュレーターでは...

### 55. `floor-column-size-definition-correction`
- confidence: `0.98` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-correction-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 列の台数でグルーピングする分析を設計・実装するとき、または座標CSVからセクションサイズを計算するとき
- summary: 2026-06-17: kamata7_kakuban_colsize_eda.py で column_size を 「同じX座標を持つ台数（coords.groupby("X").size()）」で定義していたが誤り。 例：X=1 に12台いても、2001-2010（10台）と別セクションの2台が 同じX位置に...

### 56. `android-user-cert-app-trust`
- confidence: `0.98` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: Androidアプリのhttps通信をmitmproxyで傍受しようとするとき
- summary: mitmproxyのCA証明書をAndroidにインストールしてもChromeブラウザの通信しか傍受できない。 Android 7以降、ネイティブアプリはユーザーインストールのCA証明書を無視する仕様になっている。 ブラウザ通信は傍受できるが、アプリは傍受できないと認識する 解決策は3択：(1)エミュレーターにシ...

### 57. `kakuban-1-universal-avoidance-colsize-confirmed`
- confidence: `0.97` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-newresults-insights.yaml`
- domain/source: `pachinko-visit-strategy` / `session-observation`
- trigger: 蒲田7の台選びで列サイズ（short/medium/long）に関わらず角番1の評価をするとき
- summary: 2026-06-17: `section_max - section_min + 1` ベースの正しい colsize 定義で `kamata7_kakuban_colsize_eda.py` を再実行した結果。 旧検証は **X角番の先行実験**（X座標列内の台数でビン分けする実装）として位置づけ直された。 s...

### 58. `3f-short-single-section-analysis-invalid`
- confidence: `0.97` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-colsize-newresults-insights.yaml`
- domain/source: `analysis-methodology` / `session-observation`
- trigger: 蒲田7 3F short 列（9-10台）の角番分析結果を使おうとするとき
- summary: 2026-06-17: `section_max - section_min + 1` ベースで確認。 3F の short 列（9台・10台）は 3F_short_N と 3F_short_A それぞれ **1セクションのみ**。 全 kakuban 行が support_sections=1 となり、構造シグ...

### 59. `split-apk-install-multiple`
- confidence: `0.97` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-android-mitmproxy-scraping-insights.yaml`
- domain/source: `mobile-scraping` / `session-observation`
- trigger: エミュレーターにAPKをインストールしてResources$NotFoundExceptionが出るとき
- summary: APK Extractorアプリで抽出したbase.apkのみをインストールすると、 `Resources$NotFoundException: Unable to find resource ID #0x7f080161` でクラッシュする。 モダンなアプリはApp Bundleで複数のSplit APKに分割...

### 60. `kakuban-dual-rank-correct-definition`
- confidence: `0.97` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kakuban-dual-rank-refactor-insights.yaml`
- domain/source: `domain-definition` / `user-correction`
- trigger: 角番（kakuban）の定義を実装・分析・プロンプトで扱うとき
- summary: 2026-06-17 セッションでユーザーより訂正。 旧実装（KAKUBAN_RULES）は「メイン通路＝台番号小側」と仮定して rank_from_min のみを角番とした。 正しくは「どちら側がメイン通路かはランダム」であり、各台は両端から数えた2つの角番を同時に持つ。 例: section 2001-201...

### 61. `sqlite-groupby-arbitrary-machine-name`
- confidence: `0.97` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-screening-bugfix-insights.yaml`
- domain/source: `sql-pitfall` / `session-observation`
- trigger: SQLite で GROUP BY machine_number しながら machine_name を取得するクエリを書くとき
- summary: mitoya_xdds_screening.py の `_load_latest_machine_names` で `GROUP BY machine_number HAVING COUNT(DISTINCT date) >= 5` を使っていた。 台番号608-614には過去に複数の機種が設置されており、 SQ...

### 62. `kamata1-jag-hana-name-filter`
- confidence: `0.97` | status: `unverified` | date: `2026-06-17` | file: `2026-06-17-kamata1-kakuban-position-analysis-insights.yaml`
- domain/source: `data-processing` / `session-observation`
- trigger: 蒲田1DBでジャグラー・ハナハナ台を機種名フィルタするとき
- summary: 蒲田1DBには多数の機種が混在しており、ジャグラー系・ハナハナ系を分離して分析する場面が多い。 機種名に「ジャグラー」または「ハナハナ」を含む文字列で確実に捕捉できる。 def is_jag_hana(name): return 'ジャグラー' in name or 'ハナハナ' in name 2026/06/...

### 63. `goal-prompt-4000char-limit`
- confidence: `0.99` | status: `unverified` | date: `2026-06-16` | file: `2026-06-16-when-which-backtest-insights.yaml`
- domain/source: `workflow-codex-handoff` / `user-instruction`
- trigger: Codexへの/goalプロンプトを作成するとき
- summary: 2026-06-16セッションでユーザーから明示的に指示。 初稿は不要な詳細（バリデーションリスト・例外ケース列挙）が多かった。 既存ファイルから流用する関数名を明示すれば実装詳細の記述を省略でき、 1500〜1800文字程度に圧縮しても Codex が迷わず実装できる。 既存流用関数名を明示して詳細記述を省く...

### 64. `daily-hall-summary-date-features-null-bug`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda` / `session-observation`
- trigger: daily_hall_summary の day_of_week / last_digit / is_x_day を使った分析をするとき
- summary: `date_info_calculator.py` は全日付で実行されておらず、`daily_hall_summary` の `day_of_week`, `last_digit`, `is_x_day` 等は443日中わずか3日分しか入っていない。 例：レイトギャップ 土曜 n=422（修正前）→ 24,850...

### 65. `rb-probability-juggler-hokuto-spec`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-rb-probability-analysis-insights.yaml`
- domain/source: `machine-spec` / `user-provided`
- trigger: スマスロ北斗の拳・モンキーターンV・ジャグラー各種のRB確率(rb_probability_decimal)から設定推定を行うとき
- summary: 2026-06-10セッションでユーザーから提供された、ジャグラーシリーズ以外の RB確率ベース設定判別が可能な機種のスペック表。 以下のスペックをRB確率(1/X)から設定推定する際の基準値として使う。 | 設定 | AT初当り確率 | 出玉率 | |---|---|---| | L | ※下パネルが常に点滅...

### 66. `kabaneri-s-and-l-version-distinction`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-machine-hall-fixedeffect-and-banchou4-insights.yaml`
- domain/source: `machine-naming` / `user-clarification`
- trigger: カバネリ・甲鉄城のカバネリについて分析するとき / 「カバネリ海門」という呼称が出てきたとき
- summary: 蒲田7では以下の2機種が両方とも現役（last_date=20260607）で稼働している: | machine_name | n(games>=1000) | baseline hit104 | |---|---|---| | 甲鉄城のカバネリ（無印・S版） | 1648 | 45.8% | | 甲鉄城のカバネ...

### 67. `juggler-series-bonus-probability-spec`
- confidence: `1.00` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-juggler-spec-and-debut-curve-insights.yaml`
- domain/source: `machine-spec` / `user-provided`
- trigger: ジャグラーシリーズ機種の設定別出玉率・ボーナス確率を参照するとき / kaiwari近似値の精度を機種別に検証するとき
- summary: 2026-06-10セッションでユーザーから提供されたジャグラーシリーズの公称スペック。 hit104%（機械割104%以上）の解釈や、機種ごとの設定推定の基礎データとして使う。 以下のスペック表を機種別の設定推定・閾値較正に使用する。 | 設定 | BIG | REG | 合算 | 出玉率 | |---|---...

### 68. `weekday-digit-nth-single-dim-all-null`
- confidence: `0.99` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: 曜日・台番号末尾・第N曜日を単独次元でスキャンするとき
- summary: daily_hall_summaryのJOINバグを修正した後、21次元 × 9ホールの全スキャンを実施。 以下の単独次元は全ホール・全パターンでTier A/B が1件も出なかった。 以下の単独次元に基づく台選択・設定投入予測は無効として扱う： `day_of_week`（曜日単独） `machine_digi...

### 69. `rb-threshold-monkey-hokuto-confirmed`
- confidence: `0.99` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `rb-signal` / `instinct-confirmed`
- trigger: モンキーターンV・スマスロ北斗の拳のRBシグナルを使うとき
- summary: 旧閾値 1/300=0.003333 ではモンキーターンV設定1（1/299=0.003344）が 閾値を突き抜けて全台シグナル扱いになり、発動率83.7%という汚染が発生した。 北斗の拳設定3（1/297=0.003367）も同様に捕捉されていた（設定3は低設定）。 設定4以上を識別する正しい閾値 = 1/25...

### 70. `firstday-analysis-implementation`
- confidence: `0.99` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-new-machine-firstday-hall-insights.yaml`
- domain/source: `eda-implementation` / `implementation`
- trigger: 新台初日のホール別・機種別パフォーマンスを集計するスクリプトを書くとき / debut_dateを計算するとき
- summary: `machine_detailed_results` に導入初日フラグは存在しないため、 「機種ごとの最古date = debut_date」として計算する。 pre_existing（DBスタート日に既に存在した機種）を除外する必要がある。 実装済みファイル: `eda/hall_firstday_analys...

### 71. `pre-existing-machine-debut-detection`
- confidence: `0.98` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `implementation`
- trigger: days_since_debutを計算するとき / compute_debut_features を使うとき
- summary: `compute_debut_features(df, db_start_grace_days=0)` で実装済み。 蒲田7の検証結果: DB期間: 2025-07-07 〜 2026-06-07 pre_existing 60機種: 全て debut_date == 2025-07-07（DB初日に集中） DB...

### 72. `dd-individual-x-day-confirmation`
- confidence: `0.98` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: DD個別（1-31）スキャンの結果を解釈するとき
- summary: DD個別（1-31）スキャン結果： みとや: DD4=+280, DD14=+234, DD24=+213（全Tier B）→ 4系x_dayと完全一致 蒲田7: DD7=+425 → 7系x_dayと一致 蒲田1: DD7=+194 → 7系の弱い反応 レイトギャップ: DD6=+219 → 6系x_dayと一...

### 73. `anomaly-next-day-mean-reversion`
- confidence: `0.98` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: ANOMALYを翌日の台選択シグナルとして使おうとするとき
- summary: 全ホール合算・翌日1000G以上でのANOMATY後続検証: | 条件 | 翌日avg | 翌日plus率 | |------|---------|----------| | ANOMALY日（score≥2） | +43 | 39.8% | | 通常日（score<2） | +60 | 40.6% | ANOM...

### 74. `new-machine-low-setting-start-confirmed`
- confidence: `0.97` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `hall-behavior` / `empirical-analysis`
- trigger: 新台導入後の設定投入パターンを分析するとき / days_since_debutを使うとき
- summary: 全ホール合算 days_since_debut 別 avg_diff: 0-7日: avg=-152 (n=31,579) 8-14日: avg=-190 (n=31,087) ← 最低 15-30日: avg=-116 31-60日: avg=-23 61-90日: avg=+4 91-180日: avg=+3...

### 75. `anomaly-early-debut-unreliable`
- confidence: `0.97` | status: `unverified` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: 導入後30日以内の機種のANOMALYを解釈するとき
- summary: pre_existing=False の新規機種に限定した、導入後日数帯別ANOMALY翌日検証: | 日数帯 | 翌日avg | plus率 | n | |--------|---------|--------|---| | 0-7日 | -291 | 37.5% | 2017 | | 8-14日 | -396...

### 76. `mitoya-bari-island-nonexistent`
- confidence: `0.99` | status: `unverified` | date: `2026-06-09` | file: `2026-06-09-mitoya-lag-feature-island-section-insights.yaml`
- domain/source: `data-model` / `session-observation`
- trigger: みとや大森町店で assign_island() を使うとき / island カテゴリ数を確認するとき
- summary: assign_island() の定義: machine_num >= 832 を 'bari' に分類。 みとや大森町店の machine_detailed_results における machine_number の実際の範囲: MIN=501, MAX=815, n=266台 → 815 < 832 のため、...

### 77. `python-windows-encoding-japanese-output`
- confidence: `0.99` | status: `unverified` | date: `2026-06-07` | file: `2026-06-07-island-digit-stability-insights.yaml`
- domain/source: `data-pipeline` / `empirical-validation`
- trigger: WindowsのPython分析スクリプトで日本語を含む出力を行うとき、または機種名・ホール名を表示するスクリプトを書くとき
- summary: Windows環境ではPythonのデフォルトstdoutエンコーディングがCP932（Shift-JIS）のため、 UTF-8で保存された日本語文字列をprintすると文字化けする。 分析スクリプトで機種名・ホール名が文字化けすると誤った名称を正しい名称と誤認し 分析結果の解釈を誤る危険がある。 実害の例： 機...

### 78. `kakuban-not-rank-terminology`
- confidence: `0.99` | status: `unverified` | date: `2026-06-07` | file: `2026-06-07-mitoya-corner-aisle-eda-insights.yaml`
- domain/source: `terminology` / `user-correction`
- trigger: 台配置位置の順位を表現するとき
- summary: ユーザーからの明示的な指摘: 「ランクだと成績順位と混同する。角番という言い方に統一してください」。 本プロジェクトでは: **角番**（kakuban）: メイン通路からの距離による位置順位（rank_from_aisle, rank_from_min） **ランク**: 機械ランキング（machine_ran...

### 79. `machine-name-contamination-in-ml-training`
- confidence: `0.98` | status: `unverified` | date: `2026-06-07` | file: `2026-06-07-mitoya-ml-prediction-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `empirical-validation`
- trigger: みとや（または他ホール）でCatBoostにmachine_nameをCAT_FEATUREとして使うとき
- summary: みとや大森町店 266台中 **204台（76%）** で機種名が変わっていた（515日分データ）。 例: 台501-522は「ダンベル何キロ持てる？」→「バンドリ！」→「甲鉄城のカバネリ 海門(うなと)決戦」のように変遷。 CatBoostに`machine_name`をCAT_FEATUREとして使うとき、...

### 80. `mitoya-daily-hall-summary-null-flags`
- confidence: `0.98` | status: `unverified` | date: `2026-06-06` | file: `2026-06-06-mitoya-corner-section-position-insights.yaml`
- domain/source: `data-quality` / `empirical-observation`
- trigger: みとやDBで daily_hall_summary の日付フラグを使おうとしたとき
- summary: みとやスロスのDBでは daily_hall_summary の day_of_week, last_digit, weekday_nth, is_strong_zorome が 514 行すべて NULL。 これらに依存した特徴量計算は全て 0/NaN になってしまう。 日付属性は date 文字列（YYYYM...

### 81. `full-2025-window-boundary-safety`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-leakage-audit-insights.yaml`
- domain/source: `methodology` / `code-audit`
- trigger: walk-forward の学習窓 full_2025 が holdout と重複しないか確認するとき、または新しい window_name を追加するとき
- summary: `build_train_window("full_2025", test_start)` は `(REGIME_1_START="2025-07-07", REGIME_2_END="2025-12-31")` を返す。 holdout 期間は `REGIME_3_START="2026-01-01"` 以降。...

### 82. `xday-equals-is-xday-flag`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `hall-specific` / `db-exploration`
- trigger: みとやの x_day bucket を定義または実装するとき
- summary: みとや大森町 DB で is_x_day=1 の日と「day % 10 in {4,7}（4/7/14/17/24/27日）」は 514日間で完全一致（n=102、重複率100%）。 x_day ONLY: 0件、ld4/7 ONLY: 0件。 x_day 判定は `day % 10 in {4, 7}` で計算...

### 83. `poco-diff-is-db-derived`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-analysis-db-insights.yaml`
- domain/source: `poco-data-quality` / `empirical-measurement`
- trigger: ぽこデータの差枚精度を疑うとき・ぽこCSVとDBの差枚を比較するとき
- summary: poco_data_v5.csv の `kamata7_diff` / `kamata1_diff` がアナスロデータと一致するか全期間検証した結果、 K7: 282件中1件不一致、K1: 210件中3件不一致（ほぼ完全一致）。 ぽこの差枚欄はアナスロDB（machine_detailed_results の S...

### 84. `catboost-gpu-ndcg-not-implemented`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-allhall-model-architecture-insights.yaml`
- domain/source: `ml-infrastructure` / `empirical-20260605`
- trigger: when using CatBoostRanker with GPU backend and NDCG objective
- summary: CatBoostRanker に --use-gpu を指定した場合、NDCG 目標が GPU 未実装という警告が出て 計算継続するが、精度が崩壊した： CPU: avg_diff=111.81 GPU: avg_diff=34.73（壊滅的な低下） GPU 経路では CatBoostRanker を除外する。...

### 85. `walrus-operator-parameter-overwrite`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `python-bugs` / `session-observation`
- trigger: Pythonのwalrus演算子 := をif条件の中で使うとき
- summary: `feature_engineering.py` の Feature 8 で以下のコードがあった： if is_train := False: # Placeholder: always use stored stats pass walrus演算子は関数パラメータ `is_train` をローカル変数として `...

### 86. `poco-is-post-hoc-not-realtime`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-forward-strategy-insights.yaml`
- domain/source: `poco-analysis-fundamentals` / `user-correction`
- trigger: ぽこデータを使った戦略・予測を立てるとき
- summary: ぽこ（poco）のデータは「その日の結果が出た後」に発表される事後記録である。 当日朝にぽこを確認して「今日発表された機種を打ちに行く」という使い方は不可能。 | 用途 | 可否 | |------|------| | 当日の台選択 | NG（事後発表のため不可） | | 過去パターンの統計分析 | OK（11ヶ...

### 87. `poco-hall-separation-rule`
- confidence: `0.99` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-hall-analysis-insights.yaml`
- domain/source: `poco-analysis-workflow` / `user-instruction`
- trigger: ぽこデータをK7・K1両ホールで分析・出力するとき
- summary: 蒲田七（K7）と蒲田一（K1）は戦略・規模・データ品質が根本的に異なる： 規模: K7 月平均69.7機種発表 vs K1 44.9機種（K7の約65%） K7: アニメ系スマスロを幅広く・平日も機種名明示 K1: 戦国乙女4・カバネリ海門などに集中・平日は機種全が「不明」多数 同一機種でもK7とK1で実績が真逆...

### 88. `forecast-excluded-columns-leakage-guard`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-leakage-audit-insights.yaml`
- domain/source: `methodology` / `code-audit`
- trigger: みとやまたは他ホールのLTRモデルに新しいカラムを特徴量として追加しようとするとき
- summary: `utils.py` の `FORECAST_EXCLUDED_COLUMNS` は同日の目的変数と直接相関するカラムを列挙している。 `get_numeric_features()` はこのセットと `META_COLUMNS` と `is_top_2` を除外してから 数値カラムを特徴量リストとして返す。 `...

### 89. `bucket-specific-hall-average-baseline`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: walk-forward の mean_diff から実際の期待差枚を計算するとき
- summary: walk-forward の mean_diff は「モデル予測末尾のexcess（予測末尾台平均 − その日のホール全体台平均）」であり、 絶対的な期待差枚ではない。 全期間の overall ホール台平均をベースラインとして使うと、 属性ごとに大きく異なるホール台平均を見落とす。 みとや大森町では x_day...

### 90. `dd-vs-xday-definition-clarification`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-monthly-trend-db-design-insights.yaml`
- domain/source: `db-design` / `session-interview-20260605`
- trigger: when designing aggregation axes around date patterns (DD, Xのつく日, 末尾)
- summary: 「DD別」と「Xのつく日」を混同しやすい。このプロジェクトでの定義： **DD** = 日付の日（1〜31の具体的な日番号） 4日、14日、24日はそれぞれ別のDD 月内に**1回だけ**出現する **Xのつく日（date_digit）** = 日付末尾の数字（0〜9） 4のつく日 = 4日・14日・24日（月に...

### 91. `make-binary-model-gpu-branch-bug`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-allhall-model-architecture-insights.yaml`
- domain/source: `ml-architecture` / `session-observation-20260605`
- trigger: XGBoostがインストールされている環境でGPUフラグの動作を確認するとき、またはmake_binary_modelを実装・修正するとき
- summary: `if XGBClassifier is None` という条件でモデルを分岐すると、 XGBoostがインストールされている環境では `--use-gpu` なしでも常に XGBClassifier が使われる。 これにより LogisticRegression でチューニングされたベースライン（例: hybr...

### 92. `sql-injection-fstring-table-name`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `security` / `session-observation`
- trigger: SQLクエリでテーブル名・カラム名をf-stringで埋め込むとき
- summary: `data_loader.py` の `load_machine_detailed_by_date` でf-string SQLが使われており、 `date_str` が直接クエリに埋め込まれていた。`database_accessor.py` では `table_name`・`column` もf-string...

### 93. `bare-except-swallows-keyboard-interrupt`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `python-bugs` / `session-observation`
- trigger: 例外処理で except: pass を書くとき
- summary: `date_info_calculator.py` の `_check_holiday` で `except: pass` が使われており、 `BaseException`（`KeyboardInterrupt`や`SystemExit`含む）ごと無音で飲み込んでいた。 フォールバックがあるケースでも失敗が完全に...

### 94. `poco-partial-status-multi-machine-mapping`
- confidence: `0.98` | status: `unverified` | date: `2026-06-05` | file: `2026-06-05-poco-hall-analysis-insights.yaml`
- domain/source: `poco-data-pipeline` / `session-observation`
- trigger: ぽこ機種マッピングで1つのエントリーを複数機種に展開する必要があるとき
- summary: `rebuild_poco_pipeline.py` の `PATCH_FOUND` ディクショナリは、ループで全エントリーを `('FOUND', db_match)` として登録する。`norm_one()` の FOUND ハンドラは `return [db_match]` と単一要素リストを返すため、パイ...

### 95. `machine-name-alias-normalization-critical`
- confidence: `0.98` | status: `unverified` | date: `2026-06-02` | file: `2026-06-02-poco-facility-structure.yaml`
- domain/source: `pachinko-data-analysis` / `user-domain-knowledge`
- trigger: ぽこデータの機種情報を DB と照合するとき
- summary: ぽこで使用される機種名は、DB 内の正式な機種名と大きく異なる。 正規化なしに照合すると、実際には一致する機種でも「0%的中」と判定される。 `スーパーブラックジャック` ↔ `SBJ` ↔ `スパブラ` `ミスタージャグラー` ↔ `ミスター` `北斗の拳転生2` ↔ `北斗転生2` ↔ `北斗`（曖昧） `デ...

### 96. `instinct-contamination-two-types`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-instinct-management-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク修正後に過去のinstinctを評価するとき、または古いinstinctを参照しようとするとき
- summary: 2026-05-31のリーク修正後、過去のinstinctを精査した結果、 汚染の種類によって処置が異なることが判明した（2026-06-01）。 種類1「MLモデル性能値が主体」→ contaminated/ へアーカイブ（無効化） AUC=0.8140、hit@2=98%、precision@2=83% 等の...

### 97. `instinct-scope-taxonomy-rule`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-hall-independence-principle.yaml`
- domain/source: `ml-architecture` / `user-instruction`
- trigger: 新しいinstinctを作成するとき、または既存instinctをインポートするとき
- summary: ホール固有の発見と普遍的な方法論が混在することで、 別ホール分析時に誤った前提が持ち込まれる問題が発生した（2026-06-01）。 add_instinct_scope.py で既存70件に一括追加済み。 新しいinstinctを作成するとき、必ず以下のフィールドを追加する： confidence: 0.XX...

### 98. `hall-specific-findings-never-transfer-to-other-halls`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-hall-independence-principle.yaml`
- domain/source: `domain-strategy` / `user-instruction`
- trigger: 別のホールの分析を始めるとき、または複数ホールにまたがる提案をするとき、または蒲田7の数値を引用するとき
- summary: ユーザーから繰り返し指摘された最重要ルール（2026-06-01 確立）： 「ホール固有ルールが強い。他ホールと比較することに意味がない。」 パチンコホールは独立した経営主体であり、設定投入戦略を共有する理由がない。 他業種でも経営戦略は共有しない（例：A社の販売戦略がB社でも有効とは限らない）。 蒲田7で確認さ...

### 99. `signal-existence-must-precede-ml-design`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-signal-existence-insights.yaml`
- domain/source: `ml-architecture` / `data-analysis`
- trigger: MLモデルの設計・特徴量追加を検討するとき
- summary: signal_existence_plan.py を蒲田7（holdout 150日）で実行した結果： 反復回避：P(top1_{t+1}|top1_t) = 0.098 vs 基準0.10（非有意） ランク自己相関：max |rho|≈0.035（実質ゼロ） (DD,末尾)セル：Bonferroni補正後有意0...

### 100. `grid-search-exposes-narrow-space-artifacts`
- confidence: `0.99` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: 限定的な探索で見つかったシグナルを全空間に拡張するとき
- summary: lag=14 × 2F_N × digit=8 の発見経緯： 1. is_positive autocorr で raw hit → p_raw=0.00066 2. lag=14 に絞った検定 → FDR=0.026 で有意 3. 全 expert × 全 digit × 複数 lag のグリッド探索 → FD...

### 101. `approach-transfer-vs-findings-transfer`
- confidence: `0.98` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-instinct-management-insights.yaml`
- domain/source: `domain-strategy` / `user-instruction`
- trigger: 別ホールで分析を始めるとき、または蒲田7の知見を他に適用しようとするとき
- summary: ユーザー指摘（2026-06-01）： 「同じアプローチで分かることもある。 データ探索やホールではなく機種固有のクセなどは共通している可能性がある。」 OK（アプローチ・ツール）： signal_existence_plan.py などの分析スクリプト walk-forward の枠組み・統計検定手順 upli...

### 102. `always-2fn-beats-all-calendar-rules`
- confidence: `0.98` | status: `unverified` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `domain-strategy` / `data-analysis`
- trigger: セグメント選択戦略を設計するとき、またはカレンダールールを逸脱判断に使おうとするとき
- summary: deviation_rule_eval.csv（holdout 150日）の uplift 評価結果： always_no（常に2F_N）: 0/日（基準） dd_topk: -2,032/日 weekday_high: -5,975/日 calendar_union: -7,047/日 always_yes（常...

### 103. `leakage-check-direction-must-be-inclusion-not-exclusion`
- confidence: `0.99` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-leakage-protocol-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク確認を依頼されたとき、またはget_numeric_features()の出力を確認するとき
- summary: total_diff_coins_focus のリークを複数回の確認依頼にもかかわらず見逃した。 原因は「除外リストに target 列が含まれているか」をチェックしていたこと。 しかし本当に必要なのは「get_numeric_features() が返す全列の生成元を追跡すること」。 間違ったチェック方向： e...

### 104. `total-diff-coins-focus-leakage-root-cause`
- confidence: `0.99` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテストのhit@2が95%超のとき、またはget_numeric_featuresで特徴量セットを変更するとき
- summary: clean holdout監査（2025選定→2026評価）でも hit@2=98-99% が継続したことで調査。 以下の手順でリークを特定した： 1. ナイーブ基準（過去固定Top2）: hit@2=37.8% ≈ ランダム → Top2は日次で変動しており単純暗記ではない 2. 全lag特徴量のSpearma...

### 105. `dd-value-missing-from-features`
- confidence: `0.99` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-evaluation-feature-insights.yaml`
- domain/source: `ml-architecture` / `code-inspection`
- trigger: 特徴量セットを確認・拡張するとき、またはdd_valueを実装するとき
- summary: add_simple_features()（tail_ltr_split_rule_wf.py line 167）の実際の特徴量： 既存（曜日系、追加不要）: weekday（0-6）, weekday_sin, weekday_cos, is_wed weekday_prior_top2_rate, weekd...

### 106. `outcome-leakage-vs-target-leakage-are-different`
- confidence: `0.98` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-leakage-protocol-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: MLモデルの特徴量リークを確認するとき
- summary: 古典的なリーク確認はターゲットリーク（is_top_2 を特徴量に使う）を防ぐもの。 今回のリークは「ターゲットそのものではないが、同日実績由来でターゲットと高相関な列」。 ターゲットリーク：is_top_2, is_rank_1 など → 除外リストで対処済み アウトカムリーク：total_diff_coins...

### 107. `live-vs-backtest-gap-explained-by-leakage`
- confidence: `0.98` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテスト精度と実践精度に大きな乖離があるとき
- summary: 本プロジェクトの実測値： backtest (clean holdout) precision@2: 83-87% live評価 (9日間) precision@2: 25-50% この乖離を「small sample effect」「seasonal shift」で説明しようとしていたが、 実際は total_...

### 108. `pred-span-vs-pred-span-top12-are-different`
- confidence: `0.98` | status: `unverified` | date: `2026-05-31` | file: `2026-05-31-evaluation-feature-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: pred_spanとpred_span_top12を評価・比較するとき、または「低Span日」を分析するとき
- summary: バックテストCSVには2種類のspan指標が存在する。 `pred_span`（reliability_daily）: max(pred) - min(pred) → 全10末尾の範囲 `pred_span_top12`（testperiod_topk）: top1_pred - top2_pred → 1位と2...

### 109. `hit-at-2-binary-vs-precision-confusion`
- confidence: `0.98` | status: `unverified` | date: `2026-05-30` | file: `2026-05-30-backtest-evaluation-insights.yaml`
- domain/source: `prediction-evaluation` / `backtest-analysis`
- trigger: hit@2の数値を比較・解釈するとき、または評価指標を設計するとき
- summary: コードの `hit_at_2` はバイナリ（1件でも一致したら1.0）だが、 ユーザーの手動評価は precision（一致数/2）。この違いで 「コード89%」vs「手動50%」という見かけ矛盾が生じた。 ランダム基準値： バイナリhit@2：37.8% （= 1 - C(8,2)/C(10,2)） preci...

### 110. `adjusted-lift-denominator-10-not-9`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_multi_tail_2fn の hit_rate をランダムベースラインと比較するとき
- summary: 蒲田七の末尾は 0-9 の10種類（北斗は末尾4欠番で9台だが、末尾数は10）。 summary.json の `baseline_random = 0.1` がこれを示している。 分母を 9 にすると diff・OR が「baseline 以下」に見えるが、10 にすると「baseline 水準」になる。 |...

### 111. `signal-correlation-json-output-keys`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: signal_machine_correlation_summary.jsonを読み込んで解釈するとき
- summary: 実際の出力JSONのキーは `overall_stats` や `weekday_stats` ではなく、 `signal_or`, `diff_signal_only`, `rb_signal_only`, `fake_tail_check` など。 間違ったキーでアクセスすると None が返って解釈を誤る。...

### 112. `kamata7-floor-classification`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `data-processing` / `session-observation`
- trigger: 蒲田七（マルハンメガシティ2000-蒲田7）のデータをセグメント分類するとき
- summary: machine_detailed_resultsにはフロア情報が直接ないが、台番号でフロアを判定できる。 Heatmap/2F_floor_coordinates_kamata7.csvで確認済み。 machine_number < 3000 → 2F（2001〜2351付近） machine_number >=...

### 113. `correct-segment-classification-floor-atype4`
- confidence: `0.99` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `data-processing` / `codex-correction`
- trigger: 蒲田七の機台をセグメント分類（2F_N/3F_N/3F_A/2F_A）するとき
- summary: 台番号の先頭桁（2xxx=2F / 3xxx=3F）だけで分類していたのは不正確。 正しい定義は ml/last_digit/tail_ltr_split_rule_wf.py の floor_atype4 モードにあり、 jug_flag/hana_flag/bt_flag を使ってA/N型を判定する。 df[...

### 114. `hard-miss-vs-exact-miss-definition`
- confidence: `0.98` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: testperiod_topk.csv で「予測外れ日」を定義するとき
- summary: `nextday_kamata7_20260527_tasks123_verify_...topk.csv` の2F_N（146日）: hard_miss（hit_at_2 == 0）: **1日のみ**（99.3%がhit@2） exact_miss（予測top1 ≠ 実際rank1）: **44日**（69....

### 115. `segment-specific-top3-comparison`
- confidence: `0.98` | status: `unverified` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `prediction-evaluation` / `user-correction`
- trigger: 末尾予測の精度評価を行うとき
- summary: 予測精度を評価する際、2F_N/3F_N/3F_A/2F_Aの各セグメント予測を全体の実績と比較していたが誤り。 セグメント別予測はそれぞれのセグメント実績のみと比較すべき。 ゾロ目狙い目意見もゾロ目台限定の実績（is_zorome=1）のみと比較する。 2F_N予測Top3 → 2F実績Top3（machine...

### 116. `top3-output-already-implemented-per-expert`
- confidence: `0.98` | status: `unverified` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-pipeline` / `session-observation`
- trigger: TOP3末尾の出力を実装しようとするとき / latest_test_top3を参照するとき
- summary: `tail_ltr_split_rule_nextday_gpu.py` が出力する `*_latest_test_top3.csv` は、 各エキスパート（2F_N, 3F_N, 3F_A, 2F_A）のrank1・rank2・rank3を含む。 2F_Aも2026-05-26時点ではTOP3に含まれている（除...

### 117. `progress-reporting-required-in-all-loops`
- confidence: `0.98` | status: `unverified` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-active-filter-insights.yaml`
- domain/source: `ml-implementation-standards` / `session-requirement`
- trigger: when implementing walk-forward or any time-consuming loop in ML pipeline
- summary: 機種別予測（run_machine_type_v2.py）に進捗表示が実装されておらず、 処理時間の予測ができない問題があった。 末尾予測パイプラインには実装済みのため、全パイプラインで統一する。 時間のかかるループには必ず以下のパターンを使用する： import time start_time = time.t...

### 118. `is-top2-must-be-within-expert`
- confidence: `0.99` | status: `unverified` | date: `2026-05-25` | file: `2026-05-25-within-expert-target-fix.yaml`
- domain/source: `ml-pipeline-configuration` / `session-breakthrough`
- trigger: when defining LTR ranking target for multi-expert pachinko prediction
- summary: 末尾別LTRパイプラインでは複数のエキスパート（2F_N / 3F_N / 3F_A / 2F_A）が それぞれ独立したモデルを持つ。 評価指標 hit@2 は「エキスパート内10アイテム中、予測top2が実績top2を含むか」で定義。 （metrics_ops.py: true_top2 = actual_ra...

### 119. `window-name-vs-feature-name-confusion`
- confidence: `0.99` | status: `unverified` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-pipeline-configuration` / `session-error`
- trigger: when specifying --windows-wed or --windows-nonwed arguments for tail_ltr_split_rule_nextday_gpu
- summary: ACF/PACFで「roll28が最適」という知見を得た後、 `--windows-wed "roll28"` を指定したところ全candidateが "unavailable" になった。 `roll28` は特徴量名（`roll28_total_diff_coins`）であり、 training window...

### 120. `anomaly-db-scope-must-be-single-hall`
- confidence: `0.98` | status: `unverified` | date: `2026-05-25` | file: `2026-05-25-anomaly-analysis-insights.yaml`
- domain/source: `ml-data-validation` / `session-observation`
- trigger: when running exploratory anomaly detection on pachinko data
- summary: run_exploratory_analysis.py のデフォルト --db-glob は "db/*.db" であり、 db/ 直下の全ホール（9ホール）を統合して分析する。 蒲田七は2025-07-07開業のため、他ホールのデータが混入すると 開業前データやzscoreが-22を超える極端な外れ値が混入し、...
