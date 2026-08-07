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
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Task) { Write-Host "Task not installed: $TaskName"; exit 1 }
$Info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Task: $TaskName"
Write-Host "State: $($Task.State)"
Write-Host "Last result: $($Info.LastTaskResult)"
$Lock = Join-Path $Logs "server.lock"
if (Test-Path $Lock) { Write-Host "Server PID: $((Get-Content -LiteralPath $Lock -Raw).Trim())" } else { Write-Host "Server PID: not running" }
