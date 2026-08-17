param()

$ErrorActionPreference = 'Stop'
$moduleDirectory = $PSScriptRoot
$outputDirectory = Join-Path $moduleDirectory 'output'
$runtimeDirectory = Join-Path $moduleDirectory 'runtime'
$dataPath = Join-Path $outputDirectory 'site777_full_data.json'
$templatePath = Join-Path $moduleDirectory 'site777_update_gate.js'
$runtimePath = Join-Path $runtimeDirectory 'site777_update_gate_runtime.js'
$resultPath = Join-Path $outputDirectory 'site777_update_gate_latest.json'
$historyPath = Join-Path $outputDirectory 'site777_update_gate_history.jsonl'
$profile = Join-Path $runtimeDirectory 'site777_profile'
$session = 'site777updategate'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

$config = [ordered]@{ mdc = $null; modelName = $null; listPage = 1; previousUpdateTime = $null }
if (Test-Path -LiteralPath $dataPath) {
    $prior = Get-Content -LiteralPath $dataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $models = @($prior.models.PSObject.Properties.Value)
    $latestSavedTime = @($models | ForEach-Object { [string]$_.jackpot.updateTime } | Sort-Object -Descending)[0]
    $target = @(
        $models |
            Where-Object { [string]$_.jackpot.updateTime -eq $latestSavedTime } |
            Sort-Object machineCount -Descending
    )[0]
    $config.mdc = [string]$target.mdc
    $config.modelName = [string]$target.name
    $config.listPage = [int]$target.listPage
    $config.previousUpdateTime = [string]$target.jackpot.updateTime
}
if (-not $config.mdc) { throw 'Update gate requires a prior complete snapshot.' }

$template = [System.IO.File]::ReadAllText($templatePath, [System.Text.Encoding]::UTF8)
$configJson = $config | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText(
    $runtimePath,
    $template.Replace('__SITE777_UPDATE_GATE_CONFIG__', $configJson),
    [System.Text.UTF8Encoding]::new($false)
)
$cachedCli = Get-ChildItem -Path "$env:LOCALAPPDATA\npm-cache\_npx" -Recurse -Filter 'playwright-cli.cmd' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($null -eq $cachedCli) { throw 'Cached playwright-cli.cmd was not found.' }

# PowerShell decodes native command output with the console code page (cp932 here),
# which silently corrupts Japanese model names and can break the captured JSON.
# The other collectors already pin this; the update gate was the one that did not.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

try {
    & $cachedCli.FullName "-s=$session" open about:blank --browser chrome --headed --persistent --profile $profile | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Update-gate browser open failed: $LASTEXITCODE" }
    $text = & $cachedCli.FullName --raw "-s=$session" run-code --filename $runtimePath
    if ($LASTEXITCODE -ne 0) { throw "Update-gate check failed: $LASTEXITCODE" }
    [System.IO.File]::WriteAllText($resultPath, ($text -join [Environment]::NewLine), [System.Text.UTF8Encoding]::new($false))
    $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $historyLine = $result | ConvertTo-Json -Compress -Depth 8
    [System.IO.File]::AppendAllText($historyPath, $historyLine + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}
finally {
    & $cachedCli.FullName "-s=$session" close *> $null
}
Get-Content -LiteralPath $resultPath -Raw
