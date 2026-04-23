# バックテスト検証システム - コード仕様書

## 目次
1. [ファイル構成](#ファイル構成)
2. [共通フレームワーク](#共通フレームワーク)
3. [分析スクリプト](#分析スクリプト)
4. [追加メトリクスの実装方法](#追加メトリクスの実装方法)
5. [メンテナンスガイド](#メンテナンスガイド)

---

## ファイル構成

```
backtest/
├── loader.py                                  # データ読み込み（DB → DataFrame）
├── analysis_base.py                          # 共通フレームワーク
│
├── 分析スクリプト（複数訓練期間対応）
│   ├── relative_performance_multi_period.py          # 勝率ベース
│   ├── relative_performance_analysis_coin_diff.py    # 差枚ベース
│   └── relative_performance_analysis_games.py        # G数ベース
│
├── 特殊分析
│   └── absolute_performance_analysis.py              # 絶対値分析
│
├── 出力フォルダ
│   └── results/
│       ├── relative_performance_multi_period.txt
│       ├── relative_performance_analysis_coin_diff.txt
│       ├── relative_performance_analysis_games.txt
│       └── absolute_performance_analysis.txt
│
└── ドキュメント
    ├── ANALYSIS_METHODOLOGY.md                # この説明書の分析方法論版
    ├── CODE_SPECIFICATION.md                  # このファイル
    └── MULTI_PERIOD_ANALYSIS_SUMMARY.md       # 分析結果サマリー
```

---

## 共通フレームワーク

### `analysis_base.py`

**目的**：全分析スクリプトで共通の定数と関数を統一管理

#### 定数定義

```python
TRAINING_PERIODS = [
    ('6月', '2025-10-01', '2026-03-31'),
    ('3月', '2026-01-01', '2026-03-31'),
    ('1月', '2026-03-01', '2026-03-31'),
]
# 訓練期間の定義。各スクリプトはこれを参照。変更時はここだけ修正。

TEST_START = '2026-04-01'
TEST_END = '2026-04-20'
# テスト期間（固定）。複数訓練で統一使用。

ATTRIBUTES = ['machine_number', 'machine_name', 'last_digit']
ATTRIBUTES_JA = {'machine_number': '機械番号', 'machine_name': '機種名', 'last_digit': '台末尾'}
# 分析対象属性とその日本語名

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日']
# 曜日と日本語対応

HALLS = [
    "マルハンメガシティ2000-蒲田1.db",
    "マルハンメガシティ2000-蒲田7.db"
]
# 分析対象ホール。新規ホール追加時はここに追加。
```

#### 共通関数

**1. load_and_split_data()**
```python
def load_and_split_data(db_path: str, period_name: str, start_date: str, end_date: str):
    """DB読み込みと訓練・テストデータの分割"""
    df = load_machine_data(db_path)
    df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()
    return df_train, df_test
```
- DB読み込み → 期間でフィルタ → 返却
- 各分析スクリプトで呼び出し可能（ただし現在は inline 実装）

**2. print_header(), print_dd_section(), print_weekday_section()**
```python
def print_header(db_name: str, period_name: str, start_date: str, end_date: str):
    """ヘッダー行（DB名、訓練期間、テスト期間）を出力"""
    print(f"{'=' * 140}")
    print(f"訓練期間：{period_name} ({start_date} ～ {end_date})")
    print(f"テスト期間：{TEST_START} ～ {TEST_END}")
    print(f"DB：{Path(db_name).stem}")
```
- 表示フォーマットの統一
- 各訓練期間ごとに1回呼び出し

**3. print_result_row()**
```python
def print_result_row(condition_label: str, attr: str, result: dict):
    """結果行を整形して出力"""
    if not result:
        return
    
    r = result
    high_sign = "+" if r['high_relative'] >= 0 else ""
    low_sign = "+" if r['low_relative'] >= 0 else ""
    
    print(f"{condition_label:<5} {attr:<15} {r['condition_avg']:>6.1f}% "
          f"{r['high_avg']:>6.1f}% {high_sign}{r['high_relative']:>7.1f}% "
          f"{r['low_avg']:>6.1f}% {low_sign}{r['low_relative']:>7.1f}% "
          f"{r['winner']:<12}")
```
- result 辞書のフォーマット出力
- 負数に "+" 符号を付けない制御

**4. get_condition_average(), get_group_average(), get_group_stats()**
```python
def get_condition_average(df_test: pd.DataFrame, metric_column: str) -> float:
    """条件全体の平均値を計算"""
    if metric_column == 'diff_coins_normalized':
        # 勝率の場合：勝利回数 / 全回数
        return (df_test[metric_column] > 0).sum() / len(df_test) if len(df_test) > 0 else 0
    else:
        # 数値平均の場合
        return df_test[metric_column].mean() if len(df_test) > 0 else 0

def get_group_stats(group_list: list, test_grouped: pd.DataFrame, attr: str, 
                    metric_column: str, condition_avg: float) -> dict:
    """グループの統計情報を計算"""
    values = get_group_average(group_list, test_grouped, attr, metric_column)
    if not values:
        return None
    
    avg = sum(values) / len(values)
    relative = avg - condition_avg
    
    return {
        'avg': avg,
        'relative': relative,
        'count': len(group_list),
    }
```
- メトリクス種に応じた計算ロジックを統一
- 勝率：条件判定 (x > 0)
- 他の数値：単純平均

---

## 分析スクリプト

### 基本構造（全スクリプト共通）

```python
import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *

def analyze_<metric>(df_train, df_test, condition_type, condition_value, attr):
    """
    メトリクス別の分析関数
    
    戻り値: {
        'condition_avg': float,      # テスト期間での条件全体平均
        'high_avg': float,           # テスト期間での高グループ平均
        'high_relative': float,      # 高グループの相対値
        'high_count': int,           # 高グループのメンバー数
        'low_avg': float,
        'low_relative': float,
        'low_count': int,
        'winner': str,               # "高<指標>G" or "低<指標>G"
    }
    """
    pass

def run_multi_period_<metric>_analysis(db_path: str):
    """複数訓練期間での分析実行"""
    pass

if __name__ == "__main__":
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    
    output_file = results_dir / "<output_filename>.txt"
    
    # 出力をファイルに保存
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output
    
    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_<metric>_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
```

### 各スクリプトの実装パターン

#### 1. relative_performance_multi_period.py（勝率ベース）

```python
def analyze_relative_performance(df_train, df_test, condition_type, condition_value, attr):
    """
    相対パフォーマンス分析（勝率）
    
    計算フロー：
    1. 訓練データで条件フィルタ → 属性でグループ化
    2. 各グループの勝率計算：(diff_coins_normalized > 0).sum() / count
    3. 中央値で高・低グループに分割
    4. テスト期間でグループ別の勝率を計算
    5. テスト期間での条件全体の勝率（条件平均）を計算
    6. 相対値 = グループ勝率 - 条件平均
    """
    
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]
    
    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None
    
    # 条件平均勝率
    condition_avg_wr = (test_filtered['diff_coins_normalized'] > 0).sum() / len(test_filtered)
    
    # 訓練期間での属性別勝率
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    train_grouped.columns = [attr, 'train_count', 'train_wins']
    train_grouped['train_win_rate'] = train_grouped['train_wins'] / train_grouped['train_count']
    
    if len(train_grouped) == 0:
        return None
    
    # 中央値で分割
    median_wr = train_grouped['train_win_rate'].median()
    high_wr = train_grouped[train_grouped['train_win_rate'] >= median_wr]
    low_wr = train_grouped[train_grouped['train_win_rate'] < median_wr]
    
    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
    }).reset_index()
    test_grouped.columns = [attr, 'test_count', 'test_wins']
    test_grouped['test_win_rate'] = test_grouped['test_wins'] / test_grouped['test_count']
    
    # グループ別の平均勝率
    high_test_rates = []
    for _, row in high_wr.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            high_test_rates.append(test_match.iloc[0]['test_win_rate'])
    
    low_test_rates = []
    for _, row in low_wr.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            low_test_rates.append(test_match.iloc[0]['test_win_rate'])
    
    high_avg_wr = sum(high_test_rates) / len(high_test_rates) if high_test_rates else 0
    low_avg_wr = sum(low_test_rates) / len(low_test_rates) if low_test_rates else 0
    
    high_relative = high_avg_wr - condition_avg_wr
    low_relative = low_avg_wr - condition_avg_wr
    
    return {
        'condition_avg_wr': condition_avg_wr,
        'high_test_rate': high_avg_wr,
        'high_relative': high_relative,
        'high_count': len(high_wr),
        'low_test_rate': low_avg_wr,
        'low_relative': low_relative,
        'low_count': len(low_wr),
        'winner': "高勝率G" if high_relative >= low_relative else "低勝率G",
    }
```

**key point**：
- 勝率は `(x > 0).sum() / count` で計算
- テスト期間の集計時も勝敗を再計算（訓練期間のグループメンバー属性を参照）

#### 2. relative_performance_analysis_coin_diff.py（差枚ベース）

```python
def analyze_relative_performance_coin_diff(df_train, df_test, condition_type, condition_value, attr):
    """
    相対パフォーマンス分析（平均差枚）
    
    勝率版との違い：
    - 指標：diff_coins_normalized の平均値（勝敗判定ではなく実値）
    - 中央値分割：平均差枚で分割
    - 条件平均：test_filtered['diff_coins_normalized'].mean()
    """
    
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]
    
    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None
    
    # 条件平均差枚
    condition_avg_coin = test_filtered['diff_coins_normalized'].mean()
    
    # 訓練期間での属性別平均差枚
    train_grouped = train_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean']
    }).reset_index()
    train_grouped.columns = [attr, 'train_avg_coin']
    
    if len(train_grouped) == 0:
        return None
    
    # 中央値で分割
    median_coin = train_grouped['train_avg_coin'].median()
    high_coin = train_grouped[train_grouped['train_avg_coin'] >= median_coin]
    low_coin = train_grouped[train_grouped['train_avg_coin'] < median_coin]
    
    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        'diff_coins_normalized': ['mean']
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_coin']
    
    # グループ別の平均差枚
    high_test_coins = []
    for _, row in high_coin.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            high_test_coins.append(test_match.iloc[0]['test_avg_coin'])
    
    # 同様に low_test_coins も計算...
    
    high_avg_coin = sum(high_test_coins) / len(high_test_coins) if high_test_coins else 0
    low_avg_coin = sum(low_test_coins) / len(low_test_coins) if low_test_coins else 0
    
    high_relative = high_avg_coin - condition_avg_coin
    low_relative = low_avg_coin - condition_avg_coin
    
    return {
        'condition_avg': condition_avg_coin,
        'high_avg': high_avg_coin,
        'high_relative': high_relative,
        'high_count': len(high_coin),
        'low_avg': low_avg_coin,
        'low_relative': low_relative,
        'low_count': len(low_coin),
        'winner': "高差枚G" if high_relative >= low_relative else "低差枚G",
    }
```

#### 3. relative_performance_analysis_games.py（G数ベース）

coin_diff と同じ構造。`games_normalized` を指標として使用。

#### 4. absolute_performance_analysis.py（絶対値分析）

```python
def run_absolute_analysis(db_path: str):
    """
    絶対パフォーマンス分析
    
    相対分析との違い：
    - 勝者判定：high_relative >= low_relative ではなく
               high_test_rate >= low_test_rate で判定
    - 出力に勝率の実値とマージン（差）を含む
    """
    
    for dd in range(1, 21):
        for attr in ATTRIBUTES:
            # 訓練期間で高勝率グループを特定
            result = analyze_relative_performance(df_train, df_test, 'dd', dd, attr)
            
            if result:
                r = result
                # 絶対判定：実勝率の大小
                actual_winner = "高勝率グループ" if r['high_test_rate'] >= r['low_test_rate'] else "低勝率グループ"
                margin = abs(r['high_test_rate'] - r['low_test_rate'])
                
                print(f"D{dd} {attr} {actual_winner} {r['high_test_rate']*100:.1f}% vs "
                      f"{r['low_test_rate']*100:.1f}% マージン {margin*100:.1f}%")
```

**出力統計**：
```python
# DD別勝者統計
dd_winner_count = {'machine_number': {'high': 0, 'low': 0}, ...}
for dd in range(1, 21):
    if high_test_rate >= low_test_rate:
        dd_winner_count[attr]['high'] += 1
    else:
        dd_winner_count[attr]['low'] += 1

# 勝率出力
print(f"machine_number: 高勝率グループ勝利 {high}/{total}回 ({high/total*100:.1f}%)")
```

---

## 追加メトリクスの実装方法

### ステップ1: analysis_base.py を拡張（オプション）

メトリクス固有の共通処理がある場合のみ追加：

```python
def get_condition_average(df_test: pd.DataFrame, metric_column: str) -> float:
    if metric_column == 'new_metric':
        # 新メトリクスの条件平均計算
        return df_test[metric_column].mean()
```

### ステップ2: 新分析スクリプトを作成

ファイル名：`relative_performance_analysis_<metric>.py`

```python
"""相対パフォーマンス分析 - <メトリクス日本語名>ベース"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
from pathlib import Path
from io import StringIO
from loader import load_machine_data
from analysis_base import *


def analyze_relative_performance_<metric>(df_train: pd.DataFrame, df_test: pd.DataFrame, 
                                          condition_type: str, condition_value: str, attr: str) -> dict:
    """<メトリクス>ベースの相対パフォーマンス分析"""
    
    train_filtered = df_train[df_train[condition_type] == condition_value]
    test_filtered = df_test[df_test[condition_type] == condition_value]
    
    if len(train_filtered) == 0 or len(test_filtered) == 0:
        return None
    
    # テスト期間での条件全体の平均<メトリクス>
    condition_avg_<metric> = test_filtered['<column>'].mean() if len(test_filtered) > 0 else 0
    
    # 訓練期間でこの属性別の平均<メトリクス>を計算
    train_grouped = train_filtered.groupby(attr).agg({
        '<column>': ['mean']
    }).reset_index()
    train_grouped.columns = [attr, 'train_avg_<metric>']
    
    if len(train_grouped) == 0:
        return None
    
    # 中央値で分割
    median_<metric> = train_grouped['train_avg_<metric>'].median()
    high_<metric> = train_grouped[train_grouped['train_avg_<metric>'] >= median_<metric>]
    low_<metric> = train_grouped[train_grouped['train_avg_<metric>'] < median_<metric>]
    
    # テスト期間での集計
    test_grouped = test_filtered.groupby(attr).agg({
        '<column>': ['mean']
    }).reset_index()
    test_grouped.columns = [attr, 'test_avg_<metric>']
    
    # グループ別のテスト期間での平均
    high_test_<metric> = []
    for _, row in high_<metric>.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            high_test_<metric>.append(test_match.iloc[0]['test_avg_<metric>'])
    
    low_test_<metric> = []
    for _, row in low_<metric>.iterrows():
        test_match = test_grouped[test_grouped[attr] == row[attr]]
        if len(test_match) > 0:
            low_test_<metric>.append(test_match.iloc[0]['test_avg_<metric>'])
    
    high_avg_<metric> = sum(high_test_<metric>) / len(high_test_<metric>) if high_test_<metric> else 0
    low_avg_<metric> = sum(low_test_<metric>) / len(low_test_<metric>) if low_test_<metric> else 0
    
    high_relative = high_avg_<metric> - condition_avg_<metric>
    low_relative = low_avg_<metric> - condition_avg_<metric>
    
    return {
        'condition_avg': condition_avg_<metric>,
        'high_avg': high_avg_<metric>,
        'high_relative': high_relative,
        'high_count': len(high_<metric>),
        'low_avg': low_avg_<metric>,
        'low_relative': low_relative,
        'low_count': len(low_<metric>),
        'winner': "高<メトリクス>G" if high_relative >= low_relative else "低<メトリクス>G",
    }


def run_multi_period_<metric>_analysis(db_path: str):
    """複数訓練期間での平均<メトリクス>ベース分析"""
    
    print(f"\n相対パフォーマンス分析（平均<メトリクス>ベース、複数訓練期間） (DB: {Path(db_path).stem})")
    print("=" * 140)
    
    df = load_machine_data(db_path)
    df_test = df[(df['date'] >= TEST_START) & (df['date'] <= TEST_END)].copy()
    
    for period_name, start_date, end_date in TRAINING_PERIODS:
        df_train = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()
        
        print_header(db_path, period_name, start_date, end_date)
        
        # DD別分析
        print_dd_section(period_name)
        for dd in range(1, 21):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_<metric>(df_train, df_test, 'dd', dd, attr)
                if result:
                    print_result_row(f"D{dd:<3}", f"{ATTRIBUTES_JA[attr]:<15}", result)
        
        # 曜日別分析
        print_weekday_section(period_name)
        for weekday, jp in zip(WEEKDAYS, WEEKDAY_JP):
            for attr in ATTRIBUTES:
                result = analyze_relative_performance_<metric>(df_train, df_test, 'weekday', weekday, attr)
                if result:
                    print_result_row(f"{jp}曜   ", f"{ATTRIBUTES_JA[attr]:<15}", result)
    
    print("\n" + "=" * 140)
    print("平均<メトリクス>ベース分析完了")
    print("=" * 140)


if __name__ == "__main__":
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)
    
    output_file = results_dir / "relative_performance_analysis_<metric>.txt"
    
    old_stdout = sys.stdout
    captured_output = StringIO()
    sys.stdout = captured_output
    
    try:
        for hall in HALLS:
            db_path = f"../db/{hall}"
            if Path(db_path).exists():
                run_multi_period_<metric>_analysis(db_path)
    finally:
        sys.stdout = old_stdout
        output_content = captured_output.getvalue()
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        print(output_content)
        print(f"\n出力を保存しました: {output_file.absolute()}")
```

**実装チェックリスト**：
- [ ] `<metric>` 全出現箇所を置換
- [ ] `<column>` をDBカラム名に置換（例：`avg_games`, `ratio_...`）
- [ ] メトリクスの日本語名を決定
- [ ] ファイル名を適切に設定
- [ ] 実行して `results/` に出力が生成されることを確認

---

## メンテナンスガイド

### 定期メンテナンス（訓練期間の更新）

#### 年1回（新年度開始時）

```python
# analysis_base.py の TRAINING_PERIODS を更新
TRAINING_PERIODS = [
    ('6月', '2026-10-01', '2027-03-31'),  # ← 年度を更新
    ('3月', '2027-01-01', '2027-03-31'),
    ('1月', '2027-03-01', '2027-03-31'),
]

TEST_START = '2027-04-01'  # ← テスト期間も更新
TEST_END = '2027-04-20'
```

#### 月1回（テスト期間の延長）

各月20日を超えたら、テスト期間を延長：

```python
TEST_END = '2027-04-30'  # または目的に合わせて設定
```

**注意**：複数訓練期間の関連性が失われるため、テスト期間の終了後に新しい分析を開始することを推奨。

### 新ホール追加

```python
# analysis_base.py の HALLS に追加
HALLS = [
    "マルハンメガシティ2000-蒲田1.db",
    "マルハンメガシティ2000-蒲田7.db",
    "新ホール名.db",  # ← 追加
]
```

スクリプト実行時に自動的に新ホール分析が追加される。

### DBスキーマ変更時

#### カラム名変更

```python
# loader.py で利用されるカラム名を確認
# analysis_base.py で参照されるカラム名を確認
# 全スクリプトで使用されるカラム名をチェック

例：'diff_coins_normalized' → 'profit_normalized' に変更
→ 全スクリプトの参照箇所を更新
```

#### 新属性の追加

```python
# analysis_base.py
ATTRIBUTES = ['machine_number', 'machine_name', 'last_digit', 'new_attribute']
ATTRIBUTES_JA = {
    'machine_number': '機械番号',
    'machine_name': '機種名',
    'last_digit': '台末尾',
    'new_attribute': '新属性名',
}
```

スクリプト実行時に新属性の分析が自動的に追加される。

### トラブルシューティング

#### 問題：出力がない

**原因**：
- グループのサイズが0（フィルタ後にデータなし）
- `load_machine_data()` が例外を発生

**確認方法**：
```bash
# loader.py を直接実行
python -c "from loader import load_machine_data; df = load_machine_data('../db/ホール名.db'); print(len(df))"
```

#### 問題：勝率が奇数値（0%, 50%, 100%）

**原因**：サンプル数が少ない（特に1月訓練）

**対応**：
- 1月訓練の機械番号は信頼度が低い
- 3月訓練の結果を優先する

#### 問題：相対値が異常に大きい（±300%以上）

**原因**：グループのサンプル数が極端に少ない

**確認**：
```python
# スクリプト内で high_count, low_count を確認
# 1以下の場合は無視（print_result_row() で return する）
```

### パフォーマンス最適化

#### 大規模データセット対応

```python
# メモリ効率化：不要カラムを削除
df = df[['date', 'machine_number', 'machine_name', 'last_digit', 
         'diff_coins_normalized', 'games_normalized', 'dd', 'weekday']]

# インデックス設定（グループ化高速化）
df.set_index(['dd', 'weekday'], inplace=True)
```

#### 並列処理

```python
# マルチプロセッシング対応（将来拡張）
from multiprocessing import Pool

def analyze_dd(dd):
    results = []
    for attr in ATTRIBUTES:
        result = analyze_relative_performance(...)
        results.append(result)
    return results

with Pool(4) as p:
    results = p.map(analyze_dd, range(1, 21))
```

---

## チェックリスト：新分析メトリクス追加時

- [ ] ファイル作成：`relative_performance_analysis_<metric>.py`
- [ ] analysis_base.py に必要な関数を追加（オプション）
- [ ] DBカラム名の確認
- [ ] ファイル内の全プレースホルダーを置換
- [ ] `results/` フォルダの作成確認
- [ ] 実行テスト：`python relative_performance_analysis_<metric>.py`
- [ ] 出力ファイルが `results/` に生成されることを確認
- [ ] git add & commit
- [ ] ドキュメント更新（このファイル）

---

**最終更新**: 2026-04-23  
**対象バージョン**: backtest/ v1.0  
**メンテナンス責任者**: AI Assistant
