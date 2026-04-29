# クロスメトリック検証（パーセンタイル比率自動最適化） 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 複数訓練指標（勝率・G数）からテスト期間の差枚獲得を予測し、パーセンタイル比率を自動最適化するシステムを実装

**Architecture:** analysis_base.py に比率動的指定の基盤関数を追加、cross_metric_validation_triple.py に勝率→差枚・G数→差枚の検証と比率自動最適化ロジックを実装。5つのパーセンタイル比率を試行し、複数訓練期間での勝者一貫性と相対値から最適比率を推奨。

**Tech Stack:** Pandas, SQLite, Streamlit（出力用）、TDD で実装進行

---

## Task 1: analysis_base.py 拡張 — パーセンタイル比率定義と動的グループ分割関数

**Files:**
- Modify: `backtest/analysis_base.py:187-210`

- [ ] **Step 1: PERCENTILE_CANDIDATES 定数を追加**

`analysis_base.py` の末尾に以下を追加：

```python
# ========== パーセンタイル比率の候補 ==========

PERCENTILE_CANDIDATES = [
    (50, 0, 50),    # 2分割相当：上位50%・下位50%
    (45, 10, 45),   # バランス型
    (40, 20, 40),   # 中間重視
    (36, 28, 36),   # 現在の設定
    (33, 34, 33),   # ほぼ均等
]
```

- [ ] **Step 2: split_groups_triple_custom() 関数を実装**

```python
def split_groups_triple_custom(train_grouped: pd.DataFrame, metric_column: str,
                               top_percentile: float, mid_percentile: float, low_percentile: float):
    """
    訓練期間データを3グループに分割（カスタム比率対応）
    
    パラメータ：
      top_percentile: 上位グループの割合（0-100）
      mid_percentile: 中間グループの割合（0-100）
      low_percentile: 下位グループの割合（0-100）
    
    戻り値: (top_group, mid_group, low_group)
    注：比率の合計が100になることを前提。呼び出し側で検証
    """
    if len(train_grouped) == 0:
        return None, None, None
    
    sorted_df = train_grouped.sort_values(metric_column).reset_index(drop=True)
    n = len(sorted_df)
    
    # パーセンタイル計算（インデックス位置）
    # 下位 low_percentile% の上限インデックス
    low_cutoff_idx = max(0, int(n * low_percentile / 100) - 1)
    # 上位 top_percentile% の下限インデックス
    top_cutoff_idx = min(n - 1, int(n * (low_percentile + mid_percentile) / 100))
    
    low_cutoff_val = sorted_df.iloc[low_cutoff_idx][metric_column]
    top_cutoff_val = sorted_df.iloc[top_cutoff_idx][metric_column]
    
    # 3グループに分割
    low_g = train_grouped[train_grouped[metric_column] <= low_cutoff_val]
    mid_g = train_grouped[(train_grouped[metric_column] > low_cutoff_val) &
                          (train_grouped[metric_column] <= top_cutoff_val)]
    top_g = train_grouped[train_grouped[metric_column] > top_cutoff_val]
    
    return top_g, mid_g, low_g
```

- [ ] **Step 3: split_groups_triple_custom() の単体テストを書く**

```bash
# test/test_analysis_base.py に追加

def test_split_groups_triple_custom_5050():
    """50-0-50 分割テスト"""
    df = pd.DataFrame({'id': range(100), 'value': range(100)})
    top, mid, low = split_groups_triple_custom(df, 'value', 50, 0, 50)
    
    assert len(top) == 50
    assert len(mid) == 0
    assert len(low) == 50

def test_split_groups_triple_custom_363636():
    """36-28-36 分割テスト"""
    df = pd.DataFrame({'id': range(100), 'value': range(100)})
    top, mid, low = split_groups_triple_custom(df, 'value', 36, 28, 36)
    
    assert len(top) == 36
    assert len(mid) == 28
    assert len(low) == 36
```

- [ ] **Step 4: コミット**

```bash
git add backtest/analysis_base.py test/test_analysis_base.py
git commit -m "feat: パーセンタイル比率動的指定の基盤関数を追加"
```

---

## Task 2: analysis_base.py 拡張 — 一貫性計算関数

**Files:**
- Modify: `backtest/analysis_base.py`

- [ ] **Step 1: calculate_consistency_score() 関数を実装**

