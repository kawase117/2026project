# 機種別×ホール — 104%超え率・Top3/Bottom3選出率の有意差スキャン

## 目的

現在のルールベース分類（DD・角番・曜日・セクションサイズ軸）には「機種」の情報が欠けている。
機種を予測特徴量に組み込む価値があるかを判断する前段階として、まず**機種単体の主効果**が
既存軸と切り離してどれだけ大きいかをEDAで定量化する。

具体的には、ホールごとに機種名（`machine_name`）単位で以下2種類の指標を集計し、機種間で
統計的に有意な差があるかを確認する。

1. **104%超え率**（`hit104_rate`）— 出玉率が104%を超えた日の割合
2. **Top3/Bottom3選出率** — その日のホール内実績ランキングで上位3台・下位3台に入った頻度
   （機種の設置台数による下駄を正規化した「リフト比」で評価する。設置台数が多い機種ほど
   Top3に入りやすいのは当然なので、生の出現回数で機種を比較してはいけない）

この結果は次のステップ（機種を特徴量として使うか、機種特性の数値化に留めるか）の判断材料にする。
機種を直接one-hotで投入することの是非については判断しない。

## 背景データ・既存資産

- `eda/core.py`
  - `load_hall_df(hall_name)` — `machine_detailed_results` から日付フィーチャー付きDataFrameを返す（`games_normalized >= 400` で既にフィルタ済み）
  - `scan_dimension(hall_name, group_cols, filters, min_n, df)` — 指定した次元でTier・p値（Kruskal-Wallis）・ε²・Bootstrap CI付き集計を返す。**`group_cols=['machine_name']` で呼べばそのまま機種別の集計・有意性検定に使える**
  - `compute_debut_features(df, db_start_grace_days)` — `days_since_debut` / `pre_existing` / `machine_count`（その日のホール内同機種設置台数）を付与する
  - `HALL_DBS` — ホール名→DBファイル名の対応

- `eda/cross_hall_pattern_verification.py`
  - `COINS_PER_GAME = 3` — payout_rate計算の3枚がけ係数
  - 既存の機種別Q5/Q1クインタイル分析（`load_data`, `assign_period`, `quintile`）— 今回は流用しないが設計思想（機種単位で見る発想）の先行事例

- `eda/kamata7_machinename_q5_backtest.py`
  - 蒲田7限定で機種名による強い台判定のwalk-forward検証が既にある。payout_rateの式:
    `payout_rate = ((games_sum * 3 + diff_sum) / (games_sum * 3)) * 100`
  - 今回のスクリプトもこの式に統一する（独自係数を使わない）

- 関連知見（メモリ）
  - `shindai-exclude-from-games-analysis`: 新台は設定不問で高回転するため `games_normalized` ベースの分析から除外すべき。今回は `days_since_debut` を使って新台期間を除外する
  - `exploration-coarse-to-fine`: まず粗く機種の主効果だけを見る。DD/曜日/角番との交互作用は今回のスコープ外

## 実装内容

新規ファイル: `eda/machine_name_significance_scan.py`

### 処理フロー（ホールごとに実施）

1. `load_hall_df(hall_name)` でデータ取得
2. `compute_debut_features(df)` を適用し、`days_since_debut < SHINDAI_EXCLUDE_DAYS`（既定30）かつ `pre_existing == False` の行を除外する（新台期間の除外。CLI引数 `--shindai-exclude-days` で調整可能。0を指定すれば除外なし）
3. `payout_rate = (games * 3 + diff) / (games * 3) * 100` を計算し、`hit104 = payout_rate >= 104` フラグを付与
4. **日付内ランキング**: 同一 `date` 内で `diff` の降順に順位付けし、`rank` 列を作る（同日の母集団は `load_hall_df` 済みで既に `games_normalized >= 400` フィルタ済みの台のみ）
   - `top3_flag = rank <= 3`
   - `n_active` = その日の稼働台数
   - `bottom3_flag = rank > n_active - 3`
