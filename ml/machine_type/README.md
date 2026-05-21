# Machine-Type ML

## Purpose

`machine_name` 単位で、次日予測と月次信頼度チェックを行う実験パッケージです。  
ラベルは `avg_diff_coins` の生順位ではなく、`machine_count` を使った縮約スコア順位で生成します。

## Commands

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --help
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --help
```

## Typical Run

```powershell
venv\Scripts\python.exe -m ml.machine_type.machine_type_nextday --alpha 5.0
venv\Scripts\python.exe -m ml.machine_type.machine_type_monthly_check --alpha 5.0 --eval-days 60
```

## Output Directory

All outputs are written under `ml/machine_type/reports/`.

## Key Artifacts

- `machine_type_nextday_prediction.csv`
  - next-day ranking (`nextday_rank`, `ensemble_score`) and target probabilities
- `machine_type_nextday_prediction.json`
  - run summary and target thresholds
- `machine_type_nextday_prediction_audit_report.json`
  - data quality and schema audit summary
- `machine_type_reliability_daily.csv`
  - daily `F1`, `Recall`, `Precision`, `Hit@1/2/3/5`, base rate
- `machine_type_reliability_monthly.csv`
  - monthly aggregated reliability with `is_thursday` split

## Thursday Interpretation

`*_reliability_daily.csv` と `*_reliability_monthly.csv` には `is_thursday` 列を含めています。  
v1 は単一モデルで学習し、木曜と非木曜の差分は評価レポートで確認する方針です。

