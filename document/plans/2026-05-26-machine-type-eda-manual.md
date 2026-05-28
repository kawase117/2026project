# 機種別 EDA → ML 設計マニュアル

**作成日**: 2026-05-26  
**対象**: `ml/machine_type/` の改善サイクル  
**前提**: 末尾別EDAで確立した探索手法を機種別に転用する

---

## 1. なぜ EDA を先に行うか

末尾別では walk-forward → モデル比較を先行させ、EDA を後回しにした結果、
rolling特徴量が逆張り構造に引っかかっていること・有効lagがlag1/lag15であることを
数回の無駄な実験の後にしか発見できなかった。

機種別では同じ轍を踏まないために **EDA → instinct記録 → 特徴量設計書 → walk-forward**
の順序を守る。EDA が完了するまで walk-forward は走らせない。

```
DB
 └─ run_machine_type_eda.py
     └─ output/kamata7_only/*.csv
         └─ instinct-export
             └─ feature 設計書
                 └─ walk-forward
```

---

## 2. EDA スクリプトの新規作成

### ファイル配置

```
ml/machine_type/exploratory/
├── run_machine_type_eda.py      ← 本マニュアルに従って作成する
└── output/
    └── kamata7_only/            ← CSV出力先（蒲田七単体を明示指定）
```

### データロード設計

```python
# machine_detailed_results から機種別日次集計を作成する
q = """
SELECT
    mdr.date,
    mdr.machine_name,
    mm.jug_flag,
    mm.hana_flag,
    mm.bt_flag,
    COUNT(*)            AS n_machines,
    SUM(mdr.diff_coins_normalized)  AS total_diff,
    AVG(mdr.diff_coins_normalized)  AS avg_diff,
    AVG(mdr.games_normalized)       AS avg_games,
    SUM(CASE WHEN mdr.diff_coins_normalized > 0 THEN 1 ELSE 0 END)
        * 1.0 / COUNT(*) AS win_rate
FROM machine_detailed_results mdr
LEFT JOIN machine_master mm ON mdr.machine_name = mm.machine_name
GROUP BY mdr.date, mdr.machine_name
"""
```

**機種タイプ分類**（末尾EDAと共通のロジック）

```python
def classify_machine_type(jug_flag, hana_flag, bt_flag) -> str:
    if jug_flag == 1 or hana_flag == 1:
        return "A型"
    if bt_flag == 1:
        return "BT"
    return "AT系"
```

**実行コマンド（完成後）**

```powershell
cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project
python -m ml.machine_type.exploratory.run_machine_type_eda `
  --db-glob "db/マルハンメガシティ2000-蒲田7.db" `
  --output-dir "ml/machine_type/exploratory/output/kamata7_only"
```

> **注意**: `--db-glob "db/*.db"` は使わない。複数ホール混入でzscore=-22等の偽外れ値が発生する
> （instinct: anomaly-db-scope-must-be-single-hall）

---

## 3. 実施すべき分析 10 種

### 3-1. 基底差枚分布の確認（最初に必ずやる）

**目的**: クロスセクション正規化が必要かどうかをデータで確認する。

**出力**: `machine_type_base_diff.csv`

| カラム | 内容 |
|--------|------|
| machine_type | A型 / BT / AT系 |
| mean_diff | 平均差枚（全期間） |
| median_diff | 中央値差枚 |
| std_diff | 標準偏差（分散指標） |
| n_days | 日数 |

**確認観点**:
- machine_type間の `mean_diff` に構造的な差（>100枚）があれば **正規化が必須**
  （instinct: cross-sectional-normalization-for-machine-ranking）
- A型はバラツキが大きい（大当たり1回で差枚急変）→ std_diffで確認
- 絶対値で比較する場合と rank_pct で比較する場合で上下関係が逆転しないか確認

---

### 3-2. カイ二乗検定: 曜日 × 機種タイプ

**目的**: どの曜日にどの機種タイプが「top_1」に来やすいか、独立性を検定する。

**出力**: `chi_square_weekday_machine.csv`

```python
# ピボット: 行=曜日、列=machine_type、値=is_rank_1のカウント
ct = pd.crosstab(df["weekday"], df["machine_type"],
                 values=df["is_rank_1"], aggfunc="sum")
chi2, p, dof, expected = stats.chi2_contingency(ct)
```

**確認観点**:
- p < 0.05 なら曜日 × 機種タイプの相互作用が存在する
- 残差（observed - expected）が大きいセルに注目する
- 末尾EDAでは「土曜は末尾6が断然1位（307.8）」が有意だった
  → 機種別では「土曜はAT系」「火曜はA型」等の対応仮説を探す

**ML特徴量候補**: `is_saturday AND is_at_series` など