```python
def calculate_consistency_score(winners_by_period: list) -> tuple:
    """
    複数訓練期間での勝者の一貫性をチェック
    
    パラメータ：
      winners_by_period: ['上位G', '上位G', '上位G'] など、各訓練期間での勝者リスト
    
    戻り値: (is_consistent, consistency_symbol)
      - is_consistent: bool — 3期間すべてで同じ勝者か
      - consistency_symbol: str — "✅" または "⚠️"
    """
    if not winners_by_period or len(winners_by_period) != 3:
        return False, "⚠️"
    
    first_winner = winners_by_period[0]
    is_consistent = all(w == first_winner for w in winners_by_period)
    
    return is_consistent, "✅" if is_consistent else "⚠️"
```

- [ ] **Step 2: calculate_consistency_score() のテストを書く**

```python
def test_calculate_consistency_score_consistent():
    """一貫性あり（全期間で上位G）"""
    winners = ['上位G', '上位G', '上位G']
    is_consistent, symbol = calculate_consistency_score(winners)
    
    assert is_consistent == True
    assert symbol == "✅"

def test_calculate_consistency_score_inconsistent():
    """一貫性なし"""
    winners = ['上位G', '中間G', '上位G']
    is_consistent, symbol = calculate_consistency_score(winners)
    
    assert is_consistent == False
    assert symbol == "⚠️"
```

- [ ] **Step 3: コミット**

```bash
git add backtest/analysis_base.py test/test_analysis_base.py
git commit -m "feat: 複数訓練期間での勝者一貫性計算関数を追加"
```

---

## Task 3: cross_metric_validation_triple.py 新規作成 — 勝率グループ分割検証

**Files:**
- Create: `backtest/cross_metric_validation_triple.py`

- [ ] **Step 1: ファイル基本構造を作成**

```python
"""クロスメトリック検証 - 勝率・G数グループ分割からテスト差枚を検証"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *


# ========== クロスメトリック検証関数（勝率→差枚） ==========

def analyze_cross_metric_validation_win_rate(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                             condition_type: str, condition_value: str, attr: str,
                                             top_percentile: float, mid_percentile: float, low_percentile: float) -> dict:
    """訓練勝率グループ分割 → テスト差枚+勝率を検証（カスタム比率対応）"""
    
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]
    
    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None
    
    # テスト期間での条件全体の平均差枚と勝率
    condition_avg_coin = test_filtered['diff_coins_normalized'].mean() if len(test_filtered) > 0 else 0
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered) if len(test_filtered) > 0 else 0
    
    # 訓練期間で属性別の勝率を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    train_grouped.columns = [attr, 'train_count', 'train_wins']
    train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']
    
    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None
    
    # カスタム比率でグループ分割
    top_wr, mid_wr, low_wr = split_groups_triple_custom(train_grouped, 'train_win_rate',
                                                         top_percentile, mid_percentile, low_percentile)
    
    if top_wr is None or mid_wr is None or low_wr is None:
        return None
    
    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean', 'count', lambda x: (x > 0).sum()]
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin', 'test_count', 'test_wins']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']
    
    # グループ別のテスト期間での平均差枚と勝率を計算
    def get_group_test_metrics(group_df):
        coins = []
        rates = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                coins.append(test_match.iloc[0]['test_avg_coin'])
                rates.append(test_match.iloc[0]['test_win_rate'])
        return coins, rates
    
    top_test_coins, top_test_rates = get_group_test_metrics(top_wr)
    mid_test_coins, mid_test_rates = get_group_test_metrics(mid_wr)
    low_test_coins, low_test_rates = get_group_test_metrics(low_wr)
    
    top_avg_coin = sum(top_test_coins) / len(top_test_coins) if top_test_coins else 0
    mid_avg_coin = sum(mid_test_coins) / len(mid_test_coins) if mid_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0
    
    top_avg_wr = sum(top_test_rates) / len(top_test_rates) if top_test_rates else 0
    mid_avg_wr = sum(mid_test_rates) / len(mid_test_rates) if mid_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0
    
    top_relative = top_avg_coin - condition_avg_coin
    mid_relative = mid_avg_coin - condition_avg_coin
    low_relative = low_avg_coin - condition_avg_coin
    
    # 最高値のグループを勝者とする
    max_relative = max(top_relative, mid_relative, low_relative)
    if max_relative == top_relative:
        winner = "上位G"
    elif max_relative == mid_relative:
        winner = "中間G"
    else:
        winner = "下位G"
    
    return {
        'condition_avg_coin': condition_avg_coin,
        'condition_avg_wr': condition_avg_wr,
        'top_avg_coin': top_avg_coin,
        'top_avg_wr': top_avg_wr,
        'top_relative': top_relative,
        'top_count': len(top_wr),
        'mid_avg_coin': mid_avg_coin,
        'mid_avg_wr': mid_avg_wr,
        'mid_relative': mid_relative,
        'mid_count': len(mid_wr),
        'low_avg_coin': low_avg_coin,
        'low_avg_wr': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_wr),
        'winner': winner,
        'max_relative': max_relative,
    }
```

