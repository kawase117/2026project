# 機種名×DD／機種名×イベント日／機種名×曜日 の法則性スキャン

## 目的

これまでの分析は「機種そのものの主効果」（機種スペック vs ホール裁量、ボラティリティ、東京喰種のイベント軸ギャップ）を見てきた。次は逆方向として、**機種を軸に固定し、DD・イベント日・曜日という既存の3軸それぞれが、その機種の成績（差枚・勝率・104%超え率）とどれだけ関係しているか**を全機種横断でスクリーニングする。

東京喰種のDD別分析（手動のBash集計）で「27日が強いのは蒲田7限定で、蒲田1は7日、みとやは4/14/24日が強い」というホール×機種×DD特異的なパターンが見つかった。これを1機種だけでなく**全機種に対して機械的にスクリーニングし、どの機種がどの軸（DD/イベント日/曜日）で強い法則性を持つか**を一覧化する。

## 背景データ・既存資産（必ず再利用する）

- `eda/core.py`
  - `load_hall_df(hall_name)` — `dd`（1〜31）, `day_of_week`（月〜日）, `is_x_day`（ホール固有イベント日）列を持つ
  - `_epsilon_squared(H, k, n)` — Kruskal-Wallis効果量
  - `HALL_DBS`
- `eda/machine_name_significance_scan.py`
  - `_prepare_frame(raw, shindai_exclude_days)` — `payout_rate`, `hit104`, `plus`（想定: `diff>0`と同義、無ければ`diff`から都度計算）を付与
  - `_cramers_v(chi2, n_obs, n_rows, n_cols)`
  - `DEFAULT_MIN_ACTIVE_MACHINES`
- `eda/machine_volatility_event_gap_scan.py`
  - `_apply_currently_installed_filter(frame, grace_days)` — 現在設置されているかの判定。**この関数をそのままimportして使う**（東京喰種用ではなく汎用実装になっている）
  - `DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS`
- 関連メモリ（今回のセッションでエクスポート済み: `document/instincts/2026-07-02-machine-type-volatility-event-gap-insights.yaml`）
  - `large-n-kruskal-chi2-pvalue-uninformative` — 大サンプルでのp値は判断材料にならない。効果量を主指標にする
  - `event-day-effect-is-hall-and-dd-specific-not-uniform` — DD単位の強い日はホール・機種特異的で一般化できない
  - `hit104-rate-confounds-machine-spec-with-hall-intent` — 絶対閾値の機種間比較は機種スペックを混同する（**本スキャンは機種"内"の軸比較なので、この懸念は当てはまらない**。同一機種内でDD/曜日/イベント日を比べる分には機種スペックは定数なので問題ない）

## 実装内容

新規ファイル: `eda/machine_axis_pattern_scan.py`

### Step 1: 前処理（ホールごと）

1. `load_hall_df(hall)` → `_prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)`（既定30、`machine_name_significance_scan.DEFAULT_SHINDAI_EXCLUDE_DAYS`を再利用）
2. `_apply_currently_installed_filter(frame, grace_days=CURRENTLY_INSTALLED_GRACE_DAYS)`（既定30）で現在設置されていない機種を除外
3. `n_machine_days >= MIN_MACHINE_DAYS_TOTAL`（既定200）を満たす機種のみ対象とする（3軸×アウトカムの分割検定を行うため、前段の`min_machine_days`(30)より高めに設定する）

### Step 2: 機種×軸×アウトカムのスキャン

対象軸（3種、列名`axis`）:
- `dd`（1〜31の整数、`load_hall_df`の`dd`列）
- `day_of_week`（月〜日、7水準）
- `is_x_day`（0/1、ホール固有イベント日）

対象アウトカム（3種、列名`outcome`）:
- `diff`（連続値）→ 軸内の各水準でKruskal-Wallis検定、効果量は`_epsilon_squared`
- `plus`（`diff > 0`の二値）→ 軸×plusの分割表でカイ二乗検定、効果量は`_cramers_v`
- `hit104`（`payout_rate >= 104`の二値、`_prepare_frame`が付与済み）→ 同上

機種ごとに3軸×3アウトカム＝9行を出力する。**アウトカムがdiffのときはKruskal-Wallis、plus/hit104のときはカイ二乗**、と検定方法をアウトカムで自動的に切り替える。

分割表・KW群のスパース性ガード（`machine_name_significance_scan._chi2_summary`と同じ基準）:
- 各水準のサンプル数が極端に少ない場合（`dd`は31水準あるため特に起きやすい）、期待度数5未満のセルが20%を超えたら`note`列に警告を記録する
- KW側もグループ数<2、または各グループn<`MIN_CELL_N`（既定5）の場合はスキップしてp値・効果量をNaNにし、`note`に理由を記録する

