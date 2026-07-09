# 機種横断DD一致度スキャン（ホール投入日の自動検出）

## 目的

[dd-pattern-shared-across-machines-signals-hall-strategy](../instincts/2026-06-15-machine-type-six-axis-eda-insights.yaml)（2026-07-02）で、蒲田7・みとやにおいて甲鉄城のカバネリ・ジャグラーガールズ・クレアの秘宝伝の3機種を手動で突き合わせた結果、**同一ホール内の複数機種が同じDD（1〜31日）で揃って上振れする**現象が確認された。これは機種固有のクセではなく、ホールがその日に複数機種へ横断的に高設定を投入している証拠と解釈できる。

一方で、単一機種のDD分析はセルサイズ不足による多重検定ノイズに弱いことも判明している（[successor-machine-dd-divergence-may-be-sample-noise-not-strategy-shift](../instincts/2026-06-15-machine-type-six-axis-eda-insights.yaml)、海門(うなと)決戦がn≈14/セルでplus_effect=0.227という見せかけの最大値を出した例）。

この2つの知見を組み合わせ、**手動で選んだ2〜3機種だけでなく、ホール内の全対象機種を横断してDD一致度を自動集計するツール**を実装する。個々の機種のDD効果ではなく、「そのホールで、その日に、何台の機種が自分自身のベースラインより上振れしているか」を検定する。これにより、①ノイズに強い（機種間で平均化される）、②機種固有のクセとホール裁量を分離できる（機種ごとに自分自身のbaselineからの残差を使う）、③`is_x_day`のような既知のイベント日定義でカバーされていない「未知の投入日」を新たに発見できる可能性がある。

## 背景データ・既存資産（必ず再利用する）

- `eda/core.py`
  - `HALL_DBS`, `load_hall_df(hall_name)` — `dd`（1〜31の実測日）, `is_x_day`（ホール固有イベント日、`HALL_EVENT_DIGITS`＋月末＋強ゾロ目の統合）列を持つ
- `eda/machine_name_significance_scan.py`
  - `DEFAULT_SHINDAI_EXCLUDE_DAYS`
  - `_prepare_frame(raw, shindai_exclude_days)` — `plus`, `hit104`, `payout_rate`列を付与する。**このロジックを再実装しない**
- `eda/machine_axis_pattern_scan.py`
  - `MIN_CELL_N`（=5、DD1区分あたりの最小セルサイズ）
  - `_axis_breakdown(hall, machine_name, machine_frame, axis="dd", outcome="hit104")` — machine_frameを渡すとDD別（1〜31、実測値のみ）の`n`, `avg_diff`, `plus_rate`, `hit104_rate`を返す。**このまま再利用する**
- `eda/machine_dd_deepdive_target_machines.py`
  - `MIN_MACHINE_DAYS_TOTAL`（=100）— 機種の最小サンプル日数。**同じ定数をimportして使う**（値を独自に決め直さない）
- `eda/machine_volatility_event_gap_scan.py`
  - `_parse_halls(value)` — カンマ区切り文字列をホールリストに変換するargparse用関数。**そのままimportして使う**
- `scipy.stats.binomtest`（`ml/last_digit/hall_multitest_signal_baseline.py`で使用済みのパターンを踏襲）
- `statsmodels.stats.multitest.multipletests(pvals, method="fdr_bh")`（`eda/mitoya_section_category_eda.py`, `ml/last_digit/analyze_correction_periodicity.py`で使用済みのパターンを踏襲）

## 実装内容

新規ファイル: `eda/machine_dd_cross_agreement_scan.py`

### Step 1: 機種×DD残差テーブルの構築

関数 `compute_machine_dd_residuals(hall: str, frame: pd.DataFrame, *, min_machine_days_total: int, min_cell_n: int) -> pd.DataFrame` を実装する。

1. `frame`（`_prepare_frame`済み）から`machine_name`ごとに`machine_frame`を作る
2. `len(machine_frame) < min_machine_days_total`の機種はスキップ（対象母集団を絞る。現在設置されているかどうかのフィルタは今回不要 — 過去に投入していた履歴もホール戦略のシグナルとして有効に扱う）
3. `baseline_hit104_rate = machine_frame["hit104"].mean() * 100.0`（機種自身の全期間平均、%）
4. `_axis_breakdown(hall, machine_name, machine_frame, axis="dd", outcome="hit104")`で DD別内訳を取得
5. 内訳の各行のうち`n >= min_cell_n`の行だけを採用し、`residual = hit104_rate - baseline_hit104_rate`（パーセントポイント）を計算
6. 出力列: `hall, machine_name, dd, n, hit104_rate, baseline_hit104_rate, residual`（`dd`は`_axis_breakdown`が返す`axis_level`をそのままint型で使う）

