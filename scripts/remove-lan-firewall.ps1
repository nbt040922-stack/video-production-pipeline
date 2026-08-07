#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$RuleName = "Video Production Pipeline LAN (TCP)"
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "Firewall rule absent: $RuleName"
