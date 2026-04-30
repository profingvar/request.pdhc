# Operator manual — request.pdhc

Day-2 operations for `request.pdhc`. Audience: the on-call operator.

## 1) Prerequisites

### 1.1 Software

- Docker / docker-compose v2
- PostgreSQL 16 (in container `request_pdhc_db`)
- Python 3.14 + the venv at `gateway/venv/`

### 1.2 Environment variables

Required in `gateway/.env`:

| Variable | Notes |
|---|---|
| `DATABASE_URL` | `postgresql://request:<pw>@localhost:9061/request_pdhc` |
| `FLASK_SECRET_KEY` | 32+ char random; never share across services |
| `JWT_SECRET_KEY` | 32+ char random |
| `SSO_BASE_URL` | `https://sso.pdhc.se` |
| `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET` | matched pair issued by sso.pdhc |
| `SSO_CALLBACK_URL` | `https://request.pdhc.se/api/v1/auth/callback` |
| `CONTRACT_BASE_URL` | `http://host.docker.internal:9021` |
| `HMAC_SECRET` | held only by request.pdhc (gateway delegates grant validation here) |

## 2) Start and stop

### 2.1 Start

```bash
cd /usr/local/www/request.pdhc
./start.sh
```

Brings up `request_pdhc_db` on `:9061` then `request_pdhc_app` on `:9060`. Health: `https://request.pdhc.se/api/health` returns `200` with `{"status":"ok","database":"connected"}`.

### 2.2 Stop

```bash
./stop.sh
```

Graceful: `kill -TERM` to gunicorn, wait 10s, then `compose down`. Database volume is preserved.

## 3) Backup and restore

### 3.1 Database backup

```bash
docker exec request_pdhc_db pg_dump -U request -F c -f /tmp/request_pdhc_$(date -u +%Y%m%dT%H%M%SZ).dump request_pdhc
docker cp request_pdhc_db:/tmp/request_pdhc_*.dump ~/backups/
```

### 3.2 Restore

```bash
docker cp ~/backups/<dump-file>.dump request_pdhc_db:/tmp/restore.dump
docker exec request_pdhc_db pg_restore -U request -d request_pdhc -c /tmp/restore.dump
```

Use `-c` for clean restore (drops + recreates objects). Drop `-c` to merge.

## 4) Common failures

### 4.1 Port conflicts

`9060` (app) and `9061` (db) must be free before start. `lsof -ti tcp:9060,9061 | xargs kill` only after confirming nothing else is listening.

### 4.2 Database not ready

Symptom: `/api/health` returns 503 with `database: unavailable`. Causes:

- **Stuck container**: `docker restart request_pdhc_db`
- **Stale colima port-forward** (host can't reach container — see `infra_sso_safe_restart_bug.md`): `colima ssh -- docker restart request_pdhc_db`

### 4.3 SSO callback failing silently

If users land on `/api/v1/auth/callback` and get redirected to login again with no error, the SSO client credentials in `.env` are wrong. Re-check `SSO_CLIENT_ID` + `SSO_CLIENT_SECRET` against sso.pdhc's registry.

### 4.4 Contract validation failing

Service requests rejected with 422 / "contract not active": the contract referenced in the SR does not have `Contract.status == executed`. See `admin-manual.md` §3 for status semantics; the request fulfilment gate is not negotiable.

## 5) Tests

```bash
cd gateway
source venv/bin/activate
pytest -q
```

Endpoint smoke-test:

```bash
./scripts/test_api.sh   # if present, otherwise see api.md for a curl recipe
```

Results land in `./results/<timestamp>_results/`.

---

For runbook-style procedures (credential rotation, incident response, upgrade) see the `runbooks/` directory.
