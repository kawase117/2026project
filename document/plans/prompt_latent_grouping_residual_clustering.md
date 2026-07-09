# 既知グループ効果除去後の残差相関クラスタリングによる潜在グループ発見

## 目的

Section・角番（kakuban）・末尾・列・機種という「人間が事前に決めた既知グループ」の効果を
機械割から除去した残差について、台×台の相関クラスタリングを行い、既知グループでは説明できない
潜在的な台のグループ構造（店の設定変更巡回順・什器の電源系統など、物理的には見えない構造）を
発見する。既知グループとの一致度をAdjusted Rand Index (ARI) で評価し、既知グループの言い換えに
なっていないかを検証する。

背景・却下した代替案は `document/plans/2026-07-05-label-redesign-and-latent-grouping-plan.md` の
Phase Bを参照。既存の`eda/kamata7_pair_corr_by_segment.py`（末尾軸限定・セグメント内に閉じた
ペア相関分析）とは目的・スコープが異なる別成果物として実装する（末尾軸に限定せず全台を対象に
横断的にクラスタリングする点、既知グループ効果を除去した残差を使う点が異なる）。

## 背景データ・既存資産（必ず再利用する）

- `eda/core.py`
  - `load_hall_df(hall_name)` — `machine_digit`（末尾）, `machine_number`, `games`, `diff`, `date`
- `eda/machine_name_significance_scan.py`
  - `_payout_rate(frame)`, `_prepare_frame(raw, *, shindai_exclude_days)` — 機械割計算・新台除外
- `eda/section_kakuban_axis_pattern_scan.py`
  - `_load_hall_layout_frame(hall, *, coords1, coords7_2f, coords7_3f, mitoya_db_path, mitoya_db_dir)`
    — 蒲田7・蒲田1・みとやの3ホール全てに対応した`machine_number, rank_from_min(角番), section`の
    取得関数。**この関数をそのままimportして再利用し、レイアウト取得ロジックを独自に再実装しない**
  - 呼び出しに必要な座標パス・DBパスの既定値は同ファイルの`build_parser()`のデフォルト値を確認して
    踏襲する

## 実装内容

新規ファイル: `ml/experiments/latent_grouping/residual_clustering.py`

### Step 1: データ準備・列（row）の付与

1. 対象ホール（既定 `蒲田7,蒲田1,みとや`）ごとに `load_hall_df(hall)` →
   `_prepare_frame(raw, shindai_exclude_days=DEFAULT_SHINDAI_EXCLUDE_DAYS)` で`payout_rate`付き
   フレームを作る
2. `_load_hall_layout_frame(...)`で`machine_number, rank_from_min(kakuban), section`を取得し、
   `machine_number`でマージする
3. **列（row）を新規に付与する**: `row_group = (machine_number // 10) * 10`
   （台番号の十の位ブロック。`document/instincts/2026-05-25-kamata7-weekday-investment-pattern.yaml`
   の「1列が例えば11〜20番」という実例に基づく定義。**座標は使わない**。Sectionは既存の
   `_load_hall_layout_frame`が返す座標由来の値をそのまま使う）
4. レイアウト情報（`section`, `kakuban`）が欠損している台はクラスタリング対象から除外し、
   除外件数をログ出力する

### Step 2: 既知グループ効果の除去（残差計算）

1. 固定効果回帰残差を計算する: `payout_rate ~ C(machine_name) + C(section) + C(kakuban) + C(machine_digit) + C(row_group)`
   （`statsmodels.formula.api.ols`を使用。カテゴリ数が多い列は`C()`で明示的にカテゴリ変数として扱う）
2. 頑健性チェックとして、同じ効果を「グループ内平均を逐次で引く」方式（機種平均を引く→その残差の
   Section平均を引く→…の順で`machine_name`→`section`→`kakuban`→`machine_digit`→`row_group`の順に
   逐次デミーニング）でも計算し、両者の残差の相関係数を出力する（0.9以上なら手法間で結果が
   大きく変わらないとみなし、以降は回帰残差を採用する）
3. 残差列名は`residual_payout_rate`とする

### Step 3: 台×台相関行列の構築

