param([ValidateSet("Logon", "Startup")][string]$Mode = "Logon")
$ErrorActionPreference = "Stop"
$TaskName = "Video Production Pipeline"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Watchdog = Join-Path $Root "scripts\production-watchdog.ps1"
$Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $Watchdog
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $Root
$Trigger = if ($Mode -eq "Startup") { New-ScheduledTaskTrigger -AtStartup } else { New-ScheduledTaskTrigger -AtLogOn }
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 365) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Video Production Pipeline LAN runtime" -Force | Out-Null
Write-Host "Installed task: $TaskName ($Mode)"
