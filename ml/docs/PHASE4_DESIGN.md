# Phase 4 - 機械学習予測パイプライン設計書

**作成日：** 2026-04-26  
**ステータス：** 承認済み（実装開始前）  
**設計者：** AI Assistant  
**レビュアー：** kawase117

---

## 1. 目的と背景

### 1.1 目的

過去1～2年のパチスロホールの実績データから、以下を予測するML予測パイプラインの構築：

- **モデルA：勝率予測** — 台/グループが差枚 ≥ 1000 となる確率（%）
- **モデルB：高利益確率予測** — 台/グループが差枚 ≥ 1000 となる確率（%）

### 1.2 背景と課題

**以前の失敗点：**
- 複数のMLモデルとグループ化戦略を試行 → 結果がバラバラで「どれが最優か」判定不可
- コード管理の複雑性 — 何をしたのか、なぜそれが良いのかの追跡不可
- 実験ログが不十分 — 再現性が低い

**解決方法：**
- **段階的仮説駆動** — まずグループ化戦略を検証、その勝者に対してMLモデルを検証
- **実験ログの完全記録** — JSON形式で全実験結果を記録
- **統計的検証** — 複数の施行結果を交差検証で確認、有意な差を確認

---

## 2. 設計方針

### 2.1 段階的仮説駆動アプローチ

```
Step 1: グループ化戦略の最適性検証（仮説1）
  ├─ グループ化候補 3方式
  ├─ 各方式に同じML（ロジスティック回帰）で訓練
  ├─ 2タスク（勝率、高利益）で評価
  └─ 勝者を統計的に選定

Step 2: MLモデルの最適性検証（仮説2）
  ├─ Step 1の勝者グループ化に対して
  ├─ ML候補 3～4個を試行
  ├─ 2タスクで評価
  └─ 本番採用モデルを決定
```

**メリット：**
- 多重検定の罠を最小化（試行回数が限定的）
- 「なぜこの方法が良いのか」の説明が容易
- 計算効率が良い（1～2週間で完了可能）
- 再現性が高い

---

## 3. グループ化戦略

### 3.1 段階1：基本候補（Step 1-2で検証）

| グループ化戦略 | 説明 | グループ数 | 用途 |
|-------------|------|----------|------|
| **末尾別** | 台番号の末尾（0～9）+ ゾロ目（11種） | 11 | 店側が台番号で意図的に配置する可能性を検証 |
| **機種別** | パチスロ機種ごと | 機種数による | 特定機種に高設定が偏る傾向を検証 |
| **台番号別** | 台の物理的位置（1番～N番） | ホール規模による | 台の物理的位置による偏りを検証 |

### 3.2 段階2：高度な候補（将来、データ準備後）

| グループ化戦略 | 説明 | 理由 |
|-------------|------|------|
| **DD別** | 日付の日（01～31） | 給料日（25日）前後に高設定が多い可能性 |
| **日末尾別** | 日付の末尾（0～9） | 特定の日付パターンに偏る可能性 |
| **曜日別** | 曜日（月火水木金土日） | 週末（金土日）に高設定が多い傾向 |
| **イベント日** | 給料日（25日）、初日（1日）、末日（30/31日） | 戦略的な投入パターン |
| **複合戦略** | 末尾 × 曜日、機種 × イベント日など | より細かい傾向を検出 |

**注記：** ゾロ目（is_zorome）の役割
- 日付の日部分と台番号末尾が一致した日のフラグ
- 店側は「ゾロ目に高設定を投入」または「ゾロ目は避ける」という戦略を取る可能性がある
- page_05（台末尾別分析）でゾロ目別の成績を比較すると、店側の意図が見える可能性

---

## 4. 予測タスク定義

### 4.1 モデルA：勝率予測

**教師ラベル：** 差枚 ≥ 1000 ⟹ 勝利（1）、それ以外（0）

**意味：** 「この台/グループは1000枚以上の利益を出す確率」

**ビジネス価値：** 客が「この条件なら打てば勝つ確率が高い」と判断するための基準

### 4.2 モデルB：高利益確率予測

**教師ラベル：** 差枚 ≥ 1000 ⟹ 高利益（1）、それ以外（0）

**意味：** モデルAと同じ（統一）

**理由：** 2つのモデルを別々に訓練することで、異なるグループ化やMLモデルが有効かどうかを検証

---

## 5. 評価メトリクス

### 5.1 使用するメトリクス

