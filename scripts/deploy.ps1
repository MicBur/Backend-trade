param(
    [string]$Configuration = "Release",
    [string]$QtRoot = "C:/Qt/6.9.2/msvc2022_64",
    [string]$DistDir = "dist",
    [switch]$Zip,
    [switch]$PruneMinimal
)

$ErrorActionPreference = 'Stop'
Write-Host "=== QtTradeFrontend Deploy Script ===" -ForegroundColor Cyan

# 1. Pfade
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$BuildDir = Join-Path $ProjectRoot 'build'
$BinDir = Join-Path $BuildDir $Configuration
$ExePath = Join-Path $BinDir 'QtTradeFrontend.exe'
$HiredisDll = Join-Path $BuildDir 'hiredis-1.3.0' | Join-Path -ChildPath $Configuration | Join-Path -ChildPath 'hiredis.dll'
$DeployTool = Join-Path $QtRoot 'bin/windeployqt.exe'
$Version = '0.7.0'
$CacheFile = Join-Path $BuildDir 'CMakeCache.txt'
if (Test-Path $CacheFile) {
    $verLine = Select-String -Path $CacheFile -Pattern '^QtTradeFrontend_VERSION:' -ErrorAction SilentlyContinue
    if ($verLine) { $Version = ($verLine.Line -split '=')[-1] }
}

if (!(Test-Path $ExePath)) { throw "Executable nicht gefunden: $ExePath. Bitte zuerst bauen." }
if (!(Test-Path $DeployTool)) { throw "windeployqt nicht gefunden unter $DeployTool" }

# 2. Dist vorbereiten
$DistPath = Join-Path $ProjectRoot $DistDir
if (Test-Path $DistPath) { Write-Host "Lösche alten Dist Ordner..."; Remove-Item -Recurse -Force $DistPath }
New-Item -ItemType Directory $DistPath | Out-Null

# 3. Kopiere Binaries
Copy-Item $ExePath $DistPath
if (Test-Path $HiredisDll) { Copy-Item $HiredisDll $DistPath } else { Write-Warning "hiredis.dll nicht gefunden ($HiredisDll)" }

# 4. windeployqt ausführen
Write-Host "Starte windeployqt..." -ForegroundColor Yellow
$QmlDir = Join-Path $ProjectRoot 'qml'
& $DeployTool --release --qmldir $QmlDir (Join-Path $DistPath 'QtTradeFrontend.exe') | Write-Host

# 4.5 Kopiere eigenes QML Modul
$FrontendModuleSrc = Join-Path $BuildDir 'Frontend'
$FrontendModuleDst = Join-Path $DistPath 'qml/Frontend'
if (Test-Path $FrontendModuleSrc) {
    Write-Host "Kopiere QML Modul Frontend..." -ForegroundColor Yellow
    Copy-Item -Recurse $FrontendModuleSrc $FrontendModuleDst
} else {
    Write-Warning "QML Modul nicht gefunden: $FrontendModuleSrc"
}

# 4.6 Kopiere QML Components
$ComponentsSrc = Join-Path $ProjectRoot 'qml/components'
$ComponentsDst = Join-Path $DistPath 'qml/components'
if (Test-Path $ComponentsSrc) {
    Write-Host "Kopiere QML Components..." -ForegroundColor Yellow
    Copy-Item -Recurse $ComponentsSrc $ComponentsDst
} else {
    Write-Warning "QML Components nicht gefunden: $ComponentsSrc"
}

# 5. Optional Pruning
if ($PruneMinimal) {
    Write-Host "Prune: Entferne ungenutzte Styles / Übersetzungen" -ForegroundColor Yellow
    $remove = @(
        'qml/QtQuick/Controls/Imagine',
        'qml/QtQuick/Controls/Material',
        'qml/QtQuick/Controls/Universal',
        'translations'
    )
    foreach ($rel in $remove) {
        $p = Join-Path $DistPath $rel
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

# 6. ZIP erstellen
if ($Zip) {
    $ZipName = "QtTradeFrontend-$Version-win64.zip"
    $ZipPath = Join-Path $ProjectRoot $ZipName
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Write-Host "Erzeuge Archiv $ZipName" -ForegroundColor Yellow
    Add-Type -AssemblyName 'System.IO.Compression.FileSystem'
    [System.IO.Compression.ZipFile]::CreateFromDirectory($DistPath, $ZipPath)
}

Write-Host "Fertig. Dist: $DistPath" -ForegroundColor Green
Write-Host "Version: $Version"
Write-Host "Start: pushd $DistDir; .\\QtTradeFrontend.exe --redis-port 6380" -ForegroundColor Cyan
