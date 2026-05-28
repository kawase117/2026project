# ACTIVE_INSTINCTS

- generated_at: 2026-05-28T09:09:12+09:00
- compiler_version: 1.1.0
- source_dir: `C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/document/instincts`
- total_records_scanned: 229
- active_records: 120
- filters: `confidence >= 0.80` and `file_date within 21 days` (unless pinned by high confidence)

## Usage
- Start of work: run `venv\Scripts\python.exe scripts/compile_instincts.py` (or `python scripts/compile_instincts.py`).
- Long sessions: rerun before major decisions or every 15-20 minutes.
- Preferred source for Codex: `ACTIVE_INSTINCTS.jsonl` (machine-readable canonical).
- This Markdown is a quick view. Open raw YAML only when detail is missing.
- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed.

## Active List

### 1. `correct-segment-classification-floor-atype4`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `data-processing` / `codex-correction`
- trigger: 蒲田七の機台をセグメント分類（2F_N/3F_N/3F_A/2F_A）するとき
- summary: 台番号の先頭桁（2xxx=2F / 3xxx=3F）だけで分類していたのは不正確。 正しい定義は ml/last_digit/tail_ltr_split_rule_wf.py の floor_atype4 モードにあり、 jug_flag/hana_flag/bt_flag を使ってA/N型を判定する。 df[...

### 2. `kamata7-floor-classification`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `data-processing` / `session-observation`
- trigger: 蒲田七（マルハンメガシティ2000-蒲田7）のデータをセグメント分類するとき
- summary: machine_detailed_resultsにはフロア情報が直接ないが、台番号でフロアを判定できる。 Heatmap/2F_floor_coordinates_kamata7.csvで確認済み。 machine_number < 3000 → 2F（2001〜2351付近） machine_number >=...

### 3. `signal-correlation-json-output-keys`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: signal_machine_correlation_summary.jsonを読み込んで解釈するとき
- summary: 実際の出力JSONのキーは `overall_stats` や `weekday_stats` ではなく、 `signal_or`, `diff_signal_only`, `rb_signal_only`, `fake_tail_check` など。 間違ったキーでアクセスすると None が返って解釈を誤る。...

### 4. `adjusted-lift-denominator-10-not-9`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_multi_tail_2fn の hit_rate をランダムベースラインと比較するとき
- summary: 蒲田七の末尾は 0-9 の10種類（北斗は末尾4欠番で9台だが、末尾数は10）。 summary.json の `baseline_random = 0.1` がこれを示している。 分母を 9 にすると diff・OR が「baseline 以下」に見えるが、10 にすると「baseline 水準」になる。 |...

### 5. `is-top2-must-be-within-expert`
- confidence: `0.99` | date: `2026-05-25` | file: `2026-05-25-within-expert-target-fix.yaml`
- domain/source: `ml-pipeline-configuration` / `session-breakthrough`
- trigger: when defining LTR ranking target for multi-expert pachinko prediction
- summary: 末尾別LTRパイプラインでは複数のエキスパート（2F_N / 3F_N / 3F_A / 2F_A）が それぞれ独立したモデルを持つ。 評価指標 hit@2 は「エキスパート内10アイテム中、予測top2が実績top2を含むか」で定義。 （metrics_ops.py: true_top2 = actual_ra...

### 6. `window-name-vs-feature-name-confusion`
- confidence: `0.99` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-pipeline-configuration` / `session-error`
- trigger: when specifying --windows-wed or --windows-nonwed arguments for tail_ltr_split_rule_nextday_gpu
- summary: ACF/PACFで「roll28が最適」という知見を得た後、 `--windows-wed "roll28"` を指定したところ全candidateが "unavailable" になった。 `roll28` は特徴量名（`roll28_total_diff_coins`）であり、 training window...

### 7. `segment-specific-top3-comparison`
- confidence: `0.98` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `prediction-evaluation` / `user-correction`
- trigger: 末尾予測の精度評価を行うとき
- summary: 予測精度を評価する際、2F_N/3F_N/3F_A/2F_Aの各セグメント予測を全体の実績と比較していたが誤り。 セグメント別予測はそれぞれのセグメント実績のみと比較すべき。 ゾロ目狙い目意見もゾロ目台限定の実績（is_zorome=1）のみと比較する。 2F_N予測Top3 → 2F実績Top3（machine...

### 8. `hard-miss-vs-exact-miss-definition`
- confidence: `0.98` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: testperiod_topk.csv で「予測外れ日」を定義するとき
- summary: `nextday_kamata7_20260527_tasks123_verify_...topk.csv` の2F_N（146日）: hard_miss（hit_at_2 == 0）: **1日のみ**（99.3%がhit@2） exact_miss（予測top1 ≠ 実際rank1）: **44日**（69....

### 9. `top3-output-already-implemented-per-expert`
- confidence: `0.98` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-pipeline` / `session-observation`
- trigger: TOP3末尾の出力を実装しようとするとき / latest_test_top3を参照するとき
- summary: `tail_ltr_split_rule_nextday_gpu.py` が出力する `*_latest_test_top3.csv` は、 各エキスパート（2F_N, 3F_N, 3F_A, 2F_A）のrank1・rank2・rank3を含む。 2F_Aも2026-05-26時点ではTOP3に含まれている（除...

### 10. `progress-reporting-required-in-all-loops`
- confidence: `0.98` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-active-filter-insights.yaml`
- domain/source: `ml-implementation-standards` / `session-requirement`
- trigger: when implementing walk-forward or any time-consuming loop in ML pipeline
- summary: 機種別予測（run_machine_type_v2.py）に進捗表示が実装されておらず、 処理時間の予測ができない問題があった。 末尾予測パイプラインには実装済みのため、全パイプラインで統一する。 時間のかかるループには必ず以下のパターンを使用する： import time start_time = time.t...

### 11. `ndcg-v2-dominant-model`
- confidence: `0.98` | date: `2026-05-26` | file: `2026-05-26-kamata7-ltr-multitier-strategy.yaml`
- domain/source: `ml-model-selection` / `session-observation`
- trigger: 蒲田七 last_digit LTR で複数モデルの比較・選択を行うとき
- summary: 5モデル（ndcg_v2, ndcg, pairwise, lgbm, catboost_v2）を hit@1→top1/top2, cluster23→top2/top3, hit@3→top3 の新指標で比較。 ndcg_v2 が全指標で1位。差は統計的に有意。 | 指標 | ndcg_v2 | 次点(ndc...

### 12. `anomaly-db-scope-must-be-single-hall`
- confidence: `0.98` | date: `2026-05-25` | file: `2026-05-25-anomaly-analysis-insights.yaml`
- domain/source: `ml-data-validation` / `session-observation`
- trigger: when running exploratory anomaly detection on pachinko data
- summary: run_exploratory_analysis.py のデフォルト --db-glob は "db/*.db" であり、 db/ 直下の全ホール（9ホール）を統合して分析する。 蒲田七は2025-07-07開業のため、他ホールのデータが混入すると 開業前データやzscoreが-22を超える極端な外れ値が混入し、...

### 13. `tail-vs-zorome-machine-separate-evaluation`
- confidence: `0.97` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `prediction-evaluation` / `codex-correction`
- trigger: 末尾予測精度とゾロ目台推奨精度を評価・報告するとき
- summary: CODEXの指摘：3F_Nの末尾7はセグメント1位（+13,300円）だったが、 台3077自体は-2,900円（外れ）。強さは非ゾロ目側（+16,200円）に寄っていた。 末尾精度とゾロ目台精度を混在させると「末尾は当たり、XX台は外れ」が見えない。 分析レポートで以下を常に分離して報告する： 1. tail...

### 14. `hokuto-machine-name-disambiguation`
- confidence: `0.97` | date: `2026-05-28` | file: `2026-05-28-signal-machine-analysis-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: スマスロ北斗の拳を信号機種として使う際に機種名を検索するとき
- summary: 蒲田七DBには「北斗」を含む機種が2つ存在する： `スマスロ北斗の拳`（信号機種として有効） `北斗の拳 転生の章2`（別機種・除外対象） `LIKE '%北斗%'` で検索すると両方が引っかかる。 「スマスロ北斗の拳」のみを対象にするために前方一致を使用する。 cursor.execute( "SELECT D...

### 15. `group-total-diff-is-not-per-machine`
- confidence: `0.97` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-evaluation` / `session-observation`
- trigger: LTR予測の差枚KPIを報告・解釈するとき
- summary: `loss_scenarios.csv` および `testperiod_topk.csv` の `top1_actual_raw_diff` は、 予測rank1末尾に属する**全台の差枚合計**（`total_diff_coins`）である。 kamata7の場合、2F_Nは末尾あたり約32台、3F_Nは15...

### 16. `rank2-not-rank3-equivalent`
- confidence: `0.97` | date: `2026-05-26` | file: `2026-05-26-kamata7-ltr-multitier-strategy.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: 蒲田七のLTRモデルで複数台の立ち回り戦略を設計するとき
- summary: 当初 rank2 と rank3 の差枚は微差であるという仮説が立てられていた。 もしそうなら「rank1 or rank2/3」という束ね戦略が有効になる。 strategy_eval_multitier.txt での検証（ndcg_v2、n=429日）で否定された。 rank2 と rank3 は厳密に順序付...

### 17. `train-eval-alignment-check-mandatory`
- confidence: `0.97` | date: `2026-05-25` | file: `2026-05-25-within-expert-target-fix.yaml`
- domain/source: `ml-eval-discipline` / `session-retrospective`
- trigger: when designing LTR training targets for any multi-group ranking task
- summary: hit@2 が 71% に留まっていた原因が「学習スコープ（グローバル）と 評価スコープ（エキスパート内）の不一致」だったことが今回判明した。 LTRの学習ターゲットを設計するとき、以下を必ず確認する： 1. 評価指標の group_ids に何を使っているか（date のみ？ date x group_key？...

### 18. `python-module-vs-script-execution`
- confidence: `0.97` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-pipeline-configuration` / `session-observation`
- trigger: when running ml/ 配下のPythonスクリプトをコマンドラインから実行するとき
- summary: `python ml/last_digit/tail_ltr_split_rule_nextday_gpu.py` で実行すると `ModuleNotFoundError: No module named 'ml'` が発生する。 `ml/` はパッケージ（`__init__.py` あり）として設計されており、...

### 19. `machine-master-flag-keyword-based`
- confidence: `0.97` | date: `2026-05-21` | file: `2026-05-21-machine-master-flag-system.yaml`
- domain/source: `database-maintenance` / `session-observation`
- trigger: machine_masterのbt_flagやhana_flagを追加・修正するとき
- summary: bt_flag / hana_flag / jug_flag / oki_flag はすべて機種名の部分一致で判定される。 フラグ判定ロジックは `database/data_inserter.py` の冒頭にある `_BT_KEYWORDS` リストで一元管理されている。 `get_or_create_mach...

### 20. `rb-threshold-258-not-300`
- confidence: `0.96` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_machine_correlation_analysis.py や signal_multi_tail_2fn.py でRB閾値を設定するとき
- summary: 旧来の `rb_threshold = 1/300 = 0.003333` はモンキーターンVの設定1（1/299）を捕捉してしまう。 北斗の設定3（1/297）も捕捉する。いずれも低設定であり、シグナルとして使いたい設定ではない。 両機種ともに「設定4以上」が意味のある設定で、その閾値が 1/258 = 0.0...

### 21. `zorome-correction-value-definition`
- confidence: `0.95` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `prediction-evaluation` / `user-correction`
- trigger: ゾロ目台の補正値・精度を評価するとき
- summary: 予測レポートの「台77 優先（+170）」などの数字は「同末尾の非ゾロ目台との期待差枚補正値」（過去データから算出）。 ゾロ目台の実績評価も同様に「ゾロ目台平均差枚 - 非ゾロ目台平均差枚（同末尾・同セグメント）」で計算する。 補正値 = ゾロ目台平均差枚 - 非ゾロ目台平均差枚（同末尾・同セグメント） 予測補正...

### 22. `anomaly-detection-requires-statistics`
- confidence: `0.95` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `statistical-analysis` / `user-correction`
- trigger: アノマリー判定（この日は普通か異常か）を行うとき
- summary: 「火曜日は比較的普通の日」などの直感的な判断は不十分。 ユーザーから「これは適当に行っただけですか？」と指摘を受けた。根拠なき断言は信頼を損なう。 アノマリー判定は過去30日以上のデータとz-score等の統計検定を用いる 根拠がない場合は「アノマリー判定未実施」と明記する 「普通の日」と断言しない z_scor...

### 23. `signal-correlation-or-rate-too-high`
- confidence: `0.95` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_machine_correlation_analysis.pyのシグナル発動率を確認するとき
- summary: `diff_coins > 200 OR rb_prob > 1/300` のOR条件で実行すると発動率83.7%になる根本原因が判明した。 **モンキーターンV設定1のRB確率は 1/299 = 0.003344 であり、閾値 1/300 = 0.003333 をわずかに超える。** つまり設定1台（最低設定）...

### 24. `signal-correlation-monday-confirmed`
- confidence: `0.95` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: モンキーターンV・スマスロ北斗の拳シグナルを曜日別に解釈するとき
- summary: RB閾値を正しい 1/258 に修正した上での曜日別結果（BH補正後）： | 曜日 | delta(旧1/300) | delta(新1/258) | p_adj(新) | 有意 | |------|--------------|--------------|----------|------| | 月 | +1...

### 25. `rb-quantile-0-90-optimal-cliff`
- confidence: `0.95` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_multi_tail_2fn.py で quantile を調整するとき
- summary: 蒲田七DBで `signal_multi_tail_2fn.py --signal-source rb --signal-mode quantile` を 複数 quantile で試した結果、single 日数が急崖を持つ： | quantile | single日 | hit_rate | |--------...

### 26. `wiki-reading-status-field-type`
- confidence: `0.95` | date: `2026-05-27` | file: `2026-05-27-ml-2f-3f-strategy.yaml`
- domain/source: `wiki-maintenance` / `session-observation`
- trigger: when adding Boolean fields to wiki frontmatter
- summary: に設定した値を誤って上書きする危険がある。 action: 'frontmatter repair時、既存の Boolean 値（True/False）は絶対に変更しない。型変換は String を Boolean に正規化する場合のみ。新規記事は reading_status: false をデフォルトとする。...

### 27. `explore-before-cross-feature-implementation`
- confidence: `0.95` | date: `2026-05-27` | file: `2026-05-27-cross-expert-agreement-insights.yaml`
- domain/source: `ml-methodology` / `session-observation`
- trigger: 複数モデル・グループ間の相関を特徴量にしようとしているとき
- summary: 「複数グループが同じ末尾を予測 → 信頼度UP」という直感は自然だが、 「ランダムでも起きる頻度」と比較しないとノイズ特徴量を実装するリスクがある。 本セッションでは探索先行により、実装前に「ランダム水準と区別不能」と判明し、 実装コストをゼロに抑えた。アンチパターン確認も同時に完了。 データ探索 → 判断 →...

### 28. `2fa-exclusion-is-hardcoded-default-not-data-driven`
- confidence: `0.95` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-pipeline` / `session-observation`
- trigger: 2F_Aが予測・評価から除外されているとき / テスト期間に2F_Aが現れないとき
- summary: `tail_ltr_split_rule_nextday_gpu.py` の `--reliability-exclude-experts` の デフォルト値が `"2F_A"` にハードコードされており、以下が発生する: 信頼性履歴トラッキングから2F_Aが除外される テスト期間評価（`--enable-tes...

### 29. `min-train-days-is-threshold-not-window`
- confidence: `0.95` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-active-filter-insights.yaml`
- domain/source: `ml-evaluation-design` / `session-analysis`
- trigger: when interpreting --min-train-days parameter in walk-forward evaluation
- summary: `--min-train-days=120` という設定を「訓練期間が120日」と誤解していた。 実際のコードでは以下のように動作する： start_idx = max(min_train_days, total_dates - eval_days) 蒲田7（322日）で eval_days=90 の場合： st...

### 30. `ceiling-effect-loss-based-metrics`
- confidence: `0.95` | date: `2026-05-26` | file: `2026-05-26-ceiling-effect-framework-design.yaml`
- domain/source: `ml-evaluation-strategy` / `session-observation`
- trigger: 機械学習モデルが99%以上の精度で天井効果に達し、特徴量改善が検知できない状態のとき
- summary: LTR モデルが hit@2 ≈ 99% に達すると、従来の accuracy ベースの評価では改善が検知できない。 特に「新特徴量の有効性」「グループ化戦略の最適性」「ハイパラ調整の効果」が数字に反映されない。 **実例**：digit_lag_v1 vs v2r_current hit@2: 0.8634 →...

### 31. `entity-level-rank1-unsolvable`
- confidence: `0.95` | date: `2026-05-26` | file: `2026-05-26-machine-type-v2-redesign-insights.yaml`
- domain/source: `ml-entity-level-targeting` / `session-analysis`
- trigger: when attempting machine_name (entity) level rank1 prediction
- summary: 蒲田七で machine_name（機種名）レベルの is_rank_1 予測を試みた結果： 全特徴量 MI < 0.01（ほぼノイズ） モデルが machine_type_encoded（AT系/A型/BT の3値）のみを学習 Hit@K = 0.0（ランダム以下） 機種間の長期平均ランクは有意に異なる（Kru...

### 32. `rank1-chaaichi-strategy-effective`
- confidence: `0.95` | date: `2026-05-26` | file: `2026-05-26-kamata7-ltr-multitier-strategy.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: 蒲田七で朝一狙い台を1台選ぶとき
- summary: rank1 miss (hit@1→top1 外れ) が全体の21.2%。 しかし外れたときに rank1 がどれだけ悪かったかを評価すると、 「的中（78.8%）」＋「微差ハズレ（予測rank1が実際top2に入る 16.5%）」＝ 97.9%。 完全ハズレ（rank1が著しく下位）は約2.1%にすぎない。 O...

### 33. `bt-all-high-days-only-3-of-320`
- confidence: `0.95` | date: `2026-05-25` | file: `2026-05-25-bt-digit-patterns.yaml`
- domain/source: `pachinko-domain-knowledge` / `data-observation`
- trigger: when evaluating whether BT（2FA）全台高設定 affects ML features in 蒲田七
- summary: bt_mode_classification.csv より all_high 判定日: 2025-07-07（月）、2025-07-09（水）、2025-10-30（木）の3日のみ（全期間の0.9%） ユーザーの「BT機種が全台に選ばれることは稀」という認識と完全に一致。 BT機種のML予測困難の原因は「all_...

### 34. `kamata7-weekday-investment-pattern-ground-truth`
- confidence: `0.95` | date: `2026-05-25` | file: `2026-05-25-kamata7-weekday-investment-pattern.yaml`
- domain/source: `pachinko-domain-knowledge` / `user-ground-truth`
- trigger: when designing any weekday-based feature or interpreting weekday patterns in 蒲田七
- summary: ユーザーが蒲田一と共有している法則。蒲田七の曜日別設定投入方針。 | 曜日 | イベント内容 | 投入パターン | |------|----------------|----------------------------------| | 日曜 | 機種1以上 | 各機種に最低1台は高設定 | | 土曜 | 三...

### 35. `small-sample-pattern-skepticism`
- confidence: `0.95` | date: `2026-05-25` | file: `2026-05-25-anomaly-analysis-insights.yaml`
- domain/source: `ml-evaluation` / `session-correction`
- trigger: when claiming a behavioral pattern from anomaly data with fewer than 5 examples
- summary: セッション内で「low anomaly翌週にhigh anomalyが発生」というパターンを 11/22→11/29の1例から提案してしまい、ユーザーに「再現性が低すぎる」と 正しく指摘された。9件のデータから1例では偶然と区別できない。 アノマリーベースのパターン主張は最低5例、できれば10例以上を要件とする。...

### 36. `duplicate-background-process-detection`
- confidence: `0.95` | date: `2026-05-25` | file: `2026-05-25-catboost-gpu-wf-insights.yaml`
- domain/source: `ml-execution` / `session-observation`
- trigger: when launching a long-running training job in the background
- summary: CatBoost walk-forward などの長時間ジョブをバックグラウンド実行する際、 前回のプロセスが終了していないまま再度コマンドを発行すると、 同一コマンドが複数並列起動され GPU リソースを奪い合う状態になる。 本セッションでは4プロセスが同時稼働し、それぞれが GPU を競合させた。 GPU メ...

### 37. `catboost-eval-metric-pairlogit`
- confidence: `0.95` | date: `2026-05-25` | file: `2026-05-25-catboost-gpu-wf-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when configuring CatBoostRanker with PairLogit loss
- summary: CatBoostRanker で loss_function="PairLogit" を使う場合、 eval_metric に "QueryRMSE" や "NDCG" を指定すると互換性エラーが発生する。 eval_metric も "PairLogit" に揃える必要がある。 CatBoostRanker(...

### 38. `batch-eval-time-management-checkpoints`
- confidence: `0.95` | date: `2026-05-24` | file: `2026-05-24-machine-type-ceiling-position-insights.yaml`
- domain/source: `ml-project-planning` / `session-observation`
- trigger: when planning ML evaluation runs for machine_type or last_digit models
- summary: 14時間連続実行（eval60 × 複数設定 × バッチ分割）は検証粒度が粗くなり、 途中の判断ミスが後半全体を無駄にするリスクがある。 以下の段階的基準を守る： **eval3〜5**: 動作確認・スモーク（新機能の疎通確認のみ） **eval20〜30**: 設定比較の主戦場。複数設定の優劣判定はここで行う...

### 39. `machine-type-f1-structural-limit`
- confidence: `0.95` | date: `2026-05-23` | file: `2026-05-23-machine-type-ltr-insights.yaml`
- domain/source: `ml-machine-type` / `session-observation`
- trigger: 機種別学習でF1スコアが0.10以下になったとき
- summary: 機種別学習で `is_rank_1` を二値分類ターゲットにすると、F1スコアが構造的に低くなる。 機種が N 種ある場合、`is_rank_1` の base_rate = 1/N（10〜20種なら0.05〜0.10）。 このとき F1 の理論的上限 ≈ base_rate × 2 = 0.10〜0.20 程度...

### 40. `machine-master-insert-vs-update`
- confidence: `0.95` | date: `2026-05-21` | file: `2026-05-21-machine-master-flag-system.yaml`
- domain/source: `database-maintenance` / `session-observation`
- trigger: 新規機種が追加されたのにbt_flagが0のままになっているとき
- summary: `data_inserter.py` の `get_or_create_machine_master()` は既存レコードがあれば そのまま返して終了する（UPDATEしない）。 キーワードを追加しても、すでにDBに登録済みの機種には自動で反映されない。 キーワード追加後は必ず `python database/...

### 41. `nonstationarity-invalidates-single-regime-models`
- confidence: `0.95` | date: `2026-05-14` | file: `2026-05-14-tail-ranking-nonstationarity.yaml`
- domain/source: `ml-project-planning` / `session-observation | data-analysis`
- trigger: when predicting rankings/classifications across temporal periods with shifting baseline distributions
- summary: When absolute baseline metrics shift systematically across time (e.g., high-profit rate drops from 29% to 24%), models trained on one regime will fail catast...

### 42. `data-driven-discovery-supersedes-hypothesis`
- confidence: `0.95` | date: `2026-05-14` | file: `2026-05-14-tail-ranking-nonstationarity.yaml`
- domain/source: `ml-project-planning` / `user-feedback`
- trigger: when tempted to validate domain-based hypotheses without confronting actual data patterns
- summary: Domain expertise (e.g., "payday effects on machine selection") provides useful starting hypotheses, but must be validated with rigorous statistical testing....

### 43. `rolling-window-shift-prevention`
- confidence: `0.95` | date: `2026-05-12` | file: `2026-05-12-data-leakage-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when implementing rolling window features in time-series ML
- summary: Rolling window aggregations (moving averages, rolling std, etc.) automatically include the current observation in their calculation. When these features are...

### 44. `page16-global-filter-pattern`
- confidence: `0.95` | date: `2026-05-12` | file: `2026-05-12-page16-page13-optimization.yaml`
- domain/source: `dashboard-ui-patterns` / `session-observation`
- trigger: when implementing bulk display pages with multiple filter targets
- summary: 複数のクロス検索ブロック（attribute1 × attribute2）を同時表示する場合、各ブロック内で独立してフィルタを提供すると、UIが複雑になり、一括管理ができない。 1. ページ冒頭に グローバルフィルタセクション を配置 2. 主要な属性（DD別、曜日別など）の multiselect を用意 3....

### 45. `time-series-validation-critical`
- confidence: `0.95` | date: `2026-05-09` | file: `2026-05-09-phase8-10-insights.yaml`
- domain/source: `ml-project-planning` / `phase9-03-correction`
- trigger: when building rank prediction models for time-series data with non-uniform class distribution
- summary: Phase 9-3 initially used simple sample-based test split (last 57 samples), producing AUC 0.37-0.57, inconsistent with Phase 9-2's date-based split producing...

### 46. `calibrated-beats-rebalancing`
- confidence: `0.95` | date: `2026-05-09` | file: `2026-05-09-phase7-ml-insights.yaml`
- domain/source: `ml-feature-engineering` / `phase7-experimental-validation`
- trigger: when implementing XGBoost on imbalanced classification (minority <10%)
- summary: Imbalanced binary classification typically uses class rebalancing (scale_pos_weight = neg_count / pos_count) to maximize AUC. However, this destroys probabil...

### 47. `ece-calibration-importance`
- confidence: `0.95` | date: `2026-05-08` | file: `2026-05-08-Phase7-Calibration-Insights.yaml`
- domain/source: `ml-hyperparameter-tuning` / `session-observation`
- trigger: when training XGBoost classification models with extreme class imbalance
- summary: XGBoost の scale_pos_weight パラメータには2つの使い方がある： **Balanced（adjusted）**: precision/recall のバランスを取る（daily_hit_rate が高い） **Calibrated（=1.0）**: 確率スコアを信頼できるものにする（ECE...

### 48. `hokuto-exact-miss-correction-negative`
- confidence: `0.93` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: MLモデルの予測外れ日に北斗で補正できるかを検討するとき
- summary: testperiod_topk.csv の2F_N expert で exact_miss（予測top1 ≠ 実際rank1）の44日を抽出し、 その日の北斗ベスト末尾と2FN最優秀末尾の一致率を計算した。 結果: **hit_rate = 3/44 = 6.82%**（baseline 10% を下回る） 曜日...

### 49. `auc-and-hit1-diverge-with-feature-overload`
- confidence: `0.93` | date: `2026-05-27` | file: `2026-05-27-machine-type-ltr-segmentation-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-experiment`
- trigger: LTRモデルに特徴量を大量追加したときAUCが改善するがhit@1が悪化するとき
- summary: baseline6（6特徴量）→ rich_all（130+特徴量）に変更した結果： combined AUC: 0.584 → 0.615（+0.031）✓ combined hit@1: 0.189 → 0.122（-0.067）✗ combined lift@1: 1.885 → 1.316（-0.569）...

### 50. `hit-at-2-is-soft-metric-rank1-exact-is-operational`
- confidence: `0.93` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-evaluation` / `session-observation`
- trigger: LTRモデルの精度を報告・比較するとき
- summary: hit@2 = 「予測上位2件のどちらかが実際のTOP2内に入っていれば成功」。 99.1%は「2回チャンスがある」という緩い条件での数値。 実際の運用では最も良い末尾1つを選ぶため、ランク1完全一致が核心指標。 精度報告では hit@2 だけでなく以下を必ず併記する: `top1_match`: rank1完全...

### 51. `v2-withinexpert-is-current-ceiling`
- confidence: `0.93` | date: `2026-05-26` | file: `2026-05-26-v2-withinexpert-is-ceiling.yaml`
- domain/source: `ml-feature-engineering` / `data-observation`
- trigger: when evaluating new feature variants against the last_digit LTR baseline
- summary: ceiling_effect フレームワーク（BH補正、Wilcoxon/Mann-Whitney）による再評価（2026-05-26）。 評価対象：digit_lag v2p1/v2p2/v2p3/v2r/v3/v3a/v3b/v4/v4a/v4b（11バリアント） **比較結果サマリ（同一ルールで再集計）:*...

### 52. `modular-architecture-prevents-monolith`
- confidence: `0.93` | date: `2026-05-26` | file: `2026-05-26-ceiling-effect-framework-design.yaml`
- domain/source: `code-architecture` / `session-observation`
- trigger: 複数フェーズの処理パイプラインを実装するとき、『全部 1 ファイルでいいか』と迷うとき
- summary: ceiling_effect フレームワークは本来 1000 行級の単一ファイルになりがちだが、 7 つの小モジュールに分割することで： 各モジュールの責務が明確（責務分離） テストが書きやすい（ユニットテスト化） バグ修正のスコープが小さい（デバッグ時間短縮） 再利用しやすい（他フェーズでの import） モ...

### 53. `block-resampling-date-expert-pair`
- confidence: `0.93` | date: `2026-05-26` | file: `2026-05-26-ceiling-effect-framework-design.yaml`
- domain/source: `statistical-rigor` / `session-observation`
- trigger: bootstrap 信頼区間を計算するときに、観測値の独立性が崩れているか疑うとき
- summary: 同一日内の複数台や複数 expert はクラスタ構造がある場合、 単純な iid resampling では CI が楽観化する。 理由：同一日内の台は条件を共有（相関あり）、同一 expert は skill が一定（時系列相関あり） bootstrap 実装時は必ず以下を守る： 1. **Block 単位の決...

### 54. `hall-level-rolling-features-mi-zero`
- confidence: `0.93` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `data-observation`
- trigger: when selecting features for is_top2 LTR target in last_digit prediction
- summary: MI-LTR分析（ターゲット: is_top2）の結果: roll7_avg_diff, roll14_avg_diff, roll28_avg_diff のMI = 0.0 lag1/7/14_avg_diff のMI = 0.0 weekday のMI = 1.98e-6（実質ゼロ） ホール全体のaggreg...

### 55. `exploratory-analysis-before-ml-feature-design`
- confidence: `0.93` | date: `2026-05-25` | file: `2026-05-25-anomaly-analysis-insights.yaml`
- domain/source: `ml-project-planning` / `session-retrospective`
- trigger: when starting a new ML prediction project for pachinko or similar time-series data
- summary: 今回は walk-forward 評価やモデル比較を先行させ、 アノマリー検出・生存時間分析・カイ二乗検定などの EDA を後回しにした。 EDA 先行なら window サイズ（roll7/14/28）や efficiency 列の除外判断を より早い段階でデータに基づいて行えた。 次回の ML プロジェクト開...

### 56. `rb-signal-more-stable-than-diff`
- confidence: `0.92` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: 差枚シグナルとRBシグナルのどちらを優先するか検討するとき
- summary: signal_machine_correlation_analysis.py の蒲田七結果（rb_threshold=1/258 で補正済み）： | シグナル種別 | delta | p値 | signal_n | |------------|-------|-----|---------| | diff_sig...

### 57. `signal-multi-tail-vs-correlation-distinction`
- confidence: `0.92` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: 北斗・モンキーのシグナルを2種類の分析で解釈するとき
- summary: 2つの分析が異なる問いを立てており、結果が「矛盾するように見える」場合がある。 | 分析 | 問い | 蒲田七の結果 | |------|------|------------| | signal_machine_correlation | RBシグナル末尾の他機種は平均的に良いか？ | YES (delta+6...

### 58. `correction-sign-direction-rule`
- confidence: `0.92` | date: `2026-05-28` | file: `2026-05-28-zorome-combined-strategy-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: correction 値をもとにゾロ目台を選ぶか避けるかを判断するとき
- summary: 「|correction| > 150 かつ correction > 0」という記述は正しいが冗長で誤解を招く。 correction > +150 と書けば絶対値条件も符号条件も同時に満たす。 「|correction| > 150 かつ correction < 0」は correction < -150...

### 59. `machine-ml-practical-role-as-filter`
- confidence: `0.92` | date: `2026-05-27` | file: `2026-05-27-machine-type-ltr-segmentation-insights.yaml`
- domain/source: `ml-evaluation` / `session-observation`
- trigger: 機種MLと末尾MLの精度を比較するとき / 機種MLの実用水準を判断するとき
- summary: 蒲田7での比較（2026-05-27時点、LTR 2分割 90日評価）： 末尾ML hit@1→top2: 95.3%（144日、10択） 機種ML hit@1→top3: 18.9%（90日、30択） 性能差の理由： 1. 末尾ML は 10択、機種ML は 30択（問題の難易度が3倍） 2. 末尾番号はホール...

### 60. `lambda-hyperparameter-opposite-overfitting`
- confidence: `0.92` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-segment-diagnostics-insights.yaml`
- domain/source: `ml-hyperparameter-selection` / `tune-vs-holdout-validation`
- trigger: when selecting combined_lambda via tune/holdout evaluation
- summary: combined_lambda パラメータ選択で以下を観測： | λ | tune hit@1 | holdout hit@1 | |---|-----------|--------------| | 0.0 | 0.633 | 0.389 | | 0.5 | 0.600 | **0.422** | 通常の過学習...

### 61. `cross-expert-agreement-is-random-baseline`
- confidence: `0.92` | date: `2026-05-27` | file: `2026-05-27-cross-expert-agreement-insights.yaml`
- domain/source: `ltr-feature-engineering` / `data-exploration`
- trigger: クロスエキスパート特徴量（複数グループの末尾合意）を実装しようとしているとき
- summary: 4エキスパート（2F_A/2F_N/3F_A/3F_N）が翌日の末尾top2を予測するとき、 「複数グループが同じ末尾を予測していれば信頼度が高い」という直感がある。 しかし蒲田7の147日間の実測データを検証したところ、 この直感は統計的に支持されなかった。 4グループがそれぞれ10末尾から2つを独立にランダム...

### 62. `bottom3-does-not-require-new-model`
- confidence: `0.92` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-pipeline` / `session-observation`
- trigger: BOTTOM3（下位末尾）を予測・出力したいとき
- summary: `latest_test_full.csv` は各エキスパートの全10末尾スコアを保持している。 BOTTOM3 = スコアが最も低い3末尾（rank 8, 9, 10）であり、既存データから直接抽出可能。 専用のis_worst_1モデル（worst1_hit_rate=78.9%）と同等効果が期待できる。 1...

### 63. `active-machine-filter-not-performance-filter`
- confidence: `0.92` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-active-filter-insights.yaml`
- domain/source: `ml-data-filtering` / `session-analysis`
- trigger: when filtering training machines for Layer 1 segment model
- summary: 2F_N の学習対象を絞り込む際に fleet_diff（平均差枚×台数）や avg_diff でフィルターする 案が出たが、それは誤り。Layer 1 が予測するのは「その日のセグメント内相対順位」であり、 平均的に負けている機種でも「高設定が入る日」は上位になる。 その日を予測できれば実運用上の価値がある。...

### 64. `daily-topk-beats-fixed-threshold-low-baserate`
- confidence: `0.92` | date: `2026-05-26` | file: `2026-05-26-kisyuzen-evaluation-insights.yaml`
- domain/source: `ml-evaluation-design` / `session-implementation`
- trigger: when evaluating a binary classifier with base_rate below 5%
- summary: Layer 0（is_kisyuzen 検知）を base_rate=3.45% で実装した際、 CatBoost の予測確率が全件 0.03〜0.25 程度に収束し、 閾値 0.3 でも 0.5 でも precision/recall = 0.0 となった。 原因: well-calibrated な CatB...

### 65. `mvp-first-staged-implementation`
- confidence: `0.92` | date: `2026-05-26` | file: `2026-05-26-ceiling-effect-framework-design.yaml`
- domain/source: `ml-project-planning` / `session-observation`
- trigger: 大規模な ML 評価フレームワーク構築時に、全部一度にやるか悩むとき
- summary: ceiling_effect フレームワークの実装を段階化することで、実装リスク・テスト負荷・デバッグ難易度を軽減できた： Phase 1-2 MVP（データ加工 + loss 計算）を先に完了 実データで loss_scenarios.csv, condition_layer_metrics.csv を生成確認...

### 66. `kikata-detection-machine-level-winrate`
- confidence: `0.92` | date: `2026-05-26` | file: `2026-05-26-kikata-winrate-target-insights.yaml`
- domain/source: `ml-target-engineering` / `session-analysis`
- trigger: when designing a target to detect 機種全/末尾全 events
- summary: 「全台設定」には以下の種類がある： **機種全**：特定の機種名に属する全台が高設定 **末尾全**：特定の末尾番号に属する全台が高設定 **ホール全台**：ホール全体が高設定（非常に稀） 当初 Layer 0 の target として daily_hall_summary.win_rate（ホール全体の日次勝率...

### 67. `zorome-machine-末尾-efficacy-patterns`
- confidence: `0.92` | date: `2026-05-26` | file: `2026-05-26-kamata7-zorome-machine-patterns.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: 蒲田7の立ち回り戦略を設計するとき、同じ末尾グループの台を選ぶ際に
- summary: 末尾同じだが、ゾロ目台（末尾2桁が同じ数字）とそれ以外で差枚期待値を比較した。 結果は末尾に大きく依存： 末尾0: ゾロ目 +173.80枚 優位 末尾5: ゾロ目 +123.66枚 優位 末尾9: ゾロ目 +119.52枚 優位 末尾6: ゾロ目 +91.33枚 優位 末尾1-4: ゾロ目 +11～68枚（弱い...

### 68. `bt-machine-type-db-vs-hall-definition-mismatch`
- confidence: `0.92` | date: `2026-05-25` | file: `2026-05-25-bt-machine-characteristics.yaml`
- domain/source: `pachinko-domain-knowledge` / `user-ground-truth`
- trigger: when using machine_type flags (jug_flag, hana_flag, bt_flag) for 蒲田七 or 蒲田一 analysis
- summary: DBでは A型（jug_flag/hana_flag）と BT（bt_flag）は別フラグとして管理されている 蒲田七・蒲田一の運用上の分類: A型とBTを「非AT（非N）」としてまとめて扱う 2FAフラグは実質的にBT専用フラグとして機能している 厳密には異なる機種だが、台数の少なさと「非AT」という共通点から...

### 69. `kamata7-daily-all-high-machine-layer-a`
- confidence: `0.92` | date: `2026-05-25` | file: `2026-05-25-daily-all-high-machine-layer.yaml`
- domain/source: `pachinko-domain-knowledge` / `user-ground-truth`
- trigger: when interpreting machine_type performance or BT/2FA prediction in 蒲田七
- summary: 蒲田七の設定投入は2層構造: Layer A（毎日・常時）: 2F: 特定の1機種 → 全台高設定 3F: 特定の1機種 → 全台高設定 計1〜2機種が毎日全台保証される Layer B（曜日別追加）: 水曜: 特定末尾2つ × 50% 火曜: 角からX・Y番目 × 50% 土曜: 末尾連番3台、など（[[kam...

### 70. `hall-digit-lag-complements-entity-level-lag`
- confidence: `0.92` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-reasoning`
- trigger: when adding lag features to the LTR model for last_digit prediction
- summary: 現行モデルのlag特徴量は `entity_key = "3F_N|7"` 単位（フロア×末尾）で計算。 EDAのMI分析で有効と判定された `lag7_digit_diff` は ホール全体の末尾別集計（全フロアを跨ぐ）であり、別次元の信号。 MI rank1: lag7_digit_diff (0.01237...

### 71. `rare-anomaly-days-as-heuristic-not-feature`
- confidence: `0.92` | date: `2026-05-25` | file: `2026-05-25-anomaly-analysis-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-reasoning`
- trigger: when considering whether to add anomaly-day detection as an ML feature
- summary: 蒲田七の分析では全321日中9件（2.8%）がアノマリー日。 テスト期間143日中4件。現状hit@2が90%以上の状態で アノマリー日をすべて正しく予測できても改善幅は1-2%未満。 特徴量として取り込むコストに見合わない。 アノマリー日の知見は特徴量化せず以下の用途に使う: 1. 「3〜5週間に一度、高設定大...

### 72. `catboost-gpu-model-params`
- confidence: `0.92` | date: `2026-05-25` | file: `2026-05-25-catboost-gpu-wf-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when enabling GPU for CatBoostRanker in tail_ltr_split_rule_nextday_gpu.py
- summary: tail_ltr_split_rule_nextday_gpu.py では model_params をモデル名で分岐させる。 当初 xgb_ モデルにしか GPU 設定が適用されておらず、 catboost_ranker_pairlogit は CPU で動作していた。 CatBoost は task_type...

### 73. `confirmed-feature-set-no-smooth-ewm-no-rank-trend`
- confidence: `0.92` | date: `2026-05-24` | file: `2026-05-24-machine-type-ceiling-position-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when selecting feature set for machine_type XGBoost production use
- summary: Ablation eval30 および eval60 分割評価の結果、smooth_ewm はノイズ、 rank_trend は寄与ゼロと判定。cross_section は除外で悪化するため必須。 machine_type XGBoost の本番特徴量: `ml/machine_type/reports/_ke...

### 74. `cross-sectional-normalization-for-machine-ranking`
- confidence: `0.92` | date: `2026-05-23` | file: `2026-05-23-machine-type-ltr-insights.yaml`
- domain/source: `ml-machine-type` / `session-observation`
- trigger: 機種別学習で絶対値特徴量（差枚、効率など）を使うとき
- summary: 機種ごとに差枚の構造的差異がある（ハナハナは元々差枚が少ない、AT機は多いなど）。 絶対値の差枚をそのまま特徴量として使うと、機種間の構造差がシグナルを覆い隠す。 同日の全機種に対して正規化（zscore, rank_pct, vs_mean）を施すことで、 「この機種は今日の平均よりどれだけ高いか」という相対的...

### 75. `machine-name-hyoki-zure-patterns`
- confidence: `0.92` | date: `2026-05-21` | file: `2026-05-21-machine-master-flag-system.yaml`
- domain/source: `database-maintenance` / `session-observation`
- trigger: 機種名でDBを検索・フラグ判定するとき
- summary: ana-slo.comからスクレイピングした機種名には複数の表記揺れが存在し、 同一機種が異なるキーとして登録されてしまうケースがある。 キーワード設計時は以下の揺れを考慮する： 1. **プレフィックス有無**: `L不二子BT` vs `不二子BT`、`スマスロ ハナビ` vs `新ハナビ` 2. **全角/...

### 76. `engineered-features-outperform-raw`
- confidence: `0.92` | date: `2026-05-09` | file: `2026-05-09-phase9-10-breakthroughs.yaml`
- domain/source: `ml-feature-engineering` / `phase9-10-hyperlearning`
- trigger: when implementing ML models with many raw features
- summary: Phase 9-10 tested 4 feature set strategies for Rank1 prediction: all_31d: 31 raw/derived features top_10_only: 10 features by importance top_15: 15 features...

### 77. `worktree-main-sync-awareness`
- confidence: `0.92` | date: `2026-05-12` | file: `2026-05-12-page16-page13-optimization.yaml`
- domain/source: `git-workflow-management` / `session-observation`
- trigger: when using worktrees and wondering why git status is clean but files seem modified
- summary: このセッションは worktree（claude/nice-cray-7682e2）で実行されており、main ブランチは別の worktree で使用されていた。編集ツールで修正を加えても、git status がクリーンに見えた理由は、worktree と main が分離されていたから。 1. Worktr...

### 78. `dd-concentration-analysis`
- confidence: `0.92` | date: `2026-05-09` | file: `2026-05-09-phase89-domain-analysis-tasks.yaml`
- domain/source: `ml-domain-analysis` / `phase8-9-recall-fixed-analysis`
- trigger: when investigating shop's high-setting investment timing patterns
- summary: Phase 8-9 Recall固定精度比較分析で、CatBoost + Top_5 + Recall=10% の高精度予測機械の特性を分析した結果、**DD（月内日付）の平均値が18.4日**に集中していることが発見された。これは給料日（25日）前の集客対策、または月半ばの定期リセットなどの戦略的投入を示唆する...

### 79. `moving-averages-dominate`
- confidence: `0.92` | date: `2026-05-09` | file: `2026-05-09-phase7-ml-insights.yaml`
- domain/source: `ml-feature-engineering` / `phase7-feature-importance-analysis`
- trigger: when engineering features for time-series rank/win-rate prediction
- summary: Feature importance analysis on 28D set (14D temporal + 15D rolling averages) showed moving averages capture 88-89% of predictive importance. Day-of-week, pay...

### 80. `threshold-optimization-precision-recall-tradeoff`
- confidence: `0.92` | date: `2026-05-08` | file: `2026-05-08-Phase7-Calibration-Insights.yaml`
- domain/source: `ml-hyperparameter-tuning` / `session-observation`
- trigger: when balancing model utility (precision vs coverage) for practical deployment
- summary: 確率予測モデルの実用性は「どの確度の予測を使うか」で大きく変わる。 top_5 ターゲットでの例： 閾値 0.01: Precision 0.0702, データ数 4061 閾値 0.50: Precision 0.1014, データ数 1193 閾値 0.60: Precision 0.1192, データ数 6...

### 81. `calibration-enables-risk-based-decisions`
- confidence: `0.91` | date: `2026-05-08` | file: `2026-05-08-Phase7-Calibration-Insights.yaml`
- domain/source: `ml-project-planning` / `session-observation`
- trigger: when model confidence scores are used for business decision-making
- summary: Calibrated モデル（ECE < 0.02）を使えば、確率スコアをそのまま「リスク」または「確信度」として使用できる。 Calibrated top_5 モデル例： 「50%確度」の予測 → 実際に 50% の確率で的中 「60%確度」の予測 → 実際に 60% の確率で的中 Calibrated モデル...

### 82. `combined-dynamic-weight-by-expert-reliability`
- confidence: `0.90` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `prediction-strategy` / `codex-correction`
- trigger: combined予測を作成するとき・各expertの信頼度が異なるとき
- summary: CODEXの指摘：「2F_N/2F_Aがノイズになっていてcombinedを崩した。 3F_N/3F_A中心にすれば上位の崩れは小さかった」。 等重みcombinedでは信頼度の低いexpertが予測を歪める。 各expertのtop1ミス率・直近精度を事前確認しウェイトを調整 top1ミス率 > 20% のex...

### 83. `prediction-accuracy-two-layer-structure`
- confidence: `0.90` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: 末尾別予測とゾロ目台補正予測の精度を同時に評価するとき
- summary: 2026-05-27の分析で判明：3F_Aは末尾別Top3で完全的中（3/3）だったが、 ゾロ目補正値の予測では1/3のみ的中。同じモデルでも評価軸によって精度が大きく異なる。 末尾別精度（全機種）とゾロ目補正精度（ゾロ目台）を別々に報告する 「モデルが優秀」と言う際はどの評価軸の話かを明確にする 末尾別精度が高...

### 84. `nextday-zorome-workflow-spec`
- confidence: `0.90` | date: `2026-05-28` | file: `2026-05-28-signal-machine-analysis-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: 翌日予測と台末尾ゾロ目を統合した実行可能な出力を生成するとき
- summary: 翌日の立ち回りを決定するために以下を一つの出力にまとめる： 1. 翌日予測（末尾ランキング） 2. 各末尾の確信度（combined_scoreをmin-max正規化） 3. 予測上位の末尾に該当する「台末尾ゾロ目」の機種名・台番号リスト 「台末尾ゾロ目」は `machine_detailed_results.i...

### 85. `wiki-field-name-consistency`
- confidence: `0.90` | date: `2026-05-27` | file: `2026-05-27-ml-2f-3f-strategy.yaml`
- domain/source: `wiki-maintenance` / `session-observation`
- trigger: when implementing new frontmatter fields
- summary: フィールド名不一致は修復処理を破壊する。 action: 新しい frontmatter フィールドを導入する場合、CLAUDE.md に明記し、関連するすべてのスキル（ingest-v2, frontmatter-repair, など）で統一の フィールド名と型を使用する。 example: 'reading_...

### 86. `floor2-split-beats-floor-atype4-split`
- confidence: `0.90` | date: `2026-05-27` | file: `2026-05-27-machine-type-ltr-segmentation-insights.yaml`
- domain/source: `ml-segment-design` / `session-experiment`
- trigger: 機種別MLでセグメント設計を変更するとき / 2F_Aの機種数不足でbase_rateが不安定なとき
- summary: 機種別ML v2 では当初 floor × atype の4セグメントを使用していた。 2F_A の機種数が少ない（≈10台）ためbase_rateが高止まりし学習が不安定だった。 フロア二分割（2F / 3F）に変更して各セグメントの機種数を増やした結果： 2F lift@1: 1.12 → 1.67（大幅改善...

### 87. `correction-sign-persistence-not-reversal`
- confidence: `0.90` | date: `2026-05-27` | file: `2026-05-27-zorome-training-window-optimality.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: correction テーブルの予測方向性（反転 vs 持続）を検証するとき
- summary: 3つの参加条件戦略（同一 expert×digit で参加可否のみ変化）を比較： D（correction>0 末尾優先）：mean_diff_per_calendar_day = +690.323, coverage 74.2% E（correction<0 末尾回避）：mean_diff_per_calend...

### 88. `cross-expert-lag1-performance-signal-null`
- confidence: `0.90` | date: `2026-05-27` | file: `2026-05-27-cross-expert-agreement-insights.yaml`
- domain/source: `ltr-feature-engineering` / `data-exploration`
- trigger: 昨日の複数グループ合意末尾が翌日も良いか検証するとき
- summary: 「昨日2+グループが合意した末尾は今日も高パフォーマンス（streak）」という仮説を検証。 147日間のtestperiodデータで計測した結果： Lag-1 agree → 翌日avg_diff/機 Spearman r = -0.019（実質ゼロ） Mann-Whitney p = 0.33（有意差なし）...

### 89. `2fn-base-rate-too-sparse-for-top3`
- confidence: `0.90` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-active-filter-insights.yaml`
- domain/source: `ml-target-engineering` / `session-analysis`
- trigger: when evaluating 2F_N segment Layer 1 performance
- summary: 蒲田7の 2F_N（AT系・2F）の現状： アクティブ機種: 34機種（引退済み 29 を除く） is_top3 の base_rate: 3/34 ≈ 8.8%（学習帯域 10〜30% を下回る） holdout lift@3=0.52（ランダム以下、予測が逆効果） tune 期では lift@3=1.18 だ...

### 90. `low-support-warning-15-is-high-in-this-dataset`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-v2-withinexpert-is-ceiling.yaml`
- domain/source: `ml-evaluation-strategy` / `data-observation`
- trigger: when interpreting low_support count in ceiling_effect framework evaluation
- summary: ceiling_effect フレームワークの条件層評価（16分割）で 全バリアントが low_support=12〜15/16 件という高い警告率を示した。 これは「n<10 のサブグループが多数ある」ことを意味し、 統計テストの信頼性が低い条件層が多い。 low_support が 50%（8/16）を超える...

### 91. `layer0-target-scope-is-machine-not-hall`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-kikata-winrate-target-insights.yaml`
- domain/source: `ml-hierarchical-architecture` / `session-design-correction`
- trigger: when implementing Layer 0 day-quality filter for machine_name prediction
- summary: 2層アーキテクチャの Layer 0 を「ホール全体の良い日フィルタ」として実装したが誤り。 蒲田七のホール全体 win_rate >= 80% は 320 日中 1 日（0.3%）しか存在せず、 評価期間 30 日間で正例がゼロ、モデルが全て proba=0.0 を出力して機能しなかった。 原因の根本は「全台設...

### 92. `exploration-coarse-to-fine`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-ml-exploration-coarse-to-fine.yaml`
- domain/source: `ml-exploration-strategy` / `session-observation`
- trigger: パチスロML予測で、特徴量・グループ化戦略・ハイパラを探索するとき
- summary: 制限されたリソース（計算時間、実験反復数）の中で、 探索空間全体を効率的にカバーするため、 段階的な絞り込み戦略が必須。 無計画に細かい最適化から始めると、 全体像を見落とし、局所最適解に陥る。 pachinko-analyzer Phase 5-6 での実証： Phase 5（粗い探索）: 全ホール統合 vs...

### 93. `within-segment-target-density-critical`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-machine-type-v2-redesign-insights.yaml`
- domain/source: `ml-target-engineering` / `session-observation`
- trigger: when deciding between top3 vs top5 as target within a segment
- summary: セグメントサイズが小さいと、上位K個の threshold が自動的に高くなり学習が簡単になる反面、 予測する価値が低下する（ほぼ全て推薦 = 意味がない）。 蒲田七の場合： 2F_A: 15機種 → is_top5 base_rate = 0.543 (random baseline 0.998) → is_t...

### 94. `feature-drift-detection-essential`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-machine-type-v2-redesign-insights.yaml`
- domain/source: `ml-feature-validation` / `session-eda`
- trigger: when using historical features (prior_top1_rate, lag features) in time-series prediction
- summary: EDA で特徴量ドリフトを検測した結果： **prior_top1_rate**: KS p=10^-43（極めて有意）× PSI=0.0193 → 過去の勝利実績が最近無効化 **roll7_rank_pct**: recent 期間で permutation importance=-0.024（有害） **l...

### 95. `cluster-machines-mask-individual-zorome-efficacy`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-kamata7-zorome-machine-patterns.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: 蒲田7の末尾7,8のゾロ目台が弱い理由を理解するとき
- summary: 末尾7,8の差枚期待値： 末尾7: ゾロ目 -59.36枚、非ゾロ目でも弱い → 全体的に低設定傾向 末尾8: ゾロ目 -90.55枚、非ゾロ目でも弱い → 全体的に低設定傾向 推測される背景： ホール側は「複数台同時展開」を重視する場合、 末尾7,8の同じ設定複数台をグループで投入する。 このクラスター戦略では...

### 96. `multitier-evaluation-metrics-standard`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-kamata7-ltr-multitier-strategy.yaml`
- domain/source: `ml-evaluation` / `session-observation`
- trigger: LTRモデルの評価指標を設計・更新するとき
- summary: 単純な hit@2（top2命中率）だけでは立ち回り戦略全体を評価できない。 運用は「rank1固定→rank2移行→rank3移行」の多段構造なので、 各ステップで意味のある指標を設計した。 以下の指標を標準評価セットとして使用する： hit@1→top1: rank1が実際1位になる率（朝一戦略の直接評価）...

### 97. `confidence-band-case-a-thresholds`
- confidence: `0.90` | date: `2026-05-26` | file: `2026-05-26-kamata7-ltr-multitier-strategy.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: LTRモデルの予測結果に信頼帯を付与するとき
- summary: pred_span_top12（top1予測スコア − top2予測スコア）を信頼度指標として使用。 v2 の3件のミス日すべてで span が低かった。 2026-01-04: span=0.000521（undefined） 2026-01-11: span=0.000892（undefined） 2026-...

### 98. `digit3-weakness-caused-by-at-series-dominance`
- confidence: `0.90` | date: `2026-05-25` | file: `2026-05-25-digit3-weekday-cross-insights.yaml`
- domain/source: `pachinko-domain-knowledge` / `data-observation`
- trigger: when interpreting why last_digit=3 shows lowest mean_diff in overall stats of 蒲田七
- summary: digit3_profile_report.csv（蒲田七全期間）の機種タイプ別内訳: | machine_type | mean_diff | n_rows | 構成比 | |-------------|-----------|--------|--------| | AT系 | 84.9 | 14,913 |...

### 99. `bt-machine-low-ceiling-compressed-diff-distribution`
- confidence: `0.90` | date: `2026-05-25` | file: `2026-05-25-bt-machine-characteristics.yaml`
- domain/source: `pachinko-domain-knowledge` / `user-ground-truth`
- trigger: when interpreting BT machine diff_coins distribution or ML prediction difficulty in 蒲田七
- summary: BT機種の特性（ユーザー確認済み）: 1. 機械割100%超え → 設定1でも長期的にプラスになる 2. 一定ユーザー層が平日・イベント日を問わず安定して稼働 3. 高設定の機械割が低い（設定6でも設定1との差が小さい） 4. 設定2以上を入れられることが少ない（高設定コストに見合わないため） AT系との差枚分布...

### 100. `atype-machine-has-lower-diff-coins-than-at`
- confidence: `0.90` | date: `2026-05-25` | file: `2026-05-25-machine-type-diff-and-weekday-layout-corrections.yaml`
- domain/source: `pachinko-domain-knowledge` / `user-correction`
- trigger: when comparing expected diff_coins between A型 and AT系 machines in 蒲田七 analysis
- summary: A型（ジャグラー・ハナハナ等）は機械割が低い機種が多く、高設定でも差枚の絶対値は小さい。 AT系は機械割の振れ幅が大きく、高設定時の差枚は大きくなる。 誤認しやすいポイント: digit3_profile_report で A型末尾3のmean_diff=243.0 > AT系末尾3のmean_diff=84.9...

### 101. `digit3-at-vs-atype-split`
- confidence: `0.90` | date: `2026-05-25` | file: `2026-05-25-digit3-hall-strategy-insights.yaml`
- domain/source: `ml-feature-engineering` / `data-observation`
- trigger: when designing features for last_digit=3 in machine_type or last_digit LTR model
- summary: digit3_profile_report.csv（section=digit3_by_machine_type）より: | 機種タイプ | mean_diff | std_diff | 台数比率 | |-----------|-----------|----------|---------| | AT系 | 8...

### 102. `thursday-threshold-split-rejected`
- confidence: `0.90` | date: `2026-05-24` | file: `2026-05-24-machine-type-ceiling-position-insights.yaml`
- domain/source: `ml-hyperparameter-tuning` / `session-observation`
- trigger: when considering weekday-specific thresholds for machine_type XGBoost
- summary: 木曜日は非木曜と比べてF1・Hit@3が高い傾向があった。 この差を活かすために閾値分離を実装して eval20 で比較した結果、 閾値が上昇して予測数が激減し、全ターゲットで F1・Hit@3 が悪化した。 木曜専用閾値分離は採用しない（スモーク eval3 と eval20 の両方で悪化確認） 木曜フラグを特...

### 103. `ltr-replaces-binary-classifier-for-ranking`
- confidence: `0.90` | date: `2026-05-23` | file: `2026-05-23-machine-type-ltr-insights.yaml`
- domain/source: `ml-machine-type` / `session-observation`
- trigger: 機種別・台末尾別など、同日同グループ内でのランキング予測をするとき
- summary: 日付単位でグループ化したXGBRankerは、Binary Classificationの「クラスアンバランス問題」と「絶対閾値問題」を両方回避できる。 `rank:ndcg` objective は NDCG@K を最大化し、Hit@K と相関が高い。 既存の `ml/last_digit/core_ranki...

### 104. `machine-master-per-hall-db`
- confidence: `0.90` | date: `2026-05-21` | file: `2026-05-21-machine-master-flag-system.yaml`
- domain/source: `database-architecture` / `session-observation`
- trigger: machine_masterテーブルを参照・更新するとき
- summary: `db/machine_master.db`（db_setup.pyが作る共有マスター）と、 各ホールDB内の `machine_master` テーブル（data_inserter.pyが動的に作る）は別物。 ダッシュボードのクエリ（table_config.py）は各ホールDB内の machine_maste...

### 105. `relative-ranking-stability-despite-absolute-drift`
- confidence: `0.90` | date: `2026-05-14` | file: `2026-05-14-tail-ranking-nonstationarity.yaml`
- domain/source: `ml-feature-engineering` / `data-analysis`
- trigger: when observing that absolute frequencies shift uniformly but relative order stays constant
- summary: If all groups shift by the same amount (e.g., all 末尾 drop 5pp uniformly), the relative ranking (which tail is strongest) doesn't change. This is a key insigh...

### 106. `learning-to-rank-for-non-stationary-baselines`
- confidence: `0.90` | date: `2026-05-14` | file: `2026-05-14-tail-ranking-nonstationarity.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when predicting which option ranks highest, given absolute baseline may shift over time
- summary: Classification and regression predict absolute values or categories; when baseline shifts, these fail. Learning to Rank predicts relative ordering (which opt...

### 107. `detect-leakage-via-perfect-metrics`
- confidence: `0.90` | date: `2026-05-12` | file: `2026-05-12-data-leakage-insights.yaml`
- domain/source: `ml-project-planning` / `session-observation`
- trigger: when model evaluation produces suspiciously high metrics (AUC 1.0, precision/recall 1.0)
- summary: Statistically impossible perfect metrics (AUC 1.0, F1 1.0, precision/recall 1.0) almost always indicate data leakage rather than genuinely excellent model pe...

### 108. `page13-caching-performance`
- confidence: `0.90` | date: `2026-05-12` | file: `2026-05-12-page16-page13-optimization.yaml`
- domain/source: `streamlit-performance-optimization` / `session-observation`
- trigger: when loading same database repeatedly in loop or tab-based UI
- summary: page_13 では8つのタブがあり、タブを切り替えるたびに全ホール DB を再読み込みしていた。DB 読み込み関数に @st.cache_data がなかったため、同じデータが何度も読み込まれていた。 1. DB読み込み関数に @st.cache_data(ttl=3600) をデコレータとして追加 @st.c...

### 109. `baseline-model-saturation`
- confidence: `0.90` | date: `2026-05-09` | file: `2026-05-09-phase8-10-insights.yaml`
- domain/source: `ml-hyperparameter-tuning` / `phase10-observation`
- trigger: when hyperparameter tuning yields <1% AUC improvement
- summary: Phase 10 hyperparameter grid search over max_depth=[2,3,4,5] and learning_rate=[0.001-0.05] yielded only +0.38% to +0.59% AUC improvement for rank prediction...

### 110. `days-since-cycle-verification`
- confidence: `0.90` | date: `2026-05-09` | file: `2026-05-09-phase89-domain-analysis-tasks.yaml`
- domain/source: `ml-domain-analysis` / `phase8-9-recall-fixed-analysis`
- trigger: when validating shop's high-setting investment periodicity
- summary: 高精度予測機械の days_since_rank1 (前回高設定からの経過日数) の平均値が11.7日という結果は、**約2週間サイクルで高設定が投入される**ことを示唆する。これは固定的な定期投入戦略の存在を強く示唆する。 1. 機械ごと・ホール全体で高設定投入の時間間隔を時系列で可視化 2. 実際に7日・14...

### 111. `ece-metric-for-imbalanced`
- confidence: `0.90` | date: `2026-05-09` | file: `2026-05-09-phase7-ml-insights.yaml`
- domain/source: `ml-hyperparameter-tuning` / `phase7-scale-pos-weight-comparison`
- trigger: when evaluating ML on imbalanced datasets and deciding between rebalancing strategies
- summary: Standard practice uses AUC alone for imbalanced classification. But AUC doesn't capture probability calibration. For deployment (e.g., "recommend if P > 0.8"...

### 112. `data-binning-for-noisy-features`
- confidence: `0.90` | date: `2026-05-08` | file: `2026-05-08-Phase7-Calibration-Insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when feature distributions are highly variable (range > 10x the mean)
- summary: 差枚・ゲーム数などの累積特徴量は非常に大きなばらつきを持つ： 差枚: -6000 ～ 19000（広すぎる範囲） ゲーム数: 0 ～ 3000（同様に広い） このままでは、モデルが「±100円の違い」にまで反応してしまい、過学習につながる。 高ばらつき連続値特徴量に対しては： 1. 固定幅ブロック化（pd.cut...

### 113. `tree-models-need-feature-engineering`
- confidence: `0.90` | date: `n/a` | file: `phase6b-ml-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: when implementing tree-based ML models
- summary: XGBoostなどのツリーベースモデルは、ワンホットエンコーディングのような単純な二値特徴では線形モデル（ロジスティック回帰）と同等の性能にとどまる（Δ +0%）。 相互作用特徴（interactions）や非線形関係を明示的に特徴量として追加することで、ツリーが効率的に分割でき、大幅な性能改善が実現される。 P...

### 114. `zorome-correction-strict-three-conditions`
- confidence: `0.88` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `prediction-strategy` / `codex-correction`
- trigger: ゾロ目台（XX番台）を推奨するかどうか判断するとき
- summary: CODEXの指摘：「9はcombined 2位だったが3F_Nで-800, 2F_Aで-1200で根拠として弱すぎた。 ゾロ目補正が7と9を押し上げすぎた」。補正値プラスでもサンプルや合意が薄ければ信頼できない。 XX台推奨には以下3条件を全て確認する： 1. correction > +150（同末尾非ゾロ目と...

### 115. `signal-machine-dual-condition`
- confidence: `0.88` | date: `2026-05-28` | file: `2026-05-28-signal-machine-analysis-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: モンキーターンV・スマスロ北斗の拳の兆候を判定するとき
- summary: 「モンキーターンV または スマスロ北斗の拳が兆候を示している」の判定に 2つの独立した基準がある： 1. **差枚基準**: avg(diff_coins_normalized) > threshold（例: 200枚） 2. **RB確率基準**: avg(rb_probability_decimal) <...

### 116. `machine-level-correction-does-not-hold`
- confidence: `0.88` | date: `2026-05-28` | file: `2026-05-28-machine-level-correction-negative-finding.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: ゾロ目台を台番号レベルで個別に選別しようとしているとき
- summary: 蒲田7（323日、ゾロ目台70台）で machine_level_correction_analysis を実施した結果： FDR有意台数: 1/70（1.4%）— ランダムなら5%有意で3〜4台出るはず 前半/後半の correction 符号一致率: 42/70（60.0%） 前半/後半のスピアマン相関: r...

### 117. `setting-cycle-hypothesis-rejected-kamata7`
- confidence: `0.88` | date: `2026-05-27` | file: `2026-05-27-machine-type-ltr-segmentation-insights.yaml`
- domain/source: `ml-hypothesis-validation` / `session-experiment`
- trigger: 機種別MLで days_since_last_rank1 を重要特徴量として期待しているとき
- summary: 「ホールが定期的に特定機種に設定を入れる → days_since_last_rank1 が予測に有効」 という仮説を rich_all feature importance で検証した結果： days_since_last_rank1: 2F=130位、3F=85位 days_since_last_top3:...

### 118. `zorome-training-window-optimality-120days`
- confidence: `0.88` | date: `2026-05-27` | file: `2026-05-27-zorome-training-window-optimality.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: correction テーブルの安定性とゾロ目戦略の有効性を評価するとき
- summary: 複数の訓練期間（60, 90, 120, 180, full）でゾロ目戦略シミュレーションを実行した結果、 B（ゾロ目優先）vs A（ランダム）の期待差枚が、訓練期間に対して ∩ 型（山型）の曲線を示した。 60d: +256.887 枚/機 90d: +230.067 枚/機 120d: +286.340 枚/...

### 119. `segment-machine-count-impacts-learning-difficulty`
- confidence: `0.88` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-segment-diagnostics-insights.yaml`
- domain/source: `ml-segment-design` / `segment-diagnostics-analysis`
- trigger: when comparing performance across segments with different machine pool sizes
- summary: 3F_A（16 台）と 2F_A（10 台）の Layer 1 モデルを比較したところ、同じ TOP3 特徴量を使用しているにもかかわらず精度が大きく異なることが判明した。 原因は特徴量ではなく、**セグメントあたりの機種数**の違いである。 **2F_A：10 台** is_top3 理論値 = 3/10 =...

### 120. `combined-prediction-zorome-strategy-definition`
- confidence: `0.88` | date: `2026-05-27` | file: `2026-05-27-combined-prediction-simulation-spec.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: MLモデルの翌日末尾予測とゾロ目補正を組み合わせて台選択戦略を作るとき
- summary: 4エキスパート（2F_N/3F_N/3F_A/2F_A）の翌日末尾ランキング予測に加え、 「特定の曜日において特定の末尾のゾロ目台（XX番台）が優秀な成績を残す傾向」 という観測が重なった。 水曜日（2026-05-28）の予測例： combined top10: 7, 9, 5, 4, 3, 6, 0, 8,...