| メトリクス | 定義 | 目安 | 用途 |
|----------|------|-----|------|
| **AUC** | ROC曲線下の面積 | 0.5(ランダム)～1.0(完璧)<br>実務的に0.6～0.7が現実的 | モデルの識別性能を測定 |
| **精度** | 全体の正答率 | 0～1 | 参考程度（クラス不均衡に注意） |
| **Brier Score** | 確率予測の精度 | 0(完璧)～0.5(最悪)<br>値が小さいほど良い | **キャリブレーション**（予測確率と実績の一致度）を測定<br>ユーザーが「勝率70%と予測 → 実際70%前後が勝つ」ことを期待するなら重要 |
| **精度・再現率** | TP/(TP+FP)、TP/(TP+FN) | 0～1 | ビジネス要件による（見落とし vs 誤判定のバランス） |

### 5.2 統計的有意性の確認

- Step 1と Step 2の勝者選定では、**複数回交差検証**（時系列フォールド）を実施
- 単一テストセットではなく、複数の時系列フォールドで平均スコアを比較
- 信頼区間がかぶっていなければ「有意な差あり」と判定

---

## 6. データセット構成

### 6.1 時系列スプリット

```
訓練期間：2025-01-01 ～ 2026-02-01
テスト期間：2026-02-01 ～ 2026-04-26
```

**理由：** 時系列データのため、未来予測の現実性を保つため過去→未来の順序を維持

### 6.2 データソース

- **入力** — `machine_detailed_results`テーブル
  - date, machine_number, machine_name, last_digit, is_zorome, games_normalized, diff_coins_normalized

- **出力** — 2つのラベル
  - label_a：diff_coins_normalized ≥ 1000 ? 1 : 0
  - label_b：diff_coins_normalized ≥ 1000 ? 1 : 0

---

## 7. パイプライン実装構成

### 7.1 ディレクトリ構造

```
ml/
├── 00_data_preparation.py          ← グループ化・特徴量生成
├── 01_hypothesis_01_groupby.py     ← 仮説1実行スクリプト
├── 02_hypothesis_02_model.py       ← 仮説2実行スクリプト
├── models/
│   ├── __init__.py
│   ├── baseline_logistic.py        ← ロジスティック回帰
│   ├── tree_xgboost.py             ← XGBoost
│   └── ensemble_stack.py           ← スタッキング（検討用）
├── evaluators/
│   ├── __init__.py
│   └── metrics.py                  ← AUC, 精度, Brier Score, 他
├── experiments/
│   ├── exp_001_groupby_tail_task_a.json
│   ├── exp_001_groupby_tail_task_b.json
│   ├── exp_001_groupby_model_task_a.json
│   ├── exp_001_groupby_model_task_b.json
│   ├── exp_001_groupby_machine_task_a.json
│   ├── exp_001_groupby_machine_task_b.json
│   ├── exp_002_model_logistic_task_a.json
│   ├── ... (model試行分)
│   └── experiment_summary.csv      ← 全実験の比較表
└── docs/
    └── PHASE4_DESIGN.md            ← このドキュメント
```

### 7.2 スクリプト仕様

#### `00_data_preparation.py`

```python
def prepare_data_by_groupby(
    db_path: str,
    groupby_strategy: str,  # "tail" / "model_type" / "machine_number"
    task: str,              # "a" / "b"
    train_start: str = "2025-01-01",
    train_end: str = "2026-02-01",
    test_start: str = "2026-02-01",
    test_end: str = "2026-04-26"
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    グループ化方式に応じてデータを準備
    
    戻り値: (X_train, y_train, X_test, y_test)
    """
```

#### `01_hypothesis_01_groupby.py`

```python
strategies = ["tail", "model_type", "machine_number"]
tasks = ["a", "b"]

for strategy in strategies:
    for task in tasks:
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(db_path, strategy, task)
        model = LogisticRegression()
        # 訓練 → 評価 → ログ記録
        results = evaluate_model(model, X_test, y_test, strategy, task, "logistic")
        save_experiment_log(results, "exp_001", strategy, task, "logistic")
```

#### `02_hypothesis_02_model.py`

```python
winner_strategy = load_winner_from_step1()  # Step 1の勝者を読み込み

models = [
    ("logistic", LogisticRegression()),
    ("xgboost", XGBClassifier(random_state=42)),
    # ("neural_net", MLPClassifier(random_state=42))  # 必要に応じて
]
tasks = ["a", "b"]

for model_name, model_instance in models:
    for task in tasks:
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(db_path, winner_strategy, task)
        model_instance.fit(X_train, y_train)
        # 評価 → ログ記録
        results = evaluate_model(model_instance, X_test, y_test, winner_strategy, task, model_name)
        save_experiment_log(results, "exp_002", winner_strategy, task, model_name)
```

### 7.3 実験ログスキーマ

