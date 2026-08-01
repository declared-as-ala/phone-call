# Create ivr-dashboard-YYYYMMDD.zip for email/USB (no secrets, no heavy folders).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Date = Get-Date -Format "yyyyMMdd"
$ZipName = "ivr-dashboard-$Date.zip"
$ZipPath = Join-Path (Split-Path $Root -Parent) $ZipName
$Temp = Join-Path $env:TEMP "ivr-package-$Date"
if (Test-Path $Temp) { Remove-Item $Temp -Recurse -Force }
$Dest = Join-Path $Temp (Split-Path $Root -Leaf)
Write-Host "Copying project to temp (excluding heavy/sensitive paths)..."
robocopy $Root $Dest /E /XD node_modules .venv .git __pycache__ .pytest_cache dist .brv /XF .env .env.local .env.production.local *.db .DS_Store | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $Dest -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item $Temp -Recurse -Force
$SizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "Created: $ZipPath ($SizeMb MB)"
Write-Host "Email if under ~20 MB; otherwise use WeTransfer / Google Drive / USB."
