param([string]$JavaHome = 'C:/Program Files/Android/Android Studio/jbr')
$ErrorActionPreference = 'Stop'
$appRoot = Split-Path $PSScriptRoot -Parent
$compiler = Join-Path $JavaHome 'bin/javac.exe'
$runner = Join-Path $JavaHome 'bin/java.exe'
$source = Join-Path $appRoot 'android/app/src/main/java/jp/local/pachiboledger/Accounting.java'
$test = Join-Path $PSScriptRoot 'AccountingTest.java'
$tagSource = Join-Path $appRoot 'android/app/src/main/java/jp/local/pachiboledger/TagFilter.java'
$tagTest = Join-Path $PSScriptRoot 'TagFilterTest.java'
$workSource = Join-Path $appRoot 'android/app/src/main/java/jp/local/pachiboledger/PachinkoWork.java'
$workTest = Join-Path $PSScriptRoot 'PachinkoWorkTest.java'
$output = Join-Path $appRoot 'test-build'
& $compiler -encoding UTF-8 -d $output $source $test $tagSource $tagTest $workSource $workTest
if ($LASTEXITCODE -ne 0) { throw 'Accounting compilation failed' }
& $runner -cp $output jp.local.pachiboledger.AccountingTest
if ($LASTEXITCODE -ne 0) { throw 'Accounting tests failed' }
& $runner -cp $output jp.local.pachiboledger.TagFilterTest
if ($LASTEXITCODE -ne 0) { throw 'Tag tests failed' }
& $runner -cp $output jp.local.pachiboledger.PachinkoWorkTest
if ($LASTEXITCODE -ne 0) { throw 'Pachinko work tests failed' }
