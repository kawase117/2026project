# 機種別ボラティリティ×イベント軸ギャップの全機種スキャン

## 目的

前段のクロスホール比較で、`東京喰種`が「`hit104_rate`は平均より高いが`bottom3_lift`も全ホール共通で最高」という**高ボラティリティ機種**であることが判明した（当たる日は大きく当たるが、外れる日は最下位に沈む）。これがDD/曜日のイベント軸（`is_x_day`/`is_weekend`/`is_any_event`）で説明できるか＝「イベント日に厚く投入し、通常日は極端に絞る」という投入格差仮説を検証したい。

東京喰種だけを個別に深掘りするのではなく、**全機種を対象にボラティリティを定量化し、ボラティリティが高い機種ほどイベント軸との相関（ギャップ）が大きいのかを一般化して検証する**。東京喰種はこのランキングの中の1台として自然に位置づけられる。

`回胴黙示録カイジ 狂宴`は現在ほぼ設置されていないためユーザー判断で検証対象外。個別に除外リストを作るのではなく、**「現在も設置されている機種か」を汎用フィルタとして実装**し、結果的にこの機種が自然に除外される設計にする（詳細は実装内容を参照）。

## 背景データ・既存資産（必ず再利用する）

- `eda/core.py`
  - `load_hall_df(hall_name)` — 既に `is_x_day` / `is_weekend` / `is_any_event` 列を持つ
  - `HALL_DBS`
- `eda/machine_name_significance_scan.py`（前段で実装済み）
  - `_prepare_frame(raw, shindai_exclude_days)` — `payout_rate`, `hit104`, `rank`, `n_active`, `top3_flag`, `bottom3_flag` を付与済みのフレームを返す。**このモジュールをimportして使う。同じロジックを再実装しない**
  - `_cramers_v(chi2, n_obs, n_rows, n_cols)` — 効果量計算。再利用する
  - `DEFAULT_MIN_ACTIVE_MACHINES` などの定数

`_prepare_frame`の出力は`load_hall_df`の全列（`is_x_day`等含む）を保持したまま列を追加する設計なので、`is_any_event`等はそのまま使える（列が失われていないか実装時に確認すること）。

## 実装内容

新規ファイル: `eda/machine_volatility_event_gap_scan.py`

### Step 1: ボラティリティスコアの計算（全機種）

1. `machine_name_significance_scan.load_hall_df` → `_prepare_frame` → `n_active >= min_active_machines` フィルタ、の順で前段と同じ前処理をホールごとに行う
2. **現在設置フィルタ**: ホールごとの最新日付を `hall_max_date` とし、機種ごとの最終出現日 `machine_last_date` を求める。`(hall_max_date - machine_last_date).days > CURRENTLY_INSTALLED_GRACE_DAYS`（既定30）の機種は「もう設置されていない」とみなし、**全ての出力から除外する**（ボラティリティランキング・イベントギャップ分析の両方から除外）。これにより`回胴黙示録カイジ 狂宴`のような機種は名指しせずに自然に除外される
3. `n_machine_days >= MIN_MACHINE_DAYS_VOLATILITY`（既定100。CVの推定を安定させるため前段の`min_machine_days`より高めに設定）を満たす機種のみ対象
4. 機種ごとに `volatility_score = payout_rate.std() / payout_rate.mean()`（変動係数）を計算する。**`diff`ではなく`payout_rate`を使う**（`diff`は0付近・負値を取り得るため変動係数が不安定になる。`payout_rate`は常に90〜120程度のレンジに収まるため安全）
5. ホールごとに`volatility_score`降順でランク付けする

### Step 2: イベント軸ギャップ分析（ボラティリティ上位機種のみ）

1. Step 1で`n_machine_days >= MIN_MACHINE_DAYS_VOLATILITY`を満たした機種のうち、**ホールごとにボラティリティ上位25%（または上位20機種、どちらか小さい方）** に絞って実施する（全機種×3軸×2指標のフル組み合わせは検定数が爆発するため、対象を事前に絞り込む）
2. 各対象機種について、`is_any_event`で machine-days を2群（event=1 / normal=0）に分割
   - `n_event_days`, `n_normal_days` を計算し、**両方が `MIN_GROUP_DAYS`（既定15）未満なら該当機種はスキップし、`note`に理由を記録**（結果テーブルには行を残すが検定値はNaN）
   - `hit104_rate_event`, `hit104_rate_normal`, `hit104_gap = event - normal`
   - `bottom3_rate_event`, `bottom3_rate_normal`, `bottom3_gap = normal - event`（投入格差仮説が正しければ正の値になるはず：通常日ほどbottom3に沈む）
   - 2×2分割表（event/normal × hit104フラグ、event/normal × bottom3フラグ）でカイ二乗検定、`_cramers_v`で効果量を計算。期待度数5未満のセルが20%を超える場合は`machine_name_significance_scan._chi2_summary`と同じ基準で警告を`note`に記録する（同じロジックをコピーしてよいが、可能なら`_chi2_summary`のセル比率計算部分を再利用する）