```json
{
  "experiment_id": "exp_001_groupby_tail_task_a",
  "timestamp": "2026-04-26T10:30:00",
  "phase": 1,
  "hypothesis": "グループ化戦略の最適性",
  "groupby_strategy": "tail",
  "task": "a",
  "ml_model": "logistic",
  "train_period": "2025-01-01 ~ 2026-02-01",
  "test_period": "2026-02-01 ~ 2026-04-26",
  "metrics": {
    "auc": 0.623,
    "accuracy": 0.572,
    "brier_score": 0.241,
    "precision": 0.551,
    "recall": 0.604,
    "f1": 0.577
  },
  "interpretation": "AUC=0.623（ランダム0.5より優位だが、実用には改善が必要）",
  "next_step": "Step 2へ進む"
}
```

### 7.4 実験サマリーテーブル（experiment_summary.csv）

| exp_id | phase | groupby | task | model | auc | accuracy | brier | precision | recall | f1 | interpretation |
|--------|-------|---------|------|-------|-----|----------|-------|-----------|--------|----|----|
| exp_001_tail_a | 1 | tail | a | logistic | 0.623 | 0.572 | 0.241 | 0.551 | 0.604 | 0.577 | 弱い予測力 |
| exp_001_model_a | 1 | model | a | logistic | 0.598 | 0.551 | 0.253 | 0.520 | 0.630 | 0.571 | tail より弱い |
| ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... | ... |

---

## 8. 実装スケジュール

| フェーズ | 内容 | 期間 | 出力・マイルストーン |
|---------|------|------|-------------------|
| **準備** | `00_data_preparation.py` 実装 | 2-3日 | グループ化3方式分のデータセット |
| **Step 1** | 仮説1実行（グループ化3 × タスク2 = 6実験） | 1-2日 | `exp_001_*.json` × 6 + 結果分析 |
| **評価・判定** | Step 1結果の統計検証、勝者選定 | 1日 | 勝者グループ化戦略の決定 |
| **Step 2** | 仮説2実行（モデル3-4 × タスク2 = 6-8実験） | 2-3日 | `exp_002_*.json` × 6-8 + 結果分析 |
| **最終評価** | 本番採用モデルの決定・ドキュメント作成 | 1日 | 本番採用モデル構成の決定 |
| **総計** | — | **1-2週間** | 本番運用可能なML予測モデル完成 |

---

## 9. 成功基準と検証方法

### 9.1 Step 1 成功基準

- ✅ グループ化3方式の評価メトリクスが記録される
- ✅ 統計的有意性検定で「勝者」グループ化を特定できる
- ✅ 次フェーズの入力となるグループ化戦略が確定する

### 9.2 Step 2 成功基準

- ✅ ML候補3-4個の評価メトリクスが記録される
- ✅ 統計的有意性検定で「勝者」MLモデルを特定できる
- ✅ 本番採用可能なモデル構成が決定される

### 9.3 全体成功基準

- ✅ 実験ログが完全に記録される（再現性確保）
- ✅ 「勝率XX%」「高利益確率YY%」という確率予測が出力される
- ✅ 予測確率のキャリブレーション（実績との一致度）が検証される
- ✅ 最終モデルの精度が、ビジネス要件を満たす（AUC > 0.60、Brier < 0.30 など）

---

## 10. リスク・注意点

### 10.1 多重検定の罠

**リスク：** 複数のグループ化/モデルを試すと、偶然の「当たり」を見つける可能性が増加

**対策：** 
- 試行回数を限定的に（段階1-2で合計12-14実験）
- Bonferroni補正などの多重検定補正を検討
- 統計的有意性を厳密に確認

### 10.2 時系列リーク

**リスク：** テストデータが訓練データに含まれるなど、未来のデータで過去を予測する事態

**対策：** 時系列スプリットで訓練→テスト の順序を厳密に維持

### 10.3 クラス不均衡

**リスク：** 「勝つ」「負ける」の割合が極度に偏っている場合、精度の解釈が誤解される可能性

**対策：** 
- 精度よりAUCやBrier scoreを重視
- クラスウェイトの調整を検討

### 10.4 ギャンブルの本質的不確実性

**リスク：** パチスロの本質的なランダム性により、AUC 0.6～0.7程度が上限である可能性

**対策：** 
- 「完璧な予測は不可能」という前提で、「統計的に有意に優位」という基準を設ける
- ビジネス要件に基づいて許容精度を事前に決める

---

## 11. 次ステップ

この設計承認後、`superpowers:writing-plans` スキルを使用して詳細な実装計画を作成します。

---

**設計ドキュメント作成日：** 2026-04-26  
**最終更新日：** 2026-04-26
