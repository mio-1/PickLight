param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Release version must be MAJOR.MINOR.PATCH: $Version"
}

$projectVersion = & .\.venv\Scripts\python.exe -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
if ($LASTEXITCODE -ne 0 -or $projectVersion.Trim() -ne $Version) {
    throw "Release version $Version does not match pyproject.toml ($projectVersion)"
}
$appVersion = & .\.venv\Scripts\python.exe -c "import picklight; print(picklight.__version__)"
if ($LASTEXITCODE -ne 0 -or $appVersion.Trim() -ne $Version) {
    throw "Release version $Version does not match the app version ($appVersion)"
}

$package = Join-Path $project 'dist\Preview\PickLight'
$executable = Join-Path $package 'PickLight.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Build PickLight first: $executable"
}

$release = Join-Path $project 'dist\Release'
New-Item -ItemType Directory -Path $release -Force | Out-Null
$zip = Join-Path $release "PickLight-$Version-win-x64.zip"
Compress-Archive -LiteralPath $package -DestinationPath $zip -Force
Write-Host "Packaged $zip"

if ($SkipInstaller) { return }

$compiler = (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $compiler) {
    foreach ($candidate in @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )) {
        if (Test-Path -LiteralPath $candidate) { $compiler = $candidate; break }
    }
}
if (-not $compiler) { throw 'Inno Setup 6 compiler (ISCC.exe) was not found' }

& $compiler "/DAppVersion=$Version" "/O$release" "/FPickLight-$Version-Setup" 'tools\PickLight.iss'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$installer = Join-Path $release "PickLight-$Version-Setup.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer was not created: $installer" }
Write-Host "Packaged $installer"