### Step 2: ホール×DDの機種間一致度集計

関数 `aggregate_dd_agreement(residuals: pd.DataFrame, *, min_machines_for_test: int) -> pd.DataFrame` を実装する。

`residuals`を`(hall, dd)`でgroupbyし、各グループについて:

1. `n_machines`（そのDDでresidualを持つ機種数）
2. `n_positive`（`residual > 0`の機種数。**残差が厳密に0の機種はpositiveに含めない**＝failure側として扱う。この扱いをコード内コメントで明記する）
3. `agreement_rate = n_positive / n_machines`
4. `mean_residual`, `median_residual`（`residuals`列の平均・中央値）
5. `n_machines >= min_machines_for_test`の場合のみ:
   - `p_value = binomtest(n_positive, n_machines, p=0.5, alternative="two-sided").pvalue`
   - `cohens_h = 2*np.arcsin(np.sqrt(agreement_rate)) - 2*np.arcsin(np.sqrt(0.5))`（0.5からの乖離の効果量）
   - それ以外の場合は`p_value = np.nan`, `cohens_h = np.nan`, `note = f"insufficient machines (<{min_machines_for_test})"`

出力列: `hall, dd, n_machines, n_positive, n_negative, agreement_rate, mean_residual, median_residual, p_value, cohens_h, note`
（`n_negative = n_machines - n_positive`）

### Step 3: FDR補正（ホール単位）

関数 `apply_fdr_per_hall(agreement: pd.DataFrame, *, fdr_alpha: float) -> pd.DataFrame` を実装する。

- ホールごとに、DD1〜31（最大31回）検定するため多重比較の補正が必須（[large-n-kruskal-chi2-pvalue-uninformative](../instincts/2026-07-02-machine-type-volatility-event-gap-insights.yaml)参照）
- ホールごとに`p_value`が非NaNの行だけを対象に`multipletests(pvals, method="fdr_bh")`を適用し、結果を`q_value`列に書き戻す（NaN行は`q_value`もNaNのまま）
- `is_significant = (q_value < fdr_alpha)`（NaNはFalse扱い）

### Step 4: 既知イベント軸との突き合わせ

関数 `attach_event_coverage(agreement: pd.DataFrame, hall_frames: dict[str, pd.DataFrame], *, known_event_threshold: float) -> pd.DataFrame` を実装する。

1. 各`hall_frames[hall]`（Step1で使った`_prepare_frame`済みフレーム、ホールの全行を保持）から、`dd`ごとに`is_x_day`の平均を`dd_event_coverage_rate`として計算する（例: dd=27が常にis_x_day=1の月ならrate=1.0に近い。月末フラグは月によって該当有無が変わるため1.0ちょうどにはならない点に注意）
2. `is_known_event_dd = dd_event_coverage_rate >= known_event_threshold`（既定`known_event_threshold=0.5`）
3. `agreement`テーブルに`hall`と`dd`をキーにマージする

### Step 5: サマリーレポート（新規発見された投入日の抽出）

関数 `build_summary_report(agreement: pd.DataFrame, residuals: pd.DataFrame) -> pd.DataFrame` を実装する。

`agreement`のうち`is_significant == True`の行について:

1. `top_positive_machines`列 — その`(hall, dd)`で`residual > 0`の機種を`residual`降順で並べ、`機種名(residual値+1桁小数)`形式の文字列をセミコロン区切りで**最大5件**連結する（例: `"甲鉄城のカバネリ(+7.6);ジャグラーガールズ(+9.3)"`。これらの数値・機種名はフォーマット例示であり実測値ではない）。5件を超える場合は末尾に`;...(他N件)`を追記する
2. `is_novel = not is_known_event_dd`（既知イベント軸でカバーされていない＝新規発見候補）
3. 出力列: `hall, dd, n_machines, n_positive, agreement_rate, mean_residual, q_value, cohens_h, is_known_event_dd, is_novel, top_positive_machines`
4. `is_novel`降順→`cohens_h`降順でソートする（新規発見を先頭に）

## 出力

