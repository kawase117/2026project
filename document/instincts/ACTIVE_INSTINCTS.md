# ACTIVE_INSTINCTS

- generated_at: 2026-06-11T07:28:43+09:00
- compiler_version: 1.1.0
- source_dir: `C:/Users/apto117/Documents/pachinko-analyzer/src/2026project/document/instincts`
- total_records_scanned: 559
- active_records: 120
- filters: `confidence >= 0.80` and `file_date within 21 days` (unless pinned by high confidence)

## Usage
- Start of work: run `venv\Scripts\python.exe scripts/compile_instincts.py` (or `python scripts/compile_instincts.py`).
- Long sessions: rerun before major decisions or every 15-20 minutes.
- Preferred source for Codex: `ACTIVE_INSTINCTS.jsonl` (machine-readable canonical).
- This Markdown is a quick view. Open raw YAML only when detail is missing.
- Default behavior skips files like `_cli_export.yaml`; add `--include-underscored-sources` when needed.

## Active List

### 1. `rb-probability-juggler-hokuto-spec`
- confidence: `1.00` | date: `2026-06-10` | file: `2026-06-10-rb-probability-analysis-insights.yaml`
- domain/source: `machine-spec` / `user-provided`
- trigger: スマスロ北斗の拳・モンキーターンV・ジャグラー各種のRB確率(rb_probability_decimal)から設定推定を行うとき
- summary: 2026-06-10セッションでユーザーから提供された、ジャグラーシリーズ以外の RB確率ベース設定判別が可能な機種のスペック表。 以下のスペックをRB確率(1/X)から設定推定する際の基準値として使う。 | 設定 | AT初当り確率 | 出玉率 | |---|---|---| | L | ※下パネルが常に点滅...

### 2. `kabaneri-s-and-l-version-distinction`
- confidence: `1.00` | date: `2026-06-10` | file: `2026-06-10-machine-hall-fixedeffect-and-banchou4-insights.yaml`
- domain/source: `machine-naming` / `user-clarification`
- trigger: カバネリ・甲鉄城のカバネリについて分析するとき / 「カバネリ海門」という呼称が出てきたとき
- summary: 蒲田7では以下の2機種が両方とも現役（last_date=20260607）で稼働している: | machine_name | n(games>=1000) | baseline hit104 | |---|---|---| | 甲鉄城のカバネリ（無印・S版） | 1648 | 45.8% | | 甲鉄城のカバネ...

### 3. `juggler-series-bonus-probability-spec`
- confidence: `1.00` | date: `2026-06-10` | file: `2026-06-10-juggler-spec-and-debut-curve-insights.yaml`
- domain/source: `machine-spec` / `user-provided`
- trigger: ジャグラーシリーズ機種の設定別出玉率・ボーナス確率を参照するとき / kaiwari近似値の精度を機種別に検証するとき
- summary: 2026-06-10セッションでユーザーから提供されたジャグラーシリーズの公称スペック。 hit104%（機械割104%以上）の解釈や、機種ごとの設定推定の基礎データとして使う。 以下のスペック表を機種別の設定推定・閾値較正に使用する。 | 設定 | BIG | REG | 合算 | 出玉率 | |---|---...

### 4. `daily-hall-summary-date-features-null-bug`
- confidence: `1.00` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda` / `session-observation`
- trigger: daily_hall_summary の day_of_week / last_digit / is_x_day を使った分析をするとき
- summary: `date_info_calculator.py` は全日付で実行されておらず、`daily_hall_summary` の `day_of_week`, `last_digit`, `is_x_day` 等は443日中わずか3日分しか入っていない。 例：レイトギャップ 土曜 n=422（修正前）→ 24,850...

### 5. `firstday-analysis-implementation`
- confidence: `0.99` | date: `2026-06-10` | file: `2026-06-10-new-machine-firstday-hall-insights.yaml`
- domain/source: `eda-implementation` / `implementation`
- trigger: 新台初日のホール別・機種別パフォーマンスを集計するスクリプトを書くとき / debut_dateを計算するとき
- summary: `machine_detailed_results` に導入初日フラグは存在しないため、 「機種ごとの最古date = debut_date」として計算する。 pre_existing（DBスタート日に既に存在した機種）を除外する必要がある。 実装済みファイル: `eda/hall_firstday_analys...

### 6. `weekday-digit-nth-single-dim-all-null`
- confidence: `0.99` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: 曜日・台番号末尾・第N曜日を単独次元でスキャンするとき
- summary: daily_hall_summaryのJOINバグを修正した後、21次元 × 9ホールの全スキャンを実施。 以下の単独次元は全ホール・全パターンでTier A/B が1件も出なかった。 以下の単独次元に基づく台選択・設定投入予測は無効として扱う： `day_of_week`（曜日単独） `machine_digi...

### 7. `rb-threshold-monkey-hokuto-confirmed`
- confidence: `0.99` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `rb-signal` / `instinct-confirmed`
- trigger: モンキーターンV・スマスロ北斗の拳のRBシグナルを使うとき
- summary: 旧閾値 1/300=0.003333 ではモンキーターンV設定1（1/299=0.003344）が 閾値を突き抜けて全台シグナル扱いになり、発動率83.7%という汚染が発生した。 北斗の拳設定3（1/297=0.003367）も同様に捕捉されていた（設定3は低設定）。 設定4以上を識別する正しい閾値 = 1/25...

### 8. `mitoya-bari-island-nonexistent`
- confidence: `0.99` | date: `2026-06-09` | file: `2026-06-09-mitoya-lag-feature-island-section-insights.yaml`
- domain/source: `data-model` / `session-observation`
- trigger: みとや大森町店で assign_island() を使うとき / island カテゴリ数を確認するとき
- summary: assign_island() の定義: machine_num >= 832 を 'bari' に分類。 みとや大森町店の machine_detailed_results における machine_number の実際の範囲: MIN=501, MAX=815, n=266台 → 815 < 832 のため、...

### 9. `python-windows-encoding-japanese-output`
- confidence: `0.99` | date: `2026-06-07` | file: `2026-06-07-island-digit-stability-insights.yaml`
- domain/source: `data-pipeline` / `empirical-validation`
- trigger: WindowsのPython分析スクリプトで日本語を含む出力を行うとき、または機種名・ホール名を表示するスクリプトを書くとき
- summary: Windows環境ではPythonのデフォルトstdoutエンコーディングがCP932（Shift-JIS）のため、 UTF-8で保存された日本語文字列をprintすると文字化けする。 分析スクリプトで機種名・ホール名が文字化けすると誤った名称を正しい名称と誤認し 分析結果の解釈を誤る危険がある。 実害の例： 機...

### 10. `kakuban-not-rank-terminology`
- confidence: `0.99` | date: `2026-06-07` | file: `2026-06-07-mitoya-corner-aisle-eda-insights.yaml`
- domain/source: `terminology` / `user-correction`
- trigger: 台配置位置の順位を表現するとき
- summary: title: 「角番」と「ランク」は区別必須 — 位置は角番、成績順位はランクと呼ぶ ユーザーからの明示的な指摘: 「ランクだと成績順位と混同する。角番という言い方に統一してください」。 本プロジェクトでは: **角番**（kakuban）: メイン通路からの距離による位置順位（rank_from_aisle,...

### 11. `full-2025-window-boundary-safety`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-leakage-audit-insights.yaml`
- domain/source: `methodology` / `code-audit`
- trigger: walk-forward の学習窓 full_2025 が holdout と重複しないか確認するとき、または新しい window_name を追加するとき
- summary: `build_train_window("full_2025", test_start)` は `(REGIME_1_START="2025-07-07", REGIME_2_END="2025-12-31")` を返す。 holdout 期間は `REGIME_3_START="2026-01-01"` 以降。...

### 12. `xday-equals-is-xday-flag`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `hall-specific` / `db-exploration`
- trigger: みとやの x_day bucket を定義または実装するとき
- summary: みとや大森町 DB で is_x_day=1 の日と「day % 10 in {4,7}（4/7/14/17/24/27日）」は 514日間で完全一致（n=102、重複率100%）。 x_day ONLY: 0件、ld4/7 ONLY: 0件。 x_day 判定は `day % 10 in {4, 7}` で計算...

### 13. `poco-diff-is-db-derived`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-poco-analysis-db-insights.yaml`
- domain/source: `poco-data-quality` / `empirical-measurement`
- trigger: ぽこデータの差枚精度を疑うとき・ぽこCSVとDBの差枚を比較するとき
- summary: poco_data_v5.csv の `kamata7_diff` / `kamata1_diff` がアナスロデータと一致するか全期間検証した結果、 K7: 282件中1件不一致、K1: 210件中3件不一致（ほぼ完全一致）。 ぽこの差枚欄はアナスロDB（machine_detailed_results の S...

