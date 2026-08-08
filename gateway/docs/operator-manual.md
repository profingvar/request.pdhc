# Operator manual — request.pdhc

Day-2 operations for `request.pdhc`. Audience: the on-call operator.

## 1) Prerequisites

### 1.1 Software

- Docker / docker-compose (macmini has docker-compose v1; probe and fall back)
- PostgreSQL 16 (container `request_pdhc_db`)
- Python 3.14 + the venv at `gateway/venv/` (for local pytest only — the
  containers build their own venv from the Dockerfile)

### 1.2 Containers

The `request` compose project (`docker-compose.yml`) runs three containers:

| Container | Role | Port |
|---|---|---|
| `request_pdhc_db` | PostgreSQL 16-alpine (user `request_admin`, db `request_pdhc`) | `127.0.0.1:9061 → 5432` |
| `request_pdhc_app` | Flask + gunicorn; runs `flask db upgrade` on start | `127.0.0.1:9060` |
| `request_pdhc_worker` | Outbound webhook dispatcher — `flask webhook run-worker --interval 5`; no port, no migrations | — |

Both app and worker use the **same image + `.env`**. The DB volume is the
named external volume `request_pdhc_pgdata`.

### 1.3 Environment variables

Required in `gateway/.env` (see `.env.example`; `POSTGRES_PASSWORD` has **no
insecure default** — the compose file refuses to start without it, #369):

| Variable | Notes |
|---|---|
| `POSTGRES_USER` | `request_admin` (default) |
| `POSTGRES_PASSWORD` | **required**, no default |
| `POSTGRES_DB` | `request_pdhc` (default) |
| `DATABASE_URL` | `postgresql://request_admin:<pw>@localhost:9061/request_pdhc` (host/venv view); inside the containers compose sets it to `...@db:5432/...` |
| `FLASK_SECRET_KEY` | 32+ char random; never share across services |
| `JWT_SECRET_KEY` | 32+ char random |
| `SSO_BASE_URL` | `https://sso.pdhc.se` |
| `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET` | matched pair issued by sso.pdhc |
| `SSO_CALLBACK_URL` | `https://request.pdhc.se/api/v1/auth/callback` |
| `IPS_BASE_URL` / `IPS_API_KEY` | patient proxy **and** consent-at-dispatch source |
| `PLAN_BASE_URL` | PlanDefinition snapshot + dispatch |
| `CONTRACT_BASE_URL` | contract status + PAT auto-provision |
| `INTERNAL_SERVICE_KEY` | `X-Service-Key` gateway.pdhc presents to `/internal/*` |
| `HMAC_SECRET` | grant-token signing; held **only** by request.pdhc (gateway delegates to `/internal/grant/validate`) |
| `WEBHOOK_SECRETS_KEY` | Fernet key encrypting webhook signing secrets at rest |
| `TICKET_API_KEY` | lets the worker file DLQ ops tickets (falls back to `~/.pdhc/ticket_api_key`) |

`AUTH_DISABLED=true` is honoured **only** with `FLASK_ENV=development` — the
app refuses to boot with auth bypassed in any other environment (#91). Never
ship it to the server.

## 2) Start and stop

### 2.1 Start

```bash
cd /usr/local/www/request.pdhc
./start.sh
```

Brings up `request_pdhc_db` (`:9061`), then `request_pdhc_app` (`:9060`) —
which runs `flask db upgrade` via `entrypoint.sh` — then
`request_pdhc_worker`. Health:

```bash
curl -s https://request.pdhc.se/api/health
# {"status":"ok","database":"connected","service":"request.pdhc"}   HTTP 200
```

`/api/health` pings the DB (`SELECT 1`) and returns HTTP **503** with
`"database":"unavailable"` when it can't. It also sets
`Access-Control-Allow-Origin: https://www.pdhc.se` so services.html can read
the real body (#70).

### 2.2 Stop

Graceful, scoped to this compose project only:

```bash
./stop.sh    # kill -TERM gunicorn, wait, then compose stop
```

The `request_pdhc_pgdata` volume is preserved. **Never** `docker compose down
-v` — that deletes the database (CLAUDE.md §14).

## 3) Backup and restore

The DB user is **`request_admin`** (not `request`), database `request_pdhc`.

### 3.1 Database backup

```bash
docker exec request_pdhc_db pg_dump -U request_admin -F c -d request_pdhc \
  -f /tmp/request_pdhc_$(date -u +%Y%m%dT%H%M%SZ).dump
docker cp request_pdhc_db:/tmp/request_pdhc_*.dump ~/backups/
```

### 3.2 Restore

```bash
docker cp ~/backups/<dump-file>.dump request_pdhc_db:/tmp/restore.dump
docker exec request_pdhc_db pg_restore -U request_admin -d request_pdhc -c /tmp/restore.dump
```

`-c` = clean restore (drops + recreates objects). Drop it to merge.

> The macmini's default `postgres:16-alpine` `pg_hba.conf` trusts local /
> loopback connections, so these `docker exec` commands succeed **regardless
> of password**. That is not proof the app's password is correct — verify via
> `/api/health` (CLAUDE.md §9).

## 4) Common failures

### 4.1 Port conflicts

`9060` (app) and `9061` (db) must be free before start. `lsof -ti
tcp:9060,9061 | xargs kill` **only** after confirming nothing else is
listening — never kill outside this service's block (Rule 22).

### 4.2 Database not ready

`/api/health` returns 503 with `database: unavailable`:

- **Stuck container**: `docker restart request_pdhc_db`
- **Stale colima port-forward** (host can't reach container — see
  `infra_sso_safe_restart_bug.md`): `colima ssh -- docker restart
  request_pdhc_db`
- **Credential drift** (app unhealthy, db healthy, psycopg2 auth failures):
  reset the stored hash to match `.env` (CLAUDE.md §9):
  ```bash
  docker exec request_pdhc_db psql -h 127.0.0.1 -U request_admin -d request_pdhc \
    -c "ALTER USER request_admin WITH PASSWORD '<password from .env>';"
  docker restart request_pdhc_app request_pdhc_worker
  ```

### 4.3 SSO callback failing silently

Users land on `/api/v1/auth/callback` and get bounced back to login with no
error → the SSO client credentials in `.env` are wrong. Re-check
`SSO_CLIENT_ID` + `SSO_CLIENT_SECRET` against sso.pdhc's registry
(memory: `project_pdhc_sso_client_creds`).

### 4.4 Contract validation failing

SRs rejected on create with a contract-status error: the referenced contract
is not in the required status on contract.pdhc. See `admin-manual.md` §3.

### 4.5 Outbound webhooks not arriving

The webhook worker (`request_pdhc_worker`) delivers `service_request.dispatched`
notifications with retry/backoff and a dead-letter queue.

```bash
docker logs --tail 50 request_pdhc_worker              # tick output
docker exec request_pdhc_app flask webhook list-pending
docker exec request_pdhc_app flask webhook requeue --guid <delivery-guid>
```

- **Everything goes straight to `dead_letter`**: the provider org has no
  **active** `WebhookSigningSecret`. Issue/rotate one via the `flask`
  signing-secret commands (see `docs/webhook_dispatcher.md` /
  `provider_lifecycle.md`).
- **DLQ tickets**: on dead-letter the worker files a high-priority ticket on
  `ticket.mitidbok.se` (project `request.pdhc`). Needs `TICKET_API_KEY` (or
  `~/.pdhc/ticket_api_key`); without it the DB row still records the state.

### 4.6 Dispatch refused with 403 `consent_missing`

Not a bug — the consent-at-dispatch gate (Lag 2022:913 §5, #229) refused
because the destination caregiver holds no valid patient consent (or a
concept-narrowed consent that doesn't cover the payload). Confirm the
`careplan.dispatch.refused` audit row and check the patient's consents in
ips.pdhc.

## 5) Tests

```bash
cd gateway
source venv/bin/activate
pytest -q
```

Relevant suites: `test_consent_at_dispatch.py`, `test_webhook_dispatcher.py`,
`test_dispatch*.py`, `test_audit_read_decorator.py`, `test_internal_api.py`.

---

For runbook-style procedures (credential/PAT rotation, incident response,
upgrade) see the `runbooks/` directory, `provider_lifecycle.md`, and
`webhook_dispatcher.md`.