- `eda/results/machine_dd_cross_agreement/{hall}_machine_dd_residuals.csv`（Step1の生データ、列は上記の通り）
- `eda/results/machine_dd_cross_agreement/{hall}_dd_agreement.csv`（Step2〜4の集計結果、列は上記の通り）
- `eda/results/machine_dd_cross_agreement/summary_report.csv`（Step5の全ホール統合サマリー、`hall`列で区別）
- 標準出力: ホールごとに
  - 有意（`is_significant`）なDDの件数
  - `is_novel`なDDの一覧（`dd, agreement_rate, cohens_h, top_positive_machines`）を`df.to_string(index=False)`で表示（`to_markdown()`は使わない）
  - 既知イベントDDのうち有意だったものの一覧も同様に表示（＝クロス機種一致度が既存の`is_x_day`定義を裏付けている件数の確認用）

## 実装上の注意

1. 新規ファイルは`eda/machine_dd_cross_agreement_scan.py`の1ファイルのみ。`eda/core.py`, `eda/machine_name_significance_scan.py`, `eda/machine_axis_pattern_scan.py`, `eda/machine_dd_deepdive_target_machines.py`, `eda/machine_volatility_event_gap_scan.py`は変更しない
2. `_axis_breakdown`, `_prepare_frame`, `MIN_CELL_N`, `MIN_MACHINE_DAYS_TOTAL`, `_parse_halls`は必ずimportして再利用する。DD別集計ロジック（`_axis_breakdown`相当）を独自に再実装しない
3. `binomtest`の`p_value`が`np.nan`の行を`multipletests`に渡さないこと（`analyze_correction_periodicity.py`の`lb_mask`と同じマスク方式で、有効行だけ抽出してから渡し、結果を元のindexへ書き戻す）
4. CLI引数: `--halls`（既定 `"蒲田1,蒲田7,みとや"`、`_parse_halls`でパース）、`--all-halls`（指定時は`HALL_DBS`の全ホールを使う）、`--min-machine-days-total`（既定は`machine_dd_deepdive_target_machines.MIN_MACHINE_DAYS_TOTAL`をそのまま使う）、`--min-cell-n`（既定は`machine_axis_pattern_scan.MIN_CELL_N`をそのまま使う）、`--min-machines-for-test`（既定15）、`--fdr-alpha`（既定0.05）、`--known-event-threshold`（既定0.5）、`--output-dir`
5. 出力先ディレクトリが存在しない場合は作成する
6. CSV出力は`encoding="utf-8-sig"`。ファイル冒頭で`sys.stdout.reconfigure(encoding="utf-8")`を設定する（`machine_dd_deepdive_target_machines.py`と同じ）
7. `dd`列の型はint（`_axis_breakdown`が返す`axis_level`をそのまま使えばintになる。float化しない）

## テスト

`ml/tests/test_machine_dd_cross_agreement_scan.py`に以下を含める:

- スモークテスト: `--halls 蒲田7`で例外なく実行が完了し、CSV3種（`蒲田7_machine_dd_residuals.csv`, `蒲田7_dd_agreement.csv`, `summary_report.csv`）が出力されること
- `compute_machine_dd_residuals`の単体テスト: 人工データで、`min_cell_n`未満のDDセルが残差テーブルから除外されること、`min_machine_days_total`未満の機種が丸ごと除外されることを確認
- `aggregate_dd_agreement`の単体テスト: 人工の残差テーブルを作り、
  - あるDD（例: dd=7）で20機種中18機種が`residual>0`となるよう仕込み、`p_value`が小さくなること（`agreement_rate=0.9`, `cohens_h`が正の大きな値になること）
  - 別のDD（例: dd=15）で20機種中10機種が`residual>0`となるよう仕込み、`p_value`が有意にならないこと
  - `residual == 0`ちょうどの機種が`n_positive`にカウントされない（`n_negative`側扱いになる）ことを確認
  - `n_machines < min_machines_for_test`のDDで`p_value`が`NaN`になり`note`に理由が記録されることを確認
- `apply_fdr_per_hall`の単体テスト: 複数DDのp値（NaN混在）を持つ人工`agreement`テーブルで、NaN行の`q_value`がNaNのまま保たれ、非NaN行だけが正しくFDR補正されることを確認
- `attach_event_coverage`の単体テスト: 人工フレームで、あるddの全行が`is_x_day=1`（`dd_event_coverage_rate=1.0`）、別のddの全行が`is_x_day=0`（`dd_event_coverage_rate=0.0`）となるよう仕込み、`known_event_threshold=0.5`で`is_known_event_dd`が期待通り`True`/`False`になることを確認
- `build_summary_report`の単体テスト: `top_positive_machines`文字列が`residual`降順で連結され、6件以上ある場合に`;...(他N件)`が付与されることを確認
