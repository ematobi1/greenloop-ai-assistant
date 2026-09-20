. "$PSScriptRoot\common.ps1"
Assert-VenvExists

Push-Location $BackendDir
try {
    & $VenvPython -m ruff check .
    Assert-LastExitCode "Backend lint"
    & $VenvPython -m pytest -q
    Assert-LastExitCode "Backend tests"
} finally {
    Pop-Location
}

Push-Location $FrontendDir
try {
    npm run typecheck
    Assert-LastExitCode "Frontend typecheck"
    npm run lint
    Assert-LastExitCode "Frontend lint"
    npm test
    Assert-LastExitCode "Frontend tests"
} finally {
    Pop-Location
}

Write-Host "All checks passed."
