#Requires -Version 5.1
<#
.SYNOPSIS
  Fix SIP UP DTMF by syncing public IP, recreating Asterisk, and opening Windows RTP firewall.

.DESCRIPTION
  Common causes of "IVR inbound RTP is ZERO" / missing DTMF on real calls:
  1. ASTERISK_EXTERNAL_IP in .env is stale (ISP changed your public IP)
  2. Windows firewall blocks inbound UDP 10000-10100
  3. Router does not port-forward UDP 10000-10100 to this PC

  Run from repo (will prompt for Admin when opening firewall):
    cd Project\infra\sipup
    .\scripts\fix-rtp-dtmf.ps1
#>
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root ".env"

Write-Host "=== Fix RTP / DTMF for SIP UP ===" -ForegroundColor Cyan
Write-Host ""

# 1. Live public IP
Write-Host "Fetching live public IP..."
$liveIp = (Invoke-WebRequest -Uri "https://ifconfig.me/ip" -UseBasicParsing -TimeoutSec 10).Content.Trim()
Write-Host "Live public IP: $liveIp"

# 2. Update .env if needed
$pinnedIp = $null
if (Test-Path $envFile) {
    $lines = Get-Content $envFile
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^ASTERISK_EXTERNAL_IP=") {
            if ($lines[$i] -match "^ASTERISK_EXTERNAL_IP=(.+)$") {
                $pinnedIp = $Matches[1].Trim().Trim('"').Trim("'")
            }
            if ($pinnedIp -ne $liveIp) {
                Write-Host "Updating ASTERISK_EXTERNAL_IP: $pinnedIp -> $liveIp" -ForegroundColor Yellow
                $lines[$i] = "ASTERISK_EXTERNAL_IP=$liveIp"
                Set-Content -Path $envFile -Value $lines -Encoding UTF8
            } else {
                Write-Host "[OK] ASTERISK_EXTERNAL_IP already matches live IP" -ForegroundColor Green
            }
            break
        }
    }
    if (-not $pinnedIp -and ($lines -notmatch "^ASTERISK_EXTERNAL_IP=")) {
        Add-Content -Path $envFile -Value "ASTERISK_EXTERNAL_IP=$liveIp"
        Write-Host "Added ASTERISK_EXTERNAL_IP=$liveIp to .env" -ForegroundColor Yellow
    }
} else {
    Write-Host "[WARN] Missing $envFile — copy from .env.example first" -ForegroundColor Yellow
}

# 3. Recreate Asterisk with fresh rendered config
Write-Host ""
Write-Host "Recreating Asterisk (docker compose)..."
Push-Location $root
try {
    docker compose up -d --force-recreate
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit $LASTEXITCODE" }
} finally {
    Pop-Location
}
Write-Host "[OK] Asterisk recreated" -ForegroundColor Green

# 4. Firewall (elevated)
Write-Host ""
$ruleName = "Asterisk IVR RTP UDP 10000-10100"
$fw = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($fw -and ($fw | Where-Object { $_.Enabled -eq "True" })) {
    Write-Host "[OK] Windows firewall rule already exists" -ForegroundColor Green
} else {
    Write-Host "Opening Windows firewall (UAC prompt may appear)..." -ForegroundColor Yellow
    $firewallScript = Join-Path $PSScriptRoot "open-rtp-firewall.ps1"
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $firewallScript
    ) -Wait
}

# 5. Summary
Write-Host ""
Write-Host "LAN IP for router port-forward (UDP 10000-10100 -> same ports):" -ForegroundColor Yellow
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch "^127\." -and $_.PrefixOrigin -ne "WellKnown" } |
    ForEach-Object { Write-Host "  $($_.InterfaceAlias): $($_.IPAddress)" }

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart the ARI bridge: python scripts/run_sip_up_ari_bridge.py"
Write-Host "  2. Place a test call and press a digit"
Write-Host "  3. During the call, verify Receive Count > 0:"
Write-Host '     docker exec ivr-asterisk-dev asterisk -rx "pjsip show channelstats"'
Write-Host "  4. Bridge log should show: DTMF received digit=..."
Write-Host ""
& (Join-Path $PSScriptRoot "verify-rtp.ps1")
