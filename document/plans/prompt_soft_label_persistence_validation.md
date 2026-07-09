# p_high_settingの予測的妥当性検証（翌日実績への持続性比較）

## 目的

Phase A-1で生成した`p_high_setting`（GMMソフトラベル）は`hit104`（機械割104%超えの二値ラベル）と
Pearson r=0.71〜0.72・Spearman ρ=0.66〜0.67で相関しているが、これは「同じ`payout_rate`から
派生した2つの変換関数を比較しているだけ」という数学的必然の側面が強く、一致していない約50%が
「有益な追加信号」か「GMMの機種別キャリブレーションのブレによる余計なノイズ」かはこの相関係数
だけでは判別できない。

これを判別するため、**今日のラベル（`hit104` または `p_high_setting`）が、同一台の翌営業日の
実績をどれだけ予測できるか**を比較する。同じ入力変数から派生した値同士の相関ではなく、
「未来の独立した観測」に対する予測力を比較することで、単なる数式的な言い換えではない
情報量の差を検証する。

背景は `document/plans/2026-07-05-label-redesign-and-latent-grouping-plan.md` および、
Fableとの相談・その後のPhase A-1/B実行結果の会話ログを参照。

## 背景データ・既存資産（必ず再利用する）

- `ml/experiments/label_redesign/results/{hall}_soft_label_comparison.csv`
  （Phase A-1で既に3ホール分生成済み。列: `date, machine_name, machine_number, games, diff,
  payout_rate, hit104, p_high_setting, gmm_fit_used, note`）。**このCSVをそのまま入力とし、
  `payout_rate`や`hit104`の再計算は行わない**
- `eda/core.py`の`lag_analysis`関数の設計思想（前日→翌日の連続性をshiftで見る手法）を参考にする。
  ただし`lag_analysis`は`group_col`単位（曜日・末尾等のカテゴリ集計値）の連続性を見るものであり、
  台個別の翌日実績予測ではないため、**直接の関数流用はしない。新規に台単位の実装を行う**

## 実装内容

新規ファイル: `ml/experiments/label_redesign/persistence_validation.py`

### Step 1: データ読み込みと翌日ペアの構築

1. `{hall}_soft_label_comparison.csv`をホールごとに読み込む
2. `machine_number`ごとに`date`昇順でソートする
3. **同一台の行の中で、実際の日付が暦上1日違い（`next_date - date == 1日`）である行ペアのみを
   「翌日ペア」として採用する**。`lag_analysis`のような単純な`shift(1)`（行の並び順だけで前後を
   決める）方式は、`games_normalized>=400`フィルタで欠測日がある場合に暦上の隣接日でないペアを
   誤って「前日→翌日」とみなしてしまうため、本スクリプトではこの簡易shift方式を採用しない。
   `pd.to_datetime`で日付差を明示的に計算し、1日違いのペアのみを残す
4. 翌日ペアのうち、当日側の`gmm_fit_used`が`False`（=`p_high_setting`が`NaN`）の行は除外する

### Step 2: 予測力の比較

各翌日ペアについて、「当日のラベル」→「翌日の実績」の対応関係を評価する。

1. **相関比較**: 当日の`hit104`（0/1）と当日の`p_high_setting`（連続値）それぞれについて、
   翌日の`payout_rate`（連続値、実績そのもの）とのPearson相関・Spearman順位相関を計算する
2. **AUC比較**: 翌日の`hit104`（0/1、正解ラベル）を予測対象とし、
   - 当日の`p_high_setting`をスコアとしたAUC
   - 当日の`hit104`（0/1をそのままスコアとして使う）のAUC
   の両方を`sklearn.metrics.roc_auc_score`で計算する
3. **有意性検証**: 2つのAUCの差について、ブートストラップ（同一の翌日ペア集合から復元抽出、
   既定1000回）による差のブートストラップ信頼区間（95%）を計算し、区間が0を跨がなければ
   「有意に差がある」と判定する

### Step 3: 集計粒度

1. ホール全体での比較に加え、`(dd, machine_digit)`セル単位でも同じ比較を行い、
   `p_high_setting`のAUCが`hit104`のAUCを上回るセルの割合を報告する
2. セルの最低サンプル数は`MIN_CELL_PAIRS`（既定30）とし、これ未満のセルは比較対象から除外し
   `note`に理由を残す

## 出力

`ml/experiments/label_redesign/results/{hall}_persistence_validation.csv`

列: `hall, n_next_day_pairs, corr_hit104_vs_next_payout, corr_p_high_setting_vs_next_payout,
auc_hit104_predicts_next_hit104, auc_p_high_setting_predicts_next_hit104,
auc_diff, auc_diff_ci_lo, auc_diff_ci_hi, auc_diff_significant(bool)`

`ml/experiments/label_redesign/results/{hall}_persistence_validation_by_cell.csv`

列: `hall, dd, machine_digit, n_pairs, auc_hit104, auc_p_high_setting, auc_diff, note`

標準出力: ホールごとに上記サマリーを表示し、3ホール通しての結論
（`p_high_setting`が`hit104`より有意に翌日実績を予測できているか）を最後にまとめて表示する。

## 統計的妥当性・解釈の注意

- `auc_diff_significant=True`かつ`auc_diff > 0`（`p_high_setting`の方が高い）の場合のみ、
  「ソフトラベルは差枚由来のノイズを超えた追加情報を持つ」と主張できる。
  `auc_diff`が0付近、または信頼区間が0を跨ぐ場合は「今回の検証では優位性を主張できない」と
  明確に記録し、無理に採用を推す結論にしない
- 翌日ペア数（`n_next_day_pairs`）が少ないホールでは検定力が低いため、件数を必ず併記する
- 本検証は「1日後」の予測力のみを見ている。据え置き（連続性）が2日以上続くかどうかの検証は
  スコープ外とし、必要であれば別途`lag`パラメータを変えた追加検証として扱う

## 実装上の注意

1. 新規ファイルは `ml/experiments/label_redesign/persistence_validation.py` の1ファイルのみ。
   既存の`ml/experiments/label_redesign/soft_label_gmm.py`, `eda/core.py`は変更しない
2. 入力CSVの読み込みのみを行い、DBへの再接続やpayout_rateの再計算はしない
3. CLI引数: `--halls`（既定 `蒲田7,蒲田1,みとや`）、`--input-dir`
   （既定 `ml/experiments/label_redesign/results`）、`--min-cell-pairs`（既定30）、
   `--n-bootstrap`（既定1000）、`--random-seed`（既定42、ブートストラップの再現性用）
4. 出力先ディレクトリは入力と同じ`ml/experiments/label_redesign/results/`とする

## テスト

`ml/tests/test_persistence_validation.py` に以下を含める:

- スモークテスト: 少なくとも1ホール分の実際のCSV（またはそれを模した合成データ）で例外なく
  実行が完了し、両方のCSVが出力されること
- 暦日連続性チェックの単体テスト: 同一台で日付が2日以上飛んでいる行ペアが「翌日ペア」として
  採用されないことを確認する
- AUC比較が正しく機能するケースの単体テスト: `p_high_setting`が翌日の`hit104`と完全に一致する
  人工データを作り、`auc_p_high_setting_predicts_next_hit104`が1.0に近い値になることを確認する
- `p_high_setting`が翌日実績と無関係なランダムノイズの人工データでは、AUCが0.5付近になることを
  確認する
- ブートストラップ信頼区間の単体テスト: 明確に差がある人工データでは信頼区間が0を跨がず
  `auc_diff_significant=True`になり、差がない人工データでは0を跨ぎ`False`になることを確認する
