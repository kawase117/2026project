param(
    [switch]$Resume,
    [switch]$Pipeline,
    [ValidateRange(1, 120)]
    [int]$BatchModels = 24,
    [string]$RateLimiterUrl = ''
)

$ErrorActionPreference = 'Stop'
$moduleDirectory = $PSScriptRoot
$outputDirectory = Join-Path $moduleDirectory 'output'
$runtimeDirectory = Join-Path $moduleDirectory 'runtime'
$profile = Join-Path $runtimeDirectory 'site777_profile'
$collectorTemplate = Join-Path $moduleDirectory 'site777_full_collect_parallel.js'
$collector = Join-Path $runtimeDirectory 'site777_full_collect_parallel_runtime.js'
$exporter = Join-Path $moduleDirectory 'site777_export_parallel_collect.js'
$resetter = Join-Path $moduleDirectory 'site777_reset_parallel_collect.js'
$summaryPath = Join-Path $outputDirectory 'site777_full_summary.json'
$dataPath = Join-Path $outputDirectory 'site777_full_data.json'
$partialDataPath = Join-Path $outputDirectory 'site777_full_data_partial.json'
$runPath = Join-Path $outputDirectory 'site777_full_run_latest.json'
$session = 'site777fullparallel'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

$priorSourceText = 'null'
if (Test-Path -LiteralPath $dataPath) {
    $priorSourceText = [System.IO.File]::ReadAllText($dataPath, [System.Text.Encoding]::UTF8)
}
$collectorText = [System.IO.File]::ReadAllText($collectorTemplate, [System.Text.Encoding]::UTF8)
foreach ($placeholder in @(
    '__SITE777_PRIOR_SOURCE__',
    '__SITE777_FULL_BATCH_LIMIT__',
    '__SITE777_RATE_LIMITER_URL__'
)) {
    if (-not $collectorText.Contains($placeholder)) {
        throw "Full collector template placeholder was not found: $placeholder"
    }
}
$batchLimit = if ($Pipeline) { $BatchModels } else { 0 }
$limiterJson = $RateLimiterUrl | ConvertTo-Json -Compress
$collectorText = $collectorText.Replace('__SITE777_PRIOR_SOURCE__', $priorSourceText)
$collectorText = $collectorText.Replace('__SITE777_FULL_BATCH_LIMIT__', [string]$batchLimit)
$collectorText = $collectorText.Replace('__SITE777_RATE_LIMITER_URL__', $limiterJson)
[System.IO.File]::WriteAllText(
    $collector,
    $collectorText,
    [System.Text.UTF8Encoding]::new($false)
)

$cachedCli = Get-ChildItem -Path "$env:LOCALAPPDATA\npm-cache\_npx" -Recurse -Filter 'playwright-cli.cmd' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if ($null -eq $cachedCli) {
    throw 'Cached playwright-cli.cmd was not found.'
}
$playwrightCli = $cachedCli.FullName

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if (-not $Resume -and (Test-Path -LiteralPath $dataPath)) {
    $archiveName = Get-Date -Format 'yyyyMMdd-HHmmss'
    $archiveDirectory = Join-Path $outputDirectory "history\$archiveName-before-parallel-run"
    New-Item -ItemType Directory -Path $archiveDirectory -Force | Out-Null
    foreach ($path in @($dataPath, $summaryPath, $runPath)) {
        if (Test-Path -LiteralPath $path) {
            Copy-Item -LiteralPath $path -Destination $archiveDirectory
        }
    }
}
if (-not $Resume -and (Test-Path -LiteralPath $partialDataPath)) {
    Remove-Item -LiteralPath $partialDataPath -Force
}

& $playwrightCli "-s=$session" open about:blank --browser chrome --headed --persistent --profile $profile
if ($LASTEXITCODE -ne 0) {
    throw "Playwright browser open failed: $LASTEXITCODE"
}

$startedAt = [DateTime]::UtcNow
$summary = $null
$exitCode = 1
try {
    if (-not $Resume) {
        $resetResult = & $playwrightCli --raw "-s=$session" run-code --filename $resetter
        if ($LASTEXITCODE -ne 0) {
            throw "Fresh-state reset failed: $LASTEXITCODE"
        }
    }

    foreach ($batch in 1..50) {
        $summaryText = & $playwrightCli --raw "-s=$session" run-code --filename $collector
        if ($LASTEXITCODE -ne 0) {
            throw "Parallel collector batch $batch failed: $LASTEXITCODE"
        }
        $summary = $summaryText | ConvertFrom-Json
        [System.IO.File]::WriteAllText(
            $summaryPath,
            ($summaryText -join [Environment]::NewLine),
            [System.Text.UTF8Encoding]::new($false)
        )

        $exportText = & $playwrightCli --raw "-s=$session" run-code --filename $exporter
        if ($LASTEXITCODE -ne 0) {
            throw "Parallel collector export after batch $batch failed: $LASTEXITCODE"
        }
        [System.IO.File]::WriteAllText(
            $partialDataPath,
            ($exportText -join [Environment]::NewLine),
            [System.Text.UTF8Encoding]::new($false)
        )
        if ($summary.complete) {
            [System.IO.File]::WriteAllText(
                $dataPath,
                ($exportText -join [Environment]::NewLine),
                [System.Text.UTF8Encoding]::new($false)
            )
            break
        }
        if (-not $Pipeline -or $summary.stoppedAt -ne 'batch_limit') {
            break
        }
        Write-Output (
            "full_batch={0} models={1}/{2} machines={3}/{4} requests={5} restrictions={6} failures={7}" -f
            $batch,
            $summary.completedModels,
            $summary.expectedModels,
            $summary.completedMachines,
            $summary.expectedMachines,
            $summary.requestSeq,
            $summary.restrictions,
            $summary.failures
        )
    }
    $exitCode = if ($summary.ok -and $summary.complete) { 0 } else { 2 }
}
finally {
    & $playwrightCli "-s=$session" close *> $null
    $endedAt = [DateTime]::UtcNow
    $run = [ordered]@{
        startedAt = $startedAt.ToString('o')
        endedAt = $endedAt.ToString('o')
        elapsedMinutes = [math]::Round(($endedAt - $startedAt).TotalMinutes, 2)
        freshRun = -not $Resume
        navigationMode = 'two workers, normal list-to-menu-to-data Ctrl-click'
        userAgentMode = 'same UA and persistent profile'
        workerCount = 2
        sharedIntervalMs = 3000
        pipeline = [bool]$Pipeline
        pipelineBatchModels = if ($Pipeline) { $BatchModels } else { $null }
        sharedRateLimiter = if ($RateLimiterUrl) { $RateLimiterUrl } else { $null }
        highestReuseMode = 'same business date and every machine game count unchanged'
        directDeepNavigationAllowed = $false
        recoveryDelaysMs = @(0, 60000, 300000)
        summary = $summary
    }
    $run | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runPath -Encoding utf8
}

Get-Content -LiteralPath $runPath -Raw
exit $exitCode
