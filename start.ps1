# Run from a normal PowerShell terminal with network access.
$ErrorActionPreference = 'Stop'
$brickPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $brickPython)) {
    throw 'Project Python environment is missing: .venv\Scripts\python.exe'
}
if (-not $env:LLM_API_KEY) {
    Write-Warning 'LLM_API_KEY is not set. Agent queries require an API key.'
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $brickPython -u app.py
    $brickExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $brickExitCode
