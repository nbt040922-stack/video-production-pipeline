$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$EnvFile = Join-Path $Root ".env"
if (Test-Path $EnvFile) {
    foreach ($Line in Get-Content -LiteralPath $EnvFile) {
        $Value = $Line.Trim()
        if ($Value -and -not $Value.StartsWith("#") -and $Value.Contains("=")) {
            $Name, $Content = $Value.Split("=", 2)
            [Environment]::SetEnvironmentVariable($Name.Trim(), $Content.Trim().Trim('"').Trim("'"), "Process")
        }
    }
}
Set-Location $Root
$Logs = if (-not $env:PIPELINE_LOG_DIR) { Join-Path $Root "logs" } elseif ([IO.Path]::IsPathRooted($env:PIPELINE_LOG_DIR)) { $env:PIPELINE_LOG_DIR } else { Join-Path $Root $env:PIPELINE_LOG_DIR }
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$LockPath = Join-Path $Logs "watchdog.lock"
$PidPath = Join-Path $Logs "watchdog.pid"
$Lock = $null
if (Test-Path $LockPath) {
    $ExistingPid = 0
    if (Test-Path $PidPath) { [int]::TryParse((Get-Content -LiteralPath $PidPath -Raw).Trim(), [ref]$ExistingPid) | Out-Null }
    if ($ExistingPid -and (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue)) {
        throw "Production watchdog already running with PID $ExistingPid."
    }
    Remove-Item -LiteralPath $LockPath, $PidPath -Force -ErrorAction SilentlyContinue
}
try {
    try {
        $Lock = [IO.File]::Open($LockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    } catch {
        throw "Production watchdog already running or stale lock exists: $LockPath"
    }
    [IO.File]::WriteAllText($PidPath, "$PID")
    while ($true) {
        $Process = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "scripts\run-production.ps1")) -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Logs "runtime.stdout.log") -RedirectStandardError (Join-Path $Logs "runtime.stderr.log")
        $Process.WaitForExit()
        Add-Content -LiteralPath (Join-Path $Logs "watchdog.log") -Value "$(Get-Date -Format o) server exited code=$($Process.ExitCode); restart in 10s"
        Start-Sleep -Seconds 10
    }
} finally {
    if ($Lock) { $Lock.Dispose() }
    Remove-Item -LiteralPath $LockPath, $PidPath -Force -ErrorAction SilentlyContinue
}
