$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

git submodule update --init --recursive

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
@(
    "requirements.txt",
    "engines/hook-engine/requirements.txt",
    "engines/review-engine/requirements.txt"
) | Where-Object { Test-Path $_ } | ForEach-Object {
    & $Python -m pip install -r $_
}

Write-Host "Setup complete."