### Step 3: 出力の絞り込み（法則性の一覧化）

1. `{hall}_pattern_summary.csv`（全機種×3軸×3アウトカムのロング形式、フィルタなし全件）
2. `{hall}_top_signals.csv` — `pattern_summary`のうち、**軸内の水準数に応じた最小サンプル条件**（`n_obs >= MIN_OBS_FOR_RANKING`、既定100）を満たす行を対象に、`effect_size`（`epsilon_sq`または`cramers_v`）降順で上位30件（`--top-n`で変更可）を抽出する
3. `{hall}_top_signal_breakdown.csv` — `top_signals`に含まれる(machine_name, axis)の組み合わせについてのみ、**水準ごとの記述統計**（水準値, n, avg_diff, plus_rate, hit104_rate）を出力する。全機種×全軸の水準別内訳を出すと巨大になるため、**上位シグナルに絞る**（東京喰種のDD別breakdownを手動で行った作業をここで再現可能にする）
4. `summary_report.csv` — ホールごとに、軸×アウトカムの組み合わせ別（9パターン）で「`effect_size >= 0.1`（Cramér's Vのsmall閾値と揃える。KW側のepsilon_sqも同じ0.1を暫定の目安値として使い、実装コメントで明記する）を満たした機種の件数・割合」を集計する

### 統計的妥当性（重要）

- **主指標は効果量、p値は補助**。9パターン×機種数（100件超）×3ホールで検定数が数千に及ぶため、個別のp値を「発見」として扱わない（`large-n-kruskal-chi2-pvalue-uninformative`の知見を踏襲）
- `dd`軸は31水準あり、`MIN_MACHINE_DAYS_TOTAL=200`でも1水準あたり平均6〜7件程度とかなり薄い。この軸のKW/カイ二乗は**スクリーニング目的**であり、上位シグナルは`top_signal_breakdown.csv`で必ず水準別の実数（n・平均差枚等）を確認してから解釈する
- `is_x_day`は2水準の粗い軸であり、`event-day-effect-is-hall-and-dd-specific-not-uniform`の知見の通り、この軸で効果が小さくても`dd`軸で個別の強い日が隠れている可能性がある。3軸を独立に見て、`is_x_day`の効果が小さいからといって`dd`軸の結果を無視しない

## 出力ディレクトリ

`eda/results/machine_axis_pattern_scan/`

## 実装上の注意

1. 新規ファイルは `eda/machine_axis_pattern_scan.py` の1ファイルのみ。`eda/core.py`, `eda/machine_name_significance_scan.py`, `eda/machine_volatility_event_gap_scan.py` は変更しない
2. `_prepare_frame`, `_cramers_v`, `_apply_currently_installed_filter`, `core._epsilon_squared` を必ずimportして再利用する。分割表検定・KW検定のロジックを独自に再実装しない
3. `_apply_currently_installed_filter`は`eda/machine_volatility_event_gap_scan.py`内で定義されている。インポート元がこのファイルになるため、循環importが起きないか実装時に確認する（`machine_axis_pattern_scan.py`が`machine_volatility_event_gap_scan.py`をimportし、逆方向のimportは発生させない）
4. CLI引数: `--halls`（既定 `蒲田1,蒲田7,みとや`）、`--currently-installed-grace-days`（既定30）、`--min-machine-days-total`（既定200）、`--min-obs-for-ranking`（既定100）、`--top-n`（既定30）
5. 出力先ディレクトリが存在しない場合は作成する
6. `axis`列の値は文字列`"dd"` / `"day_of_week"` / `"is_x_day"`で統一し、`outcome`列は`"diff"` / `"plus"` / `"hit104"`で統一する（後段のフィルタ・集計をしやすくするため）

## テスト

`ml/tests/test_machine_axis_pattern_scan.py` に以下を含める:

- スモークテスト: 少なくとも1ホールで例外なく実行が完了し、CSV4種が出力されること
- KW検定の単体テスト: 特定の`dd`値だけ`diff`が明らかに高い人工データで、`axis=dd, outcome=diff`の`effect_size`が高く出ることを確認
- カイ二乗検定の単体テスト: 特定の曜日だけ`hit104`率が明らかに高い人工データで、`axis=day_of_week, outcome=hit104`の`cramers_v`が高く出ることを確認
- `top_signals.csv`が`effect_size`降順でソートされ、`n_obs`が`min_obs_for_ranking`未満の行を含まないことの単体テスト
- `top_signal_breakdown.csv`が`top_signals`に含まれる(machine_name, axis)のみを含み、それ以外の機種・軸の水準別内訳を含まないことの単体テスト
- 現在設置フィルタ・`min_machine_days_total`フィルタで対象外になった機種が全出力から除外されることの単体テスト