- [ ] **Step 2: 単体テストを書く**

```bash
# test/test_cross_metric_validation.py を作成

def test_analyze_cross_metric_validation_win_rate():
    """勝率グループ分割→テスト差枚検証"""
    # モックデータを準備（省略）
    result = analyze_cross_metric_validation_win_rate(
        df_train, df_test, 'dd', 1, 'machine_number',
        top_percentile=50, mid_percentile=0, low_percentile=50
    )
    
    assert result is not None
    assert 'top_avg_coin' in result
    assert 'top_avg_wr' in result
    assert 'winner' in result
```

- [ ] **Step 3: コミット**

```bash
git add backtest/cross_metric_validation_triple.py test/test_cross_metric_validation.py
git commit -m "feat: 勝率グループ分割→テスト差枚+勝率検証関数を実装"
```

---

## Task 4: cross_metric_validation_triple.py — G数グループ分割検証

**Files:**
- Modify: `backtest/cross_metric_validation_triple.py`

- [ ] **Step 1: analyze_cross_metric_validation_games() 関数を実装**

```python
def analyze_cross_metric_validation_games(df_train: pd.DataFrame, df_test: pd.DataFrame,
                                          condition_type: str, condition_value: str, attr: str,
                                          top_percentile: float, mid_percentile: float, low_percentile: float) -> dict:
    """訓練G数グループ分割 → テスト差枚+勝率を検証（カスタム比率対応）"""
    
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]
    
    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None
    
    # テスト期間での条件全体の平均差枚と勝率
    condition_avg_coin = test_filtered['diff_coins_normalized'].mean() if len(test_filtered) > 0 else 0
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered) if len(test_filtered) > 0 else 0
    
    # 訓練期間で属性別のG数を計算
    train_grouped = train_filtered.groupby(attr).agg({
        'games_normalized': ['mean']
    }).reset_index()
    train_grouped.columns = [attr, 'train_avg_games']
    
    if len(train_grouped) < 3:  # 3グループに分割できない場合
        return None
    
    # カスタム比率でグループ分割
    top_games, mid_games, low_games = split_groups_triple_custom(train_grouped, 'train_avg_games',
                                                                  top_percentile, mid_percentile, low_percentile)
    
    if top_games is None or mid_games is None or low_games is None:
        return None
    
    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean', lambda x: (x > 0).sum()],
        'games_normalized': ['count']
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin', 'test_wins', 'test_count']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']
    
    # グループ別のテスト期間での平均差枚と勝率を計算
    def get_group_test_metrics(group_df):
        coins = []
        rates = []
        for _, row in group_df.iterrows():
            test_match = test_grouped[test_grouped[attr] == row[attr]]
            if len(test_match) > 0:
                coins.append(test_match.iloc[0]['test_avg_coin'])
                rates.append(test_match.iloc[0]['test_win_rate'])
        return coins, rates
    
    top_test_coins, top_test_rates = get_group_test_metrics(top_games)
    mid_test_coins, mid_test_rates = get_group_test_metrics(mid_games)
    low_test_coins, low_test_rates = get_group_test_metrics(low_games)
    
    top_avg_coin = sum(top_test_coins) / len(top_test_coins) if top_test_coins else 0
    mid_avg_coin = sum(mid_test_coins) / len(mid_test_coins) if mid_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0
    
    top_avg_wr = sum(top_test_rates) / len(top_test_rates) if top_test_rates else 0
    mid_avg_wr = sum(mid_test_rates) / len(mid_test_rates) if mid_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0
    
    top_relative = top_avg_coin - condition_avg_coin
    mid_relative = mid_avg_coin - condition_avg_coin
    low_relative = low_avg_coin - condition_avg_coin
    
    # 最高値のグループを勝者とする
    max_relative = max(top_relative, mid_relative, low_relative)
    if max_relative == top_relative:
        winner = "上位G"
    elif max_relative == mid_relative:
        winner = "中間G"
    else:
        winner = "下位G"
    
    return {
        'condition_avg_coin': condition_avg_coin,
        'condition_avg_wr': condition_avg_wr,
        'top_avg_coin': top_avg_coin,
        'top_avg_wr': top_avg_wr,
        'top_relative': top_relative,
        'top_count': len(top_games),
        'mid_avg_coin': mid_avg_coin,
        'mid_avg_wr': mid_avg_wr,
        'mid_relative': mid_relative,
        'mid_count': len(mid_games),
        'low_avg_coin': low_avg_coin,
        'low_avg_wr': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_games),
        'winner': winner,
        'max_relative': max_relative,
    }
```

