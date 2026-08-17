param(
    [ValidateRange(0, 1000000)]
    [int]$MinGames = 2000,
    [ValidateRange(1000, 60000)]
    [int]$GraphIntervalMs = 2500,
    [ValidateRange(1000, 60000)]
    [int]$GlobalIntervalMs = 2500,
    [ValidateRange(1, 120)]
    [int]$PipelineBatchModels = 24,
    [switch]$Sequential,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$moduleDirectory = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $moduleDirectory)
$outputDirectory = Join-Path $moduleDirectory 'output'
$runtimeDirectory = Join-Path $moduleDirectory 'runtime'
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
$fullRunner = Join-Path $moduleDirectory 'run_site777_full_collect_parallel.ps1'
$updateGateRunner = Join-Path $moduleDirectory 'run_site777_update_gate.ps1'
$updateGateOutput = Join-Path $outputDirectory 'site777_update_gate_latest.json'
$graphRunner = Join-Path $moduleDirectory 'run_site777_graph_collect.ps1'
$graphPipelineRunner = Join-Path $moduleDirectory 'run_site777_graph_pipeline.ps1'
$rateLimiter = Join-Path $moduleDirectory 'site777_rate_limiter.py'
$analyzer = Join-Path $moduleDirectory 'site777_analyze.py'
$mobileBuilder = Join-Path $moduleDirectory 'site777_mobile_report.py'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$fullData = Join-Path $outputDirectory 'site777_full_data.json'
$partialFullData = Join-Path $outputDirectory 'site777_full_data_partial.json'
$graphMetrics = Join-Path $outputDirectory 'site777_graph_metrics_filtered.json'
$analysisJson = Join-Path $outputDirectory 'site777_analysis_filtered.json'
$report = Join-Path $outputDirectory 'site777_analysis_report_filtered.md'
$singleReport = Join-Path $outputDirectory 'site777_single_machine_report_filtered.md'
$tailReport = Join-Path $outputDirectory 'site777_last_digit_report_filtered.md'
$threeMachineReport = Join-Path $outputDirectory 'site777_three_machine_report_filtered.md'
$cornerReport = Join-Path $outputDirectory 'site777_corner_report_filtered.md'
$mobileReport = Join-Path $outputDirectory 'site777_mobile_report.html'
$runReport = Join-Path $outputDirectory 'site777_complete_run_latest.json'

$startedAt = [DateTime]::UtcNow
$stages = [ordered]@{}

if (-not $Force -and (Test-Path -LiteralPath $fullData)) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updateGateRunner | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Update gate failed: $LASTEXITCODE" }
    $gate = Get-Content -LiteralPath $updateGateOutput -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $gate.ok) { throw "Update gate could not verify the site update." }
    if (-not $gate.updated) {
        $skipped = [ordered]@{
            version = 3
            startedAt = $startedAt.ToString('o')
            endedAt = [DateTime]::UtcNow.ToString('o')
            skipped = $true
            skipReason = 'site_update_time_unchanged'
            updateGate = $gate
        }
        $skipped | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runReport -Encoding UTF8
        Get-Content -LiteralPath $runReport -Raw
        exit 0
    }
}

if ($Sequential) {
    $stageStart = [DateTime]::UtcNow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fullRunner
    if ($LASTEXITCODE -ne 0) { throw "Full collection failed: $LASTEXITCODE" }
    $stages.fullCollectionMinutes = [math]::Round(([DateTime]::UtcNow - $stageStart).TotalMinutes, 2)

    $stageStart = [DateTime]::UtcNow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $graphRunner -MinGames $MinGames -IntervalMs $GraphIntervalMs
    if ($LASTEXITCODE -ne 0) { throw "Graph collection failed: $LASTEXITCODE" }
    $stages.graphCollectionMinutes = [math]::Round(([DateTime]::UtcNow - $stageStart).TotalMinutes, 2)
} else {
    if (Test-Path -LiteralPath $partialFullData) {
        Remove-Item -LiteralPath $partialFullData -Force
    }
    $readyFile = Join-Path $runtimeDirectory 'site777_rate_limiter_ready.json'
    if (Test-Path -LiteralPath $readyFile) {
        Remove-Item -LiteralPath $readyFile -Force
    }
    $rateProcess = $null
    $fullJob = $null
    $graphJob = $null
    $stageStart = [DateTime]::UtcNow
    try {
        $rateProcess = Start-Process -FilePath $python -ArgumentList @(
            $rateLimiter,
            '--interval-ms', $GlobalIntervalMs,
            '--port', 0,
            '--ready-file', $readyFile
        ) -WindowStyle Hidden -PassThru
        $readyDeadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path -LiteralPath $readyFile)) {
            if ([DateTime]::UtcNow -ge $readyDeadline) {
                throw 'Shared rate limiter did not become ready.'
            }
            Start-Sleep -Milliseconds 100
        }
        $limiterInfo = Get-Content -LiteralPath $readyFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $limiterUrl = [string]$limiterInfo.url

        $fullJob = Start-Job -ArgumentList @($fullRunner, $PipelineBatchModels, $limiterUrl) -ScriptBlock {
            param($runner, $batchModels, $url)
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner -Pipeline -BatchModels $batchModels -RateLimiterUrl $url
            if ($LASTEXITCODE -ne 0) { throw "Full pipeline failed: $LASTEXITCODE" }
        }
        $graphJob = Start-Job -ArgumentList @(
            $graphPipelineRunner,
            $MinGames,
            $GraphIntervalMs,
            $partialFullData,
            $limiterUrl
        ) -ScriptBlock {
            param($runner, $minGames, $intervalMs, $inputPath, $url)
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner -MinGames $minGames -IntervalMs $intervalMs -InputPath $inputPath -RateLimiterUrl $url
            if ($LASTEXITCODE -ne 0) { throw "Graph pipeline failed: $LASTEXITCODE" }
        }

        $jobs = @($fullJob, $graphJob)
        while (@($jobs | Where-Object State -in @('Running', 'NotStarted')).Count -gt 0) {
            Wait-Job -Job $jobs -Any -Timeout 2 | Out-Null
            $failed = @($jobs | Where-Object State -eq 'Failed')
            if ($failed.Count -gt 0) {
                $jobs | Where-Object State -in @('Running', 'NotStarted') | Stop-Job
                $failedOutput = $failed | Receive-Job -Keep 2>&1 | Out-String
                throw "Site777 pipeline worker failed.`n$failedOutput"
            }
        }
        $pipelineOutput = $jobs | Receive-Job 2>&1
        $pipelineOutput | ForEach-Object { Write-Output $_ }
        if (@($jobs | Where-Object State -ne 'Completed').Count -gt 0) {
            throw 'Site777 pipeline did not complete.'
        }
        $stages.pipelineMinutes = [math]::Round(([DateTime]::UtcNow - $stageStart).TotalMinutes, 2)
        $stages.sharedIntervalMs = $GlobalIntervalMs
        $stages.pipelineBatchModels = $PipelineBatchModels
    }
    finally {
        foreach ($job in @($fullJob, $graphJob)) {
            if ($null -ne $job) {
                if ($job.State -in @('Running', 'NotStarted')) { Stop-Job -Job $job }
                Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
            }
        }
        if ($null -ne $rateProcess -and -not $rateProcess.HasExited) {
            Stop-Process -Id $rateProcess.Id -Force
        }
    }
}

