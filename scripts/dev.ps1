$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run .\setup.ps1 first." }
if (-not (Test-Path "node_modules")) { throw "Run npm install first." }

$env:VITE_PIPELINE_MODE = "backend"
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$Backend = Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn", "apps.orchestrator.api:app",
    "--host", "127.0.0.1", "--port", "8000"
) -WorkingDirectory $Root -NoNewWindow -PassThru

Write-Host "Backend: http://127.0.0.1:8000"
Write-Host "Frontend: http://127.0.0.1:5173"
try {
    npm run dev -- --host 127.0.0.1 --port 5173
} finally {
    if (-not $Backend.HasExited) { Stop-Process -Id $Backend.Id }
}