- [ ] **Step 2: G数検証のテストを追加**

```python
def test_analyze_cross_metric_validation_games():
    """G数グループ分割→テスト差枚検証"""
    result = analyze_cross_metric_validation_games(
        df_train, df_test, 'dd', 1, 'machine_number',
        top_percentile=50, mid_percentile=0, low_percentile=50
    )
    
    assert result is not None
    assert 'top_avg_coin' in result
    assert 'top_avg_wr' in result
```

- [ ] **Step 3: コミット**

```bash
git add backtest/cross_metric_validation_triple.py test/test_cross_metric_validation.py
git commit -m "feat: G数グループ分割→テスト差枚+勝率検証関数を実装"
```

---

## Task 5: cross_metric_validation_triple.py — パーセンタイル比率自動最適化エンジン

**Files:**
- Modify: `backtest/cross_metric_validation_triple.py`

- [ ] **Step 1: find_optimal_percentile_ratio() 関数を実装**

```python
def find_optimal_percentile_ratio(db_path: str, metric_type: str, condition_type: str) -> dict:
    """
    複数パーセンタイル比率を試行 → 最適比率を推奨
    
    パラメータ：
      metric_type: 'win_rate' または 'games'
      condition_type: 'dd' または 'weekday'
    
    戻り値: {
        'optimal_ratio': (top, mid, low),
        'results': [  # 全比率の結果
            {
                'ratio': (50, 0, 50),
                'winners_by_period': ['上位G', '上位G', '上位G'],
                'is_consistent': True,
                'relative_mean': 11.5,
                'relative_std': 1.6,
                'is_recommended': True
            },
            ...
        ]
    }
    """
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
            
            # DD別・機械番号での単一分析例（実装では全属性×全条件を試行）
            result = None
            if metric_type == 'win_rate':
                result = analyze_cross_metric_validation_win_rate(
                    df_train, df_test, 'dd', 1, 'machine_number',
                    top_pct, mid_pct, low_pct
                )
            else:  # games
                result = analyze_cross_metric_validation_games(
                    df_train, df_test, 'dd', 1, 'machine_number',
                    top_pct, mid_pct, low_pct
                )
            
            if result:
                period_results.append(result['max_relative'])
                winners_by_period.append(result['winner'])
        
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
        'optimal_ratio': recommended['ratio'] if recommended else PERCENTILE_CANDIDATES[3],  # デフォルト
        'results': results
    }
```

- [ ] **Step 2: find_optimal_percentile_ratio() のテストを追加**

```python
def test_find_optimal_percentile_ratio():
    """比率最適化エンジン"""
    result = find_optimal_percentile_ratio(db_path, 'win_rate', 'dd')
    
    assert 'optimal_ratio' in result
    assert 'results' in result
    assert len(result['results']) == 5  # 5つの比率
    assert any(r['is_recommended'] for r in result['results'])  # 1つはオススメ
```

- [ ] **Step 3: コミット**

```bash
git add backtest/cross_metric_validation_triple.py test/test_cross_metric_validation.py
git commit -m "feat: パーセンタイル比率自動最適化エンジンを実装"
```

---

