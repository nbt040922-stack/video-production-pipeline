$ErrorActionPreference = "Stop"
$TaskName = "Video Production Pipeline"
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
$Logs = if (-not $env:PIPELINE_LOG_DIR) { Join-Path $Root "logs" } elseif ([IO.Path]::IsPathRooted($env:PIPELINE_LOG_DIR)) { $env:PIPELINE_LOG_DIR } else { Join-Path $Root $env:PIPELINE_LOG_DIR }
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
foreach ($Name in @("server.lock", "watchdog.pid")) {
    $Path = Join-Path $Logs $Name
    if (-not (Test-Path $Path)) { continue }
    $TargetPid = 0
    [int]::TryParse((Get-Content -LiteralPath $Path -Raw).Trim(), [ref]$TargetPid) | Out-Null
    if (-not $TargetPid) { continue }
    $Process = Get-CimInstance Win32_Process -Filter "ProcessId=$TargetPid" -ErrorAction SilentlyContinue
    if ($Process -and ($Process.CommandLine -like "*apps.orchestrator*" -or $Process.CommandLine -like "*production-watchdog.ps1*")) {
        Stop-Process -Id $TargetPid -Force
    }
}
Write-Host "Stopped task: $TaskName"
