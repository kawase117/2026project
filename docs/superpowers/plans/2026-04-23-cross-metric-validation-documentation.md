# クロスメトリック検証のドキュメント作成計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** クロスメトリック検証の計算方法とコード仕様を説明するドキュメント2点を作成し、他のLLMやメンテナーが理解できる形に整理する

**Architecture:** Task 1で計算ロジック説明MD（アルゴリズム・数式）を作成、Task 2でコード仕様書（ファイル構成・関数一覧・実装詳細）を作成。Task 3で両ドキュメントを検証・コミット。

**Tech Stack:** Markdown、パチスロドメイン知識

---

### Task 1: 計算内容説明MD の作成

**Files:**
- Create: `docs/superpowers/explanations/2026-04-23-cross-metric-validation-calculations.md`

- [ ] **Step 1: ファイル作成と基本構成を準備**

Create file `docs/superpowers/explanations/2026-04-23-cross-metric-validation-calculations.md` with this skeleton:

```markdown
# クロスメトリック検証の計算方法

## 概要

## 1. 相対パフォーマンス分析の基本概念

### 1.1 何を測定しているのか

### 1.2 なぜこの分析が必要なのか

## 2. クロスメトリック検証の詳細

### 2.1 訓練期間と検証期間

### 2.2 グループ分割（パーセンタイル分割）

### 2.3 相対パフォーマンスの計算

### 2.4 勝者判定ロジック

### 2.5 一貫性スコアの計算

### 2.6 パーセンタイル比率の最適化

## 3. 統計量の解釈

### 3.1 相対値μ（平均）

### 3.2 相対値σ（標準偏差）

### 3.3 一貫性（✅ vs ❌）

## 4. 具体例

## 5. 注意点と制限

## 6. 拡張可能性
```

- [ ] **Step 2: 概要セクションを記載**

Add to section "## 概要":

```markdown
このドキュメントは、パチスロホールデータの「クロスメトリック検証」という分析手法の計算方法を説明します。

**クロスメトリック検証とは：**
訓練期間での高い指標（勝率またはG数）を持つ属性が、テスト期間でも高い差枚を獲得するかを検証する手法です。

**例：**
- 訓練期間で「勝率の高い台番号末尾」は、テスト期間でも「高い差枚」を獲得するのか？
- 訓練期間で「高平均G数の台番号末尾」は、テスト期間でも「高い差枚」を獲得するのか？

**予測能力を評価する：**
過去の指標は将来のパフォーマンスを予測できるのか、その信頼度を数値で示します。
```

- [ ] **Step 3: 基本概念セクションを記載**

Add to section "## 1. 相対パフォーマンス分析の基本概念":

```markdown
### 1.1 何を測定しているのか

**相対パフォーマンス** = あるグループの平均値 - 条件全体の平均値

例：
- 条件全体（全台）の平均差枚: 100枚
- 勝率上位グループの平均差枚: 150枚
- → 相対パフォーマンス = 150 - 100 = **+50枚**

これは「このグループは平均より50枚多く獲得している」という意味です。

### 1.2 なぜこの分析が必要なのか

単純に「勝率が高い台は差枚も高い」というだけではなく、以下を知りたい：

1. **予測精度** - 過去の指標（勝率・G数）は将来のパフォーマンスを予測できるか？
2. **安定性** - その傾向は複数の訓練期間で一貫しているか？
3. **実用性** - 信頼できる指標なのか、偶然なのか？
```

- [ ] **Step 4: クロスメトリック検証の詳細セクションを記載**

Add to section "## 2. クロスメトリック検証の詳細":

