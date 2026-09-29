<#
.SYNOPSIS
Deploys the TSMC40 gm/ID runner without sending Python through scp.

.DESCRIPTION
The IC server's transfer policy may wrap Python files uploaded by scp with a
%TSD-Header-###% envelope. This TSMC40-specific wrapper calls the repository's
ssh-text-deploy sender for atomic SSH-stdin writes, LF normalization, SHA-256
verification, and TSD-header detection.

.PARAMETER SshHost
SSH host or user@host. Defaults to IC_Server.

.PARAMETER RemoteDir
Authorized destination directory on the remote host.

.PARAMETER Run
Runs the selected characterization profiles after deployment.

.PARAMETER Profiles
Comma-separated profile names from profiles.json. Defaults to 1v1.

.EXAMPLE
.\deploy_remote.ps1 -Run -Profiles '1v1,2v5'

.EXAMPLE
.\deploy_remote.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SshHost = 'IC_Server',
    [string]$RemoteDir = '/home/userone/AAAIC/test_tb/gmid_tsmc40',
    [string]$Profiles = '1v1',
    [switch]$Run
)

$ErrorActionPreference = 'Stop'

if ($SshHost -notmatch '^[A-Za-z0-9_.@-]+$') {
    throw "Unsafe SSH host syntax: $SshHost"
}
if ($RemoteDir -notmatch '^/[A-Za-z0-9_./-]+$' -or $RemoteDir -match '/\.\.?(/|$)') {
    throw "RemoteDir must be an absolute path without spaces or dot segments: $RemoteDir"
}

$baseDir = $PSScriptRoot
$genericSender = Join-Path $baseDir '..\..\ssh-text-deploy\scripts\send_text_over_ssh.ps1'
$profileList = @($Profiles.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($profileList.Count -eq 0 -or $profileList.Where({ $_ -notmatch '^[A-Za-z0-9_]+$' }).Count -gt 0) {
    throw "Profiles must be a comma-separated list of safe identifiers: $Profiles"
}
$files = @(
    @{ Local = Join-Path $baseDir 'run_tsmc40.py'; Remote = "$RemoteDir/run_tsmc40.py"; Executable = $true },
    @{ Local = Join-Path $baseDir 'README.md'; Remote = "$RemoteDir/README.md"; Executable = $false },
    @{ Local = Join-Path $baseDir 'profiles.json'; Remote = "$RemoteDir/profiles.json"; Executable = $false }
)

if (-not (Test-Path -LiteralPath $genericSender -PathType Leaf)) {
    throw "Generic SSH text sender is missing: $genericSender"
}
foreach ($item in $files) {
    if (-not (Test-Path -LiteralPath $item.Local -PathType Leaf)) {
        throw "Required local file is missing: $($item.Local)"
    }
}
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw 'ssh was not found in PATH'
}

if (-not $PSCmdlet.ShouldProcess("$SshHost`:$RemoteDir", 'Deploy gm/ID runner over SSH stdin')) {
    return
}

foreach ($item in $files) {
    Write-Host "Deploying $($item.Local) -> $SshHost`:$($item.Remote)"
    & $genericSender `
        -LocalPath $item.Local `
        -SshHost $SshHost `
        -RemotePath $item.Remote `
        -NormalizeLf `
        -Executable:$item.Executable
}

& ssh -o BatchMode=yes $SshHost "python3 $RemoteDir/run_tsmc40.py --help >/dev/null"
if ($LASTEXITCODE -ne 0) {
    throw 'The deployed Python runner did not pass its --help smoke test'
}

Write-Host 'Deployment verified: all files passed SHA-256 and TSD-header checks.'

if ($Run) {
    foreach ($profile in $profileList) {
        Write-Host "Running gm/ID profile: $profile"
        & ssh -o BatchMode=yes $SshHost "cd $RemoteDir && ./run_tsmc40.py --profile $profile"
        if ($LASTEXITCODE -ne 0) {
            throw "Remote gm/ID characterization failed for profile: $profile"
        }
    }
}
