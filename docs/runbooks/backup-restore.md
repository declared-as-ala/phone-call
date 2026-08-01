# SQLite Backup and Restore

## Schedule and retention

`ivr-backup.timer` runs daily at 02:15 UTC with up to 15 minutes of randomized delay.
It calls `scripts/backup_sqlite.sh`, which uses Python's SQLite online backup API and
verifies `PRAGMA integrity_check` before publishing the file. Local backups are mode
`0600` under `/opt/ivr-project/.local/backups` and are retained for 14 days.

Check the schedule and last result:

```bash
sudo systemctl status ivr-backup.timer --no-pager
sudo systemctl list-timers ivr-backup.timer --no-pager
sudo journalctl -u ivr-backup.service -n 50 --no-pager
```

## Off-box copies

Local backups do not protect against droplet loss. Set `BACKUP_UPLOAD_SCRIPT` in the
backup service environment to an executable owned by root. The script receives one
argument: the verified backup path. It should upload to a private, encrypted target
such as DigitalOcean Spaces or a restricted rsync host and exit nonzero on failure.

Example hook behavior (configure credentials through a root-readable environment or
instance role, never in this repository):

```bash
#!/usr/bin/env bash
set -euo pipefail
aws s3 cp "$1" "s3://YOUR_PRIVATE_BUCKET/ivr/$(basename "$1")" --sse AES256
```

Apply an independent 30-90 day lifecycle policy in the off-box destination and alert
on `ivr-backup.service` failures. Test downloading and opening one remote backup each
month.

## Manual backup

```bash
sudo -u ivr /usr/bin/bash /opt/ivr-project/scripts/backup_sqlite.sh \
  --database /opt/ivr-project/backend/ivr_verification.db \
  --output-dir /opt/ivr-project/.local/backups \
  --retention-days 14
```

The command prints `BACKUP_PATH=...` only after the integrity check passes.

## Restore

1. Download the selected backup from off-box storage to a root-only temporary path.
2. Verify it before stopping the application:

   ```bash
   sqlite3 /root/ivr-restore.sqlite3 'PRAGMA integrity_check;'
   ```

   Continue only when the output is `ok`.

3. Stop writers and preserve the current database through the online backup tool:

   ```bash
   sudo systemctl stop ivr-backend ivr-ari-bridge
   sudo -u ivr /usr/bin/bash /opt/ivr-project/scripts/backup_sqlite.sh \
     --database /opt/ivr-project/backend/ivr_verification.db \
     --output-dir /opt/ivr-project/.local/backups/pre-restore \
     --retention-days 30
   ```

4. Install the verified restore file, set ownership/permissions, and run migrations:

   ```bash
   sudo install -o ivr -g ivr -m 600 /root/ivr-restore.sqlite3 \
     /opt/ivr-project/backend/ivr_verification.db
   cd /opt/ivr-project/backend
   sudo -u ivr .venv/bin/alembic upgrade head
   ```

5. Start services and verify API/readiness, call history, and one end-to-end test call:

   ```bash
   sudo systemctl start ivr-backend ivr-ari-bridge
   sudo systemctl status ivr-backend ivr-ari-bridge --no-pager
   ```

Perform this restore procedure on staging before relying on it for production. Record
the backup timestamp, integrity result, row-count checks, and test-call outcome.