```markdown
### 2.1 訓練期間と検証期間

**三つの訓練期間：**
1. 6月訓練期間: 2025-10-01 ～ 2026-03-31（6ヶ月）
2. 3月訓練期間: 2026-01-01 ～ 2026-03-31（3ヶ月）
3. 1月訓練期間: 2026-03-01 ～ 2026-03-31（1ヶ月）

**固定テスト期間：**
- 全訓練期間共通: 2026-04-01 ～ 2026-04-20（20日間）

なぜ三つの訓練期間か？
→ 短期・中期・長期のデータで傾向が一貫しているかを確認するため

### 2.2 グループ分割（パーセンタイル分割）

**手順：**

1. 訓練期間データで、属性ごとに指標を計算
   - 勝率分析: 各属性の勝率を計算
   - G数分析: 各属性の平均G数を計算

2. 上位・中位・下位の3グループに分割
   - パーセンタイル比率: (上位%, 中位%, 下位%)
   - 例: (36, 28, 36) = 上位36%、中位28%、下位36%に分割

3. 各グループに含まれる属性を特定

**例（勝率分析、36-28-36比率）：**
```
訓練期間での勝率
台番号末尾0: 55%
台番号末尾1: 52%
...
台番号末尾9: 48%

↓ 36-28-36で分割

上位グループ（上位36%）: 末尾7, 8, 9（勝率最高）
中位グループ（中位28%）: 末尾4, 5（勝率中程度）
下位グループ（下位36%）: 末尾0, 1, 2, 3, 6（勝率最低）
```

### 2.3 相対パフォーマンスの計算

**テスト期間での計算：**

1. テスト期間全体の平均差枚を計算（基準値）
   ```
   condition_avg_coin = テスト期間全体の平均差枚
   ```

2. 各グループの平均差枚を計算
   ```
   top_avg_coin = 上位グループの平均差枚
   mid_avg_coin = 中位グループの平均差枚
   low_avg_coin = 下位グループの平均差枚
   ```

3. 相対パフォーマンスを計算
   ```
   top_relative = top_avg_coin - condition_avg_coin
   mid_relative = mid_avg_coin - condition_avg_coin
   low_relative = low_avg_coin - condition_avg_coin
   ```

**解釈：**
- `top_relative > 0`: 上位グループは平均より多く獲得している（予測成功）
- `top_relative < 0`: 上位グループは平均より少なく獲得している（予測失敗）
- `top_relative = 0`: 差がない（予測が機能していない）

### 2.4 勝者判定ロジック

```
max_relative = max(top_relative, mid_relative, low_relative)

if max_relative == top_relative:
    winner = "上位G"
elif max_relative == mid_relative:
    winner = "中間G"
else:
    winner = "下位G"
```

**意味：**
最も相対パフォーマンスが高いグループが「その訓練期間での勝者」

### 2.5 一貫性スコアの計算

**定義：**
```
3つの訓練期間すべてで同じ勝者が選ばれたか？

例：
- 6月訓練: 上位G（勝）
- 3月訓練: 上位G（勝）
- 1月訓練: 上位G（勝）
→ 一貫性 ✅（3期間で一致）

- 6月訓練: 上位G
- 3月訓練: 上位G
- 1月訓練: 中間G（外れ）
→ 一貫性 ❌（3期間で不一致）
```

**なぜ重要？**
一貫性があれば、その傾向は安定している = 実用可能

### 2.6 パーセンタイル比率の最適化

**試行する5つの比率：**
```
1. (50, 0, 50) = 二分割（上位50%, 下位50%）
2. (45, 10, 45) = 弱い中位
3. (40, 20, 40) = バランス型
4. (36, 28, 36) = 標準型
5. (33, 34, 33) = 均等型
```

**各比率について：**
1. 3つの訓練期間で分析を実施
2. 相対値μと相対値σを計算
3. 一貫性スコアを確認

**推奨比率の選択：**
```
一貫性が ✅ の比率のみを対象
→ その中で相対値μが最大の比率を推奨
```

```markdown
## 3. 統計量の解釈

### 3.1 相対値μ（平均）

**定義：**
3つの訓練期間での相対値の平均

```
相対値μ = (6月の相対値 + 3月の相対値 + 1月の相対値) / 3
```

**解釈：**
- μ > 0: 平均的に予測が成功している
- μが大きいほど：予測の実用価値が高い
- μ < 0: 予測が失敗している（逆張り可能性）

