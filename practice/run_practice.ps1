$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ngspiceBin = Join-Path $projectRoot '.claude\tools\Spice64\bin'
$ngspiceExe = Join-Path $ngspiceBin 'ngspice_con.exe'

if (-not (Test-Path -LiteralPath $ngspiceExe)) {
    throw "Project-local ngspice was not found at $ngspiceExe"
}

$env:PATH = "$ngspiceBin;$env:PATH"
$env:PYTHONUTF8 = '1'

Write-Host '1/4 Verify ngspice'
$versionOutput = & $ngspiceExe --version 2>&1
if ($LASTEXITCODE -ne 0) { throw 'ngspice version check failed' }
$versionOutput | Select-String 'ngspice-' | Select-Object -First 1

Write-Host '2/4 Run the RC transient smoke test'
& python (Join-Path $PSScriptRoot 'ngspice\run_tran_rc_charging.py')
if ($LASTEXITCODE -ne 0) { throw 'RC transient simulation failed' }

Write-Host '3/4 Generate the 180 nm gm/ID characterization plots'
& python (Join-Path $PSScriptRoot 'gmoverid\run_gmoverid.py')
if ($LASTEXITCODE -ne 0) { throw 'gm/ID characterization failed' }

Write-Host '4/4 Validate the table and size a 100 uA NMOS'
& python (Join-Path $PSScriptRoot 'gmoverid\validate_gmoverid.py')
if ($LASTEXITCODE -ne 0) { throw 'gm/ID validation failed' }

& python (Join-Path $PSScriptRoot 'gmoverid\demo_design.py')
if ($LASTEXITCODE -ne 0) { throw 'gm/ID sizing exercise failed' }

Write-Host 'Practice completed successfully.'
