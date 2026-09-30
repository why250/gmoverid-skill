param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path

Write-Host "Serving Sky130 MOS Explorer from $root"
Write-Host "Open http://localhost:$Port/web/"
python -m http.server $Port --directory $root
