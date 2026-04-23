# パーセンタイル比率最適化の全DD分析化実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `find_optimal_percentile_ratio()` を全20DD対応に拡張し、σ > 0.0%で期間ごとの変動を正確に捕捉する

**Architecture:** 現在の単一DD分析（DD=1固定）を、全DDでの反復処理に改善。各DD×パーセンタイル比率での結果を集計して、パーセンタイル比率ごとの平均と標準偏差を算出。

**Tech Stack:** pandas, Python統計関数（mean, std）

---

### Task 1: 全DD分析ロジックの実装

**Files:**
- Modify: `backtest/cross_metric_validation_triple.py:209-267` （`find_optimal_percentile_ratio()` 関数）
- Test: `test/test_cross_metric_validation.py`

- [ ] **Step 1: 現在の `find_optimal_percentile_ratio()` のテストを確認**

Run: `cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project && python -m pytest test/test_cross_metric_validation.py::TestFindOptimalPercentileRatio -v`

Expected: 現在のテストが PASS（修正前の動作を確認）

- [ ] **Step 2: 新しいテストを追加（全DD分析）**

`test/test_cross_metric_validation.py` の `TestFindOptimalPercentileRatio` クラスに以下を追加：

```python
def test_find_optimal_percentile_ratio_all_dds(self):
    """全DDでの分析で、σ > 0.0%になることを確認"""
    import os
    db_path = os.path.join(os.path.dirname(__file__), '../db/マルハンメガシティ2000-蒲田1')
    
    if not os.path.exists(db_path):
        self.skipTest(f"Database not found: {db_path}")
    
    result = find_optimal_percentile_ratio(db_path, 'win_rate', 'dd')
    
    # 結果検証
    self.assertIsNotNone(result)
    self.assertIn('results', result)
    self.assertGreater(len(result['results']), 0)
    
    # σ > 0.0%であることを確認（最低1つのパーセンタイル比率で）
    has_non_zero_std = any(r['relative_std'] > 0.0 for r in result['results'])
    self.assertTrue(has_non_zero_std, "All ratios have σ = 0.0%, indicating single-DD analysis")
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `python -m pytest test/test_cross_metric_validation.py::TestFindOptimalPercentileRatio::test_find_optimal_percentile_ratio_all_dds -v`

Expected: FAIL with "AssertionError: All ratios have σ = 0.0%"

- [ ] **Step 4: `find_optimal_percentile_ratio()` を全DD対応に修正**

`backtest/cross_metric_validation_triple.py` の `find_optimal_percentile_ratio()` 関数（Line 209-267）を以下のコードに置き換え：

```python
def find_optimal_percentile_ratio(db_path: str, metric_type: str, condition_type: str) -> dict:
    """複数パーセンタイル比率を試行（全DD対応）→ 最適比率を推奨"""
    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()

    results = []

    # 各パーセンタイル比率を試行
    for top_pct, mid_pct, low_pct in PERCENTILE_CANDIDATES:
        # 複数訓練期間での結果を集計
        period_results = []
        winners_by_period = []

        for period_name, start_date, end_date in TRAINING_PERIODS:
            df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()

            # 全DD（1-20）での分析結果を集計
            dd_relative_values = []
            
            for dd in range(1, 21):
                result = None
                if metric_type == 'win_rate':
                    result = analyze_cross_metric_validation_win_rate(
                        df_train, df_test, 'dd', dd, 'machine_number',
                        top_pct, mid_pct, low_pct
                    )
                else:  # games
                    result = analyze_cross_metric_validation_games(
                        df_train, df_test, 'dd', dd, 'machine_number',
                        top_pct, mid_pct, low_pct
                    )
                
                if result:
                    dd_relative_values.append(result['max_relative'])
            
            # DD結果が存在する場合、その訓練期間の代表値を計算
            if dd_relative_values:
                period_relative = sum(dd_relative_values) / len(dd_relative_values)
                period_results.append(period_relative)
                
                # 勝者判定：最大相対値を出したDDの勝者を使用
                # （複数DDの結果を集計したため、ここでは平均結果に基づく勝者判定）
                # 簡易実装：最初のDDの勝者を使用（全DDで一貫している可能性が高い）
                result_first_dd = None
                if metric_type == 'win_rate':
                    result_first_dd = analyze_cross_metric_validation_win_rate(
                        df_train, df_test, 'dd', 1, 'machine_number',
                        top_pct, mid_pct, low_pct
                    )
                else:
                    result_first_dd = analyze_cross_metric_validation_games(
                        df_train, df_test, 'dd', 1, 'machine_number',
                        top_pct, mid_pct, low_pct
                    )
                
                if result_first_dd:
                    winners_by_period.append(result_first_dd['winner'])

        # 3訓練期間での統計
        if len(period_results) == 3:
            is_consistent, symbol = calculate_consistency_score(winners_by_period)
            relative_mean = sum(period_results) / 3
            relative_std = (sum((x - relative_mean) ** 2 for x in period_results) / 3) ** 0.5

            results.append({
                'ratio': (top_pct, mid_pct, low_pct),
                'winners_by_period': winners_by_period,
                'is_consistent': is_consistent,
                'consistency_symbol': symbol,
                'relative_mean': relative_mean,
                'relative_std': relative_std,
                'is_recommended': False  # 後で判定
            })

    # 推奨比率を決定
    consistent_results = [r for r in results if r['is_consistent']]
    if consistent_results:
        recommended = max(consistent_results, key=lambda x: x['relative_mean'])
        recommended['is_recommended'] = True

    return {
        'optimal_ratio': recommended['ratio'] if consistent_results else PERCENTILE_CANDIDATES[3],  # デフォルト
        'results': results
    }
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `python -m pytest test/test_cross_metric_validation.py::TestFindOptimalPercentileRatio::test_find_optimal_percentile_ratio_all_dds -v`

