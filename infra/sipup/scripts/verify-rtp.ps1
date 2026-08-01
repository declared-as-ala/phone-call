#Requires -Version 5.1
<#
.SYNOPSIS
  Verify Windows RTP prerequisites for Asterisk + SIP UP DTMF.

.DESCRIPTION
  RFC4733 DTMF requires inbound UDP RTP on ports 10000-10100. Checks:
  - Windows firewall allow rule
  - Docker Asterisk container running
  - Published RTP port mapping
  - rtp.conf externaddr vs optional ASTERISK_EXTERNAL_IP in .env

  Run from repo:
    cd Project\infra\sipup
    .\scripts\verify-rtp.ps1
#>
$ErrorActionPreference = "Continue"
$ruleName = "Asterisk IVR RTP UDP 10000-10100"
$container = "ivr-asterisk-dev"
$rtpStart = 10000
$rtpEnd = 10100
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$sipupRoot = Join-Path $root "infra\sipup"
if (-not (Test-Path $sipupRoot)) {
    $sipupRoot = Split-Path $PSScriptRoot -Parent
}

Write-Host "=== Asterisk RTP / DTMF verification ===" -ForegroundColor Cyan
Write-Host ""

# 1. Firewall
$fw = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($fw -and ($fw | Where-Object { $_.Enabled -eq "True" })) {
    Write-Host "[OK] Windows firewall rule: $ruleName" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Missing Windows firewall rule: $ruleName" -ForegroundColor Red
    Write-Host "       Run as Administrator: .\scripts\open-rtp-firewall.ps1"
}

# 2. LAN IP hint for router port-forward
Write-Host ""
Write-Host "LAN IP (use for router port-forward target):" -ForegroundColor Yellow
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch "^127\." -and $_.PrefixOrigin -ne "WellKnown" } |
    ForEach-Object { Write-Host "  $($_.InterfaceAlias): $($_.IPAddress)" }

# 3. Docker container
Write-Host ""
$running = docker ps --filter "name=$container" --format "{{.Names}}" 2>$null
if ($running -eq $container) {
    Write-Host "[OK] Container $container is running" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Container $container is not running" -ForegroundColor Red
    Write-Host "       Run: cd infra\sipup; docker compose up -d"
}

# 4. externaddr in container
Write-Host ""
if ($running -eq $container) {
    $extern = docker exec $container grep -E "^externaddr=" /etc/asterisk/rtp.conf 2>$null
    if ($extern) {
        Write-Host "[INFO] Asterisk $extern"
    }
    $dtmf = docker exec $container asterisk -rx "pjsip show endpoint sip-up-trunk" 2>$null |
        Select-String "dtmf_mode"
    if ($dtmf) {
        Write-Host "[INFO] sip-up-trunk $dtmf"
    }
}

# 5. .env ASTERISK_EXTERNAL_IP vs live public IP
Write-Host ""
$envFile = Join-Path $sipupRoot ".env"
$pinnedIp = $null
if (Test-Path $envFile) {
    $line = Get-Content $envFile | Where-Object { $_ -match "^ASTERISK_EXTERNAL_IP=" } | Select-Object -First 1
    if ($line -match "^ASTERISK_EXTERNAL_IP=(.+)$") {
        $pinnedIp = $Matches[1].Trim().Trim('"').Trim("'")
    }
}
$liveIp = $null
try {
    $liveIp = (Invoke-WebRequest -Uri "https://ifconfig.me/ip" -UseBasicParsing -TimeoutSec 8).Content.Trim()
} catch {
    Write-Host "[WARN] Could not fetch live public IP: $_" -ForegroundColor Yellow
}
if ($liveIp) {
    Write-Host "[INFO] Live public IP: $liveIp"
}
if ($pinnedIp) {
    Write-Host "[INFO] ASTERISK_EXTERNAL_IP in .env: $pinnedIp"
    if ($liveIp -and $pinnedIp -ne $liveIp) {
        Write-Host "[FAIL] Public IP mismatch - SIP UP sends return RTP to the wrong address (Receive Count stays 0)." -ForegroundColor Red
        Write-Host "       Update infra/sipup/.env: ASTERISK_EXTERNAL_IP=$liveIp"
        Write-Host "       Then: cd infra/sipup; docker compose up -d --force-recreate"
    } elseif ($liveIp) {
        Write-Host "[OK] Pinned public IP matches live IP" -ForegroundColor Green
    }
} else {
    Write-Host "[INFO] ASTERISK_EXTERNAL_IP not set in .env - auto-detected on docker compose up"
    Write-Host "       Pin your public IP in infra/sipup/.env if DTMF breaks after ISP IP change."
}

Write-Host ""
Write-Host "During a live call, Receive Count must be > 0:" -ForegroundColor Yellow
Write-Host ('  docker exec ' + $container + ' asterisk -rx "pjsip show channelstats"')
Write-Host ""
Write-Host "Router: forward UDP ${rtpStart}-${rtpEnd} -> this PC LAN IP (same internal ports)."
