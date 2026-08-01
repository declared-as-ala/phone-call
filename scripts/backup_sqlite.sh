#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --database PATH --output-dir DIR [--retention-days N]" >&2
}

database=""
output_dir=""
retention_days="${BACKUP_RETENTION_DAYS:-14}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --database) database="${2:-}"; shift 2 ;;
    --output-dir) output_dir="${2:-}"; shift 2 ;;
    --retention-days) retention_days="${2:-}"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ -z "$database" || -z "$output_dir" || ! "$retention_days" =~ ^[0-9]+$ ]]; then
  usage
  exit 2
fi

mkdir -p "$output_dir"
umask 077
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$output_dir/ivr-${timestamp}.sqlite3"
temporary="${destination}.tmp"
python_bin="${PYTHON_BIN:-python3}"

cleanup() {
  rm -f -- "$temporary"
}
trap cleanup EXIT

"$python_bin" - "$database" "$temporary" <<'PY'
import sqlite3
import sys
from pathlib import Path

source_path = Path(sys.argv[1]).resolve()
backup_path = Path(sys.argv[2]).resolve()
if not source_path.is_file():
    raise SystemExit(f"SQLite source does not exist: {source_path}")

source = sqlite3.connect(str(source_path), timeout=30)
destination = sqlite3.connect(str(backup_path))
try:
    source.backup(destination)
    result = destination.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise SystemExit(f"Backup integrity check failed: {result!r}")
finally:
    destination.close()
    source.close()
PY

mv -- "$temporary" "$destination"
find "$output_dir" -maxdepth 1 -type f -name 'ivr-*.sqlite3' -mtime "+$retention_days" -delete

if [[ -n "${BACKUP_UPLOAD_SCRIPT:-}" ]]; then
  if [[ ! -x "$BACKUP_UPLOAD_SCRIPT" ]]; then
    echo "BACKUP_UPLOAD_SCRIPT is not executable: $BACKUP_UPLOAD_SCRIPT" >&2
    exit 1
  fi
  "$BACKUP_UPLOAD_SCRIPT" "$destination"
fi

echo "BACKUP_PATH=$destination"