5. 機種名（`machine_name`）ごとに集計:
   - `n_units`（`machine_number` のユニーク数）
   - `n_machine_days`
   - `avg_diff`, `plus_rate`（`scan_dimension` の出力をそのまま使う）
   - `hit104_rate = hit104.mean()`
   - `avg_payout_rate = payout_rate.mean()`
   - `top3_rate = top3_flag.mean()`
   - `expected_top3_rate = (3 / n_active).mean()`（**行ごとの期待値の平均**。単純に `3 / 平均稼働台数` にしない。稼働台数は日によって変動するため）
   - `top3_lift = top3_rate / expected_top3_rate`
   - 同様に `bottom3_rate`, `expected_bottom3_rate`, `bottom3_lift`
6. **統計検定**:
   - `avg_diff` / `plus_rate` の機種間差はそのまま `scan_dimension(hall_name, ['machine_name'], min_n=MIN_MACHINE_DAYS, df=df)` を呼んで使う（この2指標は`scan_dimension`が内部で`diff`/`plus`列に対して計算しているものと完全一致するため、素直に再利用できる）。
   - **`hit104_rate` と `avg_payout_rate` は `scan_dimension` では計算できない**（`scan_dimension`は`diff`/`plus`列にハードコードされており、任意の列を渡せる汎用関数ではない）。この2指標は `scan_dimension` を呼ばず、同じ考え方（Kruskal-Wallis検定 + `core._epsilon_squared`をimportして効果量ε²を計算）で、対象列を`payout_rate`および`hit104`に差し替えた集計を機種名ごとに実装する。Tier判定ロジック（`_classify_tier`）は流用せず、今回はp値・ε²・平均値のみを出力すれば十分（Tierラベルは`avg_diff`/`plus_rate`側の結果にのみ付与する）。
   - `top3_flag` / `bottom3_flag` の機種間差: `scipy.stats.chi2_contingency` で機種名×選出有無の分割表検定を行う。効果量は **Cramér's V** を使う（`V = sqrt(chi2 / (n * min(k-1, r-1)))`）。
     - `n_machine_days < MIN_MACHINE_DAYS`（既定30）の機種は分割表から除外
     - **分割表のスパース性ガード**: 除外後も分割表のセル期待度数が5未満のセルが20%を超える場合は、警告ログを出した上で通常のPearsonカイ二乗ではなく `scipy.stats.chi2_contingency(..., correction=True)` を使うか、可能であれば `scipy.stats.fisher_exact` 相当（2群限定なので機種数が2つに絞られたときのみ）にフォールバックする。フォールバックが使えない場合は「サンプル不足につき検定結果を参考値として扱う」旨を出力に明記する
     - `n_active < 3` の日（稼働台数が3台未満）は `bottom3_flag` の定義が退化する（`rank > n_active - 3` が負になり全台がbottom3判定になり得る）ため、**分割表構築前に `n_active >= 6` の日のみを対象とする**（Top3とBottom3が重複しない最小条件として、稼働台数が閾値6台未満の日は集計から除外する。この閾値はCLI引数 `--min-active-machines` で調整可能にする）

### 統計的妥当性（重要）

- **Top3/Bottom3のリフト比が主指標**。生の`top3_rate`だけを機種間で比較しない（設置台数が多い機種ほど分子が大きくなるバイアスがあるため）
- **新台除外は既定でON**。除外なしの結果も比較用に出したい場合は `--shindai-exclude-days 0` で再実行できるようにする（同一スクリプトの引数で切り替え、別ファイルは作らない）
- 機種名の比較は**ホール内で完結**させる。ホールをまたいで同じ機種名を直接比較しない（設置環境・客層が異なるため）。ホール横断の議論をしたい場合は「各ホールで機種軸の主効果がどの程度あったか」という**Tierの分布・p値の分布**を比較する程度に留める
- 多重比較の扱い: 機種数が多いホール（蒲田7など）では個々の機種のp値を過信しない。まず全体検定（KW / カイ二乗）で「機種間に有意差があるか」を先に判定し、個別機種のTier/lift値は参考情報として出す

## 出力