### 14. `catboost-gpu-ndcg-not-implemented`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-allhall-model-architecture-insights.yaml`
- domain/source: `ml-infrastructure` / `empirical-20260605`
- trigger: when using CatBoostRanker with GPU backend and NDCG objective
- summary: CatBoostRanker に --use-gpu を指定した場合、NDCG 目標が GPU 未実装という警告が出て 計算継続するが、精度が崩壊した： CPU: avg_diff=111.81 GPU: avg_diff=34.73（壊滅的な低下） GPU 経路では CatBoostRanker を除外する。...

### 15. `walrus-operator-parameter-overwrite`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `python-bugs` / `session-observation`
- trigger: Pythonのwalrus演算子 := をif条件の中で使うとき
- summary: `feature_engineering.py` の Feature 8 で以下のコードがあった： if is_train := False: # Placeholder: always use stored stats pass walrus演算子は関数パラメータ `is_train` をローカル変数として `...

### 16. `poco-is-post-hoc-not-realtime`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-poco-forward-strategy-insights.yaml`
- domain/source: `poco-analysis-fundamentals` / `user-correction`
- trigger: ぽこデータを使った戦略・予測を立てるとき
- summary: ぽこ（poco）のデータは「その日の結果が出た後」に発表される事後記録である。 当日朝にぽこを確認して「今日発表された機種を打ちに行く」という使い方は不可能。 | 用途 | 可否 | |------|------| | 当日の台選択 | NG（事後発表のため不可） | | 過去パターンの統計分析 | OK（11ヶ...

### 17. `poco-hall-separation-rule`
- confidence: `0.99` | date: `2026-06-05` | file: `2026-06-05-poco-hall-analysis-insights.yaml`
- domain/source: `poco-analysis-workflow` / `user-instruction`
- trigger: ぽこデータをK7・K1両ホールで分析・出力するとき
- summary: 蒲田七（K7）と蒲田一（K1）は戦略・規模・データ品質が根本的に異なる： 規模: K7 月平均69.7機種発表 vs K1 44.9機種（K7の約65%） K7: アニメ系スマスロを幅広く・平日も機種名明示 K1: 戦国乙女4・カバネリ海門などに集中・平日は機種全が「不明」多数 同一機種でもK7とK1で実績が真逆...

### 18. `instinct-contamination-two-types`
- confidence: `0.99` | date: `2026-06-01` | file: `2026-06-01-instinct-management-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク修正後に過去のinstinctを評価するとき、または古いinstinctを参照しようとするとき
- summary: 2026-05-31のリーク修正後、過去のinstinctを精査した結果、 汚染の種類によって処置が異なることが判明した（2026-06-01）。 種類1「MLモデル性能値が主体」→ contaminated/ へアーカイブ（無効化） AUC=0.8140、hit@2=98%、precision@2=83% 等の...

### 19. `adjusted-lift-denominator-10-not-9`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_multi_tail_2fn の hit_rate をランダムベースラインと比較するとき
- summary: 蒲田七の末尾は 0-9 の10種類（北斗は末尾4欠番で9台だが、末尾数は10）。 summary.json の `baseline_random = 0.1` がこれを示している。 分母を 9 にすると diff・OR が「baseline 以下」に見えるが、10 にすると「baseline 水準」になる。 |...

### 20. `instinct-scope-taxonomy-rule`
- confidence: `0.99` | date: `2026-06-01` | file: `2026-06-01-hall-independence-principle.yaml`
- domain/source: `ml-architecture` / `user-instruction`
- trigger: 新しいinstinctを作成するとき、または既存instinctをインポートするとき
- summary: ホール固有の発見と普遍的な方法論が混在することで、 別ホール分析時に誤った前提が持ち込まれる問題が発生した（2026-06-01）。 add_instinct_scope.py で既存70件に一括追加済み。 新しいinstinctを作成するとき、必ず以下のフィールドを追加する： confidence: 0.XX...

### 21. `hall-specific-findings-never-transfer-to-other-halls`
- confidence: `0.99` | date: `2026-06-01` | file: `2026-06-01-hall-independence-principle.yaml`
- domain/source: `domain-strategy` / `user-instruction`
- trigger: 別のホールの分析を始めるとき、または複数ホールにまたがる提案をするとき、または蒲田7の数値を引用するとき
- summary: ユーザーから繰り返し指摘された最重要ルール（2026-06-01 確立）： 「ホール固有ルールが強い。他ホールと比較することに意味がない。」 パチンコホールは独立した経営主体であり、設定投入戦略を共有する理由がない。 他業種でも経営戦略は共有しない（例：A社の販売戦略がB社でも有効とは限らない）。 蒲田7で確認さ...

### 22. `signal-existence-must-precede-ml-design`
- confidence: `0.99` | date: `2026-06-01` | file: `2026-06-01-signal-existence-insights.yaml`
- domain/source: `ml-architecture` / `data-analysis`
- trigger: MLモデルの設計・特徴量追加を検討するとき
- summary: signal_existence_plan.py を蒲田7（holdout 150日）で実行した結果： 反復回避：P(top1_{t+1}|top1_t) = 0.098 vs 基準0.10（非有意） ランク自己相関：max |rho|≈0.035（実質ゼロ） (DD,末尾)セル：Bonferroni補正後有意0...

### 23. `leakage-check-direction-must-be-inclusion-not-exclusion`
- confidence: `0.99` | date: `2026-05-31` | file: `2026-05-31-leakage-protocol-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク確認を依頼されたとき、またはget_numeric_features()の出力を確認するとき
- summary: total_diff_coins_focus のリークを複数回の確認依頼にもかかわらず見逃した。 原因は「除外リストに target 列が含まれているか」をチェックしていたこと。 しかし本当に必要なのは「get_numeric_features() が返す全列の生成元を追跡すること」。 間違ったチェック方向： e...

### 24. `grid-search-exposes-narrow-space-artifacts`
- confidence: `0.99` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: 限定的な探索で見つかったシグナルを全空間に拡張するとき
- summary: lag=14 × 2F_N × digit=8 の発見経緯： 1. is_positive autocorr で raw hit → p_raw=0.00066 2. lag=14 に絞った検定 → FDR=0.026 で有意 3. 全 expert × 全 digit × 複数 lag のグリッド探索 → FD...

### 25. `total-diff-coins-focus-leakage-root-cause`
- confidence: `0.99` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテストのhit@2が95%超のとき、またはget_numeric_featuresで特徴量セットを変更するとき
- summary: clean holdout監査（2025選定→2026評価）でも hit@2=98-99% が継続したことで調査。 以下の手順でリークを特定した： 1. ナイーブ基準（過去固定Top2）: hit@2=37.8% ≈ ランダム → Top2は日次で変動しており単純暗記ではない 2. 全lag特徴量のSpearma...

### 26. `dd-value-missing-from-features`
- confidence: `0.99` | date: `2026-05-31` | file: `2026-05-31-evaluation-feature-insights.yaml`
- domain/source: `ml-architecture` / `code-inspection`
- trigger: 特徴量セットを確認・拡張するとき、またはdd_valueを実装するとき
- summary: add_simple_features()（tail_ltr_split_rule_wf.py line 167）の実際の特徴量： 既存（曜日系、追加不要）: weekday（0-6）, weekday_sin, weekday_cos, is_wed weekday_prior_top2_rate, weekd...

### 27. `signal-correlation-json-output-keys`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: signal_machine_correlation_summary.jsonを読み込んで解釈するとき
- summary: 実際の出力JSONのキーは `overall_stats` や `weekday_stats` ではなく、 `signal_or`, `diff_signal_only`, `rb_signal_only`, `fake_tail_check` など。 間違ったキーでアクセスすると None が返って解釈を誤る。...

### 28. `kamata7-floor-classification`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `data-processing` / `session-observation`
- trigger: 蒲田七（マルハンメガシティ2000-蒲田7）のデータをセグメント分類するとき
- summary: machine_detailed_resultsにはフロア情報が直接ないが、台番号でフロアを判定できる。 Heatmap/2F_floor_coordinates_kamata7.csvで確認済み。 machine_number < 3000 → 2F（2001〜2351付近） machine_number >=...

