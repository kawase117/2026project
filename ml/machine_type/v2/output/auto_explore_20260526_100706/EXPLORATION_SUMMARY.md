# 10時間探索サマリー（自動実行）

## ベースライン vs 推奨設定

| config | split | hit@1 | hit@3 | auc | 2F_N lift@3 | 2F_N lift@5 |
|---|---:|---:|---:|---:|---:|---:|
| baseline6/default/l0=80/lambda=0.5 | tune | 0.3333 | 0.8500 | 0.6485 | 1.1797 | 1.0547 |
| baseline6/default/l0=80/lambda=0.5 | holdout | 0.5000 | 0.8000 | 0.6676 | 0.5202 | 1.1933 |
| baseline6/default/l0=75/lambda=0.1 | holdout | 0.5000 | 0.8000 | 0.6676 | 0.5202 | 1.1933 |

## 推奨設定
- feature_profile: `baseline6`
- target_policy: `default`
- layer0 win_rate threshold: `75`
- combined_lambda: `0.1`

## タスク別成果物
- task1_rich_features_result.json
- task2_layer0_threshold_sweep.json
- task3_2fn_top5_result.json
- task4_lambda_sweep.json