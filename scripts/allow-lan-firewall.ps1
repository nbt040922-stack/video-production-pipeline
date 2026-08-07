#Requires -RunAsAdministrator
param([int]$Port = $(if ($env:PIPELINE_PORT) { [int]$env:PIPELINE_PORT } else { 8000 }))
$ErrorActionPreference = "Stop"
$RuleName = "Video Production Pipeline LAN (TCP)"
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Private | Out-Null
Write-Host "Firewall rule ready: $RuleName; TCP $Port; RemoteAddress=LocalSubnet"