1. 台番号をインデックスとした`(machine_number, date) -> residual_payout_rate`のピボットテーブルを作る
2. 台ペアごとに、両台が共通して観測された日数（`common_days`）を計算する。
   **`common_days < 90` の台ペアは相関を計算せず`NaN`とする**
3. 有効なペアについてPearson相関係数を計算し、台×台の対称相関行列を作る

### Step 4: 階層クラスタリングとARI評価

1. 距離行列 `distance = 1 - corr` を計算する（`NaN`は最大距離として扱う、または該当ペアを
   クラスタリングの重み計算から除外する）
2. `scipy.cluster.hierarchy.linkage`（Ward法）でクラスタリングし、デンドログラムを保存する
3. シルエットスコアを`k=2..10`で計算し、最適なクラスタ数を決定する（`sklearn.metrics.silhouette_score`）
4. 決定したクラスタ数で`fcluster`によりクラスタIDを各台に付与する
5. 発見したクラスタと既知グループ（`section`, `kakuban`, `row_group`, `machine_digit`それぞれ）との
   Adjusted Rand Index (ARI) を`sklearn.metrics.adjusted_rand_score`で計算する

## 出力

`ml/experiments/latent_grouping/results/{hall}_residual_corr_clusters.csv`

列: `machine_number, machine_name, section, kakuban, machine_digit, row_group, cluster_id`

`ml/experiments/latent_grouping/results/{hall}_cluster_ari_report.md`

内容: 各既知グループ軸（section/kakuban/row_group/machine_digit）とのARI、選択したクラスタ数、
シルエットスコアの推移、頑健性チェック（回帰残差 vs 逐次デミーニング残差の相関係数）、
ARIが低い（既知グループと乖離した）クラスタについて、そのクラスタに属する台の`section`・`kakuban`・
`row_group`・`machine_digit`の内訳表（新しい構造の解釈材料）

## 統計的妥当性・解釈の注意

- ARIが高い（既知グループとほぼ一致する）場合、そのクラスタリングは「知っていたことの再発見」に
  過ぎない。この場合は「潜在グループなし、既知グループで説明が尽きている」という結論として記録し、
  無理に新しい解釈を作らない
- ARIが低いクラスタが見つかった場合のみ、そのクラスタの物理的・機種的特徴を人間が確認する
  次のステップに進む。本スクリプト自体はその解釈までは行わない（内訳表の出力に留める）
- `common_days < 90`で除外されたペアが多いホール（観測期間が短い、または台の入れ替わりが多い
  ホール）では、クラスタリングの信頼性が低下する。除外ペア数・除外率を`_cluster_ari_report.md`に
  必ず明記する

## 実装上の注意

1. 新規ファイルは `ml/experiments/latent_grouping/residual_clustering.py` の1ファイルのみ。
   `eda/core.py`, `eda/machine_name_significance_scan.py`, `eda/section_kakuban_axis_pattern_scan.py`
   は変更しない
2. `_load_hall_layout_frame`, `_prepare_frame`を必ずimportして再利用する。レイアウト取得・
   機械割計算ロジックを独自に再実装しない
3. CLI引数: `--halls`（既定 `蒲田7,蒲田1,みとや`）、`--min-common-days`（既定90）、
   `--shindai-exclude-days`（既定30）、`--k-range`（既定 `2,10`、シルエットスコア探索範囲）
4. 出力先ディレクトリ `ml/experiments/latent_grouping/results/` が存在しない場合は作成する

## テスト

`ml/tests/test_residual_clustering.py` に以下を含める:

- スモークテスト: 少なくとも1ホールで例外なく実行が完了し、CSVとレポートが出力されること
- 既知グループ効果除去の単体テスト: 機種・Section・角番・末尾・列それぞれに人工的な効果を
  加えた合成データを作り、固定効果回帰後の残差からこれらの効果が消えている（残差と各既知グループの
  相関がほぼ0）ことを確認する
- 頑健性チェックの単体テスト: 回帰残差と逐次デミーニング残差が、上記合成データで高い相関
  （0.9以上）になることを確認する
- `common_days < min_common_days`の台ペアが相関計算から除外されることの単体テスト
- 既知グループと完全一致するクラスタを人工的に作った場合、ARIが1.0に近い値になることの単体テスト
- 既知グループと無関係なランダムクラスタの場合、ARIが0に近い値になることの単体テスト
