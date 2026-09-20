param(
    [switch]$Deep,
    [switch]$Effective
)

. "$PSScriptRoot\common.ps1"
Assert-VenvExists

$arguments = @()
if ($Deep) { $arguments += "--deep" }
if ($Effective) { $arguments += "--effective" }

Push-Location $BackendDir
try {
    & $VenvPython -m app.security.filesystem @arguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
