param(
    [string]$ImageDirectory = (Join-Path $PSScriptRoot 'runtime\site777_graphs'),
    [string]$OutputPath = (Join-Path $PSScriptRoot 'output\site777_graph_ocr.json')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await-WinRt {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType
    )

    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

function Read-GraphOcr {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Engine
    )

    $stream = $null
    $bitmap = $null
    try {
        $storageFile = Await-WinRt `
            ([Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]::GetFileFromPathAsync($Path)) `
            ([Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime])
        $stream = Await-WinRt `
            ($storageFile.OpenAsync([Windows.Storage.FileAccessMode]::Read)) `
            ([Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime])
        $decoder = Await-WinRt `
            ([Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]::CreateAsync($stream)) `
            ([Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime])
        $bitmap = Await-WinRt `
            ($decoder.GetSoftwareBitmapAsync()) `
            ([Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime])
        $result = Await-WinRt `
            ($Engine.RecognizeAsync($bitmap)) `
            ([Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType = WindowsRuntime])

        return [ordered]@{
            text = $result.Text
            lines = @($result.Lines | ForEach-Object {
                [ordered]@{
                    text = $_.Text
                    words = @($_.Words | ForEach-Object {
                        [ordered]@{
                            text = $_.Text
                            x = [math]::Round($_.BoundingRect.X, 2)
                            y = [math]::Round($_.BoundingRect.Y, 2)
                            width = [math]::Round($_.BoundingRect.Width, 2)
                            height = [math]::Round($_.BoundingRect.Height, 2)
                        }
                    })
                }
            })
        }
    }
    finally {
        if ($null -ne $bitmap) { $bitmap.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
    }
}

$existing = @{}
if (Test-Path -LiteralPath $OutputPath) {
    $saved = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
    foreach ($item in @($saved.items)) {
        $existing[$item.fileName] = $item
    }
}

$language = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]::new('en-US')
$engine = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]::TryCreateFromLanguage($language)
if ($null -eq $engine) {
    throw 'Windows OCR engine (en-US) is unavailable.'
}

$processed = 0
$failed = 0
$files = Get-ChildItem -LiteralPath $ImageDirectory -Filter '*.png' -File |
    Where-Object { $_.Name -notlike 'test_*' } |
    Sort-Object Name

foreach ($file in $files) {
    $stamp = $file.LastWriteTimeUtc.ToString('o')
    $old = $existing[$file.Name]
    if ($null -ne $old -and $old.length -eq $file.Length -and $old.lastWriteTimeUtc -eq $stamp) {
        continue
    }

    try {
        $ocr = Read-GraphOcr -Path $file.FullName -Engine $engine
        $existing[$file.Name] = [ordered]@{
            fileName = $file.Name
            length = $file.Length
            lastWriteTimeUtc = $stamp
            processedAt = [DateTime]::UtcNow.ToString('o')
            error = $null
            text = $ocr.text
            lines = $ocr.lines
        }
        $processed++
    }
    catch {
        $existing[$file.Name] = [ordered]@{
            fileName = $file.Name
            length = $file.Length
            lastWriteTimeUtc = $stamp
            processedAt = [DateTime]::UtcNow.ToString('o')
            error = $_.Exception.Message
            text = $null
            lines = @()
        }
        $failed++
    }
}

$items = @(
    $files |
        ForEach-Object { $existing[$_.Name] } |
        Where-Object { $null -ne $_ } |
        Sort-Object fileName
)
$document = [ordered]@{
    version = 1
    updatedAt = [DateTime]::UtcNow.ToString('o')
    imageDirectory = $ImageDirectory
    total = $items.Count
    successful = @($items | Where-Object { $null -eq $_.error }).Count
    failed = @($items | Where-Object { $null -ne $_.error }).Count
    processedThisRun = $processed
    items = $items
}

$temporaryPath = "$OutputPath.tmp"
$document | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporaryPath -Encoding utf8
Move-Item -LiteralPath $temporaryPath -Destination $OutputPath -Force

[pscustomobject]@{
    total = $document.total
    successful = $document.successful
    failed = $document.failed
    processedThisRun = $processed
} | ConvertTo-Json -Compress
