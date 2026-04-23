# バックテスト検証 - 分析方法論

## 概要

パチスロ館の機械群性能を予測するため、訓練期間（過去データ）での高勝率機械が、テスト期間（将来データ）でも高勝率を達成するかを検証する。

**核となる仮説**：
- **仮説A**: 訓練期間で勝った台は、テスト期間でも勝つ（永続性）
- **仮説B**: 訓練期間で負けた台は、テスト期間で勝つ（設定反転）

---

## 相対パフォーマンス分析（基本）

### 計算ステップ

#### 1. グループ分割

各条件（DD/曜日）と属性（機械番号/機種名/台末尾）の組み合わせごとに：

```
訓練データ内で、該当条件の全機械を属性値でグループ化
↓
各グループの「中央値」を計算（指標は勝率、差枚、またはG数）
↓
中央値 >= グループと < グループに2分割
```

**例**：D11 訓練期間での機械番号グループ
```
訓練期間（6月）D11データから：
  - 機械101：勝率45%
  - 機械102：勝率52%  ← 中央値
  - 機械103：勝率48%
  
分割結果：
  - 高勝率G：{102}  （≥52%）
  - 低勝率G：{101, 103}  （<52%）
```

#### 2. 条件平均の計算

テスト期間において、該当条件全体の平均勝率を計算：

```
テスト期間 D11 の全機械の勝率を平均
= 条件平均 （45.7% など）
```

**重要**：条件平均は市場全体の景況を反映
- 条件平均 45.7% = テスト期間4月11日は全機械が平均45.7%の勝率
- グループ高と低が異なっても、条件平均が低い日は全体が低い

#### 3. グループパフォーマンスの計算

テスト期間で、各グループの平均勝率を計算：

```
テスト期間 D11 高勝率G（{102}）の勝率
= 54.9%（例）

テスト期間 D11 低勝率G（{101, 103}）の勝率
= 47.7%（例）
```

#### 4. 相対値の計算

**相対値 = グループ勝率 - 条件平均**

```
高勝率G相対値 = 54.9% - 45.7% = +9.2%
低勝率G相対値 = 47.7% - 45.7% = +2.0%

勝者：高勝率G（+9.2% > +2.0%）
```

**意味**：
- 高勝率G は条件平均より +9.2% 上振れ
- 低勝率G は条件平均より +2.0% 上振れ（ただし低勝率Gが勝つ）
- 条件平均を基準に、どのグループが相対的に優位かを評価

---

## メトリクス別の計算方法

### 1. 勝率ベース（relative_performance_multi_period.py）

```python
# 訓練期間でのグループ分割
train_grouped = train_filtered.groupby(attr).agg({
    'diff_coins_normalized': ['count', lambda x: (x > 0).sum()]
})
train_grouped['train_win_rate'] = wins / count

# 中央値で分割
median = train_grouped['train_win_rate'].median()
high_wr = train_grouped[train_grouped >= median]
low_wr = train_grouped[train_grouped < median]

# テスト期間での集計
test_grouped = test_filtered.groupby(attr).agg({...})
test_grouped['test_win_rate'] = test_wins / test_count

# グループ平均の計算
high_avg = test_grouped[high_wr属性値].mean()  # テスト期間での高グループ平均
condition_avg = (test_filtered['diff_coins_normalized'] > 0).mean()

# 相対値
high_relative = high_avg - condition_avg
```

**条件平均の定義**：
```
条件平均勝率 = テスト期間で該当条件の全機械が勝利した回数 / 全回数
= (diff_coins_normalized > 0).sum() / len(test_filtered)
```

### 2. 平均差枚ベース（relative_performance_analysis_coin_diff.py）

```python
# 訓練期間でのグループ分割
train_grouped['train_avg_coin'] = train_grouped['diff_coins_normalized'].mean()

# 中央値で分割（差枚の中央値）
median_coin = train_grouped['train_avg_coin'].median()
high_coin = train_grouped[train_grouped >= median_coin]

# テスト期間での集計
test_grouped['test_avg_coin'] = test_grouped['diff_coins_normalized'].mean()

# グループ平均の計算
high_avg_coin = test_grouped[high_coin属性値]['test_avg_coin'].mean()
condition_avg_coin = test_filtered['diff_coins_normalized'].mean()

# 相対値
high_relative = high_avg_coin - condition_avg_coin
```

**条件平均の定義**：
```
条件平均差枚 = テスト期間で該当条件の全機械の差枚の平均
= test_filtered['diff_coins_normalized'].mean()
```

**出力例**：
```
D11 機種名: 基準 239.7% 高 687.1% vs基準 +447.4%
→ 訓練で高差枚グループは、テストで条件平均（239.7%）から +447.4% 上振れ
```

### 3. 平均G数ベース（relative_performance_analysis_games.py）

勝率、差枚と同じロジック。計算式は `games_normalized` を使用。

---

## 複数訓練期間での比較

### 訓練期間の定義

| 期間 | 範囲 | 日数 |
|------|------|------|
| 6月 | 2025-10-01 ～ 2026-03-31 | 183日 |
| 3月 | 2026-01-01 ～ 2026-03-31 | 90日 |
| 1月 | 2026-03-01 ～ 2026-03-31 | 31日 |

**テスト期間（全訓練で同一）**：2026-04-01 ～ 2026-04-20（20日）

### 比較のポイント

同じDD/曜日に対して、異なる訓練期間で分析すると：