- `eda/results/machine_name_significance/{hall}_machine_summary.csv`
  列: `hall, machine_name, n_units, n_machine_days, avg_diff, plus_rate, hit104_rate, avg_payout_rate, top3_rate, expected_top3_rate, top3_lift, bottom3_rate, expected_bottom3_rate, bottom3_lift, tier`

- `eda/results/machine_name_significance/significance_summary.csv`
  列: `hall, metric(avg_diff/plus_rate/hit104_rate/avg_payout_rate/top3_selection/bottom3_selection), test(kruskal/chi2), statistic, p_value, effect_size(epsilon_sq for kruskal, cramers_v for chi2), n_groups, n_obs, note(スパース性ガードが発動した場合の注記)`

- 標準出力: ホールごとに
  - 全体検定の結果（機種間に有意差があるか、p値・効果量）
  - `top3_lift` 上位5機種・`bottom3_lift` 上位5機種（＝低設定台に選ばれやすい機種）
  - `hit104_rate` 上位5機種・下位5機種

## 実装上の注意

1. 新規ファイルは `eda/machine_name_significance_scan.py` の1ファイルのみ。`eda/core.py`, `eda/cross_hall_pattern_verification.py`, `eda/kamata7_machinename_q5_backtest.py` は変更しない
2. `load_hall_df`, `scan_dimension`, `compute_debut_features`, `_epsilon_squared` は `eda/core.py` からimportして再利用する。独自にDB接続・SQLクエリを書かない。`scan_dimension`は`avg_diff`/`plus_rate`のみに使い、`hit104_rate`/`avg_payout_rate`はscan_dimensionの内部ロジックと同じ考え方（Kruskal-Wallis + `_epsilon_squared`）で対象列を差し替えた別集計として実装する（詳細は「統計検定」節を参照）
3. payout_rateの式は `(games*3 + diff) / (games*3) * 100` で統一（`COINS_PER_GAME=3` は `eda/cross_hall_pattern_verification.py` から定数importするか、同じ値をハードコードしてコメントで出典を明示する）
4. CLI引数: `--halls`（カンマ区切り、既定 `蒲田1,蒲田7,みとや` — サンプル数が十分な3ホール）、`--all-halls`（`HALL_DBS` の全ホールを対象にするフラグ）、`--shindai-exclude-days`（既定30）、`--min-machine-days`（既定30、機種の最小サンプル数）、`--min-active-machines`（既定6、Top3/Bottom3集計対象とする日の最小稼働台数）
5. 出力先ディレクトリが存在しない場合は作成する
6. `machine_number < 3000` を2F、`>=3000` を3Fとする慣習（`kamata7_machinename_q5_backtest.py` 参照）はこのスクリプトでは使わない。フロア軸との交互作用は今回のスコープ外（機種の主効果だけを見る）

## テスト

`ml/tests/test_machine_name_significance_scan.py` に以下を含める:

- スモークテスト: 少なくとも1ホールで例外なく実行が完了し、CSV2種が出力されること
- `expected_top3_rate` の正規化ロジックの単体テスト: 稼働台数が一定の人工データ（例: 毎日10台稼働、機種Aが2台）で `expected_top3_rate` が理論値（`3/10`の平均）と一致することを確認
- 新台除外ロジックのテスト: `days_since_debut` が閾値未満の行が集計から除外されていることを確認（`--shindai-exclude-days 0` では除外されないことも確認）
- `top3_lift` が1より大きい機種（Top3に選ばれやすい）と1より小さい機種（選ばれにくい）が人工データで正しく分離されることを確認
- `hit104_rate`/`avg_payout_rate`のKruskal-Wallis集計が`scan_dimension`を経由せず独自実装であることを踏まえ、`payout_rate`が明確に異なる2機種の人工データでp値が小さく出ることを確認する単体テスト
- `n_active < min_active_machines` の日が分割表構築前に除外されていることの単体テスト（`bottom3_flag`退化ケースの再現）
- スパース分割表（機種数が多くセルの期待度数が5未満になるケース）で警告ログまたは`note`列への注記が出力されることの単体テスト
