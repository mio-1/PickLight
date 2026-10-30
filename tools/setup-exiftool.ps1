$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project

$version = '13.59.3'
$expectedHash = '7EAF41B3B02DDB9C7BD32BEA2417C783D6364A6725CB57D1A0163617AFF4B577'
$archive = Join-Path $project ".downloads\exiftool-vendored.exe-$version.tgz"
$target = Join-Path $project 'vendor\exiftool'

if (Test-Path -LiteralPath (Join-Path $target 'exiftool.exe')) {
    Write-Host 'ExifTool is already available.'
    exit 0
}

New-Item -ItemType Directory -Path '.downloads' -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    npm pack "exiftool-vendored.exe@$version" --pack-destination .downloads --silent
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) {
    throw "ExifTool archive checksum mismatch: $actualHash"
}

$extract = Join-Path $project '.downloads\exiftool-package'
New-Item -ItemType Directory -Path $extract -Force | Out-Null
tar -xf $archive -C $extract
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -Path (Join-Path $extract 'package\bin\*') -Destination $target -Recurse -Force
Copy-Item -LiteralPath (Join-Path $extract 'package\LICENSE') -Destination (Join-Path $target 'LICENSE') -Force
Write-Host 'ExifTool 13.59 is ready.'

