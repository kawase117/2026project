---
name: ml-experiment-logger
description: ML実験の起動前チェックと実験結果ロギング標準化を自動ガイドするスキル。長時間ジョブ実行時に適用。
evolved_from:
  - duplicate-background-process-detection
  - catboost-walkforward-runtime-expectation
  - exp-structured-run-json
  - exp-html-fixed-sections
  - exp-jsonl-index-search
  - progress-reporting-required-in-all-loops
confidence: 0.91
---

# ML Experiment Logger Skill

## トリガー
- 長時間訓練ジョブ（walk-forward等）をバックグラウンド実行するとき
- 実験ログの構造を設計するとき
- 50件以上の実験結果を検索・フィルタリングするとき
- GPUメモリ警告が出たとき

## 実行前チェック

### 1. 重複プロセス検出（必須）
```powershell
# 新ジョブ起動前に毎回実行
Get-WmiObject Win32_Process |
  Where-Object {$_.CommandLine -like "*tail_ltr*"} |
  Select-Object ProcessId, CommandLine

# 重複が確認された場合（最古のPIDを残す）:
Stop-Process -Id <pid1>, <pid2> -Force
```

### 2. CatBoost walk-forward の所要時間
```
testperiod 143日 x expert数（2F_N / 3F_A / 3F_N）≈ 430回の再学習
GPU独占状態での目安: 2〜3時間

監視コマンド（30分ごとに確認）:
Get-Item "db\experiments\model_comparison\tail_ltr_catboost*" -ErrorAction SilentlyContinue
```

### 3. GPUメモリ警告の兆候
```
"less than 75% GPU memory available" → 重複プロセスを即確認
```

## 実験ロギング標準

### JSON 構造（実験ごと）
```json
{
  "run_id": "catboost_v2_YYYYMMDD_HHMMSS",
  "model": "CatBoostRanker",
  "target": "is_top2_within_expert",
  "features": ["roll7_total_diff", "lag7_digit_diff"],
  "windows": {"wed": "full_2025", "nonwed": "recent_60d"},
  "results": {
    "hit_at_1": 0.31,
    "hit_at_2": 0.58,
    "ndcg": 0.72,
    "lift_at_1": 2.2
  },
  "runtime_hours": 2.4,
  "timestamp": "YYYY-MM-DDTHH:MM:SS"
}
```

### JSONL インデックス（50件以上の検索用）
```
experiments/index.jsonl に各実験のサマリーを1行ずつ追記。
検索例:
  python -c "
  import json
  with open('experiments/index.jsonl') as f:
      for line in f:
          r = json.loads(line)
          if r['results']['hit_at_1'] > 0.3:
              print(r['run_id'], r['results'])
  "
```

### HTML レポートの固定セクション
```
1. 実験概要（モデル・ターゲット・特徴量リスト）
2. 評価結果（hit@1, hit@2, NDCG, lift@1）
3. エキスパート別ブレークダウン
4. 前回実験との比較（差分表示）
5. 次のアクション（改善候補）
```

### ループ内進捗報告（必須）
```python
for i, eval_date in enumerate(eval_dates):
    if i % 10 == 0:
        print(f"[{i}/{len(eval_dates)}] Processing {eval_date} ...")
```

## 進化の背景
5件のインスティンクトから抽出。
ml-experiment-management(3) + ml-execution(2)。
