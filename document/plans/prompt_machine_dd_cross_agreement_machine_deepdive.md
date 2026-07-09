# 機種横断DD一致度の機種名レベル深堀り（カテゴリ集計からの脱却）

## 目的

これまでの`eda/machine_dd_cross_agreement_scan.py`は、有意だった(hall, dd)ごとに`top_positive_machines`列で上位5機種名だけを文字列連結して見せており、それ以外は`machine_master`のjug/hana/oki/bt/otherという**カテゴリ集計**で全体傾向を確認していた（[jug-category-amplifies-not-diverges-from-hall-wide-signal](../instincts/2026-07-02-machine-dd-cross-agreement-insights.yaml)参照）。カテゴリ集計は「特定の機種系列が信号を独占していないか」の検証には有効だったが、実運用の推奨（＝具体的にどの機種名が強い/弱いか）には粒度が粗すぎる。

今回は**機種名そのもの**を主役に、以下を明らかにする。

1. 有意な(hall, dd)ごとに、上位5件に切り詰めずに**全機種のフルランキング**（プラス側・マイナス側の両方）を出す
2. 各機種×そのDDの残差が、単なる方向の多数決票の1つではなく、**その機種自身の統計として有意な変動か**（one-vs-rest二項検定）を検証する
3. 同一ホール内で**複数の有意日にまたがって繰り返し登場する機種**（＝ホールの複数投入日で一貫して強い/弱い"常連"機種）を特定する
4. 同一機種名が複数ホールに存在する場合、**ホールをまたいで同じDDで同じ方向に動くか**を確認する（[cross-hall-same-machine-name-disentangles-spec-vs-hall-intent](../instincts/2026-07-02-machine-type-volatility-event-gap-insights.yaml)の枠組みを、今回の有意日セットに適用する）

## 背景データ・既存資産（必ず再利用する）

- `eda/machine_dd_cross_agreement_scan.py`
  - `build_hall_outputs(hall, raw, *, min_machine_days_total, min_cell_n, min_machines_for_test, fdr_alpha, known_event_threshold)` — 既にhall単位で`residuals`（機種×DD残差、category列付き）と`summary`（有意な(dd)のみ）を返す。**この関数をそのままimportして呼び出し、CSVを再パースしない**
  - `DEFAULT_HALLS`, `DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE`, `MIN_CELL_N`, `DEFAULT_MIN_MACHINES_FOR_TEST`, `DEFAULT_FDR_ALPHA`, `DEFAULT_KNOWN_EVENT_THRESHOLD` — 既定値をそのまま使う
- `eda/core.py`
  - `HALL_DBS`, `load_hall_df(hall_name)` — `build_hall_outputs`に渡す`raw`を作るのに使う
- `eda/machine_name_significance_scan.py`
  - `DEFAULT_SHINDAI_EXCLUDE_DAYS`, `_prepare_frame` — `build_hall_outputs`が内部で使っているのと同じ前処理を、machine_frame単位のone-vs-rest検定用に再度使う
- `scipy.stats.binomtest`, `statsmodels.stats.multitest.multipletests`（`eda/machine_dd_cross_agreement_scan.py`と同じ使い方を踏襲）

## 実装内容

新規ファイル: `eda/machine_dd_cross_agreement_machine_deepdive.py`

### Step 1: 対象(hall, dd)の取得とフルランキングの構築

1. 対象ホールごとに`load_hall_df(hall)` → `build_hall_outputs(hall, raw, min_machine_days_total=DEFAULT_MIN_MACHINE_DAYS_TOTAL_FROM_DEEPDIVE, min_cell_n=MIN_CELL_N, min_machines_for_test=DEFAULT_MIN_MACHINES_FOR_TEST, fdr_alpha=DEFAULT_FDR_ALPHA, known_event_threshold=DEFAULT_KNOWN_EVENT_THRESHOLD)`を呼び、`residuals`と`summary`を取得する
2. `summary`の`hall, dd`が今回の対象母集団（有意だった(hall, dd)のみ。2026-07-02時点で9ホール合計13〜14件程度）
3. 関数`build_full_machine_ranking(residuals: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame`を実装する。`summary`の各行(hall, dd)について、`residuals`を`(hall, dd)`でフィルタし、**全機種**を`residual`降順でソートして`rank_desc`（1が最も強いプラス）と`rank_asc`（1が最も強いマイナス、`residual`昇順で振り直す）を付与する。5件などに切り詰めない
4. 出力列: `hall, dd, is_novel, machine_name, category, n, hit104_rate, baseline_hit104_rate, residual, rank_desc, rank_asc`

