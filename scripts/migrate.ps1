. "$PSScriptRoot\common.ps1"
Assert-VenvExists

Push-Location $BackendDir
try {
    & $VenvPython -m alembic upgrade head
    Assert-LastExitCode "Database migration"
} finally {
    Pop-Location
}