## Task 6: cross_metric_validation_triple.py — メイン実行関数と出力

**Files:**
- Modify: `backtest/cross_metric_validation_triple.py`

- [ ] **Step 1: メイン出力ヘッダー関数を実装**

```python
def print_percentile_optimization_header(metric_type: str, condition_type: str):
    """パーセンタイル比率最適化結果のヘッダー出力"""
    metric_name = '勝率→差枚' if metric_type == 'win_rate' else 'G数→差枚'
    condition_name = 'DD別' if condition_type == 'dd' else '曜日別'
    
    print(f"\n{'=' * 100}")
    print(f"パーセンタイル比率の自動最適化結果")
    print(f"（クロスメトリック検証：{metric_name}、{condition_name}分析、機械番号属性）")
    print(f"{'=' * 100}")
    print(f"{'比率':<15} {'勝者(6月)':<12} {'勝者(3月)':<12} {'勝者(1月)':<12} {'一貫性':<8} {'相対値μ':<10} {'相対値σ':<10} {'推奨':<10}")
    print(f"{'-' * 100}")

def print_percentile_result_row(result: dict):
    """パーセンタイル比率結果行の出力"""
    ratio_str = f"{result['ratio'][0]}-{result['ratio'][1]}-{result['ratio'][2]}"
    winners_str = " | ".join(result['winners_by_period'])
    recommended = "← オススメ" if result['is_recommended'] else ""
    
    print(f"{ratio_str:<15} {result['winners_by_period'][0]:<12} {result['winners_by_period'][1]:<12} "
          f"{result['winners_by_period'][2]:<12} {result['consistency_symbol']:<8} "
          f"{result['relative_mean']:>8.1f}% {result['relative_std']:>8.1f}% {recommended:<10}")
```

- [ ] **Step 2: メイン実行関数を実装**

```python
def run_multi_period_cross_metric_validation(db_path: str):
    """複数訓練期間でのクロスメトリック検証メイン実行"""
    
    print(f"\n相対パフォーマンス分析（クロスメトリック検証、複数訓練期間） (DB: {Path(db_path).stem})")
    
    # 勝率グループ分割の比率最適化
    print("\n【 訓練勝率グループ分割 → テスト差枚+勝率 】")
    win_rate_optimization = find_optimal_percentile_ratio(db_path, 'win_rate', 'dd')
    
    print_percentile_optimization_header('win_rate', 'dd')
    for result in win_rate_optimization['results']:
        print_percentile_result_row(result)
    
    # G数グループ分割の比率最適化
    print("\n【 訓練G数グループ分割 → テスト差枚+勝率 】")
    games_optimization = find_optimal_percentile_ratio(db_path, 'games', 'dd')
    
    print_percentile_optimization_header('games', 'dd')
    for result in games_optimization['results']:
        print_percentile_result_row(result)
    
    print(f"\n{'=' * 100}")
    print("クロスメトリック検証完了")
    print(f"{'=' * 100}")
```

- [ ] **Step 3: コミット**

```bash
git add backtest/cross_metric_validation_triple.py
git commit -m "feat: メイン実行関数と出力フォーマットを実装"
```

---

## Task 7: メインエントリーポイント追加と動作確認

**Files:**
- Modify: `backtest/cross_metric_validation_triple.py`

- [ ] **Step 1: __main__ ブロックを実装**

```python
if __name__ == "__main__":
    # results/フォルダ作成
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    
    # 出力ファイルパス設定
    output_file = results_dir / "cross_metric_validation_triple.txt"
    
    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output
    
    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_cross_metric_validation(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
```

- [ ] **Step 2: スクリプト実行確認**

```bash
cd backtest
python cross_metric_validation_triple.py
```

Expected output:
```
相対パフォーマンス分析（クロスメトリック検証、複数訓練期間） (DB: マルハンメガシティ2000-蒲田1)

【 訓練勝率グループ分割 → テスト差枚+勝率 】

====================================================================================================
パーセンタイル比率の自動最適化結果
...
比率      勝者(6月)    勝者(3月)    勝者(1月)    一貫性  相対値μ  相対値σ  推奨
----------------------------------------------------------------------------------------------------
50-0-50   上位G        上位G        上位G        ✅    +11.5%  +1.6%
45-10-45  上位G        上位G        上位G        ✅    +10.8%  +0.9%  ← オススメ
...

出力を保存しました: .../results/cross_metric_validation_triple.txt
```