---

### 3-3. Kruskal-Wallis: 機種タイプ間の rank_pct 比較

**目的**: AT系 / A型 / BT の同日内 rank_pct（順位パーセンタイル）に有意差があるか。

**出力**: `kruskal_machine_type.csv`

```python
# rank_pct: 同日全機種内の相対順位（0=最良、1=最悪）
groups = [
    df[df["machine_type"] == t]["rank_pct"].dropna().values
    for t in ["AT系", "A型", "BT"]
]
stat, p = stats.kruskal(*groups)

# posthoc（有意なペア特定）
from itertools import combinations
for a, b in combinations(["AT系", "A型", "BT"], 2):
    _, p_pair = stats.mannwhitneyu(
        df[df["machine_type"]==a]["rank_pct"],
        df[df["machine_type"]==b]["rank_pct"],
    )
```

**確認観点**:
- p < 0.05 なら機種タイプ間に順位差が存在する
- 「AT系が構造的に上位を占める」ならランキングモデルに機種タイプダミーは強力なシグナル
- p ≥ 0.05 なら機種タイプより他の要因（曜日・lag）が支配的

---

### 3-4. ACF/PACF: 機種タイプ別の時系列構造

**目的**: 前回top_1だった機種が翌日もtop_1になりやすいか、有効lagを特定する。

**出力**: `acf_per_machine_type.csv`

末尾EDAの `acf_per_digit_report.csv` の機種版。

```python
for mtype, g in df.groupby("machine_type"):
    ts = g.set_index("date")["is_rank_1"].reindex(all_dates, fill_value=0)
    acf_vals = sm_acf(ts, nlags=30, fft=True, missing="drop")
    threshold = 2.0 / np.sqrt(len(ts))  # 有意水準
    sig_lags = [i for i, v in enumerate(acf_vals) if abs(v) > threshold and i > 0]
```

**確認観点**:
- 有意なlagが多い機種タイプ → ラグ特徴量が効く（順張りシグナル）
- 有意なlagが**負**の機種タイプ → 逆張り構造（前日高い→翌日低い）
  → instinct: rolling-feature-ceiling-for-antipatterned-halls
- lag7（1週間）lag28（4週間）に有意なピークがあれば週次・月次サイクルあり
- 末尾EDAでは末尾3だけACF有意lagが1件と特異的に少なかった
  → 機種タイプでも「ランダムな機種」が存在するかを確認する

---

### 3-5. ADF 定常性検定: 長期トレンドの有無

**目的**: 機種タイプ別 avg_diff に長期トレンドがあるかを確認する。

**出力**: `adf_machine_type.csv`

```python
for mtype, g in df.groupby("machine_type"):
    ts = g.set_index("date")["avg_diff"].dropna()
    adf_stat, p_val, *_ = sm_adfuller(ts)
    is_stationary = (p_val < 0.05)  # 定常 = True
```

**確認観点**:
- 非定常（p > 0.05）なら差分や相対値（rank_pct）特徴量を優先する
- 蒲田七は開業以来全体的に差枚が下落トレンド（instinct: rolling-window-masks-lows）
- 非定常確認後: 1次差分（diff(1)）で定常化できるか確認する

---

### 3-6. 機種タイプ × 曜日クロス集計

**目的**: 末尾EDAの `weekday_digit_cross_report.csv` の機種版。

**出力**: `weekday_machine_type_cross.csv`

| カラム | 内容 |
|--------|------|
| weekday | 曜日（月〜日） |
| machine_type | A型 / BT / AT系 |
| mean_diff | 平均差枚 |
| rank_pct_mean | 同日内順位パーセンタイルの平均 |
| n_days | 日数 |
| top1_rate | rank_1 になった割合 |

**確認観点**:
- 「土曜 × AT系」の top1_rate が他の組み合わせより突出しているか？
- 弱い組み合わせ（「月曜 × BT」等）を特定する
- 末尾EDAの曜日知見と整合するか確認する:
  - 土曜は末尾6が強い → AT系は末尾6の比率が高いため間接的に整合するはず

---

### 3-7. Lag 有効性スクリーニング（逆張り確認が最重要）

**目的**: rank_pct に対してどのlag長が最も予測力を持つかを確認する。
逆張り構造の有無を最初に判定する。

**出力**: `lag_screening_machine_type.csv`

| カラム | 内容 |
|--------|------|
| lag | lagの日数（1〜28） |
| cv_auc | 時系列5-fold LR評価のAUC |
| spearman_r | lag値とis_rank_1のスペアマン相関 |
| direction | positive / negative / near-zero |

