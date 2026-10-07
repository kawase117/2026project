param(
    [ValidateSet('max', 'higashiguchi')]
    [string]$Hall = 'max',
    [ValidateSet('Quick', 'Full')]
    [string]$Mode = 'Quick',
    [string[]]$Units = @(),
    [ValidateRange(1, 8)]
    [int]$Workers = 4,
    [ValidateRange(0, 10000)]
    [int]$RequestIntervalMs = 2500,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$moduleDirectory = $PSScriptRoot
$projectRoot = Split-Path -Parent (Split-Path -Parent $moduleDirectory)
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
$collector = Join-Path $moduleDirectory 'collector.py'
$arguments = @(
    $collector,
    '--hall', $Hall,
    '--mode', $Mode.ToLowerInvariant(),
    '--workers', [string]$Workers,
    '--request-interval-ms', [string]$RequestIntervalMs
)
if ($Units.Count -gt 0) {
    $arguments += '--units'
    $arguments += $Units
}
if ($Force) {
    $arguments += '--force'
}
& $python @arguments
exit $LASTEXITCODE
