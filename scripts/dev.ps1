$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run .\setup.ps1 first." }
if (-not (Test-Path "node_modules")) { throw "Run npm install first." }

$SiblingHook = Join-Path (Split-Path -Parent $Root) "AI_hook_engine"
if (-not $env:HOOK_ENGINE_PATH) {
    $env:HOOK_ENGINE_PATH = if (Test-Path (Join-Path $SiblingHook "ComfyUI\main.py")) {
        $SiblingHook
    } else {
        Join-Path $Root "engines\hook-engine"
    }
}
$ComfyRoot = Join-Path $env:HOOK_ENGINE_PATH "ComfyUI"
if (-not $env:HOOK_ENGINE_PYTHON) {
    $env:HOOK_ENGINE_PYTHON = Join-Path $ComfyRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path (Join-Path $ComfyRoot "main.py"))) {
    throw "Hook runtime missing: $ComfyRoot\main.py. Set HOOK_ENGINE_PATH."
}
if (-not (Test-Path $env:HOOK_ENGINE_PYTHON)) {
    throw "Hook Python missing: $env:HOOK_ENGINE_PYTHON. Set HOOK_ENGINE_PYTHON."
}
if (-not $env:HOOK_ENGINE_SERVER) { $env:HOOK_ENGINE_SERVER = "http://127.0.0.1:8188" }
if (-not $env:HOOK_MOTION_ID) { $env:HOOK_MOTION_ID = "motion1" }
$ComfyUri = [Uri]$env:HOOK_ENGINE_SERVER

function Test-ComfyUI {
    try {
        Invoke-RestMethod -Uri "$($env:HOOK_ENGINE_SERVER.TrimEnd('/'))/system_stats" -TimeoutSec 1 | Out-Null
        return $true
    } catch {
        return $false
    }
}

$env:VITE_PIPELINE_MODE = "backend"
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
$Comfy = $null
$Backend = $null
try {
    if (-not (Test-ComfyUI)) {
        $ServiceLogs = Join-Path $Root "workspace\services"
        New-Item -ItemType Directory -Force -Path $ServiceLogs | Out-Null
        $Comfy = Start-Process -FilePath $env:HOOK_ENGINE_PYTHON -ArgumentList @(
            "main.py", "--listen", $ComfyUri.Host, "--port", $ComfyUri.Port
        ) -WorkingDirectory $ComfyRoot -WindowStyle Hidden -PassThru `
          -RedirectStandardOutput (Join-Path $ServiceLogs "comfyui.stdout.log") `
          -RedirectStandardError (Join-Path $ServiceLogs "comfyui.stderr.log")
        Write-Host "Starting Hook ComfyUI: $env:HOOK_ENGINE_SERVER"
        $Ready = $false
        for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
            if ($Comfy.HasExited) { throw "Hook ComfyUI stopped during startup. See workspace\services logs." }
            if (Test-ComfyUI) { $Ready = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $Ready) { throw "Hook ComfyUI startup timed out after 120 seconds." }
    } else {
        Write-Host "Hook ComfyUI already running: $env:HOOK_ENGINE_SERVER"
    }

    $Backend = Start-Process -FilePath $Python -ArgumentList @(
        "-m", "uvicorn", "apps.orchestrator.api:app",
        "--host", "127.0.0.1", "--port", "8000"
    ) -WorkingDirectory $Root -NoNewWindow -PassThru
    Write-Host "Backend: http://127.0.0.1:8000"
    Write-Host "Frontend: http://127.0.0.1:5173"
    npm run dev -- --host 127.0.0.1 --port 5173
} finally {
    if ($Backend -and -not $Backend.HasExited) { Stop-Process -Id $Backend.Id }
    if ($Comfy -and -not $Comfy.HasExited) { Stop-Process -Id $Comfy.Id }
}