$stageStart = [DateTime]::UtcNow
& $python $analyzer `
    --input $fullData `
    --graph-input $graphMetrics `
    --json-output $analysisJson `
    --report-output $report `
    --single-report-output $singleReport `
    --tail-report-output $tailReport `
    --three-machine-report-output $threeMachineReport `
    --corner-report-output $cornerReport `
    --reference-db (Join-Path $projectRoot 'db\楽園蒲田店.db')
if ($LASTEXITCODE -ne 0) { throw "Analysis failed: $LASTEXITCODE" }
& $python $mobileBuilder --input $analysisJson --output $mobileReport
if ($LASTEXITCODE -ne 0) { throw "Mobile report failed: $LASTEXITCODE" }
$stages.analysisAndReportMinutes = [math]::Round(([DateTime]::UtcNow - $stageStart).TotalMinutes, 2)

# Fail with a clear message instead of an exception right after a successful run.
foreach ($required in @($fullData, $graphMetrics, $analysisJson)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Run summary input is missing: $required"
    }
}
$source = Get-Content -LiteralPath $fullData -Raw -Encoding UTF8 | ConvertFrom-Json
$metrics = Get-Content -LiteralPath $graphMetrics -Raw -Encoding UTF8 | ConvertFrom-Json
$analysis = Get-Content -LiteralPath $analysisJson -Raw -Encoding UTF8 | ConvertFrom-Json
$endedAt = [DateTime]::UtcNow
$document = [ordered]@{
    version = 3
    skipped = $false
    startedAt = $startedAt.ToString('o')
    endedAt = $endedAt.ToString('o')
    elapsedMinutes = [math]::Round(($endedAt - $startedAt).TotalMinutes, 2)
    minGames = $MinGames
    graphIntervalMs = $GraphIntervalMs
    pipeline = -not [bool]$Sequential
    globalIntervalMs = if ($Sequential) { $null } else { $GlobalIntervalMs }
    stages = $stages
    full = [ordered]@{
        complete = $source.complete
        models = $source.expectedModelCount
        machines = $source.expectedMachineCount
        requests = $source.requestSeq
        restrictions = @($source.restrictionEvents).Count
        failures = @($source.failures).Count
        highestCollectedModels = @($source.models.PSObject.Properties.Value | Where-Object { -not $_.highest.reused }).Count
        highestReusedModels = @($source.models.PSObject.Properties.Value | Where-Object { $_.highest.reused }).Count
    }
    graph = [ordered]@{
        complete = $metrics.sourceComplete
        targets = $metrics.targetCount
        collected = $metrics.collectedCount
        reused = $metrics.reuseCount
        successful = $metrics.successful
        failed = $metrics.failed
    }
    analysis = [ordered]@{
        models = $analysis.model_count
        machines = $analysis.machine_count
        eligible = $analysis.graph_eligible_count
        diffValid = $analysis.diff_valid_count
    }
    outputs = [ordered]@{
        mobileReport = $mobileReport
        analysisJson = $analysisJson
        modelReport = $report
        singleReport = $singleReport
        tailReport = $tailReport
        threeMachineReport = $threeMachineReport
        cornerReport = $cornerReport
    }
}
$document | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runReport -Encoding UTF8
Get-Content -LiteralPath $runReport -Raw
