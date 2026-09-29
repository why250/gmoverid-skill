param(
    [string]$PdkRoot = 'D:\Users\Documents\PDK\volare\sky130\versions\c6d73a35f524070e85faff4a6a9eef49553ebc2b\sky130A'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ngspice = Join-Path $projectRoot '.claude\tools\Spice64\bin\ngspice_con.exe'
$smokeScript = Join-Path $projectRoot 'sky130-pdk\assets\run_sky130_mos_iv_pvt_mc.py'
$smokeWorkdir = (Resolve-Path $PSScriptRoot).Path + '\smoke'

if (-not (Test-Path -LiteralPath $PdkRoot)) { throw "Sky130A not found: $PdkRoot" }
if (-not (Test-Path -LiteralPath $ngspice)) { throw "ngspice_con not found: $ngspice" }

$env:PYTHONUTF8 = '1'

python $smokeScript --pdk-root $PdkRoot --workdir $smokeWorkdir `
    --mc-runs 3 --jobs 1 --timeout 30 --ngspice $ngspice
if ($LASTEXITCODE -ne 0) { throw 'Sky130A PVT/MC smoke test failed' }

python (Join-Path $PSScriptRoot 'gmoverid_sky130.py') `
    --pdk-root $PdkRoot --ngspice $ngspice
if ($LASTEXITCODE -ne 0) { throw 'Sky130A gm/ID characterization failed' }
