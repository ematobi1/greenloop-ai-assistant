. "$PSScriptRoot\common.ps1"
Assert-VenvExists

$backend = Start-Process -FilePath $VenvPython -WorkingDirectory $BackendDir -NoNewWindow -PassThru -ArgumentList @(
    "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8787", "--reload"
)

Push-Location $FrontendDir
try {
    Write-Host "API: http://127.0.0.1:8787/v1/health   Dashboard: http://127.0.0.1:5173"
    npm run dev
} finally {
    Pop-Location
    if (-not $backend.HasExited) {
        taskkill /PID $backend.Id /T /F | Out-Null
    }
}