### Step 2: 機種単体のone-vs-rest統計検定

関数`compute_machine_dd_self_significance(hall: str, frame: pd.DataFrame, target_dds: set[int], *, min_machine_days_total: int, min_cell_n: int) -> pd.DataFrame`を実装する。`frame`は`_prepare_frame`済みのホール全体データ、`target_dds`はStep1の対象`(hall, dd)`のうちそのホール分の`dd`集合。

1. `frame`を`machine_name`でgroupby。`len(machine_frame) < min_machine_days_total`の機種はスキップ（`compute_machine_dd_residuals`と同じ足切り）
2. `target_dds`の各`dd`ごとに、`machine_frame`を`dd == target`と`dd != target`の2群に分ける
3. `n_at_dd = len(at_dd)`。`n_at_dd < min_cell_n`ならスキップ（この機種はこのddで検定しない）
4. `hits_at_dd = at_dd["hit104"].sum()`、`hits_rest = rest["hit104"].sum()`、`n_rest = len(rest)`。`n_rest == 0`ならスキップ
5. `rest_rate = hits_rest / n_rest`。`p_value = binomtest(int(hits_at_dd), int(n_at_dd), p=rest_rate, alternative="two-sided").pvalue`（`rest_rate`が0または1ちょうどでも`binomtest`はそのまま扱えるのでガード不要）
6. 出力列: `hall, dd, machine_name, n_at_dd, hits_at_dd, hit104_rate_at_dd, n_rest, rest_hit104_rate, p_value`

その後、関数`apply_fdr_per_hall_dd(self_significance: pd.DataFrame, *, fdr_alpha: float) -> pd.DataFrame`で**`(hall, dd)`単位**（機種数ぶんの検定が1つの(hall, dd)内で行われるため）にFDR補正し、`q_value`, `is_machine_significant`列を追加する。`eda.machine_dd_cross_agreement_scan.apply_fdr_per_hall`（hall単位でグループ化）とロジックは同型だが、groupbyキーを`["hall", "dd"]`にすること。

### Step 3: フルランキングと機種単体検定の統合

関数`merge_ranking_with_significance(ranking: pd.DataFrame, self_significance: pd.DataFrame) -> pd.DataFrame`で、Step1の`ranking`にStep2の`q_value`, `is_machine_significant`を`(hall, dd, machine_name)`キーでマージする。

### Step 4: ホール内での複数日常連チェック

関数`find_repeat_contributors(ranking_with_significance: pd.DataFrame, *, top_n: int = 10) -> pd.DataFrame`を実装する。

1. `hall`ごとに、各`(hall, dd)`グループで`rank_desc <= top_n`（プラス側上位）または`rank_asc <= top_n`（マイナス側上位）に入る機種を「その日の主要寄与機種」として抽出
2. `machine_name`ごとに、何個の異なる`dd`で主要寄与機種として登場したかを数える（`n_appearances`）
3. `n_appearances >= 2`の機種のみ抽出し、出現した`dd`のリストと、それぞれの`residual`・`is_machine_significant`を記録する
4. 出力列: `hall, machine_name, category, n_appearances, dds_appeared(セミコロン区切り), residuals_at_each_dd(セミコロン区切り), n_machine_significant_appearances`

### Step 5: ホール横断の同一機種名チェック

関数`find_cross_hall_consistency(ranking_with_significance: pd.DataFrame) -> pd.DataFrame`を実装する。

1. `ranking_with_significance`のうち`rank_desc <= 10 or rank_asc <= 10`の行に絞る（Step4と同じ主要寄与機種の定義を再利用）
2. `machine_name`が2ホール以上に登場する行だけを抽出する
3. `machine_name`ごとに、`(hall, dd, residual, is_machine_significant)`のリストを作る。**dd値が完全一致している必要はない**（同じ機種が別ホールの別ddで主要寄与になっているだけでも記録する。dd一致は目視確認用の参考情報として`dd_matches_across_halls`列に別途記録する）
4. 出力列: `machine_name, category, n_halls, halls(セミコロン区切り), dds(セミコロン区切り, hallと対応する順序を保つ), dd_matches_across_halls(完全一致するdd値があれば列挙、無ければ空文字)`

