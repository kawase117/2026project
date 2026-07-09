# 機種×DDパターンの期間分割による再現性チェック

## 目的

`eda/machine_axis_pattern_scan.py`の`{hall}_top_signals.csv`で見つかった機種×DD（1〜31日）のパターン（例: スマスロ北斗の拳のDD1/DD11好調、クレアの秘宝伝のDD27好調）は、全期間データに対して1回だけ検定したin-sampleの結果であり、「たまたまこの期間のデータでそう見えただけ」なのか「繰り返し起きる法則」なのかを区別できていない。

データを前半・後半の2期間に分割し、**各機種のDD別成績ランキングが両期間で同じような形になっているか**（Spearman順位相関）を確認することで、この点を検証する。

## 背景データ・既存資産（必ず再利用する）

- `eda/core.py`
  - `load_hall_df(hall_name)` — `dd`列を持つ
  - `HALL_DBS`
- `eda/machine_name_significance_scan.py`
  - `_prepare_frame(raw, shindai_exclude_days)` — `payout_rate`, `hit104`, `plus`を付与
  - `DEFAULT_SHINDAI_EXCLUDE_DAYS`
- `eda/machine_volatility_event_gap_scan.py`
  - `_apply_currently_installed_filter(frame, grace_days)`
  - `DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS`
- `eda/machine_axis_pattern_scan.py`
  - 既存の`eda/results/machine_axis_pattern_scan/{hall}_top_signals.csv`（本セッションで既に本番生成済み）を**候補リストとして直接読み込む**。再検定はしない
- 設計思想の先行事例: `eda/cross_hall_pattern_verification.py`の`persistence()`関数（quintileのSpearman rho, 3ヶ月期間→次期間で持続性を評価する既存パターン）。今回はquintileではなくDD別の値そのものを2期間で相関させる点が異なるが、「期間を分けてSpearman相関で持続性を測る」という設計思想はこれを踏襲する

## 実装内容

新規ファイル: `eda/machine_dd_persistence_check.py`

### Step 1: 検証対象の読み込み

1. `eda/results/machine_axis_pattern_scan/{hall}_top_signals.csv`（3ホール分）を読み込み、`axis == "dd"` かつ `outcome in ("plus", "hit104")` の行のみを候補とする（`outcome == "diff"`はKruskal-Wallis側で全体的に効果量が低かったため対象外）
2. `(hall, machine_name, outcome)`の組み合わせで重複除去する

### Step 2: 期間分割

1. ホールごとに`load_hall_df(hall)` → `_prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)` → `_apply_currently_installed_filter(frame, grace_days=DEFAULT_CURRENTLY_INSTALLED_GRACE_DAYS)`で基礎フレームを作る
2. ホールの日付範囲（`date`の最小値〜最大値）の中央日を`split_date`とし、`date < split_date`を期間A、`date >= split_date`を期間Bとする（ホール単位でsplit_dateを1つ決める。機種ごとに変えない）
3. 候補機種ごとに`n_machine_days >= MIN_MACHINE_DAYS_FOR_SPLIT`（既定400。半分に割った後も1日あたり最低限のサンプルを確保するため、`machine_axis_pattern_scan.py`の`min_machine_days_total`(200)より高く設定する）を満たさない場合はスキップし、`note`に理由を記録する

### Step 3: DD別集計とSpearman相関

1. 期間A・期間Bそれぞれで、機種のdd別（1〜31）の値を集計する
   - `outcome=="plus"` → dd別の`plus_rate`（`diff>0`の比率）
   - `outcome=="hit104"` → dd別の`hit104_rate`
   - 各dd水準で`n >= MIN_CELL_N_FOR_SPLIT`（既定3）未満の場合はその水準を欠損（NaN）として扱う
2. 期間A・期間Bのdd別ベクトル（長さ31、NaN含む）についてSpearman順位相関（`scipy.stats.spearmanr`、NaNはペアワイズ除外）を計算する
3. 両期間で有効な水準数（NaNでない共通水準数）が`MIN_COMMON_LEVELS`（既定10）未満の場合は相関を計算せず、`note`に理由を記録する

## 出力

`eda/results/machine_axis_pattern_scan/persistence_check.csv`

列: `hall, machine_name, outcome, split_date, period_a_range, period_b_range, period_a_n, period_b_n, n_common_dd_levels, spearman_rho, spearman_p, note`

標準出力: ホールごとに`spearman_rho`降順で全候補を表示する（対象機種数が多くないため上位絞り込みは不要）。

## 統計的妥当性・解釈の注意

- **`spearman_rho`が高い（目安0.3〜0.5以上）ほど、DD別パターンが2期間で似た形になっている＝再現性がある可能性が高い**。ただし機種数が少ないため、rho自体の有意性(`spearman_p`)よりも実際の値の大小と`n_common_dd_levels`（十分な水準数で計算されているか）を併記して人間が判断できるようにする
- 前回発見した「サンプル数が少ない機種（`⚠`警告付き、n=220〜330程度）はスパースな分割表で効果量が水増しされやすい」という問題は、期間を2分割するとさらに悪化する（1水準あたりのサンプルがさらに半減する）。`MIN_MACHINE_DAYS_FOR_SPLIT=400`という閾値は、これらの過去に警告が出た機種の多くを自動的に除外することを意図している。除外された機種は「再現性なし」ではなく「検証不能」として扱い、`note`列で明確に区別する
- rhoが低い（0に近い、または負）機種は「in-sample検定で見えた法則性が、別期間では再現していない」ことを意味する。これは`top_signals.csv`のランキングから除外すべき強い根拠になる

## 実装上の注意

1. 新規ファイルは `eda/machine_dd_persistence_check.py` の1ファイルのみ。既存の4ファイル（`eda/core.py`, `eda/machine_name_significance_scan.py`, `eda/machine_volatility_event_gap_scan.py`, `eda/machine_axis_pattern_scan.py`）は変更しない
2. `_prepare_frame`, `_apply_currently_installed_filter`を必ずimportして再利用する。dd別集計・期間分割ロジック以外を独自に再実装しない
3. CLI引数: `--halls`（既定 `蒲田1,蒲田7,みとや`）、`--min-machine-days-for-split`（既定400）、`--min-cell-n-for-split`（既定3）、`--min-common-levels`（既定10）
4. 出力先ディレクトリ（`eda/results/machine_axis_pattern_scan/`、既存ディレクトリ）に`persistence_check.csv`を追加する形で書き込む。既存の4種CSVは上書きしない

## テスト

`ml/tests/test_machine_dd_persistence_check.py` に以下を含める:

- スモークテスト: 少なくとも1ホールで例外なく実行が完了し、`persistence_check.csv`が出力されること
- 再現性ありのケースの単体テスト: 期間A・期間Bで同じdd水準が同じ順位関係になる人工データを作り、`spearman_rho`が高い正の値（目安0.7以上）になることを確認する
- 再現性なしのケースの単体テスト: 期間Aと期間Bでdd別の順位関係が無関係（またはランダム）になる人工データを作り、`spearman_rho`が0に近い値になることを確認する
- `n_machine_days < min_machine_days_for_split`の機種がスキップされ`note`に理由が記録されることの単体テスト
- `n_common_dd_levels < min_common_levels`のときに相関を計算せず`note`に理由が記録されることの単体テスト
