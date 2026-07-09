# machine_axis_pattern_scan.py の Cramér's V バイアス補正修正

## 問題

`eda/machine_axis_pattern_scan.py`の`_scan_binary_outcome`（`outcome=plus`/`hit104`のカイ二乗検定パス）が使っている`_cramers_v`（`eda/machine_name_significance_scan.py`から再利用）は**未補正のCramér's V**であり、水準数(`r`)が大きく異なる軸間で`effect_size >= 0.1`という固定閾値を比較すると不当な結果になることが実データで確認された。

### 実証済みの問題の大きさ

3ホール本番実行の`summary_report.csv`で、`axis=dd`（31水準）× `outcome=hit104`/`plus`の`pct_effect_ge_0_1`が69〜97%という異常値になった一方、`axis=is_x_day`（2水準）は2〜8%、`axis=day_of_week`（7水準）は16〜33%と、**水準数に応じて単調に上昇するパターン**になっていた。

さらに検証したところ：
- `dd×hit104`の`effect_size`と`log(n_obs)`の相関係数は**-0.89〜-0.92**（強い負の相関）。真のDD効果ならサンプル数と無関係なはずだが、サンプル数が少ない機種ほど効果量が大きく出ていた
- 帰無仮説（真の関連なし）のもとでの理論ノイズ下駄`sqrt(df/n_obs)`（`df=(r-1)(c-1)=30`, `c=2`の場合）を計算すると、`dd×hit104`行の57〜71%がこの理論値の1.2倍以内に収まっていた

原因は、`c=2`（二値アウトカム）の分割表で`min(r-1, c-1)=1`が常に成立するため、Cramér's Vの分母が水準数`r`の大小を反映しない一方、分子側の`chi2`は帰無仮説下でも期待値`df=(r-1)(c-1)`を持つため、`r`が大きい（`dd`=31水準）ほどノイズだけで`chi2`が大きくなり、結果として`V`が水増しされることにある。

## 修正内容

### 1. バイアス補正版Cramér's Vの追加

`eda/machine_name_significance_scan.py`に、既存の`_cramers_v`とは別の新しい関数`_cramers_v_bias_corrected(chi2, n_obs, n_rows, n_cols)`を追加する（**既存の`_cramers_v`は変更しない**。他2ファイル(`machine_name_significance_scan.py`自身の出力、`machine_volatility_event_gap_scan.py`)は既にレビュー・エクスポート済みの結果があるため、そちらのCramér's V計算には影響を与えない）。

Bergsma & Wicher (2013) のバイアス補正式を実装する:

```python
def _cramers_v_bias_corrected(chi2: float, n_obs: int, n_rows: int, n_cols: int) -> float:
    if n_obs <= 1 or n_rows <= 1 or n_cols <= 1:
        return float("nan")
    phi2 = chi2 / n_obs
    phi2_tilde = max(0.0, phi2 - (n_rows - 1) * (n_cols - 1) / (n_obs - 1))
    r_tilde = n_rows - (n_rows - 1) ** 2 / (n_obs - 1)
    c_tilde = n_cols - (n_cols - 1) ** 2 / (n_obs - 1)
    denom = min(r_tilde - 1, c_tilde - 1)
    if denom <= 0:
        return 0.0
    return float(np.sqrt(phi2_tilde / denom))
```

### 2. `machine_axis_pattern_scan.py`側の切り替え

`_scan_binary_outcome`内で`_cramers_v`ではなく`_cramers_v_bias_corrected`をimportして使うように変更する。`dd`/`day_of_week`/`is_x_day`の3軸すべてに一律で適用する（`day_of_week`も7水準あり、程度は小さいが同じバイアスの影響を受けるため）。

出力列名は変更しない（`effect_size`のままでよい）。ただし、計算方法が変わったことをコード内コメントで明記する。

### 3. `n_sparse_levels`列の命名修正（前回指摘の残タスク）

`PATTERN_SUMMARY_COLUMNS`/`TOP_SIGNALS_COLUMNS`の`n_sparse_levels`列について、Kruskal-Wallis（`outcome=diff`）側でのみ意味を持つ値のため、以下のいずれかで対応する:
- カイ二乗側（`outcome=plus`/`hit104`）の行では`n_sparse_levels`を`NaN`にする（実装コストが低い方を推奨）

### 4. 本番出力の再生成

修正後、`--halls 蒲田1,蒲田7,みとや`のデフォルト設定で`eda/results/machine_axis_pattern_scan/`に再出力する。既存の4種CSV（`{hall}_pattern_summary.csv`, `{hall}_top_signals.csv`, `{hall}_top_signal_breakdown.csv`, `summary_report.csv`）を上書きする。

## テスト

`ml/tests/test_machine_axis_pattern_scan.py`に以下を追加・更新する:

1. **バイアス補正の単体テスト**: `dd`相当の多水準軸（例: 20水準）で完全にランダムな（真の関連がない）人工データを生成し、`_cramers_v_bias_corrected`の値が未補正版`_cramers_v`より明確に小さく、理論上0に近いことを確認する
2. **真の信号が残ることの確認テスト**: 1つの水準だけ`hit104`率が明確に異なる人工データ（多水準軸、ただし信号を仕込む）で、`_cramers_v_bias_corrected`が0近辺ではなく、有意に大きい値になることを確認する（補正で信号まで消えていないことの確認）
3. 既存のテスト（`test_machine_axis_pattern_scan.py`内で`effect_size`の具体的な閾値を検証している箇所）は、補正後の値に合わせて期待値を更新する。既存テストが偶然通っていた場合は値を確認して修正する
4. `n_sparse_levels`が`outcome=plus`/`hit104`の行で`NaN`になっていることの単体テスト

## 実装上の注意

1. 変更対象は `eda/machine_name_significance_scan.py`（関数追加のみ、既存関数・既存出力は変更しない）と `eda/machine_axis_pattern_scan.py`（`_scan_binary_outcome`の切り替えと`n_sparse_levels`修正）の2ファイルに限定する
2. `eda/machine_volatility_event_gap_scan.py`は変更しない（この修正の対象範囲外。同スクリプトのCramér's Vは2水準（event/normal）の分割表のみを扱っており、今回発見したバイアスの影響は軽微なため、別途対応が必要になった場合は改めて指示する）
3. numpy(`np`)は`eda/machine_name_significance_scan.py`で既にimport済みのはず。未importなら追加する