## 出力

- `eda/results/machine_dd_cross_agreement_deepdive/{hall}_full_ranking.csv`（Step1〜3統合、そのホールの全対象(dd)×全機種）
- `eda/results/machine_dd_cross_agreement_deepdive/repeat_contributors.csv`（Step4、全ホール統合）
- `eda/results/machine_dd_cross_agreement_deepdive/cross_hall_consistency.csv`（Step5、全ホール統合）
- 標準出力: ホールごとに、`is_machine_significant=True`かつ`rank_desc<=5 or rank_asc<=5`の機種一覧（`dd, machine_name, residual, q_value`）を`df.to_string(index=False)`で表示（`to_markdown()`は使わない）。最後に`repeat_contributors`と`cross_hall_consistency`の件数サマリーを表示する

## 実装上の注意

1. 新規ファイルは`eda/machine_dd_cross_agreement_machine_deepdive.py`の1ファイルのみ。`eda/machine_dd_cross_agreement_scan.py`は変更しない（`build_hall_outputs`をimportして使うだけ）
2. Step2のone-vs-rest検定は、Step1の`residual`（`_axis_breakdown`が計算した値、丸め済みの`hit104_rate`列由来）から逆算しない。`hits_at_dd`/`hits_rest`は必ず`frame`の`hit104`列（0/1）から直接集計する（丸め誤差を避けるため）
3. `apply_fdr_per_hall_dd`は`(hall, dd)`単位でグループ化すること。`eda.machine_dd_cross_agreement_scan.apply_fdr_per_hall`をコピーして流用してよいが、groupbyキーを変えるのを忘れないこと
4. CLI引数: `--halls`（既定は`eda.machine_dd_cross_agreement_scan.DEFAULT_HALLS`と同じ値。`eda.machine_volatility_event_gap_scan._parse_halls`を再利用）、`--all-halls`、`--top-n`（Step4/5の主要寄与機種の閾値、既定10）、`--output-dir`
5. 出力先ディレクトリが存在しない場合は作成する。CSV出力は`encoding="utf-8-sig"`。ファイル冒頭で`sys.stdout.reconfigure(encoding="utf-8")`を設定する
6. `dd`列の型はint、`hall`列は文字列で統一する

## テスト

`ml/tests/test_machine_dd_cross_agreement_machine_deepdive.py`に以下を含める:

- `build_full_machine_ranking`の単体テスト: 人工の`residuals`/`summary`で、5件を超える機種数があっても全件がランキングに含まれること、`rank_desc`/`rank_asc`が`residual`の降順/昇順と一致することを確認
- `compute_machine_dd_self_significance`の単体テスト: 人工の`frame`で、ある機種の特定ddだけ`hit104`が明らかに高くなるよう仕込み、`p_value`が小さくなることを確認。`n_at_dd < min_cell_n`の機種がスキップされることも確認
- `apply_fdr_per_hall_dd`の単体テスト: 複数の`(hall, dd)`グループにまたがるp値（NaN混在）で、グループごとに独立してFDR補正されること（`eda.machine_dd_cross_agreement_scan.apply_fdr_per_hall`のテストと同型で、グループキーが`(hall, dd)`になっている点を検証する）
- `find_repeat_contributors`の単体テスト: ある機種が3つの異なる`dd`で`rank_desc<=top_n`に入るよう人工データを仕込み、`n_appearances=3`として抽出されることを確認。1回しか登場しない機種が除外されることも確認
- `find_cross_hall_consistency`の単体テスト: 同じ`machine_name`が2ホールの主要寄与機種リストに登場する人工データで、`n_halls=2`として抽出されること。dd値が一致するケースと一致しないケースの両方を含め、`dd_matches_across_halls`の挙動を確認
- スモークテスト: `--halls 蒲田7`で例外なく実行が完了し、CSV3種が出力されること（`build_hall_outputs`の呼び出しをmonkeypatchして、`eda.machine_dd_cross_agreement_scan.load_hall_df`と`load_machine_categories`相当のI/Oを避けること。`test_machine_dd_cross_agreement_scan.py`の`test_main_writes_requested_csvs`と同じmonkeypatchパターンを踏襲する）
