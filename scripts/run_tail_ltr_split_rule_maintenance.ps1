$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo

$python = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
  throw "Python not found: $python"
}

$today = Get-Date -Format "yyyy-MM-dd"
$outputPrefix = Join-Path $repo "db\experiments\tail_ltr_split_rule_maintenance"

& $python -m ml.experiments.tail_ltr_split_rule_ops_suite run-maintenance `
  --output-prefix $outputPrefix `
  --seed 42 `
  --inverse-seeds "42" `
  --inverse-test-days 14 `
  --inverse-warmup-days 56 `
  --expected-groups "2F_N,3F_N,3F_A,2F_A" `
  --allowed-missing-groups "2F_A" `
  --min-group-days 60 `
  --a-weight 0.4 `
  --non-a-weight 1.3

Write-Host "Split-rule maintenance completed."
Write-Host "Check outputs under: $repo\db\experiments"
