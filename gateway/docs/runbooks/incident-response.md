# Incident response — request.pdhc

Triage and recovery for production issues.

## 0) Triage tree

```
/api/health → 200 ?
  ├─ Yes:  service is up, look for behaviour bugs (provider feed, dispatch, validation)
  └─ No:   503 → "database: unavailable"  → §1
                  502 → app not reachable     → §2
                  Else                        → §3
```

## 1) DB unavailable (`/api/health` returns 503 with `database: unavailable`)

**Diagnosis sequence**:

1. Is the container running?
   ```bash
   colima ssh -- docker ps --format '{{.Names}}|{{.Status}}' | grep request_pdhc_db
   ```
   - If down: `colima ssh -- docker start request_pdhc_db`. Wait 5s, retry health.

2. Is the host port-forward to 9061 alive?
   ```bash
   lsof -iTCP:9061 -sTCP:LISTEN -P
   ```
   - If empty: Colima's host→VM forward died. Fix:
     ```bash
     colima ssh -- docker restart request_pdhc_db
     ```
     This re-triggers Lima's forward registration. (See memory `infra_sso_safe_restart_bug` — same class of bug.)

3. Can the app reach the DB inside the docker network?
   ```bash
   colima ssh -- docker exec request_pdhc_app python3 -c \
     'import os, psycopg2; psycopg2.connect(os.environ["DATABASE_URL"]).cursor().execute("select 1")'
   ```
   - If this fails with auth error: silent credential drift (see CLAUDE.md §9). The `pg_authid` hash and the password in `.env` have diverged. Reset:
     ```bash
     docker exec request_pdhc_db psql -h 127.0.0.1 -U request -d request_pdhc \
       -c "ALTER USER request WITH PASSWORD '$(grep DATABASE_URL gateway/.env | cut -d: -f3 | cut -d@ -f1)';"
     docker restart request_pdhc_app
     ```

## 2) App not reachable (`/api/health` 502 / connection refused)

**Diagnosis sequence**:

1. Is gunicorn alive?
   ```bash
   colima ssh -- docker exec request_pdhc_app sh -c 'pgrep -af gunicorn || echo NONE'
   ```

2. Is the host port-forward to 9060 alive?
   ```bash
   lsof -iTCP:9060 -sTCP:LISTEN -P
   ```

3. If both look fine but external still fails, the public reverse proxy is the issue — check miserver's nginx vhost for request.pdhc.se. **Don't edit nginx without the operator's approval.**

**Restart**:

```bash
cd /usr/local/www/request.pdhc
./safe_restart.sh
```

If `safe_restart.sh` includes a `kill` on any DB port, narrow the PORTS list to the **app port only** before running (see memory `infra_sso_safe_restart_bug` for the pattern).

## 3) Other 503 / 5xx from `/api/health`

Read `gunicorn.error.log`:

```bash
colima ssh -- docker exec request_pdhc_app tail -50 /app/logs/error.log
```

Common causes:

- Migration head mismatch after deploy → run `flask db upgrade` inside the container.
- SSO unreachable → `sso.pdhc` health degraded; request.pdhc tightly couples token validation to SSO. See sso.pdhc runbook.
- Disk full → `colima ssh -- df -h` then prune old containers / volumes.

## 4) Provider reports being rejected at gateway

Symptom: provider sees `/api/v1/provider/report/<sr_guid>` returning 4xx.

- **403 contract_not_active**: the contract's `Contract.status` is not `executed`. Edit the contract on contract.pdhc and set status to "Active". Provider can retry; same grant token still works.
- **410 grant_expired**: the DataExchangeGrant TTL elapsed. Provider must call `GET /provider/feed` to fetch a new one.
- **422 concept_out_of_scope**: provider trying to report a concept not in `Contract.return_scope`. Either add the concept to the contract (admin action) or the provider needs to drop it.

## 5) Audit chain compromise (suspected)

If you have any reason to believe `JWT_SECRET_KEY` or `HMAC_SECRET` was leaked:

1. **Rotate the affected secret immediately** (see `credential-rotation.md`).
2. Bump `User.token_revocation_epoch` for every user (forces re-login).
3. Invalidate all outstanding `DataExchangeGrant` rows:
   ```sql
   UPDATE data_exchange_grants SET expires_at = now(), uses_remaining = 0 WHERE expires_at > now();
   ```
4. Re-issue grants on demand as providers call `/provider/feed`.
5. Notify partners and the data protection officer.

## 6) Alerting & escalation

- **Pager target**: `ops@pdhc.se` + the on-call phone in CLAUDE.md.
- **First responder**: silence the alert only after confirming the symptom is resolved AND the audit log shows a clean trail.
- **Post-incident**: write a short note in `progress.md` with cause + fix + prevention. Add a memory entry if it's a class of bug we'd hit again.

## 7) Known recurring incidents

- **Colima port-forward wedge** after a `restart_all.sh` (`infra_sso_safe_restart_bug`): docker restart the DB container via `colima ssh`.
- **Silent credential drift** (CLAUDE.md §9): `ALTER USER ... WITH PASSWORD ...` re-syncs the hash.
- **CSV export hangs** on very large CarePlans: increase `--timeout` on gunicorn or paginate the export.
