# G数条件付き事後確率ソフトラベル（GMMベース）の生成と既存hit104ラベルとの分散比較

## 目的

差枚・機械割ベースの二値ラベル（`hit104`＝機械割104%超え）は、同じ+3000枚でも2000Gと8000Gで
設定を示唆する強さが全く違うという情報を捨てている。機種内で機械割の2成分ガウス混合モデル
（低設定群・高設定群）をEM推定し、各台日の「高設定群である事後確率」`p_high_setting`をソフト
ラベルとして生成する。モデル訓練は行わず、既存`hit104`ラベルとの分散比較のみを行い、ラベルの
ノイズが減っているかを安価に検証する。

背景・却下した代替案は `document/plans/2026-07-05-label-redesign-and-latent-grouping-plan.md` の
Phase A-1を参照。

## 背景データ・既存資産（必ず再利用する）

- `eda/core.py`
  - `load_hall_df(hall_name)` — 台レベル日次データ（`games`, `diff`, `machine_name`,
    `machine_number`, `dd`, `date`等）。`games_normalized < MIN_GAMES(400)`の台は既に除外済み
  - `HALL_DBS` — `"蒲田7"`, `"蒲田1"`, `"みとや"`のキーを使う
  - `compute_debut_features(df)` — 新台除外用の`days_since_debut` / `pre_existing`
- `eda/machine_name_significance_scan.py`
  - `_payout_rate(frame)` — `payout_rate = ((games*COINS_PER_GAME + diff) / (games*COINS_PER_GAME)) * 100`
    の計算式。**この式をそのまま再利用し、独自の機械割計算式を作らない**
  - `_prepare_frame(raw, *, shindai_exclude_days)` — `payout_rate`, `hit104`（104%超えの二値ラベル）,
    `plus`, `year_month`を付与する既存関数。**既存の`hit104`列をそのまま比較対象として使う**
  - `_apply_shindai_filter(frame, shindai_exclude_days)` — 新台除外
  - `DEFAULT_SHINDAI_EXCLUDE_DAYS = 30`
  - `COINS_PER_GAME` 定数

## 実装内容

新規ファイル: `ml/experiments/label_redesign/soft_label_gmm.py`

### Step 1: データ準備

1. 対象ホール（既定 `蒲田7,蒲田1,みとや`）ごとに `load_hall_df(hall)` →
   `_prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)` で
   `payout_rate` / `hit104` 付きフレームを作る
2. `machine_name`（機種）でグループ化する

### Step 2: 機種内GMM推定

1. **EM学習対象は `games >= MIN_GAMES_FOR_GMM_FIT`（既定2000）の台日のみに絞る**。
   sklearnの`GaussianMixture.fit()`は`sample_weight`を正式サポートしないため、重み付けではなく
   この下限フィルタで低G数（＝高分散）データの混入を防ぐ
2. 機種ごとの`payout_rate`（フィルタ後の値、1次元）に対し
   `sklearn.mixture.GaussianMixture(n_components=2, random_state=42)`をfitする。
   十分なサンプル数（既定 `MIN_MACHINE_DAYS_FOR_GMM`=100件）に満たない機種はスキップし、
   `note`列に理由を記録する
3. 2成分のうち平均`payout_rate`が高い方を「高設定群」と定義する
4. フィルタ後・フィルタ前を問わず全台日（`games >= MIN_GAMES(400)`、Step1でロードした全件）に
   ついて、学習済みGMMを使い`predict_proba`で「高設定群である事後確率」`p_high_setting`を計算する
   （低G数の台日も、学習済み分布への当てはめ自体は行う）

### Step 3: ラベル分散比較

1. `(dd, section, machine_digit)` のようなセルではなく、まずは既存資産のみで完結させるため
   `(hall, dd, machine_digit)` をセル単位とする（`section`列は`load_hall_df`に含まれないため、
   本スクリプトでは付与しない。Section込みの比較はPhase Bの成果物と合流後に行う）
2. セルごとに、日をまたいだ`hit104`の分散と`p_high_setting`の分散を計算し、両者を並べて出力する
3. `hit104`と`p_high_setting`のPearson相関・Spearman順位相関も全体で計算する

## 出力

`ml/experiments/label_redesign/results/{hall}_soft_label_comparison.csv`

列: `date, machine_name, machine_number, games, diff, payout_rate, hit104, p_high_setting,
gmm_fit_used(bool), note`

`ml/experiments/label_redesign/results/{hall}_cell_variance_comparison.csv`

列: `hall, dd, machine_digit, n_days, var_hit104, var_p_high_setting,
variance_reduced(bool)`

標準出力: ホールごとに `hit104` と `p_high_setting` の相関係数、および
`variance_reduced=True` のセル割合を表示する。

## 統計的妥当性・解釈の注意

- `variance_reduced`セルの割合が高いほど、ソフトラベルがノイズを減らせている根拠になる。
  ただし本スクリプトはモデル訓練を行わないため、これは「採用判断のための予備検証」であり、
  実際のwalk-forward性能改善を保証するものではない
- 機種内サンプル数が少ない機種（`MIN_MACHINE_DAYS_FOR_GMM`未満）はGMM推定自体が不安定になるため
  スキップする。スキップされた機種は「ラベル生成不可」として`note`列で明確に区別し、
  全体傾向の解釈から除外する

## 実装上の注意

1. 新規ファイルは `ml/experiments/label_redesign/soft_label_gmm.py` の1ファイルのみ。
   `eda/core.py`, `eda/machine_name_significance_scan.py` は変更しない
2. `_payout_rate`, `_prepare_frame`, `_apply_shindai_filter`, `COINS_PER_GAME`を必ずimportして
   再利用する。機械割計算・新台除外ロジックを独自に再実装しない
3. CLI引数: `--halls`（既定 `蒲田7,蒲田1,みとや`）、`--min-games-for-gmm-fit`（既定2000）、
   `--min-machine-days-for-gmm`（既定100）、`--shindai-exclude-days`（既定30）
4. 出力先ディレクトリ `ml/experiments/label_redesign/results/` が存在しない場合は作成する

## テスト

`ml/tests/test_soft_label_gmm.py` に以下を含める:

- スモークテスト: 少なくとも1ホールで例外なく実行が完了し、両方のCSVが出力されること
- GMM分離が明確なケースの単体テスト: 明確に二峰性を持つ人工`payout_rate`データ（低設定群平均97%、
  高設定群平均110%、それぞれ十分なサンプル数）を作り、高設定群に属するデータ点の`p_high_setting`が
  0.5超になることを確認する
- サンプル不足でスキップされるケースの単体テスト: `MIN_MACHINE_DAYS_FOR_GMM`未満の機種が
  スキップされ`note`に理由が記録されることの確認
- `games < min_games_for_gmm_fit`の台日がEM学習には使われないが、事後確率計算には含まれることの確認
  （フィルタ後のデータのみでfitしたGMMのpredict_probaを、フィルタ前の全データに適用しているかの確認）
