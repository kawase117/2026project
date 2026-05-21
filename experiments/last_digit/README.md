# Last-Digit ML (末尾別機械学習)

このディレクトリは、末尾別機械学習の運用・検証に必要な中核コードと最終成果物を集約したものです。

## 構成

- `tail_time_adaptive_ltr_poc_improved.py`
  - 末尾別LTRの基盤ロジック（特徴量・窓設定・評価補助）
- `tail_ltr_full_walkforward_ops.py`
  - Walk-forward学習/予測の共通処理
- `tail_ltr_profit_ops.py`
  - 指標計算と収益評価補助
- `tail_ltr_split_rule_wf.py`
  - split rule（2F/3F/A非A）検証本体
- `tail_ltr_split_rule_nextday_gpu.py`
  - 翌日予測（GPU）
- `tail_ltr_split_rule_monthly_check_gpu.py`
  - 月次定期チェック（GPU）
- `reports/`
  - 最終評価レポート・履歴ファイル

## 実行互換性

既存の `ml.experiments.*` 実行パスは、互換ラッパーで維持しています。

例:

```powershell
venv\Scripts\python.exe -m ml.experiments.tail_ltr_split_rule_nextday_gpu --help
venv\Scripts\python.exe -m ml.experiments.tail_ltr_split_rule_monthly_check_gpu --help
```

## 運用ルール（現時点）

- 2F_A は判断不能（フラット予測）時に総合から除外する。
- 信頼度指標は日次・月次の両方で確認する。
- 評価期間の直接集計は `--enable-test-period-report` を使用する。

