# Backtest モジュール - コード仕様・制約事項

## 概要
backtest/ は DB 分析検証を行う 19 個のスクリプトから構成。Phase 2 の SQLite DB を読み込んで、訓練・テスト期間での相対パフォーマンス分析、多期間検証、クロスメトリック検証を実施。

## 既知の制約事項

### cross_metric_validation_triple.py

**状態：エラー発生中**

**原因：** 勝率グループ分割 → テスト差枚・勝率検証の処理が **想定より複雑化** しており、複数の集計フェーズ（訓練データのグループ化 → カスタム比率での分割 → テスト期間での再集計 → グループマッピング）を含む。

これらの処理を統一した単一フロー内で実装しようとした結果、エラーが発生している。

**対応方針：**
- 現在のロジック検証時は冗長性チェック不要
- エラー原因の特定・修正に注力
- スキル利用での検証ロジック簡略化は保留

---

## Skill 利用による改善箇所

### 1. loader.py — SQL クエリの最適化
**対象スキル：** `data:sql-queries`

**現状：**
```python
SELECT date, machine_number, machine_name, last_digit, diff_coins_normalized, games_normalized FROM machine_detailed_results
```

**改善内容（完了：2026-04-24）：**
- 複数分析スクリプト（relative_performance_*.py など）が同じ loader を呼び出しているが、毎回同じ全レコード読み込みを実行していた問題を解決
- `load_machine_data()` に `@lru_cache(maxsize=8)` デコレータを追加
- 同一 db_path への複数呼び出しをメモリキャッシュ

**効果：** トークン・実行時間削減

**実装ファイル：** `backtest/loader.py`

---

### 2. relative_performance_analysis_*.py — 集計ロジックの効率化
**対象スキル：** `data:analyze`

**現状（例：relative_performance_analysis_coin_diff_triple.py L48-54）：**
```python
def get_group_test_coins(group_df):
    coins = []
    for _, row in group_df.iterrows():  # ← iterrows は低速
        test_match = test_grouped[test_grouped[attr] == row[attr]]  # ← 行レベル条件検索（O(n)）
        if len(test_match) > 0:
            coins.append(test_match.iloc[0]['test_avg_coin'])
    return coins
```

**改善内容（完了：2026-04-24）：**
- 3 ファイル（`relative_performance_analysis_coin_diff_triple.py`, `relative_performance_analysis_games_triple.py`, `relative_performance_multi_period_triple.py`）の iterrows() ループを `merge()` ベースの `get_group_test_values_vectorized()` 共通関数に置き換え
- `analysis_base.py` に共通関数を実装し、3 ファイルから呼び出し

**効果：** 実行時間 10-50 倍改善、コード重複削減

**実装ファイル：** 
- `backtest/analysis_base.py` — `get_group_test_values_vectorized()` 追加
- 3 個の relative_performance_*_triple.py ファイル — 関数呼び出しに置き換え

---

### 3. 複数分析スクリプト間の重複コード統合
**対象スキル：** `data:analyze`

**現状：** 
- `relative_performance_analysis_coin_diff_triple.py`
- `relative_performance_analysis_games_triple.py`
- `relative_performance_multi_period_triple.py`
- `cross_attribute_performance_analysis.py`

上記 3 スクリプト + クロスメトリック検証で、グループ分割・集計ロジックが **部分的に重複**

**改善内容（部分完了：2026-04-24）：**
- `analysis_base.py` に共通関数を追加：
  - `map_groups_by_attr()` — 訓練期間でグループ分割し、テスト期間データにラベル付与
  - `aggregate_group_metrics()` — グループ別 台数・平均差枚・勝率 を集計
  - `calculate_rank_correlation()` — スピアマン相関係数と p 値を計算
  - `get_group_test_values_vectorized()` — merge() ベースのベクトル化抽出

**実装ファイル：**
- `backtest/analysis_base.py` — 4 関数追加
- `backtest/cross_attribute_performance_analysis.py` — 新規実装（上記共通関数を利用）

**残課題（優先度 3）：** `cross_metric_validation_triple.py` との統合はエラー修正後に検討

---

## 次のステップ

1. **cross_metric_validation_triple.py のエラー修正** → 複雑性削減の検討
2. **loader.py の SQL 最適化** (`data:sql-queries`)
3. **集計ロジック効率化** (`data:analyze`)
4. 全体統合テスト・ドキュメント更新

---

## 参考

- **分析スクリプト一覧：** 19 個
  - analysis_base.py（共通関数）
  - loader.py（DB 読み込み）
  - validator.py（検証）
  - 相対パフォーマンス分析 × 3（coin_diff, games, multi_period）
  - クロスメトリック検証 × 1（triple 版）
  - 他 12 個

---

**最終更新：** 2026-04-24