```python
for lag in [1, 2, 3, 5, 7, 10, 14, 21, 28]:
    feat = f"lag{lag}_rank_pct"
    # spearman_r の符号で逆張りを判定
    r, p_val = stats.spearmanr(X[feat].dropna(), y.loc[X[feat].dropna().index])
    direction = "positive" if r > 0.02 else "negative" if r < -0.02 else "near-zero"
```

**確認観点**:
- `direction = "negative"` が多数のlag → 逆張り構造確定
  → 特徴量として `lag{N}_rank_pct` の符号を反転（`-lag`）して試す
  → または「lag前後の差分」を使う
- `direction = "positive"` → 末尾EDAと同じ順張り。lag1から開始
- 末尾EDAの教訓: **MI top1(lag7)とcv_auc top1(lag1)が一致しなかった**
  → 両方確認し、walk-forward の初期候補は cv_auc 基準で選ぶ

---

### 3-8. Mutual Information スクリーニング（LTR用）

**目的**: walk-forward の前に特徴量候補を事前スクリーニングする。

**出力**: `mi_machine_type_features.csv`

```python
from sklearn.feature_selection import mutual_info_classif

candidate_features = [
    "lag1_rank_pct",
    "lag7_rank_pct",
    "roll7_rank_pct",
    "prior_top1_rate",
    "weekday_prior_top1_rate",
    "machine_type_encoded",      # カテゴリ数値化
    "is_at_series",              # AT系フラグ
    "is_atype",                  # A型フラグ
]
mi = mutual_info_classif(X[candidate_features].fillna(0), y["is_rank_1"])
```

**確認観点**:
- MI > 0.01 の特徴量のみを walk-forward の初期候補に採用する
- MI ≈ 0 の特徴量は walk-forward に持ち込まない（計算コスト削減）
- **末尾EDAの教訓**: MI ≠ 予測力。MI は参考指標に留め、最終判定は cv_auc で行う

---

### 3-9. アノマリー日 × 機種タイプ応答

**目的**: Layer A（全台高設定）日に機種タイプ別の応答パターンを確認する。

**出力**: `machine_type_anomaly_response.csv`

```python
# anomaly_detection_report.csv の high anomaly 日で機種タイプ別rank_pctを確認
anomaly_dates = anomaly_df[anomaly_df["anomaly_direction"]=="high"]["date"]
normal_dates  = anomaly_df[anomaly_df["is_anomaly"]==0]["date"]

for mtype in ["AT系", "A型", "BT"]:
    sub = df[df["machine_type"]==mtype]
    anom_pct = sub[sub["date"].isin(anomaly_dates)]["rank_pct"].mean()
    norm_pct = sub[sub["date"].isin(normal_dates)]["rank_pct"].mean()
    change_pct = (norm_pct - anom_pct) / norm_pct  # rank_pctは低いほど良い
```

**確認観点**:
- 末尾EDAでは「末尾3はアノマリー日に通常日比+527%」という逆転があった
  → 機種別でも「通常最下位の機種がアノマリー日に突出する」パターンを探す
- **n=5件未満のアノマリーからパターンを導かない**（instinct: small-sample-pattern-skepticism）

---

### 3-10. 連続高順位状態の継続日数（生存時間分析）

**目的**: 機種タイプが「top_1連続」する典型的な継続日数を確認する。

**出力**: `machine_type_streak.csv`

```python
for mtype, g in df.groupby("machine_type"):
    g = g.sort_values("date")
    # ランが変わるたびにIDを付与
    g["streak_id"] = (g["is_rank_1"] != g["is_rank_1"].shift()).cumsum()
    streaks = g[g["is_rank_1"] == 1].groupby("streak_id").size()
```

**確認観点**:
- 1日で終わる割合が 80% 超 → 逆張り構造が強い（lag特徴量の符号に注意）
- 連続2日以上の割合が高い → lag1 の正の自己相関あり
- 機種タイプによって継続日数の分布が大きく異なる場合 → 機種タイプ別の lag 設計が必要

---

## 4. 分析結果の読み取りと ML 特徴量への変換

### 4-1. 判断マトリックス

| EDA結果 | 意味 | ML設計への影響 |
|---------|------|--------------|
| ACF lag1 > +2σ | 前日の状態が持続（順張り） | `lag1_rank_pct` を第一特徴量に採用 |
| ACF lag1 < -2σ | 逆張り構造 | `lag1_rank_pct` の符号反転か差分を試す |
| Kruskal p < 0.05 | 機種タイプ間に順位差あり | `machine_type` ダミーを特徴量に追加 |
| カイ二乗 p < 0.05 | 曜日 × 機種タイプの相互作用あり | `is_saturday_AND_at_series` 等の交差特徴量を設計 |
| ADF p > 0.05（非定常） | 長期トレンドあり | 絶対値より `rank_pct` 差分を優先 |
| MI(lag7) >> MI(lag1) | 週次サイクルが支配的 | `lag7_rank_pct` を必須特徴量に追加 |
| streak 1日率 > 80% | 逆張り構造 | rolling特徴量の天井を認識して期待値を下げる |

