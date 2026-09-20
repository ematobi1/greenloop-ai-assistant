. "$PSScriptRoot\common.ps1"

if (-not (Test-Path $VenvPython)) {
    py -3.12 -m venv (Join-Path $RepoRoot ".venv")
    Assert-LastExitCode "Create virtual environment (Python 3.12 required)"
}

& $VenvPython -m pip install --quiet -e "$BackendDir[dev]"
Assert-LastExitCode "Install backend dependencies"

Push-Location $FrontendDir
try {
    npm ci
    Assert-LastExitCode "Install frontend dependencies"
} finally {
    Pop-Location
}

$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $RepoRoot ".env.example") $envFile
}

Write-Host "Restricting data\, .env, and the Claude sandbox to your account (docs\security\file-permissions.md)"
& "$PSScriptRoot\secure-permissions.ps1" -Apply
if ($LASTEXITCODE -ne 0) { throw "Permission check failed. Fix the reported paths before continuing." }

& "$PSScriptRoot\migrate.ps1"
& "$PSScriptRoot\new-token.ps1" -IfMissing
Write-Host "Setup complete. Run scripts\dev.ps1 to start GreenLoop."
