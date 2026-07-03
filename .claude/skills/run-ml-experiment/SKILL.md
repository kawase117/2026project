---
name: run-ml-experiment
description: LTR実験の安全な起動・ログ記録・監視の標準手順。walk-forward実行前・長時間ML実験の起動時に使用。
evolved_from:
  - duplicate-background-process-detection
  - catboost-walkforward-runtime-expectation
  - window-name-vs-feature-name-confusion
  - python-module-vs-script-execution
  - exp-structured-run-json
  - exp-html-fixed-sections
  - exp-jsonl-index-search
  - progress-reporting-required-in-all-loops
confidence: 0.93
---

# run-ml-experiment

LTR実験（tail_ltr_split_rule_nextday_gpu.py）を安全に起動し、ログを標準形式で保存する。

## 実行ステップ

### Step 1: 重複プロセス検出
```powershell
Get-WmiObject Win32_Process |
  Where-Object {$_.CommandLine -like "*tail_ltr*"} |
  Select-Object ProcessId, CommandLine
```
重複が1件でもあれば実行を中止。最古のPIDを残して他をkill。

### Step 2: 引数の事前検証
```
確認項目:
  [ ] --windows-wed / --windows-nonwed に有効名を指定しているか
      有効: full_2025 / recent_60d / recent_90d / opening_early / regime1_full
      無効: roll28, roll7 など（特徴量名は使えない）
  [ ] python -m 形式で実行しているか（直接実行はModuleNotFoundError）
  [ ] is_top2 は within-expert になっているか
```

### Step 3: 実行（バックグラウンド）
```powershell
Start-Process python `
  -ArgumentList "-m ml.last_digit.tail_ltr_split_rule_nextday_gpu --windows-wed full_2025 --windows-nonwed recent_60d" `
  -NoNewWindow -RedirectStandardOutput "logs\exp_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
```

### Step 4: 監視（30分ごと）
```powershell
# 出力ファイル確認
Get-Item "db\experiments\model_comparison\tail_ltr_catboost*" -EA SilentlyContinue

# GPU状態確認
Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -like "*tail_ltr*"} | Measure-Object
```

### Step 5: 完了後のログ記録
```json
// experiments/index.jsonl に追記
{
  "run_id": "catboost_YYYYMMDD_HHMMSS",
  "windows": {"wed": "full_2025", "nonwed": "recent_60d"},
  "results": {"hit_at_1": 0.0, "hit_at_2": 0.0, "ndcg": 0.0, "lift_at_1": 0.0},
  "runtime_hours": 0.0,
  "timestamp": "YYYY-MM-DDTHH:MM:SS"
}
```

## 完了の目安
GPU独占状態: 2〜3時間。
出力ファイル（_testperiod_daily_*.csv）が生成されたら正常完了。

## 進化の背景
8件のインスティンクトから抽出。
ml-execution(2) + ml-pipeline-configuration(3) + ml-experiment-management(3)。