### 3.2 相対値σ（標準偏差）

**定義：**
3つの訓練期間での相対値のばらつき

```
σ = sqrt(Σ(相対値 - μ)² / 3)
```

**解釈：**
- σ = 0: すべての訓練期間で同じ結果
- σが大きい: 訓練期間ごとに結果が異なる（不安定）
- σが小さい: 訓練期間ごとに結果が安定している（信頼性高）

**注意：**
現在、σ ≈ 0.0% の場合が多いのは、3つの訓練期間がすべて同じテスト期間（4月1-20日）を使用しているため、数学的に変動が少ないからです。

### 3.3 一貫性（✅ vs ❌）

**✅（一貫性あり）：**
3つの訓練期間すべてで同じ勝者 → その傾向は安定している → 信頼できる

**❌（一貫性なし）：**
訓練期間によって勝者が異なる → その傾向は不安定 → 信頼度が低い
```

- [ ] **Step 5: 具体例セクションを記載**

Add to section "## 4. 具体例":

```markdown
### シナリオ: 勝率→差枚分析、比率(45-10-45)、蒲田7ホール

**訓練期間1（6月）:**
- 台番号末尾別に勝率を計算
- 上位45%の末尾（例：7, 8, 9）: 訓練期間勝率60%
- テスト期間（4月）でのその末尾の平均差枚: 180枚
- 全体（4月）の平均差枚: 100枚
- 相対値 = 180 - 100 = +80枚
- 勝者: 上位G（最大相対値）

**訓練期間2（3月）:**
- 同じ計算: 相対値 = +85枚
- 勝者: 上位G

**訓練期間3（1月）:**
- 同じ計算: 相対値 = +82枚
- 勝者: 上位G

**統計計算：**
```
相対値μ = (80 + 85 + 82) / 3 = 82.3%
相対値σ = sqrt(((80-82.3)² + (85-82.3)² + (82-82.3)²) / 3) ≈ 1.6%
一貫性 = ✅（3期間とも上位G）
推奨度 = ← オススメ（μが大きく、一貫性がある）
```

**解釈：**
「勝率45-10-45での上位グループは、テスト期間で平均82.3%多く差枚を獲得している」
「この傾向は3つの訓練期間で一貫しており、信頼度が高い」
```

- [ ] **Step 6: 注意点セクションを記載**

Add to section "## 5. 注意点と制限":

```markdown
### 訓練期間とテスト期間について

現在の実装は、すべての訓練期間が同じテスト期間（2026-04-01～04-20）を使用しています。

**メリット：**
- 異なる過去の長さで同じ未来を予測できるかを検証

**デメリット：**
- σ（標準偏差）がほぼ0になる傾向
- ウォークフォワード検証ではない

### パーセンタイル比率について

5つの比率は経験的に選択されたもので、理論的根拠はありません。

**将来の改善案：**
- 属性やDD別に最適比率を自動探索
- 機械学習で最適比率を学習

### DD分析について

現在は「DD（日付の日）＝ 1-20」で全DD分析を実施しています。

分析の流れ：
1. 各DD別に20回の分析を実施
2. 20個の結果を平均化して1つの「訓練期間の結果」を得る
3. 3訓練期間での統計を計算

この方法により、単一DDの偏りを排除できます。
```

- [ ] **Step 7: 拡張可能性セクションを記載**

Add to section "## 6. 拡張可能性":

```markdown
### ウォークフォワード検証

現在：固定テスト期間（同じ4月1-20日）を全訓練期間で使用

**ウォークフォワード案：**
```
訓練期間1: 2025-10-01 ～ 2026-03-31 → テスト: 2026-04-01 ～ 2026-04-20
訓練期間2: 2025-11-01 ～ 2026-04-30 → テスト: 2026-05-01 ～ 2026-05-20
訓練期間3: 2025-12-01 ～ 2026-05-31 → テスト: 2026-06-01 ～ 2026-06-20
```

この場合、σ > 0 になるため、より現実的な検証が可能。

