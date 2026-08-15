param(
    [ValidateRange(0, 1000000)]
    [int]$MinGames = 2000,
    [ValidateRange(1000, 60000)]
    [int]$IntervalMs = 2500,
    [Parameter(Mandatory = $true)]
    [string]$InputPath,
    [string]$RateLimiterUrl = ''
)

$ErrorActionPreference = 'Stop'
$moduleDirectory = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $moduleDirectory)
$outputDirectory = Join-Path $moduleDirectory 'output'
$runtimeDirectory = Join-Path $moduleDirectory 'runtime'
$profile = Join-Path $runtimeDirectory 'site777_graph_profile'
$collectorTemplate = Join-Path $moduleDirectory 'site777_graph_collect.js'
$collector = Join-Path $runtimeDirectory 'site777_graph_pipeline_runtime.js'
$exporter = Join-Path $moduleDirectory 'site777_graph_export.js'
$summaryPath = Join-Path $outputDirectory 'site777_graph_summary_filtered.json'
$dataPath = Join-Path $outputDirectory 'site777_graph_data_filtered.json'
$targetConfigPath = Join-Path $outputDirectory 'site777_graph_targets.json'
$targetPreparer = Join-Path $moduleDirectory 'site777_prepare_graph_targets.py'
$ocrScript = Join-Path $moduleDirectory 'site777_graph_ocr.ps1'
$analyzer = Join-Path $moduleDirectory 'site777_graph_analyze.py'
$ocrPath = Join-Path $outputDirectory 'site777_graph_ocr_filtered.json'
$metricsPath = Join-Path $outputDirectory 'site777_graph_metrics_filtered.json'
$priorAnalysisPath = Join-Path $outputDirectory 'site777_analysis_filtered.json'
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
$session = 'site777graphspipeline'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

$cachedCli = Get-ChildItem -Path "$env:LOCALAPPDATA\npm-cache\_npx" -Recurse -Filter 'playwright-cli.cmd' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Select-Object -First 1
if ($null -eq $cachedCli) {
    throw 'Cached playwright-cli.cmd was not found.'
}
$playwrightCli = $cachedCli.FullName
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

while (-not (Test-Path -LiteralPath $InputPath)) {
    Start-Sleep -Milliseconds 250
}

& $playwrightCli "-s=$session" open about:blank --browser chrome --headed --persistent --profile $profile
if ($LASTEXITCODE -ne 0) {
    throw "Playwright browser open failed: $LASTEXITCODE"
}

