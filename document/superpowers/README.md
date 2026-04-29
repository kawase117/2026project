# Superpowers Documentation

高度な分析機能の実装仕様・設計ドキュメント群。

---

## 2026-04-23 Cross-Metric Validation

複数メトリクス・時期間にわたる統計仮説を検証する包括的分析システム。

### 計算方法解説書 (Explanation Guide)

**File:** `2026-04-23-cross-metric-validation-calculations.md`

**対象読者：** AI, 新規開発者, ビジネススタッフ

**目的：** Cross-metric validation が何を行い、なぜ重要か、計算方法を理解する

**構成：**
- 相対パフォーマンス分析
- パーセンタイル分割
- 複数時期間での一貫性スコア（6月/3月/1月）
- 統計解釈
- 検証ワークフロー

**使い方：** このドキュメントを最初に読み、パチスロ分析における価値と概念的枠組みを理解する。

---

### コード仕様書 (Code Specification)

**File:** `2026-04-23-cross-metric-validation-code-spec.md`

**対象読者：** 保守者、機能拡張・デバッグ開発者

**目的：** 実装詳細、API契約、テスト戦略を理解する

**構成：**
- モジュール構成（`analysis_base.py`, `cross_metric_validation_triple.py`）
- 関数仕様・シグネチャ
- データモデル・戻り値型
- テストスイート（15テスト）
- 定数・設定
- トラブルシューティング

**使い方：** 新機能実装、検証ロジック拡張、デバッグ時にリファレンスとして使用。

---

## バックテスト検証設計

**File:** `2026-04-23-backtest-validation-design.md`

Phase 3 ダッシュボード（`page_15_backtest_validation.py`）の設計仕様。

---

## Integration with Phase 3 Dashboard

これらのドキュメントは **page_15_backtest_validation.py** 実装をサポート：

- **Calculations doc** → ビジネスロジック・統計公式
- **Spec doc** → 実装詳細・API契約
- **Code modules** → `backtest/analysis_base.py`, `backtest/cross_metric_validation_triple.py`
- **Tests** → `test/test_analysis_base.py`, `test/test_cross_metric_validation.py`

---

## Document Governance

| ドキュメント | 状態 | 最終更新 |
|------------|------|---------|
| 計算方法 | 完成 | 2026-04-23 |
| コード仕様 | 完成 | 2026-04-23 |
| バックテスト設計 | 完成 | 2026-04-23 |

全てのドキュメントはバージョン管理され、メインリポジトリに committed。