### 4-2. クロスセクション正規化の必要判断

```python
# 正規化が必要かの判断基準
base = df.groupby("machine_type")["avg_diff"].mean()
if base.max() - base.min() > 100:  # 機種タイプ間で構造差 100枚超
    # 全特徴量を以下3種で自動生成する（cross_cols タプルに追加）:
    # - {col}_vs_mean  : 同日平均との差
    # - {col}_zscore   : 同日標準偏差で正規化
    # - {col}_rank_pct : 同日内パーセンタイルランク
    cross_normalize = True
```

`add_machine_type_features()` の `cross_cols` タプルに対象カラムを追加するだけで自動生成される。

---

## 5. EDA 完了判定チェックリスト

以下がすべて完了するまで walk-forward を開始しない。

- [ ] `machine_type_base_diff.csv` — 機種タイプ間の構造差を確認済み
- [ ] `chi_square_weekday_machine.csv` — 曜日 × 機種タイプの独立性を確認済み
- [ ] `kruskal_machine_type.csv` — Kruskal検定で有意差を確認済み（posthoc含む）
- [ ] `acf_per_machine_type.csv` — 各機種タイプの有効 lag を特定済み
- [ ] `adf_machine_type.csv` — 定常性を確認済み
- [ ] `lag_screening_machine_type.csv` — **逆張り vs 順張りの方向を確認済み**（最重要）
- [ ] `weekday_machine_type_cross.csv` — 曜日 × 機種タイプのクロス集計完了
- [ ] `mi_machine_type_features.csv` — MI スクリーニング完了（MI > 0.01 候補を絞り込み済み）
- [ ] `machine_type_streak.csv` — 連続状態分析完了
- [ ] `machine_type_anomaly_response.csv` — アノマリー日応答確認済み
- [ ] **instinct YAML への記録完了**（`/instinct-export` で出力）

---

## 6. 末尾 EDA との主要な違い（注意点）

| 項目 | 末尾 EDA | 機種別 EDA |
|------|---------|----------|
| グループ数 | 10（末尾0-9）、固定 | 5〜20（新台入替で増減） |
| 構造的差異 | 機種タイプで末尾の意味が変わる | 機種タイプ自体に abs(diff) の構造差あり |
| 逆張り構造 | 比較的弱い（lag1が正） | **強い可能性あり**（要確認） |
| 有効 lag | lag1 + lag15（確認済み） | **未確定**（EDAで初めて確認） |
| アノマリー応答 | 末尾3が+527%の逆転（確認済み） | 機種別の逆転パターンは未確認 |
| 評価指標 | hit@2_mean（3専門家 × top2） | hit@1, hit@3, NDCG@3 |

---

## 7. EDA 後の walk-forward 設計書テンプレート

EDA完了後、以下に記入してから walk-forward に進む。

```markdown
## 機種別 ML v1 設計書（EDA 完了後に記入）

### 採用特徴量
- lag{N}_rank_pct       # lag_screeningで有効と判定した lag
- roll{M}_rank_pct      # ACFの有意窓幅を使う
- prior_top1_rate       # expanding 累積率（全期間）
- weekday_prior_top1_rate
- machine_type_dummy    # Kruskalで有意なら追加
- is_{weekday}_AND_{machine_type}  # カイ二乗で有意だった組み合わせ

### 採用しない特徴量とその理由
- avg_diff（絶対値）  : 機種間構造差 → クロスセクション正規化版を使う
- lag{K}_rank_pct     : MI≈0 かつ cv_auc≈0.5 だったため
- rank_trend_1m_vs_2m : Ablationで寄与ゼロ確認済み

### 評価指標
- 主: hit@1（rank_1 正答率）
- 副: hit@3, NDCG@3
- ベースライン（ランダム） = 1/N（N=機種数）
- 実用目標: hit@1 > 2/N かつ hit@3 > 3/N

### walk-forward 設定
- 最初は eval30 で設定比較
- eval60 は eval30 で +0.01 以上改善した設定のみ実行
  （instinct: batch-eval-time-management-checkpoints）
```

---

*参照 instinct:*  
`exploratory-analysis-before-ml-feature-design` /
`rolling-feature-ceiling-for-antipatterned-halls` /
`cross-sectional-normalization-for-machine-ranking` /
`anomaly-db-scope-must-be-single-hall` /
`small-sample-pattern-skepticism` /
`batch-eval-time-management-checkpoints`