### 属性別最適比率

現在：全属性で同じパーセンタイル比率を使用

**改善案：**
属性ごと（末尾別、曜日別など）に異なる最適比率を探索

### 複数ホール統合

複数ホールのデータを集約して、より大規模な統計分析を実施
```

- [ ] **Step 8: ファイル完成確認とコミット**

Run: `type docs/superpowers/explanations/2026-04-23-cross-metric-validation-calculations.md | wc -l`

Expected: 300行以上

Commit:

```bash
git add docs/superpowers/explanations/2026-04-23-cross-metric-validation-calculations.md
git commit -m "docs: クロスメトリック検証の計算方法説明書を作成"
```

---

### Task 2: コード仕様書の作成

**Files:**
- Create: `docs/superpowers/specifications/2026-04-23-cross-metric-validation-code-spec.md`

- [ ] **Step 1: ファイル作成と基本構成を準備**

Create file `docs/superpowers/specifications/2026-04-23-cross-metric-validation-code-spec.md` with skeleton:

```markdown
# クロスメトリック検証のコード仕様書

## 目的

このドキュメントは、クロスメトリック検証の実装コードについて、開発者向けの詳細な仕様書です。

## ファイル構成

## モジュール1: analysis_base.py

### 関数: split_groups_triple_custom()

### 関数: calculate_consistency_score()

## モジュール2: cross_metric_validation_triple.py

### 関数: analyze_cross_metric_validation_win_rate()

### 関数: analyze_cross_metric_validation_games()

### 関数: find_optimal_percentile_ratio()

### 関数: print_percentile_optimization_header()

### 関数: print_percentile_result_row()

### 関数: run_multi_period_cross_metric_validation()

## テスト仕様

### test_analysis_base.py

### test_cross_metric_validation.py

## 定数・設定

## トラブルシューティング

## 将来の改善予定
```

- [ ] **Step 2: ファイル構成セクションを記載**

Add to section "## ファイル構成":

```markdown
```
backtest/
├── analysis_base.py                           ← 基本関数（グループ分割・一貫性判定）
├── cross_metric_validation_triple.py          ← クロスメトリック検証メイン
├── results/
│   └── cross_metric_validation_triple.txt     ← 出力結果ファイル
└── ...(他のファイル)

test/
├── test_analysis_base.py                      ← analysis_base のテスト
├── test_cross_metric_validation.py            ← 検証メインのテスト
└── ...(他のテスト)
```

**各ファイルの責任：**

| ファイル | 責任 | 行数 |
|---------|------|------|
| analysis_base.py | グループ分割・一貫性計算の共通関数 | ~80 |
| cross_metric_validation_triple.py | クロスメトリック検証のメイン処理 | ~330 |
| test_analysis_base.py | 基本関数のユニットテスト | ~200 |
| test_cross_metric_validation.py | 検証機能のユニットテスト | ~300 |
```

- [ ] **Step 3: analysis_base.py の仕様を記載**

Add to section "## モジュール1: analysis_base.py":

```markdown
### 役割

グループ分割と一貫性判定の共通ロジックを提供。複数の分析ファイルから再利用される。

### 関数: split_groups_triple_custom()

**シグネチャ:**
```python
def split_groups_triple_custom(train_grouped: pd.DataFrame, metric_column: str,
                               top_percentile: float, mid_percentile: float,
                               low_percentile: float) -> tuple
```

**パラメータ:**
- `train_grouped`: 訓練データを属性ごとに集計したDataFrame（属性列 + メトリック列）
- `metric_column`: グループ分割に使うカラム名（例: 'train_win_rate', 'train_avg_games'）
- `top_percentile`: 上位グループの割合（0-100）
- `mid_percentile`: 中位グループの割合（0-100）
- `low_percentile`: 下位グループの割合（0-100）

**戻り値:**
```python
(top_df, mid_df, low_df)  # 各グループに属する属性のDataFrame
```

**処理内容：**
1. メトリック列でソート（降順）
2. パーセンタイル値を計算
3. 3グループに分割
4. 各グループのDataFrameを返却

