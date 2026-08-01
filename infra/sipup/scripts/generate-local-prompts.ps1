# Generate static IVR WAV clips for Asterisk (Windows).
# Files land in Project/.local/asterisk-ivr/ (bind-mounted as /var/lib/asterisk/sounds/ivr).
#
# Usage (from repo root or infra/sipup):
#   .\infra\sipup\scripts\generate-local-prompts.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..\..")
$OutDir = if ($env:ASTERISK_IVR_SOUNDS_DIR) { $env:ASTERISK_IVR_SOUNDS_DIR } else { Join-Path $ProjectRoot ".local\asterisk-ivr" }
$DynDir = Join-Path $OutDir "dyn"
$ContainerName = if ($env:ASTERISK_CONTAINER_NAME) { $env:ASTERISK_CONTAINER_NAME } else { "ivr-asterisk-dev" }

New-Item -ItemType Directory -Force -Path $OutDir, $DynDir | Out-Null

function Find-Ffmpeg {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $winget) {
        $found = Get-ChildItem -Path $winget -Recurse -Filter "ffmpeg.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

$Ffmpeg = Find-Ffmpeg
if (-not $Ffmpeg) {
    Write-Error "ffmpeg not found. Install via: winget install Gyan.FFmpeg"
}

function New-IvrPrompt {
    param(
        [string]$Name,
        [string]$Text
    )
    $NativeWav = Join-Path $OutDir "$Name-native.wav"
    $Wav = Join-Path $OutDir "$Name.wav"

    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SetOutputToWaveFile($NativeWav)
    $synth.Speak($Text)
    $synth.Dispose()

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Ffmpeg -y -i $NativeWav -ar 8000 -ac 1 -sample_fmt s16 $Wav 2>&1 | Out-Null
    $ErrorActionPreference = $prevEap
    Remove-Item -Force $NativeWav -ErrorAction SilentlyContinue

    if (-not (Test-Path $Wav) -or (Get-Item $Wav).Length -lt 100) {
        Write-Error "Failed to create $Wav"
    }
    Write-Host "Created $Wav ($((Get-Item $Wav).Length) bytes)"
}

New-IvrPrompt "consent" "Hello. This is the exam verification system. To continue, press 1 or 2."
New-IvrPrompt "verification-code" "You received a 6 digit verification code from the official verification system. Please enter it now."
New-IvrPrompt "admin-send-code-instruction" "Please send the verification code to the administrator."
New-IvrPrompt "code-sent" "Code sent. Please wait."
New-IvrPrompt "pending-admin" "Please wait while the administrator verifies your code."
New-IvrPrompt "approved" "Approved. Thank you."
New-IvrPrompt "rejected" "Code not verified. Please try again."
New-IvrPrompt "failed" "Verification failed. Please contact the administration."
New-IvrPrompt "declined" "Verification declined. Goodbye."
New-IvrPrompt "goodbye" "Goodbye."

$running = docker ps --format "{{.Names}}" 2>$null | Select-String -Pattern "^$([regex]::Escape($ContainerName))$"
if ($running) {
    Write-Host ""
    Write-Host "Static prompts installed under $OutDir (mounted into $ContainerName as /var/lib/asterisk/sounds/ivr)."
} else {
    Write-Host ""
    Write-Host "Static prompts installed under $OutDir. Start Asterisk (docker compose up -d) to mount them."
}
