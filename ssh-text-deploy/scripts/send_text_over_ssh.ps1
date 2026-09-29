<#
.SYNOPSIS
Atomically deploys one authorized UTF-8 text file over SSH standard input.

.DESCRIPTION
Use when the destination permits shell-created files but an ordinary managed
file-transfer path changes or wraps text content. The script rejects binaries,
validates conservative host/path syntax, supports optional LF normalization,
and verifies the deployed SHA-256 hash and TSD header.

.PARAMETER LocalPath
Existing local UTF-8 text file.

.PARAMETER SshHost
SSH config host or user@host.

.PARAMETER RemotePath
Absolute POSIX destination path. Spaces and dot segments are intentionally not
accepted so the remote command remains unambiguous.

.PARAMETER NormalizeLf
Converts CRLF and lone CR line endings to LF before transmission.

.PARAMETER Executable
Sets remote mode 0755 instead of 0644.

.PARAMETER MaxBytes
Maximum accepted source size. Defaults to 10 MiB.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$LocalPath,

    [Parameter(Mandatory = $true)]
    [string]$SshHost,

    [Parameter(Mandatory = $true)]
    [string]$RemotePath,

    [switch]$NormalizeLf,
    [switch]$Executable,

    [ValidateRange(1, 104857600)]
    [long]$MaxBytes = 10485760
)

$ErrorActionPreference = 'Stop'

function Invoke-SshProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][string]$RemoteCommand,
        [byte[]]$InputBytes = [byte[]]::new(0)
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $ExecutablePath
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $startInfo.ArgumentList.Add('-o')
    $startInfo.ArgumentList.Add('BatchMode=yes')
    $startInfo.ArgumentList.Add($HostName)
    $startInfo.ArgumentList.Add($RemoteCommand)

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw 'Could not start ssh'
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if ($InputBytes.Length -gt 0) {
        $process.StandardInput.BaseStream.Write($InputBytes, 0, $InputBytes.Length)
    }
    $process.StandardInput.Close()
    $process.WaitForExit()

    [pscustomobject]@{
        ExitCode = $process.ExitCode
        Stdout = $stdoutTask.GetAwaiter().GetResult()
        Stderr = $stderrTask.GetAwaiter().GetResult()
    }
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash($Bytes)
    }
    finally {
        $sha256.Dispose()
    }
    return ([System.BitConverter]::ToString($hash) -replace '-', '').ToLowerInvariant()
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7 or newer is required for exact byte streaming'
}
if ($SshHost -notmatch '^[A-Za-z0-9_.@-]+$') {
    throw "Unsafe SSH host syntax: $SshHost"
}
if (
    $RemotePath -notmatch '^/[A-Za-z0-9._/-]+$' -or
    $RemotePath -match '(^|/)\.\.?(/|$)' -or
    $RemotePath.Contains('//') -or
    $RemotePath.EndsWith('/')
) {
    throw "RemotePath must be an absolute POSIX file path without spaces, repeated slashes, or dot segments: $RemotePath"
}

$lastSlash = $RemotePath.LastIndexOf('/')
if ($lastSlash -le 0) {
    throw 'Writing directly below the remote filesystem root is not allowed'
}
$remoteDirectory = $RemotePath.Substring(0, $lastSlash)

$resolvedLocalPath = (Resolve-Path -LiteralPath $LocalPath -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $resolvedLocalPath -PathType Leaf)) {
    throw "LocalPath is not a file: $resolvedLocalPath"
}
$bytes = [System.IO.File]::ReadAllBytes($resolvedLocalPath)
if ($bytes.LongLength -gt $MaxBytes) {
    throw "Source is $($bytes.LongLength) bytes; MaxBytes is $MaxBytes"
}
if ([System.Array]::IndexOf($bytes, [byte]0) -ge 0) {
    throw 'Source contains a NUL byte and is not accepted as text'
}

$strictUtf8 = [System.Text.UTF8Encoding]::new($false, $true)
try {
    $text = $strictUtf8.GetString($bytes)
}
catch {
    throw 'Source is not valid UTF-8 text'
}
if ($text.StartsWith('%TSD-Header-###%')) {
    throw 'Source already has a TSD wrapper; do not deploy or attempt to decrypt it'
}
if ($NormalizeLf) {
    $text = $text.Replace("`r`n", "`n").Replace("`r", "`n")
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($text)
}

$sshCommand = Get-Command ssh -ErrorAction SilentlyContinue
if (-not $sshCommand) {
    throw 'ssh was not found in PATH'
}
$sshPath = $sshCommand.Source
$mode = if ($Executable) { '0755' } else { '0644' }
$localHash = Get-Sha256Hex -Bytes $bytes

if (-not $PSCmdlet.ShouldProcess("$SshHost`:$RemotePath", "Atomically deploy $($bytes.Length) UTF-8 bytes with mode $mode")) {
    return
}

$deployTemplate = @'
set -e; mkdir -p {0}; tmp=$(mktemp {0}/.ssh-text-deploy.XXXXXX); trap 'rm -f "$tmp"' EXIT; cat > "$tmp"; chmod {1} "$tmp"; mv "$tmp" {2}; trap - EXIT
'@
$deployCommand = $deployTemplate -f $remoteDirectory, $mode, $RemotePath
$deploy = Invoke-SshProcess -ExecutablePath $sshPath -HostName $SshHost -RemoteCommand $deployCommand -InputBytes $bytes
if ($deploy.ExitCode -ne 0) {
    throw "SSH deployment failed with exit code $($deploy.ExitCode): $($deploy.Stderr.Trim())"
}

$verifyTemplate = @'
set -e; sha256sum {0} | awk '{{print $1}}'; head -c 16 {0} | od -An -tx1 | tr -d ' \n'
'@
$verifyCommand = $verifyTemplate -f $RemotePath
$verify = Invoke-SshProcess -ExecutablePath $sshPath -HostName $SshHost -RemoteCommand $verifyCommand
if ($verify.ExitCode -ne 0) {
    throw "Remote verification failed with exit code $($verify.ExitCode): $($verify.Stderr.Trim())"
}

$verifyLines = @($verify.Stdout -split '\r?\n' | Where-Object { $_.Trim().Length -gt 0 })
if ($verifyLines.Count -lt 2) {
    throw "Remote verification returned incomplete output: $($verify.Stdout.Trim())"
}
$remoteHash = $verifyLines[0].Trim().ToLowerInvariant()
$remotePrefixHex = $verifyLines[1].Trim().ToLowerInvariant()
if ($remotePrefixHex -eq '255453442d4865616465722d23232325') {
    throw 'Remote file has a TSD wrapper; stop and use the administrator-approved transfer mechanism'
}
if ($remoteHash -ne $localHash) {
    throw "SHA-256 mismatch: local=$localHash remote=$remoteHash"
}

Write-Host "Deployed and verified $($bytes.Length) bytes: $SshHost`:$RemotePath"
Write-Host "SHA-256: $localHash"