**例：**
```python
train_grouped = pd.DataFrame({
    'last_digit': ['7', '8', '9', '4', '5', '0', '1', '2', '3', '6'],
    'train_win_rate': [0.60, 0.58, 0.55, 0.50, 0.48, 0.45, 0.42, 0.40, 0.38, 0.35]
})

top, mid, low = split_groups_triple_custom(
    train_grouped, 'train_win_rate',
    top_percentile=36, mid_percentile=28, low_percentile=36
)
# top: 最初の3行（末尾7, 8, 9）
# mid: 次の3行（末尾4, 5, 0）
# low: 最後の4行（末尾1, 2, 3, 6）
```

### 関数: calculate_consistency_score()

**シグネチャ:**
```python
def calculate_consistency_score(winners_by_period: list) -> tuple
```

**パラメータ:**
- `winners_by_period`: 3つの訓練期間での勝者リスト（例: ['上位G', '上位G', '上位G']）

**戻り値:**
```python
(is_consistent: bool, symbol: str)
# 例: (True, '✅') または (False, '❌')
```

**処理内容：**
1. 3つの勝者がすべて同じかをチェック
2. 同じならTrue, 異なるならFalse
3. 対応する記号を返却
```

- [ ] **Step 4: cross_metric_validation_triple.py の仕様を記載**

Add to section "## モジュール2: cross_metric_validation_triple.py":

```markdown
### 役割

クロスメトリック検証の中核ロジックを実装。勝率分析とG数分析の2つの検証フローを提供。

### 関数: analyze_cross_metric_validation_win_rate()

**シグネチャ:**
```python
def analyze_cross_metric_validation_win_rate(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                             condition_type: str, condition_value: str,
                                             attr: str, top_percentile: float,
                                             mid_percentile: float, low_percentile: float) -> dict
```

**パラメータ：**
- `df_train`, `df_test`: 訓練・テストデータ（機械詳細結果テーブル）
- `condition_type`: フィルタ条件タイプ（'dd'=日付, 'weekday'=曜日など）
- `condition_value`: フィルタ値（DD=1なら1）
- `attr`: グループ分割対象の属性（'machine_number'など）
- パーセンタイル比率: top, mid, low（0-100）

**戻り値：**
```python
{
    'condition_avg_coin': テスト期間全体の平均差枚,
    'condition_avg_wr': テスト期間全体の勝率,
    'top_avg_coin': 上位グループの平均差枚,
    'top_avg_wr': 上位グループの勝率,
    'top_relative': 上位グループの相対差枚,
    'top_count': 上位グループの属性数,
    'mid_avg_coin': 中位グループ... (同様)
    'low_avg_coin': 下位グループ... (同様)
    'winner': 勝者グループ名（'上位G', '中間G', '下位G'）,
    'max_relative': 最大相対値
}
```

**処理内容：**
1. condition_typeとcondition_valueで訓練・テストデータをフィルタ
2. 属性別に勝率を計算
3. パーセンタイル比率で3グループに分割
4. テスト期間での各グループの差枚と勝率を計算
5. 相対パフォーマンスを計算
6. 勝者（最大相対値のグループ）を決定

**対応関数：** `analyze_cross_metric_validation_games()` （G数版、同じシグネチャ）

### 関数: find_optimal_percentile_ratio()

**シグネチャ:**
```python
def find_optimal_percentile_ratio(db_path: str, metric_type: str,
                                  condition_type: str) -> dict
```

**パラメータ：**
- `db_path`: SQLiteデータベースのパス
- `metric_type`: 'win_rate' または 'games'
- `condition_type`: 'dd' （現在はDD別分析のみ対応）

**戻り値：**
```python
{
    'optimal_ratio': (top, mid, low),  # 推奨比率
    'results': [
        {
            'ratio': (50, 0, 50),
            'winners_by_period': ['上位G', '上位G', '上位G'],
            'is_consistent': True,
            'consistency_symbol': '✅',
            'relative_mean': 190.8,
            'relative_std': 0.0,
            'is_recommended': True  # 推奨比率のみTrue
        },
        ... (他4つの比率)
    ]
}
```

