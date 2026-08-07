$ErrorActionPreference = "Stop"
$TaskName = "Video Production Pipeline"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if ($Task.State -ne "Running") { Start-ScheduledTask -TaskName $TaskName }
Write-Host "Started task: $TaskName"