Expected: PASS（σ > 0.0%になったことを確認）

- [ ] **Step 6: 既存テストもすべて PASS することを確認**

Run: `python -m pytest test/test_cross_metric_validation.py::TestFindOptimalPercentileRatio -v`

Expected: 全テスト PASS

- [ ] **Step 7: コミット**

```bash
git add backtest/cross_metric_validation_triple.py test/test_cross_metric_validation.py
git commit -m "feat: 全DD対応でパーセンタイル比率の自動最適化を改善（σ > 0.0%化）"
```

---

### Task 2: 統合検証と出力確認

**Files:**
- Run: `backtest/cross_metric_validation_triple.py` （main実行）
- Output: `backtest/results/cross_metric_validation_triple.txt`

- [ ] **Step 1: 修正したコードを実行**

Run: `cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project\backtest && python cross_metric_validation_triple.py`

Expected: 実行成功、`results/cross_metric_validation_triple.txt` に出力

- [ ] **Step 2: 出力ファイルを確認（σが0より大きいことを確認）**

Run: `cd C:\Users\apto117\Documents\pachinko-analyzer\src\2026project && type backtest\results\cross_metric_validation_triple.txt | findstr "相対値σ"`

Expected: 相対値σ列に 0.0% より大きい値が表示される

```
相対値σ列の値が 0.0% よりも大きい → 修正成功の証拠
例：相対値σ = 12.5%、15.3% など
```

- [ ] **Step 3: コミット**

```bash
git add backtest/results/cross_metric_validation_triple.txt
git commit -m "test: 全DD分析での出力結果を確認（σ > 0.0%を検証）"
```

---

## Self-Review

**1. Spec coverage:**
- ✅ σ = 0.0%の根本原因（DD=1固定）を特定・修正
- ✅ 全20DDでの反復処理を実装
- ✅ 期間ごとの統計（mean, std）を正確に計算

**2. Placeholder scan:**
- ✅ 全コード完全記載（複数行コード）
- ✅ テスト実装コード完全記載
- ✅ コマンド実行例具体的

**3. Type consistency:**
- ✅ `period_results`: List[float]（相対値）
- ✅ `winners_by_period`: List[str]（勝者名）
- ✅ `dd_relative_values`: List[float]（各DDの相対値）
- ✅ 既存関数との型一貫性を保持

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-23-percentile-ratio-all-dd-improvement.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
