#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$ROOT_DIR/../.." && pwd)"
OUT_DIR="${ASTERISK_IVR_SOUNDS_DIR:-$PROJECT_ROOT/.local/asterisk-ivr}"
DYN_DIR="$OUT_DIR/dyn"
CONTAINER_NAME="${ASTERISK_CONTAINER_NAME:-ivr-asterisk-dev}"

if ! command -v say >/dev/null 2>&1 || ! command -v afconvert >/dev/null 2>&1; then
  echo "This helper currently uses macOS 'say' and 'afconvert'."
  echo "Create WAV files manually under $OUT_DIR in the Asterisk container."
  exit 1
fi

mkdir -p "$OUT_DIR" "$DYN_DIR"

make_prompt() {
  local name="$1"
  local text="$2"
  local aiff="$OUT_DIR/$name.aiff"
  local wav="$OUT_DIR/$name.wav"

  say -v Samantha -o "$aiff" "$text"
  afconvert -f WAVE -d LEI16@8000 "$aiff" "$wav"
  rm -f "$aiff"
}

make_prompt consent "Hello. This is the exam verification system. To continue, press 1 or 2."
make_prompt verification-code "You received a 6 digit verification code from the official verification system. Please enter it now."
make_prompt pending-admin "Please wait while the administrator verifies your code."
make_prompt approved "Approved. Thank you."
make_prompt rejected "Code not verified. Please try again."
make_prompt failed "Verification failed. Please contact the administration."
make_prompt declined "Verification declined. Goodbye."

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  docker exec "$CONTAINER_NAME" mkdir -p /var/lib/asterisk/sounds/ivr/dyn
  echo "Installed static IVR prompts under $OUT_DIR (bind-mounted into $CONTAINER_NAME when compose is up)."
else
  echo "Installed static IVR prompts under $OUT_DIR (start Asterisk to mount them)."
fi
