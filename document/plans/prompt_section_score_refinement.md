# Codex プロンプト: セクションスコアの改善（A系閾値 + DD/曜日補正）

## 背景

predict_section.pyの2段階パイプラインは蒲田7で有効（section_5x5で累積+545,700枚、勝率76.7%）だが、
詳細検証で2つの構造的問題が判明した:

1. **A系の104%閾値が不適切**
   - セクションスコア上位はN-only（AT機）セクションが独占（Top15にA系ゼロ）
   - Section score vs A-type ratio: rho=-0.636（A系セクションほどスコアが低い）
   - 原因: AT機は大当たり時の振れが大きく104%超え頻度が構造的に高い。A系（ジャグラー等）は設定6でも機械割107-109%で運用も低めのため、104%閾値ではA系の設定差を拾えない
   - A系には102%程度の閾値の方が適切な可能性がある

2. **DD/曜日パターンを捉えていない**
   - セクションスコアは90日全体の平均で、イベント日やDD固有のパターンを無視
   - DD-specificスコアを直接使うとサンプル不足（各DDは90日中3回程度）で精度低下
   - 90日平均をベースに補正項を加える方式が有望

## 固定前提（ユーザー確認済み）

- DB: `db/マルハンメガシティ2000-蒲田7.db`
- セクション定義: `ml/experiments/walkforward_scoring/config.py` の SECTION_RANGES_2F, SECTION_RANGES_3F
- フィルタ: `games_normalized >= 1500`、日付`0707`除外、台番号`2026`除外
- リーク防止: `date_dt < target_date` を厳密適用
- 評価期間: 60日walk-forward、window=90日
- A系判定: `scoring_model.classify_seg()` を使用（ジャグラー/ハナハナ等のキーワードマッチ）

## 実験A: A系閾値の最適化

### 目的
A系（ジャグラー/ハナハナ）の104%超え率ではなく、より低い閾値での超え率を使うことで、
A系セクションのスコアリング精度が改善するか検証する。

### 実装

```
ファイル: eda/section_threshold_optimization.py
```

1. hit_flagの計算をA/N別閾値で行う:
   ```python
   # 現行
   threshold = 104.0 for A, 106.0 for N
   # 候補
   thresholds_A = [100.0, 101.0, 102.0, 103.0, 104.0]
   thresholds_N = [104.0, 105.0, 106.0]  # N系も変えてみる
   ```

2. 各A閾値×N閾値の組み合わせで:
   - section_avg_hist を再計算
   - 60日walk-forwardでSpearman rho（section score vs actual section_hit_rate）を計算
   - Top5セクション×5台のhit_104率を計算（最終評価は104%で統一）

3. 出力:
   - 閾値の組み合わせ別のrhoとlift
   - A-onlyセクション限定のrhoとlift
   - 最適閾値の特定

### 注意
- 最終的な評価（パイプライン収支）は104%超え率で行う（閾値はスコア計算用であり、ターゲット自体は変えない）
- A/N判定は `classify_seg()` を使い、セクション内のA比率が100%のセクションをA-only、0%をN-onlyと分類

## 実験B: DD/曜日補正の追加

### 目的
90日全体の平均に、DD固有・曜日固有の補正項を加えることで、
イベント日やDD固有のセクション構造を捉える。

### 実装

```
ファイル: eda/section_dd_adjustment.py
```

1. セクションスコアの計算:
   ```
   adjusted_score = base_score + alpha * dd_adjustment + beta * dow_adjustment
   ```

   - `base_score`: 現行のsection_avg_hist（90日全体平均）
   - `dd_adjustment`: 過去90日のうちDD=target_ddの日だけで計算したセクション104%超え率 - base_score
   - `dow_adjustment`: 過去90日のうちDOW=target_dowの日だけで計算したセクション104%超え率 - base_score
   - alpha, betaはグリッドサーチ: [0.0, 0.1, 0.2, 0.3, 0.5]

2. dd_adjustmentとdow_adjustmentの計算（リーク防止）:
   ```python
   train_dd = train[train["dd"] == target_date.day]
   dd_section_rate = train_dd.groupby("section")["hit_flag"].mean()
   base_section_rate = train.groupby("section")["hit_flag"].mean()  # = section_avg_hist相当
   dd_adjustment = dd_section_rate - base_section_rate
   # NaN（そのDDにデータがないセクション）は0で埋める
   ```

