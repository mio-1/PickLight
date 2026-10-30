param([switch]$Preview)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project

$distRoot = if ($Preview) { 'dist\Preview' } else { 'dist' }
$packageDir = Join-Path $distRoot 'PickLight'

if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Create .venv and install the project before building.'
}

& .\tools\setup-exiftool.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$releaseAssets = & .\.venv\Scripts\python.exe tools\stage_release_assets.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $project 'build'))
$stagedAssets = [System.IO.Path]::GetFullPath($releaseAssets.Trim())
if (-not $stagedAssets.StartsWith($buildRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Staged assets are outside the build directory: $stagedAssets"
}
$exiftoolAssets = Join-Path $project 'vendor\exiftool'
$iconPath = Join-Path $project 'assets\picklight.ico'

try {
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed `
        --name PickLight --paths src --icon $iconPath --distpath $distRoot --specpath build `
        --add-data "$stagedAssets;assets" `
        --add-data "$exiftoolAssets;exiftool" src\picklight\app.py
    $buildExitCode = $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $stagedAssets -Recurse -Force -ErrorAction Stop
}
if ($buildExitCode -ne 0) { exit $buildExitCode }

Copy-Item -LiteralPath LICENSE -Destination (Join-Path $packageDir 'LICENSE') -Force
Copy-Item -LiteralPath README.md -Destination (Join-Path $packageDir 'README.md') -Force
Copy-Item -LiteralPath docs -Destination (Join-Path $packageDir 'docs') -Recurse -Force
New-Item -ItemType Directory -Path (Join-Path $packageDir 'assets') -Force | Out-Null
Copy-Item -LiteralPath assets\screenshots -Destination (Join-Path $packageDir 'assets\screenshots') -Recurse -Force
Copy-Item -LiteralPath assets\picklight.png -Destination (Join-Path $packageDir 'assets\picklight.png') -Force
Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction Stop
Write-Host "Built $packageDir\PickLight.exe"
