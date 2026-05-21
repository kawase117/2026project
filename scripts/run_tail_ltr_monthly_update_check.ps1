$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo

$python = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "Python not found: $python"
}

$today = Get-Date -Format "yyyy-MM-dd"
$outputPrefix = Join-Path $repo "db\experiments\tail_ltr_monthly_update_check_$today"

& $python -m ml.experiments.tail_ltr_wed_ops_suite monthly-update-check `
  --run-date $today `
  --output-prefix $outputPrefix `
  --eval-days 56 `
  --seeds "42,77,123,202,303,404,505,606" `
  --test-days 14 `
  --min-train-days-wed 12 `
  --min-train-days-nonwed 42 `
  --inc-cadence fold `
  --inc-windows-wed "full_2025" `
  --inc-lambdas-wed "0.75,1.0,1.25" `
  --inc-q-grid-wed "0.0,0.1,0.2,0.3,0.4" `
  --inc-windows-nonwed "recent_60d,full_2025" `
  --inc-lambdas-nonwed "0.75,1.0,1.25" `
  --inc-q-grid-nonwed "0.0,0.1,0.2,0.3,0.4,0.5,0.6" `
  --ch-cadence fold `
  --ch-windows-wed "full_2025,recent_60d" `
  --ch-lambdas-wed "0.5,0.75,1.0,1.25,1.5" `
  --ch-q-grid-wed "0.0,0.1,0.2,0.3,0.4,0.5" `
  --ch-windows-nonwed "recent_60d,full_2025,regime2_only" `
  --ch-lambdas-nonwed "0.5,0.75,1.0,1.25,1.5" `
  --ch-q-grid-nonwed "0.0,0.1,0.2,0.3,0.4,0.5,0.6" `
  --min-mean-gain-for-update 5.0 `
  --min-challenger-p-gt0 0.95 `
  --degrade-ci-low 0.0 `
  --degrade-p-gt0 0.9

Write-Host "Monthly update check completed:"
Write-Host "$outputPrefix.json"