3. サンプル不足のガード:
   - dd_adjustmentの計算に使える**distinct date**が3日未満のセクションはadjustment=0（行数ではなく日数基準）
   - dow_adjustmentも同様（distinct date 3日未満は0）
   - 全体のbase_scoreが計算不能（履歴なし）の場合はスキップ

4. 60日walk-forwardで評価:
   - 各alpha×betaの組み合わせでadjusted_scoreのSpearman rhoを計算
   - Top5セクション×5台のhit_104率を計算
   - alpha=0, beta=0（補正なし＝現行）をベースラインとする

5. イベント日 vs 非イベント日の分割評価:
   - EVENT_DDS = {1, 7, 11, 17, 21, 22, 27, 31}
   - イベント日のみ / 非イベント日のみ でrhoとliftを別々に報告

### リーク防止の明確化

全ての計算（base_score, dd_adjustment, dow_adjustment, hist_metric）は各foldの
`date_dt < target_date` かつ `date_dt >= target_date - window_days` のデータのみで行う。
target_date当日のデータは特徴量計算に一切使わない。
```python
train = data[(data["date_dt"] < target_date) & (data["date_dt"] >= target_date - pd.Timedelta(days=window_days))]
# base_score, dd_adjustment, dow_adjustment, hist_metric は全て train から計算
# actual = data[data["date_dt"] == target_date] は評価にのみ使用
```

## 実装順序

1. **まず実験A（閾値）+ 実験B（DD/曜日補正）+ Part 3（結合再評価）を実装・実行する**
2. 結果を報告する
3. **実験C/Dは結果を見てから実施判断する**（A/Bで十分な改善があれば不要）

---

## 実験C: DD/曜日別の過去実績ベーススコア（A/B完了後に実施判断）

### 目的
実験Bは「90日全体平均 + 補正項」だが、発想を変えて
「過去X回の同一DD（または同一曜日）のsection_avg_histだけで直接スコアリング」する。
90日全体平均とは別軸の実績として、DD固有・曜日固有のセクション強度を直接測る。

### 実装

```
ファイル: eda/section_dd_adjustment.py 内に実験Cとして追加
```

1. DD-onlyスコア:
   ```python
   # 過去90日のうちDD=target_ddの日だけを抽出
   train_dd = train[train["dd"] == target_date.day]
   # セクション内全台のhit_flagの平均 = DD限定section_avg_hist
   dd_only_score = train_dd.groupby("section")["hit_flag"].mean()
   ```

2. DOW-onlyスコア:
   ```python
   train_dow = train[train["dow"] == target_date.dayofweek]
   dow_only_score = train_dow.groupby("section")["hit_flag"].mean()
   ```

3. ブレンドスコア:
   ```
   blended = gamma * base_score + (1 - gamma) * dd_only_score
   ```
   gamma: [0.3, 0.5, 0.7, 1.0]（1.0 = 現行、0.3 = DD重視）

4. ガード:
   - DD-onlyのdistinct date が3日未満のセクションはdd_only_score = base_scoreで代替（fallback）
   - DOW-onlyも同様

5. 評価:
   - dd_only_score単体のSpearman rho
   - dow_only_score単体のSpearman rho
   - blendedの各gammaでのrhoとlift

## 実験D: 現行機種限定の90日平均（A/B完了後に実施判断）

### 目的
90日窓内に入替で消えた機種のデータが平均を歪めている可能性がある。
最新日（target_dateの前日またはroster_date）に存在する機種のみでsection_avg_histを計算し直す。

### 実装

```
ファイル: eda/section_dd_adjustment.py 内に実験Dとして追加
```

1. roster制限付きスコア:
   ```python
   # 最新日の台リスト
   latest_date = train["date_dt"].max()
   current_machines = train[train["date_dt"] == latest_date]["machine_number"].unique()
   # 90日窓のうち、現行機種のデータのみに限定
   train_current = train[train["machine_number"].isin(current_machines)]
   current_score = train_current.groupby("section")["hit_flag"].mean()
   ```

2. 比較:
   - 全台での90日平均（現行）vs 現行機種限定の90日平均
   - Spearman rhoの差
   - 90日未満の実績しか持たない機種が多いセクションでの影響を確認

3. 注意:
   - 現行機種限定にするとサンプルが減る。減少量をセクション別に報告する
   - 90日未満の機種は「参考記録」として扱い、3日以上のデータがある場合のみ含める

### 出力

既存のPart 1/2に加えて:

**Part 4: DD/DOW別実績ベーススコア**（report_dd_direct.md）
```
| score_type | rho | rho_event | rho_nonevent | lift_5x5 |
| base_only (現行) | ... | ... | ... | ... |
| dd_only | ... | ... | ... | ... |
| dow_only | ... | ... | ... | ... |
| blend_gamma_0.5 | ... | ... | ... | ... |
```