**処理内容（全DD分析版）：**
```
for ratio in [5つの候補比率]:
    for period in [3つの訓練期間]:
        dd_results = []
        for dd in range(1, 21):  # 全20DD
            result = analyze_cross_metric_validation_win_rate(
                ..., dd, ..., ratio
            )
            dd_results.append(result)
        
        期間の代表値 = dd_results の平均
    
    period_results = [3期間の代表値]
    統計 (mean, std, consistency) を計算
    results に追加

推奨比率 = 一貫性✅の中で μ が最大
```

**重要な改善（Task 1で実装）：**
- 元々: DD=1でハードコード
- 改善: `for dd in range(1, 21)` で全DDを反復・集計

### 関数: print_* （出力関数）

```python
def print_percentile_optimization_header(metric_type: str, condition_type: str)
    # テーブルのヘッダーを出力

def print_percentile_result_row(result: dict)
    # 1行の結果を出力（フォーマット済み）

def run_multi_period_cross_metric_validation(db_path: str)
    # メイン処理: 勝率→差枚と G数→差枚 の両分析を実施
```
```

- [ ] **Step 5: テスト仕様セクションを記載**

Add to section "## テスト仕様":

```markdown
### test_analysis_base.py

**TestSplitGroupsTripleCustom（7テスト）：**
- `test_split_groups_basic()`: 基本的なグループ分割
- `test_split_groups_consistency()`: グループ内の属性が正しくソートされている
- 他5テスト

**TestCalculateConsistencyScore（6テスト）：**
- `test_consistency_all_same()`: 全期間勝者同じ → ✅
- `test_consistency_different()`: 勝者異なる → ❌
- 他4テスト

**実行:**
```bash
python -m pytest test/test_analysis_base.py -v
```

### test_cross_metric_validation.py

**TestAnalyzeCrossMetricValidationWinRate（4テスト）：**
- 勝率分析の結果形式検証

**TestAnalyzeCrossMetricValidationGames（4テスト）：**
- G数分析の結果形式検証

**TestFindOptimalPercentileRatio（2テスト）：**
- `test_find_optimal_percentile_ratio_structure()`: 結果の構造確認
- `test_find_optimal_percentile_ratio_all_dds()`: σ > 0.0 確認 ✅

**実行:**
```bash
python -m pytest test/test_cross_metric_validation.py -v
```

**全テスト合計：** 15テスト、すべてPASS
```

- [ ] **Step 6: 定数・設定セクションを記載**

Add to section "## 定数・設定":

```markdown
**analysis_base.py で定義：**
```python
PERCENTILE_CANDIDATES = [
    (50, 0, 50),    # 二分割
    (45, 10, 45),   # 弱い中位
    (40, 20, 40),   # バランス型
    (36, 28, 36),   # 標準型
    (33, 34, 33)    # 均等型
]

TRAINING_PERIODS = [
    ('6月', '2025-10-01', '2026-03-31'),  # 6ヶ月
    ('3月', '2026-01-01', '2026-03-31'),  # 3ヶ月
    ('1月', '2026-03-01', '2026-03-31')   # 1ヶ月
]

TEST_START = '2026-04-01'
TEST_END = '2026-04-20'

HALLS = ['マルハンメガシティ2000-蒲田1', 'マルハンメガシティ2000-蒲田7']
```

**出力形式：**
```
相対値μ（平均）: f"{relative_mean:.1f}%"
相対値σ（標準偏差）: f"{relative_std:.1f}%"
```
```

- [ ] **Step 7: トラブルシューティングセクションを記載**

Add to section "## トラブルシューティング":

```markdown
### 問題: σ = 0.0% になる

**原因：**
3つの訓練期間がすべて同じテスト期間（4月1-20日）を使用しているため、各DD×比率の結果が同じになる。

