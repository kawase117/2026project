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

**改善余地：**
- 複数分析スクリプト（relative_performance_*.py など）が同じ loader を呼び出しているが、毎回同じ全レコード読み込みを実行
- キャッシュ機構なし

**推奨：** SQL 最適化 + キャッシュの導入（効果：トークン・実行時間削減）

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

**改善余地：** `merge()` / `groupby()` による Pandas ベクトル化

**推奨：** Pandas 集計ロジック最適化（効果：実行時間 10-50 倍改善）

---

### 3. 複数分析スクリプト間の重複コード
**対象スキル：** `data:analyze`

**現状：** 
- `relative_performance_analysis_coin_diff_triple.py`
- `relative_performance_analysis_games_triple.py`
- `relative_performance_multi_period_triple.py`

上記 3 スクリプト + クロスメトリック検証で、グループ分割・集計ロジックが **部分的に重複**している可能性

**推奨：** 共通抽出関数の実装（`analysis_base.py` に統合）

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
