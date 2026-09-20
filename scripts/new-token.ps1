param([switch]$IfMissing)

. "$PSScriptRoot\common.ps1"
Assert-VenvExists

$envFile = Join-Path $RepoRoot ".env"
$hashKey = "GREENLOOP_API_TOKEN_HASH"
$lines = @()
if (Test-Path $envFile) {
    $lines = @(Get-Content $envFile)
}

$hasHash = $lines | Where-Object { $_ -match "^$hashKey=.+" }
if ($IfMissing -and $hasHash) {
    Write-Host "API token already configured. Run scripts\new-token.ps1 to rotate it."
    return
}

Push-Location $BackendDir
try {
    $generated = @(& $VenvPython -m app.security.token)
    Assert-LastExitCode "Token generation"
} finally {
    Pop-Location
}

$token = $generated[0]
$lines = @($lines | Where-Object { $_ -notmatch "^$hashKey=" }) + "$hashKey=$($generated[1])"
[IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))

Write-Host ""
Write-Host "Your GreenLoop API token (shown once, not stored anywhere):"
Write-Host ""
Write-Host "    $token"
Write-Host ""
Write-Host "Paste it into the dashboard unlock screen. Only its hash is saved in .env."
Write-Host "Restart the backend if it is running."
