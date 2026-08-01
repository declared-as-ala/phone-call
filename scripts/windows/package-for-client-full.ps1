# Full client handoff zip (includes backend/.env and infra/sipup/.env).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Date = Get-Date -Format "yyyyMMdd"
$ZipName = "ivr-dashboard-full-$Date.zip"
$ZipPath = Join-Path (Split-Path $Root -Parent) $ZipName
$Temp = Join-Path $env:TEMP "ivr-package-full-$Date"
if (Test-Path $Temp) { Remove-Item $Temp -Recurse -Force }
$Dest = Join-Path $Temp (Split-Path $Root -Leaf)
Write-Host "Copying project (includes .env, excludes node_modules/.venv)..."
robocopy $Root $Dest /E /XD node_modules .venv .git __pycache__ .pytest_cache dist .brv .cursor /XF .env.local .env.production.local *.db .DS_Store | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $Dest -DestinationPath $ZipPath -CompressionLevel Optimal
Remove-Item $Temp -Recurse -Force
$SizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host "Created: $ZipPath ($SizeMb MB)"
if (Test-Path "$Root\backend\.env") { Write-Host "Included backend\.env (LuvVoice token)" }
Write-Host "WARNING: zip contains secrets — send only to the client."