$complete = $false
$exitCode = 2
$lastSourceUpdatedAt = $null
$graphDirectory = $null
$ocrJob = $null
try {
    foreach ($batch in 1..100) {
        $source = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $prepareArgs = @(
            $targetPreparer,
            '--input', $InputPath,
            '--output', $targetConfigPath,
            '--min-games', $MinGames,
            '--interval-ms', $IntervalMs,
            '--prior-analysis', $priorAnalysisPath,
            '--prior-metrics', $metricsPath,
            '--allow-incomplete'
        )
        & $python @prepareArgs | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Graph target preparation failed: $LASTEXITCODE"
        }
        $targetConfig = Get-Content -LiteralPath $targetConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $graphDirectory = Join-Path $runtimeDirectory $targetConfig.imageDirectory.Replace('/', '\')
        New-Item -ItemType Directory -Path $graphDirectory -Force | Out-Null

        $runtimeConfig = $targetConfig.PSObject.Copy()
        $runtimeConfig.imageDirectory = $graphDirectory
        $runtimeConfig | Add-Member -NotePropertyName rateLimiterUrl -NotePropertyValue $RateLimiterUrl -Force
        $compactConfig = $runtimeConfig | ConvertTo-Json -Depth 12 -Compress
        $collectorText = [System.IO.File]::ReadAllText($collectorTemplate, [System.Text.Encoding]::UTF8)
        if (-not $collectorText.Contains('__SITE777_TARGET_CONFIG__')) {
            throw 'Graph collector template placeholder was not found.'
        }
        [System.IO.File]::WriteAllText(
            $collector,
            $collectorText.Replace('__SITE777_TARGET_CONFIG__', $compactConfig),
            [System.Text.UTF8Encoding]::new($false)
        )

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

        Write-Output (
            "graph_batch={0} source_complete={1} models={2} collected={3}/{4} reused={5} targets={6} requests={7} restrictions={8} failures={9} stopped_at={10}" -f
            $batch,
            $targetConfig.sourceComplete,
            $summary.completedModels,
            $summary.completedMachines,
            $summary.collectTargetCount,
            $summary.reuseCount,
            $summary.targetCount,
            $summary.requestSeq,
            $summary.restrictions,
            $summary.failures,
            $summary.stoppedAt
        )

        if ($null -ne $ocrJob -and $ocrJob.State -in @('Completed', 'Failed', 'Stopped')) {
            if ($ocrJob.State -eq 'Failed') {
                $ocrError = Receive-Job -Job $ocrJob -Keep 2>&1 | Out-String
                throw "Background OCR failed.`n$ocrError"
            }
            Receive-Job -Job $ocrJob | Out-Null
            Remove-Job -Job $ocrJob -Force
            $ocrJob = $null
        }
        if ($null -eq $ocrJob) {
            $ocrJob = Start-Job -ArgumentList @($ocrScript, $graphDirectory, $ocrPath) -ScriptBlock {
                param($scriptPath, $imagePath, $outputPath)
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath -ImageDirectory $imagePath -OutputPath $outputPath
                if ($LASTEXITCODE -ne 0) { throw "OCR failed: $LASTEXITCODE" }
            }
        }

        if ($targetConfig.sourceComplete -and $summary.complete) {
            $complete = $true
            $exitCode = 0
            break
        }
        if ($summary.stoppedAt -notin @('batch_limit', 'source_incomplete', 'completion_check')) {
            $exitCode = 1
            break
        }
        if ($summary.stoppedAt -eq 'source_incomplete') {
            $lastSourceUpdatedAt = $source.updatedAt
            do {
                Start-Sleep -Milliseconds 500
                $nextSource = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
            } while (-not $nextSource.complete -and $nextSource.updatedAt -eq $lastSourceUpdatedAt)
        }
    }
}
finally {
    & $playwrightCli "-s=$session" close *> $null
}

if (-not $complete) {
    if ($null -ne $ocrJob) {
        if ($ocrJob.State -in @('Running', 'NotStarted')) { Stop-Job -Job $ocrJob }
        Remove-Job -Job $ocrJob -Force -ErrorAction SilentlyContinue
    }
    Write-Error 'Pipeline graph collection did not complete.'
    exit $exitCode
}

if ($null -ne $ocrJob) {
    Wait-Job -Job $ocrJob | Out-Null
    if ($ocrJob.State -eq 'Failed') {
        $ocrError = Receive-Job -Job $ocrJob -Keep 2>&1 | Out-String
        Remove-Job -Job $ocrJob -Force -ErrorAction SilentlyContinue
        throw "Background OCR failed.`n$ocrError"
    }
    Receive-Job -Job $ocrJob | Out-Null
    Remove-Job -Job $ocrJob -Force
}

$ocrResult = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ocrScript -ImageDirectory $graphDirectory -OutputPath $ocrPath
if ($LASTEXITCODE -ne 0) {
    throw "Final OCR failed: $LASTEXITCODE"
}
$ocrSummary = $ocrResult | ConvertFrom-Json
$analysisResult = & $python $analyzer --ocr $ocrPath --graph-data $dataPath --target-config $targetConfigPath --output $metricsPath
if ($LASTEXITCODE -ne 0) {
    throw "Final graph analysis failed: $LASTEXITCODE"
}
$analysisSummary = $analysisResult | ConvertFrom-Json
Write-Output (
    "graph_complete collected={0} reused={1} targets={2} ocr={3} diff_ok={4} diff_failed={5}" -f
    $summary.completedMachines,
    $summary.reuseCount,
    $summary.targetCount,
    $ocrSummary.total,
    $analysisSummary.successful,
    $analysisSummary.failed
)
exit 0
