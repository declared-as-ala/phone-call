#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Allow inbound UDP RTP (10000-10100) through Windows Firewall for Asterisk IVR.

.DESCRIPTION
  Docker Desktop publishes these ports on the Windows host. Without an inbound
  allow rule, SIP UP return RTP (and RFC4733 DTMF) never reaches Asterisk -
  channelstats shows Receive Count = 0.

  Run in an elevated PowerShell:
    cd Project\infra\sipup
    .\scripts\open-rtp-firewall.ps1

  Also forward UDP 10000-10100 on your home router to this PC's LAN IP.
#>
$ErrorActionPreference = "Stop"
$ruleName = "Asterisk IVR RTP UDP 10000-10100"
$start = 10000
$end = 10100

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $ruleName"
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol UDP `
        -LocalPort ${start}-${end} `
        -Action Allow `
        -Profile Any | Out-Null
    Write-Host "Created firewall rule: $ruleName"
}

Write-Host ""
Write-Host "Next: on your router, port-forward UDP ${start}-${end} to this PC."
Write-Host "Then during a live call run:"
Write-Host '  docker exec ivr-asterisk-dev asterisk -rx "pjsip show channelstats"'
Write-Host "Receive Count must be > 0 for RFC4733 DTMF. With dtmf_mode=info, keypad may still work via SIP INFO even when Receive is 0."
