# Credential rotation — request.pdhc

When to rotate any of the secrets request.pdhc holds, and how.

## What needs rotation

| Secret | Where stored | Rotation cadence | Who needs the new value |
|---|---|---|---|
| `JWT_SECRET_KEY` | `gateway/.env` | Every 90 days, or on suspected compromise | request.pdhc only — used to sign session-side data |
| `FLASK_SECRET_KEY` | `gateway/.env` | Same as above | request.pdhc only — Flask session cookie integrity |
| `HMAC_SECRET` | `gateway/.env` | Every 6 months, or on compromise | request.pdhc only — never shared with gateway.pdhc |
| `SSO_CLIENT_SECRET` | `gateway/.env` + sso.pdhc registry | Yearly, or on compromise | sso.pdhc (rotate there first, then update request.pdhc's .env) |
| Database password | `gateway/.env` + `pg_authid` in container | Yearly | request.pdhc only |
| Provider Access Tokens (PATs) | DB (`provider_access_tokens` table) + provider's secrets manager | Per-PAT — every 6 months by default | The specific provider |

## General procedure

1. **Generate new secret**:
   ```bash
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
   ```
2. **Update `gateway/.env`** with the new value.
3. **Restart the service**:
   ```bash
   ./safe_restart.sh
   ```
   (Per CLAUDE.md memory `infra_docker_restart_env`: `docker restart` keeps create-time env. Use `docker compose up -d` or the service's `safe_restart.sh` to pick up new `.env` values.)
4. **Verify**: `curl https://request.pdhc.se/api/health` returns 200.
5. **Audit**: an entry is auto-written to the audit log; verify via `GET /api/v1/audit?action=secret-rotated`.

## Rotating PATs (provider-facing)

Special workflow because the new credential must reach the partner securely:

1. Run `wire_provider.py --rotate <slug>` on miserver (idempotent; old PAT invalidated immediately, new one minted).
2. Capture the new PAT from the script's output (shown once).
3. Deliver to the partner's named technical contact via secure channel — Signal / Wire / encrypted ZIP. **Never** in plain email or shared password manager.
4. Confirm the partner authenticates successfully (check access log for first 200).
5. Rotation event is logged to `provider_access_token_audit` automatically.

Default cadence: 6 months. PDHC ops emails the partner 30 days in advance with the rotation date and a 24-hour overlap window so the swap is zero-downtime.

## Rotating the database password

```bash
# On miserver
NEW_PW=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# 1) Update inside the container's pg_authid (auth source of truth)
docker exec request_pdhc_db psql -h 127.0.0.1 -U request -d request_pdhc \
  -c "ALTER USER request WITH PASSWORD '$NEW_PW';"

# 2) Update .env
sed -i.bak "s|DATABASE_URL=.*|DATABASE_URL=postgresql://request:$NEW_PW@localhost:9061/request_pdhc|" \
  /usr/local/www/request.pdhc/gateway/.env

# 3) Restart the app (DB stays up)
docker restart request_pdhc_app
```

**Don't recreate the DB container on a password change** — `POSTGRES_PASSWORD` env var is consulted only on first init of the volume; changes don't take effect until the volume is wiped. The `ALTER USER` step is what actually updates `pg_authid`. (See CLAUDE.md §9 for the silent-credential-drift gotcha.)

## After any rotation

- Bump `User.token_revocation_epoch` if you rotated `JWT_SECRET_KEY` (forces all users to re-login).
- Add an entry to `changed_files.md` and `progress.md` with the date + reason.
- Confirm `/api/health` is 200 from the public URL, not just localhost.

## If rotation breaks something

Roll back: revert `.env`, restart. The audit log will show two rotation events with the second one as the rollback marker. Investigate the failure cause before re-attempting.
