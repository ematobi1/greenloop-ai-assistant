param([switch]$Apply)

# Restricts GreenLoop's private paths (data\, .env, the Claude CLI sandbox) to this Windows user,
# SYSTEM, and Administrators. Nothing changes unless -Apply is passed. It touches only those
# paths, never C:\Users, C:\Windows, or anything outside the GreenLoop project. GreenLoop itself
# never runs this script and refuses to start when permissions are unsafe instead of changing them.

. "$PSScriptRoot\common.ps1"

$userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$sandbox = Join-Path $env:LOCALAPPDATA "GreenLoop\claude-sandbox"
$targets = @(
    @{ Path = Join-Path $RepoRoot "data"; Kind = "Directory" },
    @{ Path = Join-Path $RepoRoot ".env"; Kind = "File" },
    @{ Path = $sandbox; Kind = "Directory" }
)

$backupDirectory = Join-Path $env:LOCALAPPDATA "GreenLoop\acl-backups"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

foreach ($target in $targets) {
    $path = $target.Path
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "skip (missing): $path"
        continue
    }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to change permissions through a link: $path"
    }
    Write-Host ""
    Write-Host "== $path"
    Write-Host "current permissions:"
    icacls $path | Where-Object { $_.Trim() -ne "" -and $_ -notmatch "Successfully processed" }

    if (-not $Apply) {
        Write-Host "(dry run) would restrict to: current user, SYSTEM, Administrators"
        continue
    }

    New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
    $backup = Join-Path $backupDirectory ("{0}-{1}.acl" -f $stamp, $item.Name.Replace(".", "_"))
    icacls $path /save $backup | Out-Null
    Assert-LastExitCode "Back up permissions of $path"
    Write-Host "backup: $backup (restore with: icacls <parent> /restore <backup>)"

    if ($target.Kind -eq "Directory") {
        $rights = "(OI)(CI)F"
    } else {
        $rights = "F"
    }
    icacls $path /inheritance:r /grant:r "*${userSid}:$rights" "*S-1-5-18:$rights" "*S-1-5-32-544:$rights" | Out-Null
    Assert-LastExitCode "Restrict $path"
    Write-Host "restricted."
}

Write-Host ""
if ($Apply) {
    & "$PSScriptRoot\verify-permissions.ps1"
    exit $LASTEXITCODE
}
Write-Host "No changes made. Re-run with -Apply to restrict the paths above."
