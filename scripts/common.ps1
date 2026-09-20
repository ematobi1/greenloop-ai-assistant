$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "services\backend"
$FrontendDir = Join-Path $RepoRoot "services\frontend"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Assert-VenvExists {
    if (-not (Test-Path $VenvPython)) {
        throw "Missing .venv. Run scripts\setup.ps1 first."
    }
}
