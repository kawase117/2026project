param(
    [ValidateRange(0, 1000000)]
    [int]$MinGames = 2000,
    [ValidateRange(1000, 60000)]
    [int]$IntervalMs = 2500
)

$ErrorActionPreference = 'Stop'

$moduleDirectory = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $moduleDirectory)
$outputDirectory = Join-Path $moduleDirectory 'output'
$runtimeDirectory = Join-Path $moduleDirectory 'runtime'
$profile = Join-Path $runtimeDirectory 'site777_profile'
$collectorTemplate = Join-Path $moduleDirectory 'site777_graph_collect.js'
$collector = Join-Path $runtimeDirectory 'site777_graph_collect_runtime.js'
$exporter = Join-Path $moduleDirectory 'site777_graph_export.js'
$summaryPath = Join-Path $outputDirectory 'site777_graph_summary_filtered.json'
$dataPath = Join-Path $outputDirectory 'site777_graph_data_filtered.json'
$targetConfigPath = Join-Path $outputDirectory 'site777_graph_targets.json'
$fullDataPath = Join-Path $outputDirectory 'site777_full_data.json'
$targetPreparer = Join-Path $moduleDirectory 'site777_prepare_graph_targets.py'
$ocrScript = Join-Path $moduleDirectory 'site777_graph_ocr.ps1'
$analyzer = Join-Path $moduleDirectory 'site777_graph_analyze.py'
$ocrPath = Join-Path $outputDirectory 'site777_graph_ocr_filtered.json'
$metricsPath = Join-Path $outputDirectory 'site777_graph_metrics_filtered.json'
$priorAnalysisPath = Join-Path $outputDirectory 'site777_analysis_filtered.json'
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
$session = 'site777graphs'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

$prepareArgs = @(
    $targetPreparer,
    '--input', $fullDataPath,
    '--output', $targetConfigPath,
    '--min-games', $MinGames,
    '--interval-ms', $IntervalMs,
    '--prior-analysis', $priorAnalysisPath,
    '--prior-metrics', $metricsPath
)
& $python @prepareArgs
if ($LASTEXITCODE -ne 0) {
    throw "Graph target preparation failed: $LASTEXITCODE"
}
$targetConfig = Get-Content -LiteralPath $targetConfigPath -Raw | ConvertFrom-Json
$graphDirectory = Join-Path $runtimeDirectory $targetConfig.imageDirectory.Replace('/', '\')
New-Item -ItemType Directory -Path $graphDirectory -Force | Out-Null

$targetConfig.imageDirectory = $graphDirectory
$compactConfig = $targetConfig | ConvertTo-Json -Depth 12 -Compress
$collectorText = [System.IO.File]::ReadAllText($collectorTemplate, [System.Text.Encoding]::UTF8)
if (-not $collectorText.Contains('__SITE777_TARGET_CONFIG__')) {
    throw 'Graph collector template placeholder was not found.'
}
[System.IO.File]::WriteAllText(
    $collector,
    $collectorText.Replace('__SITE777_TARGET_CONFIG__', $compactConfig),
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

& $playwrightCli "-s=$session" open about:blank --browser chrome --headed --persistent --profile $profile
if ($LASTEXITCODE -ne 0) {
    throw "Playwright browser open failed: $LASTEXITCODE"
}

$complete = $false
$exitCode = 2
try {
    foreach ($batch in 1..20) {
        $result = & $playwrightCli --raw "-s=$session" run-code --filename $collector
        if ($LASTEXITCODE -ne 0) {
            throw "Collector batch $batch failed: $LASTEXITCODE"
        }
        $result | Set-Content -LiteralPath $summaryPath -Encoding utf8
        $summary = $result | ConvertFrom-Json

        $export = & $playwrightCli --raw "-s=$session" run-code --filename $exporter
        if ($LASTEXITCODE -ne 0) {
            throw "Collector export after batch $batch failed: $LASTEXITCODE"
        }
        [System.IO.File]::WriteAllText(
            $dataPath,
            ($export -join [Environment]::NewLine),
            [System.Text.UTF8Encoding]::new($false)
        )

        $ocrResult = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ocrScript -ImageDirectory $graphDirectory -OutputPath $ocrPath
        if ($LASTEXITCODE -ne 0) {
            throw "OCR after batch $batch failed: $LASTEXITCODE"
        }
        $ocrSummary = $ocrResult | ConvertFrom-Json

        $analysisResult = & $python $analyzer --ocr $ocrPath --graph-data $dataPath --target-config $targetConfigPath --output $metricsPath
        if ($LASTEXITCODE -ne 0) {
            throw "Graph analysis after batch $batch failed: $LASTEXITCODE"
        }
        $analysisSummary = $analysisResult | ConvertFrom-Json

        Write-Output (
            "batch={0} complete={1} models={2} collected={3}/{4} reused={5} total_targets={6} excluded={7} min_games={8} requests={9} restrictions={10} failures={11} ocr={12} diff_ok={13} diff_failed={14} stopped_at={15}" -f
            $batch,
            $summary.complete,
            $summary.completedModels,
            $summary.completedMachines,
            $summary.collectTargetCount,
            $summary.reuseCount,
            $summary.targetCount,
            $summary.excludedCount,
            $summary.graphMinGames,
            $summary.requestSeq,
            $summary.restrictions,
            $summary.failures,
            $ocrSummary.total,
            $analysisSummary.successful,
            $analysisSummary.failed,
            $summary.stoppedAt
        )

        if ($summary.complete) {
            $complete = $true
            $exitCode = 0
            break
        }
        if ($summary.stoppedAt -ne 'batch_limit') {
            $exitCode = 1
            break
        }
    }
}
finally {
    & $playwrightCli "-s=$session" close *> $null
}

if (-not $complete) {
    Write-Error 'Graph collection did not complete.'
}
exit $exitCode