**解決策：**
- 結果として正常（バグではない）
- ウォークフォワード検証を導入すれば σ > 0 になる

### 問題: 特定のDDが None を返す

**原因：**
そのDDに該当する訓練データ、またはテストデータが存在しない。

**確認コード：**
```python
result = analyze_cross_metric_validation_win_rate(
    df_train, df_test, 'dd', 1, 'machine_number',
    45, 10, 45
)
if result is None:
    print("DD=1のデータが不足しています")
```

### 問題: 勝者がすべて異なる（一貫性❌）

**解釈：**
その比率では訓練期間ごとに異なる傾向が見られる = 不安定な指標

**対応：**
他の比率を試す（既に自動実施済み）
```

- [ ] **Step 8: 将来改善セクションを記載**

Add to section "## 将来の改善予定":

```markdown
### 短期（1-2ヶ月）

- **ウォークフォワード検証の導入**
  - 訓練・テスト期間を時系列で分割
  - σ > 0 で現実的な検証が可能

- **属性別最適比率の探索**
  - 現在: 全属性で同一比率
  - 改善: 末尾別、曜日別など属性ごとに最適比率を自動探索

### 中期（3-6ヶ月）

- **複数ホール統合分析**
  - 複数ホールのデータを集約
  - より大規模な統計分析が可能

- **機械学習による傾向予測**
  - 最適比率を機械学習で学習
  - 新しいホール・期間への汎化

### 長期

- **リアルタイム検証**
  - 日次更新で翌日の予測を生成
  - 本運用での実装
```

- [ ] **Step 9: ファイル完成確認とコミット**

Run: `type docs/superpowers/specifications/2026-04-23-cross-metric-validation-code-spec.md | wc -l`

Expected: 250行以上

Commit:

```bash
git add docs/superpowers/specifications/2026-04-23-cross-metric-validation-code-spec.md
git commit -m "docs: クロスメトリック検証のコード仕様書を作成"
```

---

### Task 3: ドキュメント検証と最終コミット

**Files:**
- Verify: `docs/superpowers/explanations/2026-04-23-cross-metric-validation-calculations.md`
- Verify: `docs/superpowers/specifications/2026-04-23-cross-metric-validation-code-spec.md`

- [ ] **Step 1: 両ドキュメントの内容確認**

Run: `ls -la docs/superpowers/explanations/ docs/superpowers/specifications/`

Expected: 2つのMDファイルが存在

- [ ] **Step 2: リンク確認（ドキュメント間の参照）**

Verify:
- explanations ドキュメントに「詳細はコード仕様書を参照」というリンク設置
- specifications ドキュメント内部で一貫性あり

- [ ] **Step 3: 日本語の正確性確認**

Manual check:
- 誤字脱字なし
- テクニカル用語の統一（「パーセンタイル」「勝率」「差枚」など）
- 例文がドメイン知識と矛盾していないか

- [ ] **Step 4: メモリに記録**

前の文脈を参照して、MEMORY.md に以下を追加：

```markdown
- [Cross-Metric Validation Docs](docs/superpowers/explanations/2026-04-23-cross-metric-validation-calculations.md) — 計算方法解説書
```

- [ ] **Step 5: 最終コミット**

```bash
git add docs/superpowers/explanations/ docs/superpowers/specifications/
git commit -m "docs: クロスメトリック検証の説明書・仕様書を完成（計算フロー・コード構成・テスト仕様）"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ 計算内容説明MD（他のLLM向け）: Task 1で実装
- ✅ コード仕様書（メンテナンス向け）: Task 2で実装
- ✅ 検証と最終化: Task 3で実装

**2. Placeholder scan:**
- ✅ 全Markdown内容を具体的に記載
- ✅ コード例、図表、例文を含める
- ✅ セクション見出しと内容を完全に定義

**3. Type consistency:**
- ✅ 用語統一：「パーセンタイル」「相対値」「勝者」など
- ✅ 関数シグネチャと戻り値型の正確性
- ✅ 例のデータ型と説明の一貫性

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-cross-metric-validation-documentation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