- [ ] **Step 3: 結果ファイルが正しく生成されたか確認**

```bash
ls -la results/cross_metric_validation_triple.txt
cat results/cross_metric_validation_triple.txt | head -50
```

- [ ] **Step 4: コミット**

```bash
git add backtest/cross_metric_validation_triple.py
git commit -m "feat: クロスメトリック検証メイン実行とファイル出力を実装"
```

---

## Task 8: 統合テストと動作確認

**Files:**
- Modify: `test/test_cross_metric_validation.py`

- [ ] **Step 1: 統合テストを追加**

```python
def test_run_multi_period_cross_metric_validation():
    """統合テスト：全フロー動作確認"""
    # モックDBを使用（またはテスト用DBを指定）
    db_path = "../db/test_hall.db"  # テスト用
    
    # 実行しても例外が出ないことを確認
    try:
        run_multi_period_cross_metric_validation(db_path)
    except Exception as e:
        pytest.fail(f"統合テスト失敗: {e}")
```

- [ ] **Step 2: 全テスト実行**

```bash
cd test
pytest test_cross_metric_validation.py -v
```

Expected:
```
test_split_groups_triple_custom_5050 PASSED
test_split_groups_triple_custom_363636 PASSED
test_calculate_consistency_score_consistent PASSED
test_calculate_consistency_score_inconsistent PASSED
test_analyze_cross_metric_validation_win_rate PASSED
test_analyze_cross_metric_validation_games PASSED
test_find_optimal_percentile_ratio PASSED
test_run_multi_period_cross_metric_validation PASSED

========== 8 passed in X.XXs ==========
```

- [ ] **Step 3: コミット**

```bash
git add test/test_cross_metric_validation.py
git commit -m "test: クロスメトリック検証の統合テストを実装"
```

---

## Task 9: 結果検証と動作確認

**Files:**
- No new files — verification only

- [ ] **Step 1: 既存検証（相対パフォーマンス分析）と並行実行確認**

```bash
cd backtest
python relative_performance_multi_period_triple.py  # 既存
python cross_metric_validation_triple.py  # 新規

# 両方が正常に実行されることを確認
cat ../results/relative_performance_multi_period_triple.txt | head -30
cat ../results/cross_metric_validation_triple.txt | head -30
```

- [ ] **Step 2: 出力形式が仕様通りか確認**

- パーセンタイル比率比較表が全5比率を表示しているか
- 勝者一貫性（✅/⚠️）が正しく判定されているか
- 推奨比率がハイライトされているか
- 相対値μ・相対値σが正確に計算されているか

- [ ] **Step 3: 2つのホール（蒲田1・蒲田7）でも実行確認**

```bash
python cross_metric_validation_triple.py
# 両ホール分の結果が出力されることを確認
```

- [ ] **Step 4: 最終コミット**

```bash
git add -A
git commit -m "test: クロスメトリック検証の全機能動作確認完了"
```

---

## 実装完了時の確認事項

✅ **コード品質：**
- [ ] すべての関数に docstring がある
- [ ] エラーハンドリングが適切（None 返却など）
- [ ] パーセンタイル計算が正確
- [ ] テスト覆率 > 80%

✅ **機能完成度：**
- [ ] 5つのパーセンタイル比率を自動試行
- [ ] 複数訓練期間での勝者一貫性を判定
- [ ] 推奨比率を正しく選別
- [ ] クロスメトリック検証（勝率→差枚、G数→差枚）実行
- [ ] 詳細な出力表を生成

✅ **実行環境：**
- [ ] 既存検証との並行実行で矛盾なし
- [ ] 2つのホール（蒲田1・蒲田7）で動作
- [ ] 結果ファイルが正しく保存される

---

## 技術ノート

**パーセンタイル計算の注意点：**
- インデックス位置を正確に計算（`int(n * percentage / 100)` の使用）
- ソート後の lower/upper cutoff 値で正確にグループを分割

**勝者判定：**
- テスト期間での「相対値が最大」のグループが勝者
- 複数期間での勝者が一致することが推奨比率の条件

**過学習回避：**
- 一貫性が高い中から相対値が最大を選ぶ（単純な相対値最大ではない）