### 29. `correct-segment-classification-floor-atype4`
- confidence: `0.99` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `data-processing` / `codex-correction`
- trigger: 蒲田七の機台をセグメント分類（2F_N/3F_N/3F_A/2F_A）するとき
- summary: 台番号の先頭桁（2xxx=2F / 3xxx=3F）だけで分類していたのは不正確。 正しい定義は ml/last_digit/tail_ltr_split_rule_wf.py の floor_atype4 モードにあり、 jug_flag/hana_flag/bt_flag を使ってA/N型を判定する。 df[...

### 30. `is-top2-must-be-within-expert`
- confidence: `0.99` | date: `2026-05-25` | file: `2026-05-25-within-expert-target-fix.yaml`
- domain/source: `ml-pipeline-configuration` / `session-breakthrough`
- trigger: when defining LTR ranking target for multi-expert pachinko prediction
- summary: 末尾別LTRパイプラインでは複数のエキスパート（2F_N / 3F_N / 3F_A / 2F_A）が それぞれ独立したモデルを持つ。 評価指標 hit@2 は「エキスパート内10アイテム中、予測top2が実績top2を含むか」で定義。 （metrics_ops.py: true_top2 = actual_ra...

### 31. `window-name-vs-feature-name-confusion`
- confidence: `0.99` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-pipeline-configuration` / `session-error`
- trigger: when specifying --windows-wed or --windows-nonwed arguments for tail_ltr_split_rule_nextday_gpu
- summary: ACF/PACFで「roll28が最適」という知見を得た後、 `--windows-wed "roll28"` を指定したところ全candidateが "unavailable" になった。 `roll28` は特徴量名（`roll28_total_diff_coins`）であり、 training window...

### 32. `pre-existing-machine-debut-detection`
- confidence: `0.98` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `implementation`
- trigger: days_since_debutを計算するとき / compute_debut_features を使うとき
- summary: `compute_debut_features(df, db_start_grace_days=0)` で実装済み。 蒲田7の検証結果: DB期間: 2025-07-07 〜 2026-06-07 pre_existing 60機種: 全て debut_date == 2025-07-07（DB初日に集中） DB...

### 33. `dd-individual-x-day-confirmation`
- confidence: `0.98` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: DD個別（1-31）スキャンの結果を解釈するとき
- summary: DD個別（1-31）スキャン結果： みとや: DD4=+280, DD14=+234, DD24=+213（全Tier B）→ 4系x_dayと完全一致 蒲田7: DD7=+425 → 7系x_dayと一致 蒲田1: DD7=+194 → 7系の弱い反応 レイトギャップ: DD6=+219 → 6系x_dayと一...

### 34. `anomaly-next-day-mean-reversion`
- confidence: `0.98` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: ANOMALYを翌日の台選択シグナルとして使おうとするとき
- summary: 全ホール合算・翌日1000G以上でのANOMATY後続検証: | 条件 | 翌日avg | 翌日plus率 | |------|---------|----------| | ANOMALY日（score≥2） | +43 | 39.8% | | 通常日（score<2） | +60 | 40.6% | ANOM...

### 35. `machine-name-contamination-in-ml-training`
- confidence: `0.98` | date: `2026-06-07` | file: `2026-06-07-mitoya-ml-prediction-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `empirical-validation`
- trigger: みとや（または他ホール）でCatBoostにmachine_nameをCAT_FEATUREとして使うとき
- summary: みとや大森町店 266台中 **204台（76%）** で機種名が変わっていた（515日分データ）。 例: 台501-522は「ダンベル何キロ持てる？」→「バンドリ！」→「甲鉄城のカバネリ 海門(うなと)決戦」のように変遷。 CatBoostに`machine_name`をCAT_FEATUREとして使うとき、...

### 36. `mitoya-daily-hall-summary-null-flags`
- confidence: `0.98` | date: `2026-06-06` | file: `2026-06-06-mitoya-corner-section-position-insights.yaml`
- domain/source: `data-quality` / `empirical-observation`
- trigger: みとやDBで daily_hall_summary の日付フラグを使おうとしたとき
- summary: title: みとやの daily_hall_summary フラグは全行 NULL — date 文字列から直接導出する みとやスロスのDBでは daily_hall_summary の day_of_week, last_digit, weekday_nth, is_strong_zorome が 514 行...

### 37. `forecast-excluded-columns-leakage-guard`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-leakage-audit-insights.yaml`
- domain/source: `methodology` / `code-audit`
- trigger: みとやまたは他ホールのLTRモデルに新しいカラムを特徴量として追加しようとするとき
- summary: `utils.py` の `FORECAST_EXCLUDED_COLUMNS` は同日の目的変数と直接相関するカラムを列挙している。 `get_numeric_features()` はこのセットと `META_COLUMNS` と `is_top_2` を除外してから 数値カラムを特徴量リストとして返す。 `...

### 38. `bucket-specific-hall-average-baseline`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: walk-forward の mean_diff から実際の期待差枚を計算するとき
- summary: walk-forward の mean_diff は「モデル予測末尾のexcess（予測末尾台平均 − その日のホール全体台平均）」であり、 絶対的な期待差枚ではない。 全期間の overall ホール台平均をベースラインとして使うと、 属性ごとに大きく異なるホール台平均を見落とす。 みとや大森町では x_day...

### 39. `dd-vs-xday-definition-clarification`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-monthly-trend-db-design-insights.yaml`
- domain/source: `db-design` / `session-interview-20260605`
- trigger: when designing aggregation axes around date patterns (DD, Xのつく日, 末尾)
- summary: 「DD別」と「Xのつく日」を混同しやすい。このプロジェクトでの定義： **DD** = 日付の日（1〜31の具体的な日番号） 4日、14日、24日はそれぞれ別のDD 月内に**1回だけ**出現する **Xのつく日（date_digit）** = 日付末尾の数字（0〜9） 4のつく日 = 4日・14日・24日（月に...

### 40. `make-binary-model-gpu-branch-bug`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-allhall-model-architecture-insights.yaml`
- domain/source: `ml-architecture` / `session-observation-20260605`
- trigger: XGBoostがインストールされている環境でGPUフラグの動作を確認するとき、またはmake_binary_modelを実装・修正するとき
- summary: `if XGBClassifier is None` という条件でモデルを分岐すると、 XGBoostがインストールされている環境では `--use-gpu` なしでも常に XGBClassifier が使われる。 これにより LogisticRegression でチューニングされたベースライン（例: hybr...

### 41. `sql-injection-fstring-table-name`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `security` / `session-observation`
- trigger: SQLクエリでテーブル名・カラム名をf-stringで埋め込むとき
- summary: `data_loader.py` の `load_machine_detailed_by_date` でf-string SQLが使われており、 `date_str` が直接クエリに埋め込まれていた。`database_accessor.py` では `table_name`・`column` もf-string...

### 42. `bare-except-swallows-keyboard-interrupt`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `python-bugs` / `session-observation`
- trigger: 例外処理で except: pass を書くとき
- summary: `date_info_calculator.py` の `_check_holiday` で `except: pass` が使われており、 `BaseException`（`KeyboardInterrupt`や`SystemExit`含む）ごと無音で飲み込んでいた。 フォールバックがあるケースでも失敗が完全に...

### 43. `poco-partial-status-multi-machine-mapping`
- confidence: `0.98` | date: `2026-06-05` | file: `2026-06-05-poco-hall-analysis-insights.yaml`
- domain/source: `poco-data-pipeline` / `session-observation`
- trigger: ぽこ機種マッピングで1つのエントリーを複数機種に展開する必要があるとき
- summary: `rebuild_poco_pipeline.py` の `PATCH_FOUND` ディクショナリは、ループで全エントリーを `('FOUND', db_match)` として登録する。`norm_one()` の FOUND ハンドラは `return [db_match]` と単一要素リストを返すため、パイ...

### 44. `machine-name-alias-normalization-critical`
- confidence: `0.98` | date: `2026-06-02` | file: `2026-06-02-poco-facility-structure.yaml`
- domain/source: `pachinko-data-analysis` / `user-domain-knowledge`
- trigger: ぽこデータの機種情報を DB と照合するとき
- summary: ぽこで使用される機種名は、DB 内の正式な機種名と大きく異なる。 正規化なしに照合すると、実際には一致する機種でも「0%的中」と判定される。 `スーパーブラックジャック` ↔ `SBJ` ↔ `スパブラ` `ミスタージャグラー` ↔ `ミスター` `北斗の拳転生2` ↔ `北斗転生2` ↔ `北斗`（曖昧） `デ...

### 45. `approach-transfer-vs-findings-transfer`
- confidence: `0.98` | date: `2026-06-01` | file: `2026-06-01-instinct-management-insights.yaml`
- domain/source: `domain-strategy` / `user-instruction`
- trigger: 別ホールで分析を始めるとき、または蒲田7の知見を他に適用しようとするとき
- summary: ユーザー指摘（2026-06-01）： 「同じアプローチで分かることもある。 データ探索やホールではなく機種固有のクセなどは共通している可能性がある。」 OK（アプローチ・ツール）： signal_existence_plan.py などの分析スクリプト walk-forward の枠組み・統計検定手順 upli...

### 46. `hit-at-2-binary-vs-precision-confusion`
- confidence: `0.98` | date: `2026-05-30` | file: `2026-05-30-backtest-evaluation-insights.yaml`
- domain/source: `prediction-evaluation` / `backtest-analysis`
- trigger: hit@2の数値を比較・解釈するとき、または評価指標を設計するとき
- summary: コードの `hit_at_2` はバイナリ（1件でも一致したら1.0）だが、 ユーザーの手動評価は precision（一致数/2）。この違いで 「コード89%」vs「手動50%」という見かけ矛盾が生じた。 ランダム基準値： バイナリhit@2：37.8% （= 1 - C(8,2)/C(10,2)） preci...

### 47. `hard-miss-vs-exact-miss-definition`
- confidence: `0.98` | date: `2026-05-28` | file: `2026-05-28-signal-quantile-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: testperiod_topk.csv で「予測外れ日」を定義するとき
- summary: `nextday_kamata7_20260527_tasks123_verify_...topk.csv` の2F_N（146日）: hard_miss（hit_at_2 == 0）: **1日のみ**（99.3%がhit@2） exact_miss（予測top1 ≠ 実際rank1）: **44日**（69....

### 48. `top3-output-already-implemented-per-expert`
- confidence: `0.98` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-pipeline` / `session-observation`
- trigger: TOP3末尾の出力を実装しようとするとき / latest_test_top3を参照するとき
- summary: `tail_ltr_split_rule_nextday_gpu.py` が出力する `*_latest_test_top3.csv` は、 各エキスパート（2F_N, 3F_N, 3F_A, 2F_A）のrank1・rank2・rank3を含む。 2F_Aも2026-05-26時点ではTOP3に含まれている（除...

### 49. `anomaly-db-scope-must-be-single-hall`
- confidence: `0.98` | date: `2026-05-25` | file: `2026-05-25-anomaly-analysis-insights.yaml`
- domain/source: `ml-data-validation` / `session-observation`
- trigger: when running exploratory anomaly detection on pachinko data
- summary: run_exploratory_analysis.py のデフォルト --db-glob は "db/*.db" であり、 db/ 直下の全ホール（9ホール）を統合して分析する。 蒲田七は2025-07-07開業のため、他ホールのデータが混入すると 開業前データやzscoreが-22を超える極端な外れ値が混入し、...

### 50. `outcome-leakage-vs-target-leakage-are-different`
- confidence: `0.98` | date: `2026-05-31` | file: `2026-05-31-leakage-protocol-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: MLモデルの特徴量リークを確認するとき
- summary: 古典的なリーク確認はターゲットリーク（is_top_2 を特徴量に使う）を防ぐもの。 今回のリークは「ターゲットそのものではないが、同日実績由来でターゲットと高相関な列」。 ターゲットリーク：is_top_2, is_rank_1 など → 除外リストで対処済み アウトカムリーク：total_diff_coins...

### 51. `always-2fn-beats-all-calendar-rules`
- confidence: `0.98` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `domain-strategy` / `data-analysis`
- trigger: セグメント選択戦略を設計するとき、またはカレンダールールを逸脱判断に使おうとするとき
- summary: deviation_rule_eval.csv（holdout 150日）の uplift 評価結果： always_no（常に2F_N）: 0/日（基準） dd_topk: -2,032/日 weekday_high: -5,975/日 calendar_union: -7,047/日 always_yes（常...

### 52. `live-vs-backtest-gap-explained-by-leakage`
- confidence: `0.98` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテスト精度と実践精度に大きな乖離があるとき
- summary: 本プロジェクトの実測値： backtest (clean holdout) precision@2: 83-87% live評価 (9日間) precision@2: 25-50% この乖離を「small sample effect」「seasonal shift」で説明しようとしていたが、 実際は total_...

### 53. `pred-span-vs-pred-span-top12-are-different`
- confidence: `0.98` | date: `2026-05-31` | file: `2026-05-31-evaluation-feature-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: pred_spanとpred_span_top12を評価・比較するとき、または「低Span日」を分析するとき
- summary: バックテストCSVには2種類のspan指標が存在する。 `pred_span`（reliability_daily）: max(pred) - min(pred) → 全10末尾の範囲 `pred_span_top12`（testperiod_topk）: top1_pred - top2_pred → 1位と2...

### 54. `segment-specific-top3-comparison`
- confidence: `0.98` | date: `2026-05-28` | file: `2026-05-28-prediction-evaluation-methodology.yaml`
- domain/source: `prediction-evaluation` / `user-correction`
- trigger: 末尾予測の精度評価を行うとき
- summary: 予測精度を評価する際、2F_N/3F_N/3F_A/2F_Aの各セグメント予測を全体の実績と比較していたが誤り。 セグメント別予測はそれぞれのセグメント実績のみと比較すべき。 ゾロ目狙い目意見もゾロ目台限定の実績（is_zorome=1）のみと比較する。 2F_N予測Top3 → 2F実績Top3（machine...

### 55. `progress-reporting-required-in-all-loops`
- confidence: `0.98` | date: `2026-05-27` | file: `2026-05-27-machine-type-v2-active-filter-insights.yaml`
- domain/source: `ml-implementation-standards` / `session-requirement`
- trigger: when implementing walk-forward or any time-consuming loop in ML pipeline
- summary: 機種別予測（run_machine_type_v2.py）に進捗表示が実装されておらず、 処理時間の予測ができない問題があった。 末尾予測パイプラインには実装済みのため、全パイプラインで統一する。 時間のかかるループには必ず以下のパターンを使用する： import time start_time = time.t...

### 56. `hall-firstday-kaiwari-ranking-arrow-mitoya-top`
- confidence: `0.97` | date: `2026-06-10` | file: `2026-06-10-new-machine-firstday-hall-insights.yaml`
- domain/source: `hall-strategy` / `empirical-analysis`
- trigger: 新台初日にどのホールを狙うべきか判断するとき / ホール別の新台設定投入傾向を調べるとき
- summary: 全9ホール × DBスタート以降の新台 × 初日データ（games_normalized >= 200 フィルタ） を集計した結果（n=401〜558台×日）。 生平均機械割ランキング: 1. みとや 103.9%（avg差枚+243, plus率43.9%） 2. ARROW 102.9%（avg差枚+499,...

### 57. `hall-firstday-104pct-threshold-ranking`
- confidence: `0.97` | date: `2026-06-10` | file: `2026-06-10-new-machine-firstday-hall-insights.yaml`
- domain/source: `hall-strategy` / `empirical-analysis`
- trigger: 新台初日に高設定（機械割104%以上）に当たる確率をホール別に比較するとき
- summary: 各台×初日データで「機械割 >= 104%」を判定した出現率: | ホール | 104%+ 出現率 | ヒット時avg機械割 | |--------------|------------|--------------| | ARROW | 38.5% | 123.6% | | みとや | 36.7% | 130....

### 58. `new-machine-low-setting-start-confirmed`
- confidence: `0.97` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `hall-behavior` / `empirical-analysis`
- trigger: 新台導入後の設定投入パターンを分析するとき / days_since_debutを使うとき
- summary: 全ホール合算 days_since_debut 別 avg_diff: 0-7日: avg=-152 (n=31,579) 8-14日: avg=-190 (n=31,087) ← 最低 15-30日: avg=-116 31-60日: avg=-23 61-90日: avg=+4 91-180日: avg=+3...

### 59. `kamata7-7kei-monday-strongest-signal`
- confidence: `0.97` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: 蒲田7の台選択・イベント日分析をするとき
- summary: DBバグ修正後の全ホール横断スキャン（21次元 × 9ホール）で、 蒲田7の「7系/月」が avg=+807 n=2850 CI=[692,930] を記録。 CI下限+692と余裕があり、n=2850と十分なサンプル。 全スキャン中で最も強力な集計レベルシグナル。 7系 = DD=7,17,27（蒲田7のx_d...

### 60. `anomaly-early-debut-unreliable`
- confidence: `0.97` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: 導入後30日以内の機種のANOMALYを解釈するとき
- summary: pre_existing=False の新規機種に限定した、導入後日数帯別ANOMALY翌日検証: | 日数帯 | 翌日avg | plus率 | n | |--------|---------|--------|---| | 0-7日 | -291 | 37.5% | 2017 | | 8-14日 | -396...

### 61. `hall-specific-vs-universal-patterns-equal-value`
- confidence: `0.97` | date: `2026-06-09` | file: `2026-06-09-eda-framework-design-and-discovery-insights.yaml`
- domain/source: `methodology` / `design-decision`
- trigger: クロスホール比較でパターンが一致しない（矛盾に見える）とき
- summary: みとや固有のパターン（x_day末尾4が強い）と他ホールで確認できないパターンを 「矛盾」として扱うのは誤り。 各ホールは独自の設定投入戦略を持つ（CLAUDE.mdの実証済み事実）。 ホール固有パターンはそのホールを攻略するための固有知識として価値がある。 cross_hall_scan()の出力で unive...

### 62. `catboost-windows-py314-bad-allocation-warmup`
- confidence: `0.97` | date: `2026-06-09` | file: `2026-06-09-mitoya-lag-feature-island-section-insights.yaml`
- domain/source: `ml-engineering` / `session-experiment`
- trigger: CatBoostRegressor.fit() が Windows + Python 3.14 環境で初回呼び出し時に bad allocation で落ちるとき
- summary: Windows + Python 3.14 環境において、CatBoostRegressor の最初の `.fit()` 呼び出しが `_catboost.CatBoostError: bad allocation` で必ず失敗する現象が発生した。 メモリ（9GB空き）・ディスク（177GB空き）・GPU使用率に...

### 63. `is-far-corner-reversed-section-bug`
- confidence: `0.97` | date: `2026-06-07` | file: `2026-06-07-mitoya-ml-prediction-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `user-ground-truth`
- trigger: is_far_corner（壁側角番フラグ）をmachine_layoutから計算するとき
- summary: みとや大森町店の台723-733島は `is_reversed_section=1`（台番号の昇順と通路側の向きが逆）。 この島では台723が壁側角番、台733が通路側角番（rank_from_aisle=1）。 `rank_from_max == 1` で is_far_corner を定義すると、 rever...

### 64. `anaslo-l-prefix-first-day-behavior`
- confidence: `0.97` | date: `2026-06-07` | file: `2026-06-07-island-digit-stability-insights.yaml`
- domain/source: `data-pipeline` / `empirical-validation`
- trigger: ana-slo.comスクレイピングで機種名が『L〇〇〇』という形式で出現したとき、またはjson_processor.pyで機種名正規化を実装するとき
- summary: 機種入れ替えがあった日のみ、ana-slo.comのサイトが機種名の先頭に「L」を付けて掲載する。 翌日からは正式名称に戻る。これはスクレイピングエラーではなくサイト側の仕様。 確認例（JSON原本で検証済み）： 台509-512: 2025-03-03のみ「Lバイオハザード5」→翌日「バイオハザード5」 台55...

### 65. `reversed-sections-in-hall-config-not-code`
- confidence: `0.97` | date: `2026-06-07` | file: `2026-06-07-mitoya-corner-aisle-eda-insights.yaml`
- domain/source: `architecture` / `design-decision`
- trigger: 逆順セクション定義をコードに書こうとしたとき、またはホールレイアウト情報を管理するとき
- summary: title: 逆順セクション定義は hall_config.json に書く — コードにハードコードしない 当初 Python の frozenset としてスクリプト内にハードコードされていた逆順セクション定義を、 `config/hall_config.json` の `layout_settings.re...

### 66. `xday-weekday-confounding-ruled-out`
- confidence: `0.97` | date: `2026-06-07` | file: `2026-06-07-xday-weekday-confounding-insights.yaml`
- domain/source: `methodology` / `empirical-validation`
- trigger: x_day の末尾シグナルが曜日効果によるものではないかと疑うとき、またはDD×曜日の交絡を検証するとき
- summary: x_day（day%10 in {4,7}）の末尾選択シグナルが「たまたま特定曜日に偏って当たっていた」という 曜日交絡の可能性を検証した。 x_day DD（4/7/14/17/24/27）はそれぞれ 17 回出現し、7 曜日に std=0.53（min=2, max=3）で均等分散。 さらに土曜という同一曜日...

### 67. `verify-current-placement-before-dd-eda`
- confidence: `0.97` | date: `2026-06-07` | file: `2026-06-07-mitoya-dd7-current-placement-insights.yaml`
- domain/source: `methodology` / `empirical-validation`
- trigger: 特定DDのEDA・運用ルール作成をするとき
- summary: title: EDA前に現在の機種配置を必ず確認する — 撤去済み機種の成績は運用に使えない DD=7 EDA を実施したところ「スマスロ北斗の拳 (540-556/557-573)」が最優先Aと判定されたが、 実際には 2026/05/10 以前に全て撤去済みで現在は存在しない機種だった。 歴史データ全期間を使...

### 68. `month-dd-seasonality-requires-3plus-years`
- confidence: `0.97` | date: `2026-06-06` | file: `2026-06-06-dd-digit-cross-analysis-insights.yaml`
- domain/source: `methodology` / `empirical-validation`
- trigger: 月×DD の組み合わせで季節性パターン（特定の月の特定 DD が強いなど）を分析しようとするとき
- summary: みとや大森町 1.5 年データで (月, DD, 末尾) セルの n_dates を確認したところ、 月×DD の各セルは n=1〜2 しかなかった。 月1〜5（2年分）：n=2 月6〜12（1年分）：n=1 n=1 のセルは mean = その1日の値そのもので、平均の意味をなさない。 DD=19 の9月に d...

### 69. `mitoya-group-level-position-aggregation`
- confidence: `0.97` | date: `2026-06-06` | file: `2026-06-06-mitoya-corner-section-position-insights.yaml`
- domain/source: `ml-pipeline` / `session-observation`
- trigger: walk-forward パイプラインにマシンレベルの位置特徴量を追加しようとしたとき
- summary: title: 位置特徴量はグループ集計後のパイプラインでは aggregation 経由で追加する tail_ltr_mitoya_wf.py は aggregate_mode_mitoya でマシン行を (last_digit × date) グループに集計してから walk-forward を走らせる。Fea...

### 70. `margin-threshold-is-primary-adoption-filter`
- confidence: `0.97` | date: `2026-06-06` | file: `2026-06-06-seed-consensus-insights.yaml`
- domain/source: `hall-specific` / `empirical-validation`
- trigger: みとや x_day の翌日予測で採用条件を設計・変更しようとするとき
- summary: walk-forward の calibration 段階で margin（1位と2位のスコア差）の分位点閾値が最適化されている。 複数 seed の合意度は追加の弁別力を持たなかった（1/19 日しか発火しない上に外れた）。 margin フィルタが played_rate=0.77 を実現している既存設計が正...

### 71. `strong-zorome-date-computation`
- confidence: `0.97` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `methodology` / `bug-fix`
- trigger: strong_zorome bucket の判定を実装するとき
- summary: `is_strong_zorome` カラムは `daily_hall_summary` に存在するが、 `aggregate_mode_mitoya()` の後段でカラムが消えるため、 bucket 分類が `is_strong_zorome` を参照すると n_days=0 になるバグが発生した。 stron...

### 72. `model-excess-vs-absolute-return`
- confidence: `0.97` | date: `2026-06-05` | file: `2026-06-05-mitoya-bucket-design-insights.yaml`
- domain/source: `methodology` / `session-observation`
- trigger: walk-forward の mean_diff で bucket 間の優先順位を決めようとするとき
- summary: dd4 の model excess = -2.31、dd7 = +36.59 から「dd7 の方が強い」と解釈しがちだが誤り。 model excess はその日のホール平均を引いた相対値。 ホール台平均を加算すると dd4（+239）> dd7（+217）となる。 実戦上の優先順位（どの日に行くか）は絶対値...

### 73. `narabi-jug-other-split-anchor`
- confidence: `0.97` | date: `2026-06-05` | file: `2026-06-05-poco-analysis-db-insights.yaml`
- domain/source: `poco-strategy-parsing` / `user-instruction`
- trigger: ジャグN、他M絡みのような並び策略をパースするとき
- summary: K1の「並び（ジャグ1、他5絡み）」はジャグラー系（N機）が末尾1起点、 それ以外（A機）が末尾5起点の並びを意味する。 パーサーが `末尾` プレフィックスを探すと取れないため専用パターンが必要。 for m in re.finditer(r'(?:ジャグ|他)(\d)', s): digits.append(...

### 74. `hall-selection-vs-tail-ranking-model-separation`
- confidence: `0.97` | date: `2026-06-05` | file: `2026-06-05-allhall-model-architecture-insights.yaml`
- domain/source: `ml-architecture` / `session-observation-20260605`
- trigger: ホール選択モデルのパラメータ（C, logreg_c等）を末尾ランク予測モデルに適用しようとするとき
- summary: C=0.1（hybrid LogReg最適値）はホール選択モデル専用のパラメータ。 末尾ランク予測（tail_ltr_*）はLTR + XGBoost LambdaMARTを使っており、 LogisticRegression の C パラメータとは無関係。 | モデル | ファイル | 問題設定 | アルゴリズム...

### 75. `ml-rolling-stats-shift1-leakage`
- confidence: `0.97` | date: `2026-06-05` | file: `2026-06-05-code-review-security-ml-insights.yaml`
- domain/source: `ml-feature-engineering` / `session-observation`
- trigger: 機械別のローリング統計（移動平均・標準偏差）を特徴量として計算するとき
- summary: `feature_engineering.py` の `_build_machine_history_features` と `_compute_machine_rolling_stats` で `.rolling(14).mean().values` のように shift なしで計算していた。`rolling(...

### 76. `poco-signal-strength-quantified`
- confidence: `0.97` | date: `2026-06-05` | file: `2026-06-05-poco-hall-analysis-insights.yaml`
- domain/source: `poco-analysis` / `empirical-measurement`
- trigger: ぽこ発表シグナルの信頼性を評価・使用するとき
- summary: 2025/7/12〜2026/5/31 K7全期間における発表日 vs 非発表日の実測値。 「発表日」= その日の poco full_half_normalized に機種名が記載されている台日。 | 区分 | 台日数 | avg差枚 | 勝率 | |------|--------|--------|-----...

### 77. `poco-format-three-variants`
- confidence: `0.97` | date: `2026-06-03` | file: `2026-06-03-poco-normalization-pipeline-insights.yaml`
- domain/source: `data-pipeline` / `session-observation`
- trigger: ぽこデータを新たに抽出・処理するとき、または月次更新でMDファイルを追加するとき
- summary: docs/ぽこデータ抽出/ 配下のMDファイルは月によってフォーマットが異なる： **Format A（7〜1月）**: CSV形式（カンマ区切り、diff/contentが別カラム） **Format B（2〜4月）**: Markdownテーブル（`|`区切り、`**bold**`、diff/contentが...

### 78. `random-baseline-negative-hall-selection-critical`
- confidence: `0.97` | date: `2026-06-02` | file: `2026-06-02-allhall-optimization-insights.yaml`
- domain/source: `ml-evaluation` / `empirical-20260602`
- trigger: when evaluating whether hall selection strategy matters or setting performance expectations
- summary: holdout 150日でベースライン比較を実施した結果（2026-06-02）： ランダム選択: chosen_avg_diff = -7.15（赤字） historical_best_fixed: 111.8 現在モデル: 123.2 oracle: 264.7 ランダムが赤字の理由：9ホール中の多くが平均的...

### 79. `data-observation-is-leakage-immune`
- confidence: `0.97` | date: `2026-06-01` | file: `2026-06-01-instinct-management-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: 過去のデータ分析結果がリークによって無効化されているか判断するとき
- summary: リーク（total_diff_coins_focus が特徴量に混入）はMLモデルの学習過程の問題。 生データの集計・観察には影響しない。 影響を受けない（有効）： 曜日別の平均 diff_coins（DBの生データから集計） 特定末尾の出現頻度・配置パターン ゾロ目日のホール全体差枚統計 機種別の稼働日数・平均...

### 80. `group-total-diff-is-not-per-machine`
- confidence: `0.97` | date: `2026-05-27` | file: `2026-05-27-ltr-operational-kpi-insights.yaml`
- domain/source: `ltr-evaluation` / `session-observation`
- trigger: LTR予測の差枚KPIを報告・解釈するとき
- summary: `loss_scenarios.csv` および `testperiod_topk.csv` の `top1_actual_raw_diff` は、 予測rank1末尾に属する**全台の差枚合計**（`total_diff_coins`）である。 kamata7の場合、2F_Nは末尾あたり約32台、3F_Nは15...

### 81. `weak-p-value-with-multiple-segments-is-artifact`
- confidence: `0.97` | date: `2026-06-01` | file: `2026-06-01-signal-existence-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: 複数セグメントで検定して1つだけp≈0.05が出たとき
- summary: signal_existence_plan で 3F_N のみ反復回避 p≈0.05 が出た。 しかし 4セグメント（2F_A, 2F_N, 3F_A, 3F_N）を同時検定した場合、 Bonferroni補正の閾値は p=0.05/4=0.0125。 p≈0.05 は補正後に消える → 「4回試してたまたま1回...

### 82. `calendar-features-hurt-means-non-stationary`
- confidence: `0.97` | date: `2026-06-01` | file: `2026-06-01-signal-existence-insights.yaml`
- domain/source: `ml-architecture` / `data-analysis`
- trigger: カレンダー特徴量（DD/曜日）を追加して性能が悪化するとき
- summary: カレンダールール holdout 比較結果（蒲田7）： global（カレンダーなし）：precision@2 = 0.2025（最良） dd_value追加：0.1800（悪化 -2.25pp） weekday追加：0.1900（悪化 -1.25pp） dd+weekday：0.1942（悪化 -0.83pp）...

### 83. `empirical-leakage-detection-over-code-review`
- confidence: `0.97` | date: `2026-05-31` | file: `2026-05-31-leakage-protocol-insights.yaml`
- domain/source: `prediction-evaluation` / `session-observation`
- trigger: リーク確認をコードレビューのみで完結させようとするとき
- summary: total_diff_coins_focus のリークはコードレビューで複数回見逃された。 発見のきっかけは「単独特徴量で hit@2 を計算する」という経験的テストだった。 コードレビューが失敗する理由： 列名が lag 特徴量と区別しにくい generate 元のコードを全追跡するには認知負荷が高い 複数ファ...

### 84. `deviation-rule-uplift-cost-is-large`
- confidence: `0.97` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `domain-strategy` / `data-analysis`
- trigger: 逸脱ルールのコストを評価するとき
- summary: always_yes（常に3F_N）= -9,731/日は： 2F_Nを完全に外した場合の1日あたりの期待損失 150日合計では約-146万差枚 各ルールのコスト比率： dd_topk: -2,032/日 → always_yes の 21% weekday_high: -5,975/日 → 61% calend...

### 85. `classification-metrics-mislead-for-uplift-problems`
- confidence: `0.97` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: セグメント逸脱予測や二値分類の精度をrecall/precisionで評価しようとするとき
- summary: calendar_union ルールの評価： recall=0.87, precision=0.34, accuracy=44-47% mean_uplift_vs_2fn = -7,047/日 recall=0.87 は「良い」に見えるが、全日の78%にフラグを立てており 2F_Nを頻繁に離れるコストが蓄積して...

### 86. `leakage-diagnosis-three-step-procedure`
- confidence: `0.97` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテスト精度が異常に高いとき、またはモデルの評価妥当性を疑うとき
- summary: 今回のリーク発見は3ステップで確定した。 ステップ1・2だけでは「非線形相互作用」と誤判断するリスクがある。 ステップ1: ナイーブ基準との比較 「過去の頻度Top2を固定して毎日予測」→ hit@2がランダム基準と同等か確認 同等なら「Top2は日次変動あり、単純暗記ではない」が確認できる ステップ2: 個別特...

### 87. `backtest-saturation-is-reliability-alarm`
- confidence: `0.97` | date: `2026-05-31` | file: `2026-05-31-evaluation-feature-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: バックテストのhit@2が95%以上のとき、または低Span日のhit@2が高いとき
- summary: 蒲田7バックテスト（2026-01〜05）のspan band別hit@2： span < 0.01（121件）: hit@2 = 94.2% ← 異常（ランダム基準37.8%） span 0.01-0.1（157件）: hit@2 = 100% span >= 0.3（200件）: hit@2 = 100% セ...

### 88. `hokuto-machine-name-disambiguation`
- confidence: `0.97` | date: `2026-05-28` | file: `2026-05-28-signal-machine-analysis-insights.yaml`
- domain/source: `operational-strategy` / `session-observation`
- trigger: スマスロ北斗の拳を信号機種として使う際に機種名を検索するとき
- summary: 蒲田七DBには「北斗」を含む機種が2つ存在する： `スマスロ北斗の拳`（信号機種として有効） `北斗の拳 転生の章2`（別機種・除外対象） `LIKE '%北斗%'` で検索すると両方が引っかかる。 「スマスロ北斗の拳」のみを対象にするために前方一致を使用する。 cursor.execute( "SELECT D...

### 89. `tail-vs-zorome-machine-separate-evaluation`
- confidence: `0.97` | date: `2026-05-28` | file: `2026-05-28-codex-analysis-improvements.yaml`
- domain/source: `prediction-evaluation` / `codex-correction`
- trigger: 末尾予測精度とゾロ目台推奨精度を評価・報告するとき
- summary: CODEXの指摘：3F_Nの末尾7はセグメント1位（+13,300円）だったが、 台3077自体は-2,900円（外れ）。強さは非ゾロ目側（+16,200円）に寄っていた。 末尾精度とゾロ目台精度を混在させると「末尾は当たり、XX台は外れ」が見えない。 分析レポートで以下を常に分離して報告する： 1. tail...

### 90. `train-eval-alignment-check-mandatory`
- confidence: `0.97` | date: `2026-05-25` | file: `2026-05-25-within-expert-target-fix.yaml`
- domain/source: `ml-eval-discipline` / `session-retrospective`
- trigger: when designing LTR training targets for any multi-group ranking task
- summary: hit@2 が 71% に留まっていた原因が「学習スコープ（グローバル）と 評価スコープ（エキスパート内）の不一致」だったことが今回判明した。 LTRの学習ターゲットを設計するとき、以下を必ず確認する： 1. 評価指標の group_ids に何を使っているか（date のみ？ date x group_key？...

### 91. `python-module-vs-script-execution`
- confidence: `0.97` | date: `2026-05-25` | file: `2026-05-25-ltr-feature-engineering-insights.yaml`
- domain/source: `ml-pipeline-configuration` / `session-observation`
- trigger: when running ml/ 配下のPythonスクリプトをコマンドラインから実行するとき
- summary: `python ml/last_digit/tail_ltr_split_rule_nextday_gpu.py` で実行すると `ModuleNotFoundError: No module named 'ml'` が発生する。 `ml/` はパッケージ（`__init__.py` あり）として設計されており、...

### 92. `machine-master-flag-keyword-based`
- confidence: `0.97` | date: `2026-05-21` | file: `2026-05-21-machine-master-flag-system.yaml`
- domain/source: `database-maintenance` / `session-observation`
- trigger: machine_masterのbt_flagやhana_flagを追加・修正するとき
- summary: bt_flag / hana_flag / jug_flag / oki_flag はすべて機種名の部分一致で判定される。 フラグ判定ロジックは `database/data_inserter.py` の冒頭にある `_BT_KEYWORDS` リストで一元管理されている。 `get_or_create_mach...

### 93. `technical-machine-saturday-bias-not-significant`
- confidence: `0.96` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `technical-machine-bias` / `empirical-analysis`
- trigger: 新ハナビ・ディスクアップ・うみねこ等の技術介入機の曜日分析をするとき
- summary: 新ハナビ・ディスクアップULTRAREMIX・うみねこ・ディスクアップ2の 土曜 vs 平日 avg_diff を Mann-Whitney U検定で検証: | 機種 | 土曜avg | 平日avg | プレミアム | p値 | |------|---------|---------|-----------|--...

### 94. `xday-auto-discovery-validates-eda-framework`
- confidence: `0.96` | date: `2026-06-09` | file: `2026-06-09-eda-framework-design-and-discovery-insights.yaml`
- domain/source: `methodology` / `empirical-validation`
- trigger: EDA自動スキャナーの信頼性を評価するとき、または新しいパターンが本物かを検証するとき
- summary: full_scan()をみとやに適用した結果、事前知識ゼロでDD=4,14,24がTier B、 DD=7,17,27がTier Cとして自動検出された。 これはinstinct記録済みの「x_day={4,7,14,17,24,27}」と完全一致。 DD別 avg_diff（みとや全機種、n>=10）: DD=...

### 95. `machine-name-walkforward-agg-features-b-plan`
- confidence: `0.96` | date: `2026-06-07` | file: `2026-06-07-mitoya-ml-prediction-engineering-insights.yaml`
- domain/source: `ml-feature-engineering` / `empirical-validation`
- trigger: CatBoostでmachine_nameをCAT_FEATUREとして使うとき、新機種（データが少ない）の埋め込みが薄い問題を解決したいとき
- summary: 機種が変わった台は旧機種名の学習データが多く、新機種名の学習データが少ない 機種名正規化（全履歴書き換え）は逆効果（別機種のデータが混入） 解決策: 各機種名が **実際に稼働していた期間のデータのみ** を使って集約統計を計算し、数値特徴量として追加 追加した特徴量（shift(1)でデータリーク回避）: `m...

### 96. `epsilon-squared-interpretation-for-pachinko`
- confidence: `0.96` | date: `2026-06-07` | file: `2026-06-07-mitoya-island-corner-analysis-insights.yaml`
- domain/source: `methodology` / `explanation`
- trigger: 角番などの位置効果を評価するとき、ε² が小さい値に見えて不安になるとき
- summary: title: パチスロ成績分析では ε²0.006 で「十分な説明力」 — 差枚は多因子現象 Kruskal-Wallis ε² は 0〜1 で「角番という要因が成績のばらつきをどれだけ説明できるか」を示す。 みとやでは: main_jug ε² = 0.006653（0.67%） 一見小さく見える しかし差枚（...

### 97. `aisle-corrected-rank-5x-epsilon-improvement`
- confidence: `0.96` | date: `2026-06-07` | file: `2026-06-07-mitoya-corner-aisle-eda-insights.yaml`
- domain/source: `feature-engineering` / `empirical-validation`
- trigger: 通路距離ベースの角番指標と通常の角番指標を比較するとき、またはみとやのlayoutデータを使うとき
- summary: title: 通路距離補正した角番（rank_from_aisle）はノーマル角番の5倍の説明力（ε²）を持つ みとや大森町店の台番号は交互逆順配置（メイン通路側が高番号のセクションと低番号のセクションが交互）。 逆順補正なしの rank_from_min はメイン通路からの距離を正しく表せない。 Kruskal...

### 98. `mitoya-section-dd-effect-is-machine-dd-effect`
- confidence: `0.96` | date: `2026-06-06` | file: `2026-06-06-mitoya-machine-dd-eda-insights.yaml`
- domain/source: `domain-analysis` / `empirical-validation`
- trigger: みとやでセクション×DDのパターンを分析したとき、または「なぜこのセクションがこのDDに強いのか」を調べるとき
- summary: title: みとやの「セクション×DD効果」は「機種×DD効果」の代理変数にすぎない section_by_dd.csv で 574-590 が DD=4 に平均 +1200 超と突出して強かったが、 同じセクション内の機種別DD分析を実施したところ以下の事実が判明した。 強い機種（モンキーターン）: DD=4...

### 99. `hall-digit-mean-diff-merge-exclusion`
- confidence: `0.96` | date: `2026-06-05` | file: `2026-06-05-leakage-audit-insights.yaml`
- domain/source: `methodology` / `code-audit`
- trigger: aggregate_mode 系の関数で hall レベルのラグ特徴量を merge するとき
- summary: `aggregate_mode_mitoya()` では `hall_digit_mean_diff`（同日の末尾別ホール平均差枚）を 中間変数として計算し、そのラグ版（lag1〜lag15）のみを `agg` に merge する。 非シフトの `hall_digit_mean_diff` は `is_top_...

### 100. `narabi-strategy-window-calculation`
- confidence: `0.96` | date: `2026-06-05` | file: `2026-06-05-poco-analysis-db-insights.yaml`
- domain/source: `poco-strategy-calculation` / `user-instruction`
- trigger: 並び仕掛けの差枚・勝率を計算するとき
- summary: 「並び」とは連番台に高設定を入れる戦略。末尾Nの3台並びは、 末尾Nの台番号Mを起点として[M-1,M,M+1]が範囲。 すなわち |machine_number - M| <= 2 がターゲット台集合になる。 3台並び → window = 2 4台並び → window = 3 5台並び → window =...

### 101. `poco-patch-delete-structural-misclassification`
- confidence: `0.96` | date: `2026-06-03` | file: `2026-06-03-poco-data-integrity-comprehensive.yaml`
- domain/source: `data-quality` / `session-investigation`
- trigger: PATCH_DELETE に機種名が登録されている場合、削除対象ノイズと判断する前に内容を検証するとき
- summary: ぽこデータの PATCH_DELETE リストに登録された項目のうち、複数の項目が実は有効な機種情報（複合戦略）を含んでいたことが判明。 例： `ハナハナ天膳` → 当日稼働しているハナハナ機種全 + 天膳全 `ゾンサガ` → ゾンビランドサガ（機種名） `カイジ` → 回胴黙示録カイジ 狂宴（機種名） `ハッピ...

### 102. `effect-size-gap-makes-live-collection-impractical`
- confidence: `0.96` | date: `2026-06-01` | file: `2026-06-01-signal-existence-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: ライブデータ収集で統計的検出力を稼ごうとするとき
- summary: 蒲田7の結果： 観測された最良改善量：drought_relative で 1.25pp（21.25% - 20%） 80%検出力に必要な改善量：6.68pp（26.68% - 20%） 必要サンプル数：約2,000日/セグメント ≈ 約13年分 効果量が検出力閾値の1/5しかない場合、ライブデータ収集で確認する...

### 103. `cross-hall-strategy-comparison-is-domain-invalid`
- confidence: `0.96` | date: `2026-06-01` | file: `2026-06-01-segment-strategy-insights.yaml`
- domain/source: `domain-strategy` / `session-observation`
- trigger: 複数ホールを横断してパターンを検証しようとするとき
- summary: 「他ホールでもlag=14パターンが再現するか」という検証提案に対して 「系列店でない限り経営戦略を共有する理由がない」という指摘。 同一チェーン/系列店：設定方針が共有される可能性あり（検証価値あり） 異なる経営主体のホール：設定方針の共有を前提にしてはいけない 複数ホール横断分析を提案するとき、まず確認する：...

### 104. `clean-holdout-does-not-fix-feature-leakage`
- confidence: `0.96` | date: `2026-05-31` | file: `2026-05-31-leakage-diagnosis-insights.yaml`
- domain/source: `prediction-evaluation` / `data-analysis`
- trigger: パラメータ選定のclean holdoutを実施してもhit@2が高止まりするとき
- summary: clean holdout監査（2025年内で候補選定→2026年holdout評価）を実施： 2025年選定期間（n=109日）の hit@2: 3F_N=1.000, 2F_A=1.000, 2F_N=0.991 2026年holdout（n=150日）の hit@2: 全セグメント98-99% 元の99%と...

### 105. `rb-threshold-258-not-300`
- confidence: `0.96` | date: `2026-05-28` | file: `2026-05-28-signal-correlation-result-insights.yaml`
- domain/source: `ml-strategy` / `session-observation`
- trigger: signal_machine_correlation_analysis.py や signal_multi_tail_2fn.py でRB閾値を設定するとき
- summary: 旧来の `rb_threshold = 1/300 = 0.003333` はモンキーターンVの設定1（1/299）を捕捉してしまう。 北斗の設定3（1/297）も捕捉する。いずれも低設定であり、シグナルとして使いたい設定ではない。 両機種ともに「設定4以上」が意味のある設定で、その閾値が 1/258 = 0.0...

### 106. `floor-coordinate-generation-workflow`
- confidence: `0.95` | date: `2026-06-11` | file: `2026-06-11-rakuen-kamata-floor-coordinates-insights.yaml`
- domain/source: `heatmap-coordinate-generation` / `session-observation`
- trigger: 新しいホールのフロア座標CSV(Heatmap/*_floor_coordinates_*.csv)を画像から作成・拡張するとき
- summary: 楽園蒲田店の本館3F/2F/1F・新館1F/2F、計569台のフロア座標CSVを `Heatmap/generate_rakuen_kamata_coordinates.py` に実装した。 画像から手動で座標を起こす作業は、関数化された build パターンと ASCIIプレビュー検証を組み合わせることで、ミス...

### 107. `monkeyturn-v-rb-data-incompatibility`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-rb-probability-analysis-insights.yaml`
- domain/source: `data-quality` / `empirical-analysis`
- trigger: モンキーターンVのRB確率(rb_probability_decimal)でホール間比較をしようとするとき / bb_count・bb_probability_decimalがNoneや0になっている機種を扱うとき
- summary: モンキーターンVのRB確率(1/X)をホール別に集計したところ、 蒲田7(1/308.7, 台2026除外後)・みとや(1/314.7)・蒲田1(1/310.8)・ ザシティ(1/317.5)・金時(1/320.9)はAT初当りスペック設定1(1/299.8) 付近に集まる一方、楽園(1/494.7)・ARROW...

### 108. `heatmap-db-path-resolution-bug-fix`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-rakuen-kamata-heatmap-and-pathfix-insights.yaml`
- domain/source: `heatmap-implementation` / `session-bugfix`
- trigger: page_17_heatmap.py / heatmap_common.py で 'DB file not found: .../Heatmap/db/...' エラーが出たとき
- summary: render_heatmap_page / render_last_digit_highlight 内の _resolve_path() が coords_file と db_path を両方 script_dir（Heatmap/フォルダ）基準で解決していた。 しかし db_path は main_app.py...

### 109. `machine-hall-fixed-effect-implementation`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-machine-hall-fixedeffect-and-banchou4-insights.yaml`
- domain/source: `eda-implementation` / `implementation`
- trigger: 全期間データで機種×ホール固定効果やhit104トップ組み合わせを集計するスクリプトを書くとき
- summary: 新台初日限定ではなく全期間データで、3ホール以上に導入されている機種について ホール間の機械割差（固定効果）とhit104率トップ組み合わせを抽出する実装。 実装済みファイル: `eda/machine_hall_fixed_effect.py` MIN_GAMES=1000, MIN_N_PER_HALL=30...

### 110. `hit104-scan-implementation`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-hit104-rate-allday-scan-insights.yaml`
- domain/source: `eda-implementation` / `implementation`
- trigger: 機械割104%以上の出現率で差枚スキャンと同じ次元を再探索するスクリプトを書くとき
- summary: 差枚ベースの21次元スキャン（2026-06-09実施）と同じ軸を、 「機械割>=104%」の二値フラグの出現率で再走査するための実装。 実装済みファイル: `eda/hit104_scan.py` PASS1: min_games=1000で全次元スキャン PASS2: min_games=3000で再検証（P...

### 111. `hit104-hall-ranking-reverses-vs-firstday`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-hit104-rate-allday-scan-insights.yaml`
- domain/source: `hall-strategy` / `empirical-analysis`
- trigger: 全日程ベースでホール別の高設定投入傾向を調べるとき / 新台初日と通常営業の戦略差を比較するとき
- summary: 新台初日（2026-06-10セッション前半）: みとや(103.9%)・ARROW(102.9%)が機械割で1-2位、 104%以上出現率でもARROW(38.5%)・みとや(36.7%)が1-2位だった。 しかし全日程・3000G以上フィルタでの機械割104%以上出現率: 1. 楽園 38.7% (+3.2p...

### 112. `dd-and-lastdigit-invalid-for-hit104-too`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-hit104-rate-allday-scan-insights.yaml`
- domain/source: `eda-pattern` / `empirical-analysis`
- trigger: DD系統(dd_mod10)・台番号末尾を機械割104%出現率で評価するとき
- summary: 全日程3000G以上での結果: DD_mod10単独: 最大pp = +0.5（dd_mod10=0）、最小 = -0.3。全てTier C 台番号末尾単独: 最大pp = +0.4（末尾8）、最小 = -0.3。全てTier C 曜日×DD_mod10（全ホール）: pp>=5かつn>=20を満たす組み合わせ...

### 113. `kaiwari-approximation-formula`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-new-machine-firstday-hall-insights.yaml`
- domain/source: `calculation` / `implementation`
- trigger: diff_coins_normalizedとgames_normalizedから機械割を計算するとき
- summary: DBには機械割が直接格納されていない。 パチスロの標準的な投入枚数は「1G = 3枚」なので以下で近似: 機械割(%) = (投入枚数 + 差枚) / 投入枚数 × 100 = (G数×3 + 差枚) / (G数×3) × 100 = 100 + (差枚 / G数) / 3 × 100 df['kaiwari']...

### 114. `mitoya-4kei-saturday-signal`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `eda-pattern` / `empirical-scan`
- trigger: みとやの台選択・イベント日分析をするとき
- summary: 全ホール横断スキャンで、みとやの「4系/土」が avg=+356 n=2126 CI=[217,493]。 また4系は月/火/水/木でも全てTier B（+190〜+269）で、4系全体が優位。 みとやのx_day = {4,14,24,7,17,27} のうち4系が全曜日で機能している。 みとやで4日・14日・...

### 115. `kamata7-aim-juggler-streak-86`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `lag-analysis` / `empirical-analysis`
- trigger: 蒲田7でアイムジャグラーEX-TPの台を選ぶとき / ラグ分析の結果を見るとき
- summary: lag_analysis の結果: streak_rate=86%: 前日プラスなら翌日も86%の確率でプラス（n=139, avg=+285） rebound_rate=74%: 前日マイナスでも74%でプラスに戻る（n=27, avg=+137） 全ホール・全機種中でstreak=86%は突出して高い値。 一...

### 116. `anomaly-realtime-usecase`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: ANOMALYの実用的な使い方を考えるとき
- summary: 全検証結果のまとめ: ANOMALY翌日は通常日より悪い（平均回帰） 逆張り条件では翌日-90（カンフルは1日限り） 好baseline×ANOMALYのみ翌日+113で続く 「カンフル注入仮説」への結論: カンフルが存在する場合、多くは1日限り 翌日予測シグナルとしてのANOMALYは機能しない ANOMALY...

### 117. `anomaly-detection-framework`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `implementation`
- trigger: 機種・台番号レベルで今日の異常好調台を検出したいとき
- summary: 「回転数が落ちた台にホールが設定を投入する」というカンフル仮説の検証と、 「今日突然好調な台の検出」をリアルタイムで行うためのフレームワーク。 実装済み: `eda/core.py` `compute_debut_features(df, db_start_grace_days=0)`: 機種初登場日・台数を付与...

### 118. `anomaly-baseline-positive-better`
- confidence: `0.95` | date: `2026-06-10` | file: `2026-06-10-eda-anomaly-techbias-insights.yaml`
- domain/source: `anomaly-detection` / `empirical-analysis`
- trigger: ANOMALYをどの条件で信頼するか判断するとき
- summary: 逆張り条件の翌日検証（全ホール合算、翌日1000G以上）: | 条件 | 翌日avg | plus率 | |------|---------|--------| | 全ANOMALY | +43 | 39.8% | | 少台数（≤3台）のANOMALY | +26 | 40.5% | | 低baseline（≤-...

### 119. `eda-over-ml-current-phase`
- confidence: `0.95` | date: `2026-06-09` | file: `2026-06-09-eda-framework-design-and-discovery-insights.yaml`
- domain/source: `methodology` / `session-conclusion`
- trigger: MLによる予測精度が頭打ちになったとき、または次の分析方向を検討するとき
- summary: 蒲田七・みとやの両ホールでML予測を試みた結果、「現状の情報ではMLによる予測は困難だが EDAは一定の効果がある」「MLで読み取れるのは粒度の粗い情報のみ」という結論に達した。 MLが苦手な理由：ホール側の意図的なランダム化、データ量不足、ノイズが多い。 MLによる精度改善に時間を費やすより、EDAを「信じられ...

### 120. `individual-rank-precision-is-wrong-metric-for-gambling-variance`
- confidence: `0.95` | date: `2026-06-07` | file: `2026-06-07-prediction-verification-evaluation-unit-insights.yaml`
- domain/source: `prediction-evaluation` / `user-correction`
- trigger: 日次予測（個別台の差枚順位予測）の的中率を評価しようとするとき
- summary: 6/7予測の検証で「予測TOP10のうち実際にTOP10に入ったのは何台か」(hit@k)を主指標として 報告したところ、ユーザーから明確な訂正を受けた： 「同じ設定6であっても、運によって2000枚出るのか、5000枚出るのかは分かりません。 そこは予測できる範囲ではないのでTOPで個別台予測性能を測るのは間違...
