param([switch]$BuildFrontend)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Import-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    foreach ($Line in Get-Content -LiteralPath $Path) {
        $Value = $Line.Trim()
        if (-not $Value -or $Value.StartsWith("#") -or -not $Value.Contains("=")) { continue }
        $Name, $Content = $Value.Split("=", 2)
        [Environment]::SetEnvironmentVariable($Name.Trim(), $Content.Trim().Trim('"').Trim("'"), "Process")
    }
}
Import-DotEnv (Join-Path $Root ".env")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run .\setup.ps1 first." }
if (-not (Test-Path (Join-Path $Root "node_modules"))) { throw "Run npm install first." }
if (-not $env:PIPELINE_ENV) { $env:PIPELINE_ENV = "production" }
if (-not $env:PIPELINE_HOST) { $env:PIPELINE_HOST = "0.0.0.0" }
if (-not $env:PIPELINE_PORT) { $env:PIPELINE_PORT = "8000" }
if (-not $env:PIPELINE_FRONTEND_DIST) { $env:PIPELINE_FRONTEND_DIST = Join-Path $Root "dist" }
if (-not $env:PIPELINE_LOG_DIR) { $env:PIPELINE_LOG_DIR = Join-Path $Root "logs" }

$Index = Join-Path $env:PIPELINE_FRONTEND_DIST "index.html"
if ($BuildFrontend -or -not (Test-Path $Index)) {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}
if (-not (Test-Path $Index)) { throw "Frontend build missing: $Index" }
if (-not $env:PIPELINE_SESSION_SECRET) {
    throw "Set PIPELINE_SESSION_SECRET in .env or process environment."
}

$SiblingHook = Join-Path (Split-Path -Parent $Root) "AI_hook_engine"
if (-not $env:HOOK_ENGINE_PATH) {
    $env:HOOK_ENGINE_PATH = if (Test-Path (Join-Path $SiblingHook "ComfyUI\main.py")) { $SiblingHook } else { Join-Path $Root "engines\hook-engine" }
}
$ComfyRoot = Join-Path $env:HOOK_ENGINE_PATH "ComfyUI"
if (-not $env:HOOK_ENGINE_PYTHON) { $env:HOOK_ENGINE_PYTHON = Join-Path $ComfyRoot ".venv\Scripts\python.exe" }
if (-not $env:HOOK_ENGINE_SERVER) { $env:HOOK_ENGINE_SERVER = "http://127.0.0.1:8188" }
if (-not $env:HOOK_MOTION_ID) { $env:HOOK_MOTION_ID = "motion1" }
if (-not (Test-Path (Join-Path $ComfyRoot "main.py"))) { throw "Hook ComfyUI missing: $ComfyRoot" }
if (-not (Test-Path $env:HOOK_ENGINE_PYTHON)) { throw "Hook Python missing: $env:HOOK_ENGINE_PYTHON" }

$Logs = $env:PIPELINE_LOG_DIR
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Comfy = $null
function Test-ComfyUI {
    try {
        Invoke-RestMethod -Uri "$($env:HOOK_ENGINE_SERVER.TrimEnd('/'))/system_stats" -TimeoutSec 2 | Out-Null
        return $true
    } catch { return $false }
}

try {
    if (-not (Test-ComfyUI)) {
        $Uri = [Uri]$env:HOOK_ENGINE_SERVER
        $Comfy = Start-Process -FilePath $env:HOOK_ENGINE_PYTHON -ArgumentList @("main.py", "--listen", $Uri.Host, "--port", $Uri.Port) -WorkingDirectory $ComfyRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Logs "comfyui.stdout.log") -RedirectStandardError (Join-Path $Logs "comfyui.stderr.log")
        for ($Attempt = 0; $Attempt -lt 120 -and -not (Test-ComfyUI); $Attempt++) {
            if ($Comfy.HasExited) { throw "Hook ComfyUI exited. See logs." }
            Start-Sleep -Seconds 1
        }
        if (-not (Test-ComfyUI)) { throw "Hook ComfyUI startup timed out." }
    }
    # Uvicorn writes normal startup messages to stderr. Windows PowerShell must
    # not turn those messages into terminating NativeCommandError exceptions.
    $ErrorActionPreference = "Continue"
    & $Python -m apps.orchestrator.cli serve 2>&1 | Tee-Object -FilePath (Join-Path $Logs "server-console.log") -Append
    $ServerExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    exit $ServerExitCode
} finally {
    if ($Comfy -and -not $Comfy.HasExited) { Stop-Process -Id $Comfy.Id }
}