```
D11 機種名 6月訓練：
  中央値 → {機種A, 機種B} が高勝率G
  テスト結果：+10.8%

D11 機種名 3月訓練：
  中央値 → {機種A, 機種C} が高勝率G ← グループ構成が異なる！
  テスト結果：+12.2%

D11 機種名 1月訓練：
  中央値 → {機種A} のみ高勝率G  ← サンプル不足でグループ変動
  テスト結果：+4.4%
```

**結果の解釈**：
- **信号強化/減弱**：同じグループで相対値が変わる → 訓練期間長の影響
- **グループ組成変化**：異なるグループが形成される → 市場環境変化の影響

---

## 絶対パフォーマンス分析との違い

### 相対パフォーマンス（相対値ベース）

```
判定：high_relative >= low_relative ？
→ グループ同士の比較（条件平均を除いた相対値で判定）
意味：「この日のこのグループは、市場平均をどれだけ上/下回るか」
```

### 絶対パフォーマンス（勝率の実値ベース）

```python
winner = "高勝率G" if high_avg_wr >= low_avg_wr else "低勝率G"
→ グループの実勝率を直接比較
意味：「テスト期間で実際に勝つのはどちらか」
```

**例**：
```
D11 機械番号（蒲田1）
  高勝率G：47.0%
  低勝率G：43.0%
  
相対分析：高勝率G が +2.3% 優位
絶対分析：高勝率G が 47.0% 達成（勝者）

→ 相対値では僅差だが、絶対値では確実に高勝率Gが勝つ
```

---

## 統計的な信頼度

### シグナル強度の解釈

| マージン（相対値） | 評価 |
|------------------|------|
| ≥ ±5% | 強い信号 |
| ±3% ～ ±5% | 中程度 |
| < ±3% | 弱い信号 |

**例**：
- D11 機種名 6月：+10.8% → 強い信号 ⭐⭐⭐
- D11 機種名 1月：+4.4% → 中程度信号 ⭐⭐
- D20 機械番号 6月：+2.0% → 弱い信号 ⭐

### グループサイズの影響

```
訓練期間が短いほど：
  - 各機械のサンプル数が減少
  - 中央値が変動しやすい
  - グループ組成が不安定
  → 1月訓練は信号信頼度が低い
```

---

## 計算フロー図

```
訓練データ (2025-10-01 ～ 2026-03-31)
  ↓
[条件別グループ化]
  DD=11, 属性=機種名
  ↓
[訓練期間での勝率計算]
  機種A: 52%, 機種B: 48%, ...
  ↓
[中央値で分割]
  中央値 50%
  高勝率G: {A}, 低勝率G: {B, ...}
  ↓
テスト期間データ (2026-04-01 ～ 2026-04-20)
  ↓
[テスト期間での勝率計算]
  条件平均: 45.7%
  高G: 54.9%, 低G: 47.7%
  ↓
[相対値計算]
  高: +9.2%, 低: +2.0%
  ↓
[結果出力]
  勝者: 高勝率G
```

---

## 注意点と制限事項

### 1. 小サンプルの問題

1月訓練では、機械番号が月内1-2回しか出現しないケースがある。
```
訓練期間内での勝敗：0回or1回
→ 勝率は 0%, 50%, 100% のいずれかになる
→ 中央値での分割が不安定
```

**対応**：1月の機械番号は「勝敗再現性」（前月勝利台が今月も勝つか）で評価

### 2. 関連性の仮定

相対値分析は「高勝率グループと低勝率グループの質の差」を仮定。
```
実際には：
  - ホールの設定調整
  - 季節変動
  - 顧客層の変化
などが影響している可能性
```

### 3. 訓練期間の選択バイアス

3月訓練が最適とされるのは、このデータセット内での結果。
別の時期・ホールでは異なる可能性がある。

---

## 参考：出力フォーマット

### 出力ファイル

| ファイル | 内容 |
|---------|------|
| `relative_performance_multi_period.txt` | 勝率ベースの複数訓練期間比較 |
| `relative_performance_analysis_coin_diff.txt` | 平均差枚ベースの分析 |
| `relative_performance_analysis_games.txt` | 平均G数ベースの分析 |
| `absolute_performance_analysis.txt` | 絶対パフォーマンス分析 |

### 出力フォーマット例

```
D11   機種名      45.7%   56.5%     10.8%   46.2%      0.5%  高勝率G
      ↑          ↑       ↑         ↑       ↑         ↑      ↑
      DD      条件平均  高G平均  高相対値  低G平均  低相対値  勝者
```

---

## 今後の拡張

### 新メトリクスの追加方法

`analysis_base.py` の `get_condition_average()` と `get_group_stats()` を拡張：

```python
def get_condition_average(df_test: pd.DataFrame, metric_column: str) -> float:
    if metric_column == 'diff_coins_normalized':
        return (df_test[metric_column] > 0).sum() / len(df_test)  # 勝率
    elif metric_column == 'games_normalized':
        return df_test[metric_column].mean()  # 平均G数
    elif metric_column == 'diff_coins_normalized':  # 差枚
        return df_test[metric_column].mean()
    # 新メトリクスをここに追加
    elif metric_column == 'new_metric':
        return df_test[metric_column].mean()
```

新分析スクリプトを `relative_performance_analysis_<metric>.py` として作成。

---

**生成日**: 2026-04-23  
**対象分析システム**: `backtest/` フォルダ内の4スクリプト
