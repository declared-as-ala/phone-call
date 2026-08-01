# SIP Credential Storage

The SIP UP password edited in the admin dashboard is stored in
`backend/.local/sip_up_account.json` as Fernet ciphertext. Production and staging
must set a stable `SIP_UP_SETTINGS_SECRET`; generate one with:

```bash
openssl rand -hex 32
```

Keep that value in the backend environment/secret manager and include it in the
encrypted infrastructure backup. Losing or changing it makes the stored SIP
password unreadable. Restore the original key or enter the SIP password again.

On first read, the backend automatically replaces a legacy plaintext JSON password
with ciphertext. The JSON file is written atomically and restricted to mode `0600`.
Do not copy its contents into tickets, logs, or chat.

The Asterisk renderer still requires `infra/sipup/.env` to contain the operational
password. That file is also forced to mode `0600`; it must remain untracked and be
handled as a production secret.

The SIP password found on the original developer checkout must be rotated in the SIP
UP control panel. Encryption protects future storage but cannot revoke a credential
that was previously exposed.
