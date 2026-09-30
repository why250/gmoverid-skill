param(
    [string]$Models = 'all',
    [ValidateSet('nmos', 'pmos', 'both')]
    [string]$Polarity = 'both',
    [double]$Step = 0.005,
    [string]$LtspiceExe
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runner = Join-Path $repoRoot 'ltspice\assets\run_ptm_gmoverid.py'
$output = Join-Path $PSScriptRoot 'results'
$arguments = @(
    $runner,
    '--models', $Models,
    '--polarity', $Polarity,
    '--step', $Step.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--output-dir', $output
)
if ($LtspiceExe) {
    $arguments += @('--ltspice', $LtspiceExe)
}

& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "LTspice practice failed with exit code $LASTEXITCODE"
}