**Part 5: 現行機種限定**（report_current_machines.md）
```
| score_type | rho | n_machines_avg | sample_reduction_pct | lift_5x5 |
| all_machines (現行) | ... | ... | 0% | ... |
| current_machines | ... | ... | XX% | ... |
```

### 出力

**Part 1: 閾値最適化**（report_threshold.md）
```
| threshold_A | threshold_N | rho_all | rho_A_only | rho_N_only | lift_5x5 |
```

**Part 2: DD/曜日補正**（report_adjustment.md）
```
| alpha | beta | rho | rho_event | rho_nonevent | lift_5x5 | lift_5x5_event | lift_5x5_nonevent |
```

**Part 3: 最良組み合わせのパイプライン比較**（report_best.md）
- Part1の最適閾値 + Part2の最適alpha/betaを**結合した状態で60日walk-forwardを再実行**する
- 独立に選んだ最適値を単純合成するのではなく、結合パラメータでの再評価が必須
- 現行（A=104, N=106, alpha=0, beta=0）との台数揃え比較

### 注意
- DBデフォルトパスは `db/マルハンメガシティ2000-蒲田7.db`（`--db-path`引数で変更可能にする）
- `to_markdown()` は使わない。print文で出力する
- 出力先: `eda/results/section_score_refinement/`
- Part 1とPart 2は独立して実行可能にする（`--part 1` / `--part 2` / `--part 3`）
- Part 3はPart 1とPart 2の結果を読んで最良パラメータを使う
- 防御的ガード: dd/dowのサンプル3日未満は補正0、空セクションはNaN処理、qcutはduplicates="drop"

## 評価基準

- 固定閾値での成否判定は行わない
- 主指標: Spearman rho（現行+0.172〜+0.204との比較）
- 副指標: Top5×5台のhit_104率と**1台あたり平均差枚**
- A-onlyセクションでの改善を特に注視する（現行ではA系が構造的に不利）
- 過学習に注意: グリッドサーチの最適値が過剰にフィットしていないか、イベント日/非イベント日の分割で安定性を確認する

---

## 追加修正指示（2026-06-29）

### 修正1: 差枚はトータルではなく1台あたり平均で出す

全レポート（Part 1〜5）の `selected_diff_sum` を `selected_avg_diff`（1台あたり平均差枚）に変更する。
```python
# 変更前
selected_diff_sum = float(selected["diff_coins_normalized"].sum())
# 変更後
selected_avg_diff = float(selected["diff_coins_normalized"].mean())
```
レポートのカラム名も `selected_diff_sum` → `avg_diff_per_machine` に変更。

### 修正2: イベント日/非イベント日で別集計のsection_avg_histを追加

Part 4に以下のスコアタイプを追加する:

- `event_only_score`: 過去90日のうちイベント日（EVENT_DDS={1,7,11,17,21,22,27,31}）だけで計算したsection_avg_hist
- `nonevent_only_score`: 非イベント日だけで計算したsection_avg_hist
- `event_blend_gamma_X`: gamma * base_score + (1 - gamma) * event_only_score（イベント日に使用）
- `nonevent_blend_gamma_X`: gamma * base_score + (1 - gamma) * nonevent_only_score（非イベント日に使用）

評価時の使い分け:
```python
if target_date.day in EVENT_DDS:
    score = event_blend  # イベント日にはイベント日の実績ベースを使う
else:
    score = nonevent_blend  # 非イベント日には非イベント日の実績ベースを使う
```

これはDD別（31通り）ではなくイベント/非イベント（2通り）の分割なので、
各カテゴリのサンプルは90日中30-40日程度あり、DD別より遥かにサンプルが豊富。

ガード: イベント日/非イベント日のdistinct dateが5日未満のセクションはfallbackとしてbase_scoreを使う。

出力テーブルに追加:
```
| score_type | rho | rho_event | rho_nonevent | lift_5x5 | avg_diff_per_machine |
| event_only | ... | ... | ... | ... | ... |
| nonevent_only | ... | ... | ... | ... | ... |
| event_blend_0.5 | ... | ... | ... | ... | ... |
| adaptive (event日→event_blend, non-event日→nonevent_blend) | ... | ... | ... | ... | ... |
```

`adaptive` は「イベント日にはevent_blend、非イベント日にはnonevent_blend」を自動で切り替えるスコア。
これが最も有望な候補。