3. `is_x_day`（DD軸単独）、`is_weekend`（曜日軸単独）についても同じ処理を行い、`event_type`列で区別する（`is_any_event` / `is_x_day` / `is_weekend`の3パターンを同一機種に対して出力）

### Step 3: 集計・東京喰種の位置づけ確認

1. ホールごとに「ボラティリティ上位機種のうち、`is_any_event`のhit104_gapまたはbottom3_gapの効果量（Cramér's V）が0.1以上の機種の割合」を算出する（投入格差仮説がどの程度一般化するかの要約統計）
2. `東京喰種`の`volatility_score`順位と、3種類の`event_type`それぞれのgap・効果量を明示的に出力する（既存の仮説との整合性確認）
3. **多重比較の警告を出力に明記する**: ホールごとに20機種×3 event_type×2指標 = 最大120回程度の検定を行うため、個別のp値を「発見」として扱わない。効果量（Cramér's V）でのランキングを主指標とし、p値は参考情報として添える

## 出力

- `eda/results/machine_volatility_event_gap/{hall}_volatility_ranking.csv`
  列: `hall, machine_name, n_machine_days, days_since_last_seen, volatility_score, hit104_rate, bottom3_lift, volatility_rank`

- `eda/results/machine_volatility_event_gap/{hall}_event_gap.csv`
  列: `hall, machine_name, event_type(is_any_event/is_x_day/is_weekend), n_event_days, n_normal_days, hit104_rate_event, hit104_rate_normal, hit104_gap, hit104_chi2_p, hit104_cramers_v, bottom3_rate_event, bottom3_rate_normal, bottom3_gap, bottom3_chi2_p, bottom3_cramers_v, note`

- `eda/results/machine_volatility_event_gap/summary_report.csv`
  列: `hall, n_volatile_machines_tested, pct_with_cramers_v_over_0.1(hit104, is_any_event), pct_with_cramers_v_over_0.1(bottom3, is_any_event), tokyo_ghoul_volatility_rank, tokyo_ghoul_hit104_gap_any_event, tokyo_ghoul_bottom3_gap_any_event`
  （列名は実装時に機械的に生成してよいが、東京喰種の値を明示的に含めること。機種名の文字列は`"東京喰種"`で決め打ちせず、`eda/results/machine_name_significance/`の既存CSVから前段で確認した名称をそのまま使う）

- 標準出力: ホールごとに、ボラティリティ上位10機種のリストと、その中で`is_any_event`のgap効果量が大きい上位5機種

## 実装上の注意

1. 新規ファイルは `eda/machine_volatility_event_gap_scan.py` の1ファイルのみ。`eda/core.py`, `eda/machine_name_significance_scan.py` は変更しない
2. `machine_name_significance_scan._prepare_frame`, `_cramers_v` を必ずimportして再利用する。`payout_rate`/`hit104`/`bottom3_flag`等の計算ロジックを独自に再実装しない
3. CLI引数: `--halls`（既定 `蒲田1,蒲田7,みとや`）、`--currently-installed-grace-days`（既定30）、`--min-machine-days-volatility`（既定100）、`--min-group-days`（既定15、event/normal分割後の最小サンプル）、`--volatility-top-pct`（既定0.25）
4. 出力先ディレクトリが存在しない場合は作成する
5. `is_any_event = is_weekend OR is_x_day` という既存定義（`eda/core.py`）を変更しない。3つの`event_type`は排他的な新しい定義を作るのではなく、それぞれ独立した2群分割（`is_any_event`基準、`is_x_day`基準、`is_weekend`基準）として扱う
6. 「現在設置されているか」の判定は機種名の決め打きリストを作らない。`hall_max_date - machine_last_date`の日数比較のみで判定する

## テスト

`ml/tests/test_machine_volatility_event_gap_scan.py` に以下を含める:

- スモークテスト: 少なくとも1ホールで例外なく実行が完了し、CSV3種が出力されること
- 現在設置フィルタの単体テスト: 人工データで、ホール最終日から一定日数以上出現していない機種が`volatility_ranking.csv`・`event_gap.csv`の両方から除外されることを確認（`回胴黙示録カイジ 狂宴`のような「過去にあったが今はない」機種の除外パターンを想定した合成データで検証する。機種名をハードコードしたテストにはしない）
- `volatility_score`（変動係数）の単体テスト: `payout_rate`が一定の機種（CV=0）と大きくばらつく機種（CV>0）を人工データで作り、ランキング順が正しいことを確認
- `hit104_gap`/`bottom3_gap`の符号が人工データで期待通りになることの単体テスト（event日に明らかに高い`payout_rate`を持つよう仕込んだ機種で`hit104_gap>0`になることを確認）
- `n_event_days`または`n_normal_days`が`min_group_days`未満の機種がスキップされ`note`に理由が記録されることの単体テスト
