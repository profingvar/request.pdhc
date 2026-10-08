# request.pdhc — Progress Log

This document tracks progress after each step in the deployment plan (`readme.md`). Numbering matches the deployment plan. Test results are included per Rule 4.

---

## 1) Environment and infrastructure setup

### 1.1 Prerequisites (1.a–1.d) — DONE

- Docker Compose v5.1.0 — available
- Python 3.14.3 — available
- `psql` not installed locally (not blocking — DB accessed via Docker)
- Ports 9060–9063 — confirmed free

### 1.2 Project directory structure (1.e–1.j) — DONE

- Full directory tree created per plan
- `progress.md`, `changed_files.md`, `CLAUDE.md` created
- `pdhc.css` copied to `gateway/app/static/css/`
- `pdhc_markdown_layout_standard.md` and `repo_css.md` copied to project root
- `.gitignore` created

### 1.3 Git initialisation (1.k–1.l) — PENDING

- Git init not yet performed (awaiting operator decision)

---

## 2) Docker and database setup

### 2.1–2.3 Docker configuration (2.a–2.h) — DONE

- `docker-compose.yml` created with `db` (PostgreSQL 16) and `app` services
- `.env` and `.env.example` created
- `Dockerfile` and `entrypoint.sh` created
- Port allocation: 9060 (Flask), 9061 (PostgreSQL)

### 2.4 Start/stop scripts (2.i–2.k) — DONE

- `start.sh` created — kills ports, checks Docker, activates venv, starts compose, tails logs, Ctrl+C shutdown
- `stop.sh` created — graceful shutdown
- Both scripts made executable

---

## 3) Application foundation (3.a–3.j) — DONE

- Virtual environment created (`gateway/venv`)
- Dependencies installed via `requirements.txt`
- Flask app factory implemented (`app/__init__.py`)
- Configuration implemented (`app/config.py`)
- Upstream URLs configured (IPS, Plan, SSO)

### Tests — 6/6 PASSED

| Test | Result |
|------|--------|
| `test_app_creates` | PASSED |
| `test_app_testing_config` | PASSED |
| `test_config_upstream_urls` | PASSED |
| `test_config_database_url` | PASSED |
| `test_health_endpoint` | PASSED |
| `test_404_api_returns_json` | PASSED |

---

## 4) Data models (4.a–4.g) — DONE

- `dispatch_models.py`: `LocalUser`, `DispatchRequest`, `DispatchReceipt`
- `audit_models.py`: `AuditLog`
- `export_models.py`: `ExportRecord`
- All models use GUID (Rule 18), idempotency keys on dispatch
- Migration pending Docker DB start (using SQLite for tests)

---

## 5) Authentication and SSO (5.a–5.f) — DONE

- `auth_service.py`: SSO handshake, token validation, role mapping, dev mode
- `auth_middleware.py`: `@requires_auth`, `@requires_role` decorators
- `auth.py` API: login redirect, callback, logout, /me
- AUTH_DISABLED mode for local development

### Tests — 3/3 PASSED

| Test | Result |
|------|--------|
| `test_auth_me_dev_mode` | PASSED |
| `test_auth_login_redirect_disabled` | PASSED |
| `test_protected_endpoint_accessible_in_dev` | PASSED |

---

## 6) Patient lifecycle service (6.a–6.e) — DONE

- `patient_service.py`: proxy to IPS backend (list, get, create, update, delete)
- `patients.py` API: all CRUD endpoints with auth/role enforcement
- `patients.py` web routes: list, view, create, edit, delete with templates
- 4 patient templates created (list, view, create, edit)

### Tests — 6/6 PASSED

| Test | Result |
|------|--------|
| `test_list_patients_endpoint` | PASSED |
| `test_get_patient_endpoint` | PASSED |
| `test_create_patient_no_body` | PASSED |
| `test_create_patient_with_body` | PASSED |
| `test_update_patient_no_body` | PASSED |
| `test_delete_patient_endpoint` | PASSED |

---

## 7) CarePlan readout service (7.a–7.e) — DONE

- `careplan_service.py`: proxy to Plan backend (list, get)
- `careplans.py` API: list and read endpoints
- `careplans.py` web routes: list, view, readout with parsed transactions
- 3 careplan templates created (list, view, readout)

### Tests — 2/2 PASSED

| Test | Result |
|------|--------|
| `test_list_careplans_endpoint` | PASSED |
| `test_get_careplan_endpoint` | PASSED |

---

## 8) CarePlan parse and normalization (8.a–8.c) — DONE

- `parse_service.py`: transforms CarePlan into normalized transaction rows
- Idempotent, deterministic GUIDs, fallback defaults, partial-success handling

### Tests — 10/10 PASSED

| Test | Result |
|------|--------|
| `test_parse_produces_rows` | PASSED |
| `test_parse_idempotent` | PASSED |
| `test_parse_row_fields` | PASSED |
| `test_parse_sort_order` | PASSED |
| `test_parse_concept_data` | PASSED |
| `test_parse_expected_value` | PASSED |
| `test_parse_performer` | PASSED |
| `test_parse_empty_careplan` | PASSED |
| `test_parse_none_input` | PASSED |
| `test_parse_missing_optional_fields` | PASSED |

---

## 9) CSV export service (9.a–9.h) — DONE

- `csv_service.py`: generate CSV, preview, filename convention, schema v1.0.0
- `export.py` API: preview and CSV download endpoints
- `export.py` web routes: preview page and download
- Export records tracked in database

### Tests — 8/8 PASSED

| Test | Result |
|------|--------|
| `test_csv_valid_utf8` | PASSED |
| `test_csv_headers_match_schema` | PASSED |
| `test_csv_row_count` | PASSED |
| `test_csv_escaping` | PASSED |
| `test_csv_reproducible` | PASSED |
| `test_preview_returns_subset` | PASSED |
| `test_preview_has_headers` | PASSED |
| `test_filename_format` | PASSED |

---

## 10) Provider directory service (10.a–10.d) — DONE

- `provider_service.py`: proxy to Plan backend
- `providers.py` API: list endpoint

### Tests — 1/1 PASSED

| Test | Result |
|------|--------|
| `test_list_providers_endpoint` | PASSED |

---

## 11) CarePlan dispatch service (11.a–11.e) — DONE

- `dispatch_service.py`: create dispatch, idempotency check, receipt generation, audit logging
- `dispatch.py` API: submit and status endpoints
- `dispatch.py` web routes: form and receipt pages

### Tests — 3/3 PASSED

| Test | Result |
|------|--------|
| `test_dispatch_no_body` | PASSED |
| `test_dispatch_missing_provider` | PASSED |
| `test_dispatch_status_not_found` | PASSED |

---

## 12) Audit and observability (12.a–12.d) — DONE

- `audit_service.py`: log_event for all mutations
- Audit logging integrated into patient, careplan, dispatch, export flows

---

## 13) FHIR capability statement (13.a–13.d) — DONE

- `capability.py`: FHIR R5 CapabilityStatement at `/api/v1/metadata`
- Describes Patient (CRUD), CarePlan (read/search), dispatch, export operations

### Tests — 2/2 (in test_all_endpoints)

| Test | Result |
|------|--------|
| `test_metadata` | PASSED |
| `test_health` | PASSED |

---

## 14) Comprehensive endpoint test script (14.a–14.c) — DONE

### Full test suite results: 58/58 PASSED

Results stored in: `./results/2026-03-20T15-00-43Z_results/pytest_output.txt`

---

## 15) Web UI templates (15.a–15.j) — DONE

- `base.html` with PDHC design system, navbar, Lucide icons
- Dashboard with overview cards
- Patient templates: list, view, create, edit
- CarePlan templates: list, view, readout
- Dispatch templates: form, receipt
- Export templates: preview, download

---

## 16) Git initialisation (1.k–1.l) — DONE

- Git repository initialised on `main` branch
- Initial commit: 73 files, 5429 insertions
- `.env` excluded by `.gitignore` — verified safe

---

## 17) Docker stack test — DONE

- PostgreSQL 16 on port 9061 — healthy
- Flask-Migrate: `flask db init` + `flask db migrate` + `flask db upgrade` — 5 tables created
- Gunicorn on port 9060 — running (with `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` for macOS)

### Live endpoint test results

| Endpoint | Expected | Actual |
|----------|----------|--------|
| `GET /api/health` | 200 | 200 |
| `GET /api/v1/metadata` | 200 (CapabilityStatement, FHIR 5.0.0) | 200 |
| `GET /api/v1/auth/me` | 200 (dev access blob) | 200 |
| `GET /api/v1/Patient` | 502 (no live IPS in dev) | 502 |
| `GET /api/v1/CarePlan` | 502 (no live Plan in dev) | 502 |
| `GET /api/v1/providers` | 502 (no live Plan in dev) | 502 |
| `POST /api/v1/CarePlan/test/dispatch` (no body) | 400 | 400 |
| `POST /api/v1/CarePlan/test/dispatch` (missing provider) | 400 | 400 |
| `GET /` (dashboard) | 200 | 200 |
| `GET /patients` (web UI) | 200 | 200 |
| `GET /careplans` (web UI) | 200 | 200 |

All endpoints behave correctly. Upstream proxy calls return 502 as expected without live IPS/Plan backends in dev environment.

---

## 18) Provider subscription feed (subscription_design) — DONE

Implemented the `request.pdhc` upstream side of the provider subscription design.

### Changes made:
- **`dispatch_models.py`**: Added `provider_status`, `provider_status_updated_at` fields; added index on `provider_guid`
- **`auth_middleware.py`**: Added X-API-Key authentication (validates via SSO in prod, mock in dev)
- **`auth_service.py`**: Added `validate_api_key()` function
- **`capability.py`**: Added request-feed and request-status-update to CapabilityStatement
- **`app/api/requests.py`** (NEW): Three endpoints — list feed, single request, status callback
- **`app/services/request_feed_service.py`** (NEW): Core feed service with cursor pagination, careplan enrichment
- **`tests/test_request_feed.py`** (NEW): 18 tests
- **`subscription_design copy.md`**: Annotated Sections 6, 7, 8, and 13 with confirmed implementation details
- **Migration `837810485062`**: Applied — adds `provider_status`, `provider_status_updated_at`, `ix_dispatch_requests_provider_guid`

### Tests — 76/76 PASSED (58 existing + 18 new)

---

## 19) Remaining steps — PENDING

- Server deployment preparation (`safe_restart.sh`, nginx config)
- Transfer procedure per Rule 12 (when deploying to Mac Mini)

---

## 20) Production hotfixes — 2026-04-11

### 20.a — `/service-requests/create` patient dropdown was empty
Symptom: logged-in user opens *New ServiceRequest* → Patient dropdown has no
options. No error banner.

Root cause: `/usr/local/www/request.pdhc/gateway/.env` on the macmini had
**no `IPS_API_KEY=` line** at all. `patient_service._headers()` therefore
sent `Authorization: ApiKey ` (empty). `https://ips.pdhc.se/fhir/Patient`
returned `401 "Missing Authorization header"`, `resp.raise_for_status()`
raised `HTTPError`, `list_patients()` returned `(…, 502)`, and
`create_view` (`routes/service_requests.py:175`) fell through with
`patients = []` — template silently renders an empty `<select>`.

The key value still existed in three sibling backup dirs
(`gateway.bak.20260326_*`/.env, identical `NP_cT6G4n3S…`). Regression
likely happened during a .env rewrite after 2026-03-26 that also set
`AUTH_DISABLED=true`.

Fix applied:
```
cp .env .env.bak-2026-04-11T08-34-54Z
printf '\nIPS_API_KEY=NP_cT6G4n3S…\n' >> .env
docker-compose up -d --no-deps app    # recreate needed — docker restart
                                       # does NOT re-read env_file
```
Verified inside container: `IPS_BASE_URL` + `IPS_API_KEY` both set;
`patient_service.list_patients()` returned Bundle with total=16 across
3 managingOrganizations; `/service-requests/create` rendered with 16
`<option>` entries.

Worth remembering: `docker restart` re-uses the existing env, so .env
changes DO NOT take effect without `docker compose up -d` (or
`--force-recreate`). `env_file:` directives are resolved at container
create time, not boot time.

### 20.b — `.env` rewrite forensic, and why we are NOT restoring from the March backup

While investigating 20.a I also diffed the live `.env` against
`/usr/local/www/request.pdhc/gateway.bak.20260326_231722/.env` (last
miserver-owned backup, mtime 2026-03-26 23:17). Significant changes
between that backup and the pre-fix live `.env`:

- `DATABASE_URL` password `tzFy0B6HhHVrSLzlZT16hrVvzDH2Cb9I` → `request_dev_2026!`
- `FLASK_ENV=production` → `development`
- `AUTH_DISABLED=false` → `true`
- `JWT_SECRET_KEY` rotated
- `SSO_CLIENT_ID` + `SSO_CLIENT_SECRET` removed entirely
- `SSO_CALLBACK_URL=https://request.pdhc.se/…` → `http://localhost:9060/…`
- `PLAN_BASE_URL=https://plan.pdhc.se` → `http://localhost:9030`
- `CONTRACT_BASE_URL` added pointing at `http://localhost:9021`
- `HMAC_SECRET` added (new for DataExchangeGrant)
- `FORMS_1177_WEBHOOK_URL` + `FORMS_1177_API_KEY` added
- `IPS_API_KEY` removed (this was the actual regression — see 20.a)

Ownership footprint: `gateway.bak/.env` (not `gateway.bak.<ts>/…`) is
**root-owned** with mtime 2026-03-27 08:23:04 — meaning whoever rewrote
`.env` used `sudo`. Claude's envelope is non-sudo (Rule 19), so this
was an operator action, not mine.

**Important caveat from user on 2026-04-11:** the March 26 backup is
two weeks stale and the service has been running fine in the rewritten
state for those two weeks. That means the rewrite was intentional, not
a botched template fill. Do NOT restore the old SSO/DB/URLs from the
backup — they are stale, and the current state is the intended state.

During diagnosis I briefly flipped `AUTH_DISABLED` to `false` and
recreated the app. With that on, the auth gate was live (302 →
`/api/v1/auth/login` → SSO), but the surrounding SSO config is now
incomplete (no `SSO_CLIENT_ID`/`SECRET`, callback URL points at
localhost), so the login flow would dead-end in a real browser. I
reverted to `AUTH_DISABLED=true` at 08:45 UTC — service is back to the
"working well" steady state plus the IPS key fix.

### 20.c — `/service-requests/create` Plan + Forms dropdowns were empty
Symptom (reported after 20.a was verified): patient dropdown now fills,
but the PlanDefinition picker and the Forms multi-select render empty.

Root cause: `.env` had `PLAN_BASE_URL=http://localhost:9030` and
`CONTRACT_BASE_URL=http://localhost:9021`. These URLs had been pointing
at localhost since the 2026-03-27 rewrite, which works only if the
Flask app is bare-metal on the macmini. This app is containerised, so
`localhost` inside the container is the container's loopback, not the
host — `plan.pdhc` is unreachable and the HTTP GETs die with
`ConnectionError`, which the service layer catches and returns as
`(…, 502)`. The create view sees status ≠ 200 and silently passes an
empty list to the template.

Probe from inside `request_pdhc_app`:
  http://localhost:9030/api/v1/plandefinitions     ConnectionError
  http://host.docker.internal:9030/api/v1/…         200
  https://plan.pdhc.se/api/v1/plandefinitions       200

Fix: `PLAN_BASE_URL=https://plan.pdhc.se`. Went public-URL rather than
`host.docker.internal:9030` because (a) it's the canonical pdhc.se
pattern used by dashboard.pdhc and siblings, (b) it doesn't depend on
Colima's host-internal aliasing being present on whatever runs the
container in future, and (c) plan.pdhc's `/plandefinitions` and
`/forms` endpoints return 200 unauthenticated, so no API-key/SSO hop
is needed. Verified inside container after recreate:
  plan_definition_service.list_plan_definitions() → 200, 7 items
  form_service.list_forms()                       → 200, 1 item
  `/service-requests/create` (external 200, size 42 KB, 7 plandef
  options + 1 form checkbox rendered alongside the 16 patients)

**`CONTRACT_BASE_URL=http://localhost:9021` was also fixed** — see 20.d below.

### 20.d — No providers listed after Finalize
Symptom (reported right after 20.c verified): user finalized a
ServiceRequest, landed on `view_detail`, got no eligible-provider list.

Root cause: `CONTRACT_BASE_URL=http://localhost:9021` — same
localhost-in-container bug as 20.c but on a different upstream.
`view_detail` only calls `find_eligible_providers` when
`sr.status == "active"` (i.e. post-Finalize), which is why the create
page worked but the post-finalize view didn't. Inside
`find_eligible_providers → contract_service.find_matching_contracts →
list_contracts` the `requests.get("http://localhost:9021/fhir/Contract")`
hit ConnectionError, bubbled up as (…, 502), and `view_detail`
silently rendered `eligible_providers=[]`.

Also affected (same root cause): contract-name resolution for matches
already attached to existing SRs. Before the fix, `view_detail` would
leave both the SR header's contract name AND the matches-table
contract names blank.

Fix: `CONTRACT_BASE_URL=https://contract.pdhc.se`. Same public-URL
pattern as 20.c. Verified end-to-end:
  contract_service.list_contracts() → 200, 4 contracts
  Four active SRs in DB (pd `99d0c2c6…` = "Ask_CGM"):
    f61dcc00 → 2 eligible (ASK CGM/cgm_provider, Form till 1177/1177)
    523d1227 → 1 eligible (Form till 1177)
    dc95194b → 1 eligible (Form till 1177)
    3e2b96bf → 1 eligible (Form till 1177)

### 20.e — CGM→gateway: grant validation bug (INTERNAL_SERVICE_KEY + validate_grant contract_guid filter)

**Symptom.** `active streaming from CGM is running but gateway fails to receive.`
Gateway's error.log was spamming one POST per minute:

```
ERROR in grant_validation: Grant validation auth rejected — check REQUEST_INTERNAL_SERVICE_KEY
WARNING in push_service: Receipt delivery failed: HTTP 503
```

and gateway's access.log showed CGM's `POST /api/v1/provider/report/f61dcc00-…`
returning `403 63 bytes` every minute.

**Two bugs, stacked.**

**Bug 1 — `INTERNAL_SERVICE_KEY` missing from request.pdhc's `.env`.**
request.pdhc's `/internal/grant/validate` (internal.py:35) is guarded by
`@requires_service_key` (middleware/auth_middleware.py:120-132), which compares
the caller's `X-Service-Key` header against `current_app.config['INTERNAL_SERVICE_KEY']`
via `hmac.compare_digest`. If the config key is empty, the middleware short-circuits
with `401 unauthorized` — which is exactly what gateway's `GrantValidationService.validate()`
(gateway_app/app/services/grant_validation.py:98-104) then logs as
`Grant validation auth rejected — check REQUEST_INTERNAL_SERVICE_KEY`.

Cause: the server's request.pdhc `.env` was missing the whole line. Gateway's own
`.env` has `REQUEST_INTERNAL_SERVICE_KEY=<64-char value>`; the two sides of the
link were never in sync.

**Fix for bug 1.** Copied gateway's `REQUEST_INTERNAL_SERVICE_KEY` value into
request.pdhc's `.env` as `INTERNAL_SERVICE_KEY=<same value>`, entirely server-side,
without exposing the secret in conversation. Backup:
`.env.bak-2026-04-11T10-20-15Z`. `docker-compose up -d --no-deps app` to make
env_file re-resolve (Rule: `docker restart` does NOT re-read `env_file:`; only
create-time compose ops do). Verified the old repeating ERROR line stopped in
gateway's error.log at `12:19:16` — from then on, no more `auth rejected`.

**Bug 2 — gateway's grant/validate call doesn't send `contract_guid`, request.pdhc's `validate_grant()` used to require it.**

Once bug 1 was out of the way, gateway's POSTs started returning `403 78 bytes`
(different size = different error code). Direct probe from the macmini to
`/internal/grant/validate` with the right service key:

```
curl -s -X POST http://127.0.0.1:9060/api/v1/internal/grant/validate \
  -H 'X-Service-Key: $SK' -H 'Content-Type: application/json' \
  -d '{"sr_guid":"f61dcc00-…","patient_guid":"c5b5958e-…","org_guid":"077d02be-…","grant_token":"$TOK"}'
→ HTTP 200  {"valid": false, "error": "Grant invalid, expired, or revoked"}
```

The stored grant row **was** valid (not revoked, not expired, HMAC matches the
token CGM holds). The difference vs. success: gateway's `GrantValidationService.validate()`
(grant_validation.py:82-87) only sends `{sr_guid, patient_guid, org_guid, grant_token}` —
**no `contract_guid`**, because gateway derives `contract_guid` *from* the
grant validation response (report_ingestion.py:92 `contract_guid = grant_result.contract_guid`)
and cannot know it at call time.

On the request.pdhc side, `internal.py:59` was reading `body.get('contract_guid', '')`,
and `grant_service.validate_grant()` then did:

```python
grant = DataExchangeGrant.query.filter_by(
    service_request_guid=service_request_guid,
    provider_org_guid=provider_org_guid,
    contract_guid=contract_guid,   # = '' from gateway
    revoked=False,
).first()
```

Empty string never matched the real `contract_guid='ef7aee85-…'`, so every
gateway-initiated grant check returned `None` → `"Grant invalid, expired, or revoked"`
→ `GRANT_TOKEN_INVALID` 403. Probing WITH `contract_guid` returned `valid: true`,
confirming the field mismatch was the whole story.

The contract_guid filter was redundant anyway — `validate_grant()` already HMAC-
verifies the `grant_token` via `hmac.compare_digest` (grant_service.py:128), so a
caller without the `HMAC_SECRET` cannot forge a match. The 4-tuple (sr, org,
patient) + HMAC is sufficient. Only caller needing the contract filter to remain
a filter is request.pdhc's own `report_service.py:54`, which always passes a
real contract_guid — unaffected by the change.

**Fix for bug 2.** `app/services/grant_service.py::validate_grant()` now treats
`contract_guid` as an optional filter:

```python
filters = dict(
    service_request_guid=service_request_guid,
    provider_org_guid=provider_org_guid,
    revoked=False,
)
if contract_guid:
    filters['contract_guid'] = contract_guid
grant = DataExchangeGrant.query.filter_by(**filters).first()
```

Edited locally, then deployed:

```
scp grant_service.py miserver:/usr/local/www/request.pdhc/gateway/app/services/
# backup: grant_service.py.bak-2026-04-11T10-51-05Z
cd /usr/local/www/request.pdhc/gateway
docker-compose up -d --no-deps --build app
```

**Verification.** Direct probe post-deploy, no `contract_guid`:
```
HTTP 200  {"valid": true, "contract_guid": "ef7aee85-…", "grant_type": "bidirectional", ...}
```

Gateway `audit_log` shows the cutover cleanly:

```
until 10:50 UTC   report.rejected  GRANT_TOKEN_INVALID   "Grant invalid, expired, or revoked"
from 10:51 UTC    report.rejected  VALIDATION_ERROR      "concept_guid / response_type missing"
```

**Remaining downstream issue (out of scope for this fix).** CGM's POSTs now
clear PAT auth → grant validation → SR context, but fail `ObservationValidator`
with `observation[0]` missing `concept_guid` and `response_type`. Gateway's
`report_ingestion.py:142-154` auto-fills `concept_guid` from the SR's transaction
map when the obs carries a `transaction_guid` — so either CGM isn't sending
`transaction_guid`, or its transaction_guid doesn't match an entry on the SR.
That's a CGM-side data/contract issue, not a request.pdhc or gateway auth bug.

**Also noted, not this session's work.** `push_service: Receipt delivery failed:
HTTP 503` continues once per minute — gateway's rejection-receipt push to
`provider1.pdhc` (via `PROVIDER_SERVICE_URL`) is returning 503 on every attempt.
Separate broken endpoint on provider1.

### 20.f — open questions + remaining tasks, not blocking

- When was the last time the patient dropdown on `/service-requests/create`
  actually worked in production? If it was within the last 2 weeks, the
  IPS_API_KEY drop happened after the Mar 27 rewrite, not during it —
  which would point at a second, more recent silent .env edit.
- The DB-side password drift I fixed this morning (ALTER USER to
  `request_dev_2026!`) does not have a clean root cause. If the service
  had been running in the `request_dev_2026!` state all along,
  `pg_authid` should already have matched. Something rotated the hash
  between "working well" and this morning's `(unhealthy)` state.
- Rule 23 is still technically violated by `AUTH_DISABLED=true` on a
  `.pdhc.se` subdomain, but switching it on is non-trivial given the
  above — needs operator to supply the current prod `SSO_CLIENT_ID`/
  `SSO_CLIENT_SECRET`/callback URL before it becomes useful.

---

## 2026-04-11 afternoon — Goal enrichment fallback + PAT push-field exposure

Context: gateway.pdhc was rejecting every CGM observation with
`SCOPE_VIOLATION` because it tagged observations with the transaction's
procedure concept (CGM) instead of the goal's measurement concept
(B-glucos). Fix lives primarily in gateway.pdhc/report_ingestion but
needs two upstream changes on request.pdhc:

1. **`gateway/app/services/context_service.py`** — `_extract_transactions`
   now emits `goal_guid` / `goal_concept_guid` / `goal_concept_name` on
   every transaction, reading from the transaction → the activity → a
   top-level single-goal inference over `snapshot.goals[]`. Today's
   PlanDefinitions are built by plan.pdhc with a single top-level goal
   per plan and no activity→goal FK, so the inference path is what
   currently wins. Future multi-goal support will need plan.pdhc's
   `_plandef_full_dict` (already edited but not yet deployed) to stamp
   the activity and transaction with an explicit `goal_guid`.

2. **`gateway/app/api/provider.py`** — `/provider/validate-token` now
   includes `push_endpoint_url` and `push_auth_key` in its response
   body, sourced from the `ProviderAccessToken` record. This lets
   gateway.pdhc route receipts per-PAT without a global
   `PROVIDER_SERVICE_URL` / `BOOTSTRAP_SU_API_KEY` config — a single
   gateway deployment can serve many providers (CGM, provider1, …)
   without config changes.

### Deploy
- `scp` both files over the existing `/usr/local/www/request.pdhc/gateway/app/...`
  on miserver.
- `docker-compose up -d --build app` in `/usr/local/www/request.pdhc/gateway`
  — app image rebuilt, db untouched.
- Verified via
  `curl http://127.0.0.1:9060/api/v1/internal/service-request/523d1227-132b-4d2a-8129-fdbb1519b039/context`
  — returned `goal_concept_guid = 1c34a590-... (B-glucos)` and
  `goal_concept_name = B-glucos` on the transaction via the
  single-goal fallback (the activity has no `goal_guid` today, so
  inference kicks in).

---

## 2026-04-19 — Ticket #90: archived-request searchability + late-arrival flag

Paired change across `request.pdhc` + `gateway.pdhc`. This file covers
the `request.pdhc` half; the corresponding gateway work is in
`gateway.pdhc/progress.md`.

### Ticket
`#90 When request is archived — It should still be searchable from the
gateway, but data should be labelled late when arriving after end of
request time. So see to that the request has a clear endpoint that is
communicated to all different providers.`

### Changes on request.pdhc

- `provider_feed_service.list_for_provider`: now includes SRs with
  `status in ('active', 'archived')` instead of `status == 'active'`.
  Feed entries gain `sr_status`, `period_start`, `period_end` so
  providers see the submission window cutoff (the "clear endpoint").
- `provider_feed_service.download_bundle`: accepts downloads for
  archived SRs too, still blocks drafts/revoked. Response gains
  `sr_status` + `period_start` + `period_end` so that a late download
  immediately signals the provider to expect its reports to be flagged.

Tests (5/5 pass): `tests/test_provider_feed_archived.py`:
- archived SR appears in feed
- feed entry exposes period_end + sr_status
- draft SR still excluded
- archived SR downloadable
- draft SR download returns 400.

### Test suite
- New: 5/5 pass.
- Full suite: 89 pass, 3 fail — all 3 failures are pre-existing (not
  touched by this change): `test_careplans.test_list_careplans_endpoint`
  + `test_all_endpoints.TestCarePlanEndpoints.test_list` (404 instead of
  200/502, upstream Plan unreachable in dev) and
  `test_internal_api.TestSRContext.test_returns_context` (transaction
  extraction mismatch from an earlier context_service change, unrelated
  to archived-feed work).

### Deploy status
**Deployed to macmini 2026-04-19T18:36Z.** Backup first
(`~/backups/20260419T183459Z_ticket90_preflight/` — request_pdhc.pgdump
488K, gateway_pdhc_db.pgdump 1.3M).
Shipped: `gateway/app/services/provider_feed_service.py` (sha
`397f277f275f55ea60da3d5cbcb53dd0c9f5cd81`, verified match).
Rebuilt container via `docker-compose up -d --no-deps --build app` in
`/usr/local/www/request.pdhc/gateway`. Both `request_pdhc_app` and
`request_pdhc_db` report `healthy`. `/api/health` returns 200
`{"status":"ok","database":"connected"}` on both internal
(127.0.0.1:9060) and external (https://request.pdhc.se/api/health).

Smoke test against prod data (org `e0153481-…-c356ca`): feed returns
7 items — 3 active + 4 archived. Each entry carries new `sr_status`
and `period_end` fields. `download_bundle()` on archived SR
`6b5c103a-…-cecf1a` returns 200 with grant token + FHIR resource.
Ticket #90 request.pdhc side verified live.

### Earlier in the day — grant_service contract_guid bug

Before the enrichment work, gateway's grant auth was failing on every
CGM POST with `GRANT_TOKEN_INVALID`. Root cause:
`grant/app/services/grant_service.py :: validate_grant()` required
`contract_guid` as a filter, but gateway's
`GrantValidationService.validate()` doesn't pass it (it derives
`contract_guid` from the validated grant response). Old code did
`filter_by(contract_guid='')` and matched nothing.

Fix: `validate_grant` treats `contract_guid` as an **optional** filter.
HMAC `grant_token` + patient/org/sr uniqueness is already sufficient;
the contract_guid filter was redundant when present and broken when
absent. Rebuilt via `docker-compose up -d --no-deps --build app`.
Confirmed live via audit_log cutover: CGM POSTs to `/provider/report/...`
flipped from `403 GRANT_TOKEN_INVALID` (10:50 UTC) to `422
VALIDATION_ERROR` (10:51 UTC) — grant auth path fully clear.
The remaining 422 was then unblocked by the goal enrichment fix above.

---

## Ticket #94 — "Callback URL not in allowlist" banner on login (2026-04-21)

**Symptom.** Users logging in from request.pdhc landed on the sso.pdhc
dashboard with a yellow banner "Callback URL not in allowlist." — login
itself succeeded session-wise, but the redirect back to request.pdhc
never happened.

**Root cause.** `/usr/local/www/request.pdhc/gateway/.env` on miserver
still held the dev default:

```
SSO_CALLBACK_URL=http://localhost:9060/api/v1/auth/callback
```

sso.pdhc's `ALLOWED_CALLBACK_URLS` contains the prod URL
`https://request.pdhc.se/api/v1/auth/callback` but not the localhost
one, so `sso.pdhc/app/src/routes/frontend.py:237` fell through to the
`flash('Callback URL not in allowlist.', 'warning')` branch and
redirected to the SSO dashboard instead.

**Fix.** Flipped the env value on the server to
`https://request.pdhc.se/api/v1/auth/callback`, backed up the old file
at `.env.bak.20260421T064416Z`, recreated the container via
`docker-compose up -d app` (NOT `docker restart` — `restart` skips
`env_file` reload; see auto-memory). Container came back healthy in
9 s; `docker exec request_pdhc_app env | grep SSO_CALLBACK_URL`
confirmed the new value.

**Verification.**
```
$ curl -sI https://request.pdhc.se/api/v1/auth/login | grep -i location
location: https://sso.pdhc.se/login?next=https://request.pdhc.se/api/v1/auth/callback&state=...
```
The `next=` is now an allowlisted URL — the warning branch will no
longer fire.

**Secondary finding.** cdr.pdhc's configured
`SSO_CALLBACK_URL=https://cdr.pdhc.se/auth/callback` is also missing
from sso.pdhc's `ALLOWED_CALLBACK_URLS`. Flagged in the ticket response
for the operator to add (Rule 22: Claude does not edit sso.pdhc's .env).

**Fix 2 (underlying bug exposed after Fix 1).** With SSO accepting the
callback URL, the callback landed but returned
`{"code":"auth_error","message":"Token validation failed"}`. Diagnosis
via `current_app.logger.warning()` instrumentation on the callback path
revealed `validate_sso_token()` returning `None` — SSO's
`/api/auth/me/service` was rejecting the call. Root cause:
**request.pdhc's `.env` had no `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET`
set**, so the service-to-service `X-SSO-Client-*` headers were empty.
sso.pdhc stores the per-service creds as `SSO_CLIENT_ID_REQUEST` /
`SSO_CLIENT_SECRET_REQUEST`.

Appended to `/usr/local/www/request.pdhc/gateway/.env` (backup
`.env.bak.20260421T074242Z`):
```
SSO_CLIENT_ID=zfncsCKhQ2-ZLRrQ-9mqamW7hKeGy0Xv
SSO_CLIENT_SECRET=<matches SSO_CLIENT_SECRET_REQUEST>
```
Container recreated with `docker-compose up -d app`. Login flow
end-to-end verified by operator in a fresh Safari private window.

**Cleanup.** Instrumentation backed up to
`/usr/local/www/request.pdhc/gateway/app/api/auth.py.bak.20260421T065948Z`
and restored via `docker-compose up -d --build app`. Server auth.py
sha256 now matches local (`98896f90...`).

**Why this only bit now.** request.pdhc on the server had been running
with `AUTH_DISABLED=true` + `FLASK_ENV=development` (Ticket #91), so
the SSO path was never exercised. Flipping to prod auth mode unmasked
both config gaps at once. See CLAUDE.md §9-style sibling: worth a
proactive audit of every service's `.env` on miserver for missing
`SSO_CLIENT_ID`/`SECRET` before the next prod flip.

---

## Patient timeline (metro map) — 2026-08-10

New feature: a "separate HTML" that draws a plan schedule as a metro map —
one line per activity, one station per scheduled occurrence; hovering a
station lists the concepts collected there (the activity's transactions,
required/optional + unit). Endless (unbounded recurring) requests draw the
first month then a dashed "…"; requests bounded by count/duration/period_end
end in a solid terminus ring.

**Files**
- `gateway/app/services/timeline_service.py` (NEW) — pure `build_timeline()`
  schedule model (lines/stations/gridlines). 10 unit tests
  (`tests/test_timeline_service.py`), all green.
- `gateway/app/templates/service_requests/plan_timeline.html` (NEW) — SVG map
  + self-contained hover-tooltip JS + static per-line concept legend.
- `gateway/app/routes/service_requests.py` — `timeline_view`
  (`/service-requests/<guid>/timeline`, from the SR snapshot, anchored at
  period_start, bounded by period_end) + `plan_timeline_preview`
  (`/plan-timeline/<plandef_guid>`, anchored today, endless).
- `view.html` — "View Timeline" button on the SR PlanDefinition card.
- `create.html` — "Preview schedule timeline ↗" link that appears on the
  create form once a PlanDefinition is picked (preview before dispatch).

**Deployed** to request.pdhc.se 2026-08-10 via `docker-compose up -d --build app`
(project `request`; both prod files diffed identical to base before overwrite —
no server-only divergence). Verified live: health 200, both routes registered,
and the dispatched Medituner SR `4b8598b0-…` (asthma plan, UAS requester,
no period → endless) renders through the running container: Daily diary 31
stations/9 concepts + Weekly spirometry 5 stations/1 concept.
Commits b8ae4db (feature) + create-page preview link.

---

## Spärr filter auth fix (ips 401) — 2026-08-10

Chased down the `ips block fetch … -> 401` seen while rendering the timeline.
Root cause (three layers, all real): request.pdhc's `ips_client` sent the key
as `X-API-Key`, but ips.pdhc `require_auth` reads ONLY the `Authorization`
header (`Bearer`/`ApiKey`) — so every `/blocks` call 401'd; the code swallowed
4xx as "no blocks" → `is_sr_visible` always True → **the SR-list/detail spärr
filter silently failed open** (no SR ever hidden). It also targeted the staff
`/blocks` list (clinic-gated, redacts `source_scope_id` for the service-account
key) and parsed the wrong response key (`blocks`/`entry` vs ips `items`).

Fix (chosen approach A): switched to ips.pdhc's purpose-built cross-service
predicate `GET /api/v1/patients/<pid>/blocks/check?source_clinic_id=<org>` with
`Authorization: ApiKey`. No patient-clinic relationship required, un-redacted
`is_blocked` + `blocking_scopes`, clinic-vs-caregiver match done server-side.
Filter is now one cached lookup per (patient, requester_org); v1
lift-exposes-SR semantics preserved; fails open only on genuine errors.
Rewrote `test_blocks_filter.py` (17 tests, incl. a transport assertion that the
header is `Authorization: ApiKey` and the endpoint is `/blocks/check`). Full
suite 185 passing. Deployed 2026-08-10 (`docker-compose up -d --build app`);
verified live: `check_block` returns non-401, Medituner SR stays visible
(patient absent from ips → no block).

**Follow-up (ticketed):** `ips_consent_client.py` has the SAME `X-API-Key` bug
on the `/consents` gate used by `dispatch_service` when a
`destination_caregiver_guid` is present. Failure mode is fail-CLOSED (empty
consents → dispatch refused 403), so it over-blocks rather than leaks — safer,
but wrong. Not bundled here (separate safety gate); ticket opened.

---

## #558 — consent-gate auth fix (twin of the spärr block fix) — 2026-08-10

`ips_consent_client` had the same `X-API-Key` bug as the block client, on the
`/consents` gate used by `dispatch_service` when a `destination_caregiver_guid`
is present. Confirmed the header flip alone was insufficient: ips `list_consents`
is clinic-gated (`_can_act_on_patient`) → 403 for the service-account key; and
`care_access_check` answers a different question (observation-read zone, not the
dispatch consent gate). Failure mode was fail-CLOSED (empty consents →
`no_consent` → every cross-caregiver dispatch refused 403).

Fix (2-service): added a relationship-free predicate on **ips.pdhc**
(`GET /api/v1/patients/<pid>/consents/check?grantee_caregiver_guid=<cg>`, commit
d8b6dbb, mirror of `/blocks/check`), and pointed `ips_consent_client` at it with
`Authorization: ApiKey`, cached per (patient, grantee); `dispatch_service` passes
the destination caregiver through. `consent_covers_dispatch` logic unchanged.
ips suite 402 green; request suite 188 green. Both deployed 2026-08-10; verified
live: the deployed request client → deployed ips `/consents/check` returns 404
(patient absent) instead of 401 — auth now passes.

---

## 2026-09-23 — #583 concept definition on the request, #582 archiving

**#583 — the request now carries each concept's full definition.**
plan.pdhc holds `response_type` and `unit` on the *concept*, not the
transaction, so a captured PlanDefinition snapshot carried neither and every
consumer had to call plan.pdhc back to interpret an observation
(`_infer_response_type`, and #559 for unit). Two consequences: a stored request
could not be read without a live plan.pdhc, and editing a concept later
silently changed how an already-captured request was interpreted.

`context_service.enrich_snapshot_concepts()` now stamps `response_type`
(gateway vocab), `response_type_name` (plan.pdhc's own name — "Numerical",
"Single choice"; this is what #583 literally asked for) and `unit` into the
snapshot at capture time, at both capture points: ServiceRequest creation
(`service_request_service.py:91`) and CarePlan creation (`care_plans.py:81`).
`_infer_response_type` now PREFERS what the snapshot carries over the live
lookup, so interpretation cannot drift. Never overwrites a value the snapshot
already has; a no-op if plan.pdhc is unreachable, so it can only add
information. Live resolution stays as the fallback for older snapshots.

**#582 — archiving.** Two halves:
1. *Not actively exposed.* `provider_feed_service.list_for_provider()` now
   excludes archived SRs by default, with `include_archived` (and
   `?include_archived=1` on `/api/v1/provider/feed`) to opt back in. This
   SUPERSEDES #90 on the listing point only — #90's clinical value, a provider
   submitting late past `period_end`, is served by `download_bundle`, which
   still accepts `archived` and is unchanged.
2. *Auto-archive on provider completion.*
   `completion_service.archive_if_provider_work_complete()` archives an
   `active` SR once EVERY `ServiceRequestContractMatch` is terminal
   (completed/rejected). One provider finishing is deliberately not enough: an
   SR can be matched to several providers and archiving early would pull live
   work out of another provider's feed. Called from
   `mark_service_request_completed` (the gateway clinical-completion path).
   Audited as `servicerequest.auto_archived`.

**Known gap, recorded not fixed:** `request_feed_service.update_provider_status`
also takes a provider `completed`, but `DispatchRequest` has no
`service_request_guid` — it links only to `plan_definition_guid` + provider —
so that path cannot reach a ServiceRequest to archive it. Auto-archive
therefore fires only via the gateway completion path. Closing that needs a link
column on `DispatchRequest`; raise a ticket if the dispatch feed is still in use.

**Tests:** 226 passed, up from 207. New: `test_concept_definition_snapshot.py`
(11), `test_auto_archive_on_completion.py` (7). `test_provider_feed_archived.py`
rewritten to encode the new #582 contract while still asserting #90's download
guarantee.

**Pre-existing failure, NOT caused by this work:** the 3 `test_blocks_filter.py`
`TestServiceLayer` tests fail in a full run and pass in isolation (17/17). They
assert `data["total"] == 2` against an admin-wide list and see SRs leaked by
earlier tests. Present at baseline before any change here. Test-hygiene defect,
not a product bug — worth its own ticket.

**NOT COMMITTED:** git is blocked on this machine (macOS 27 Xcode licence, see
the simprovider note). All of the above is on disk only.

---

## 2026-09-23 — #598: HTTP forms of the provider CLI, for onboard.pdhc

onboard.pdhc runs in its own container and cannot shell into
request_pdhc_app, so OB-8 (mint the secret, show it once) and OB-10 (verify,
then the go-live gate) needed these over HTTP. All on the existing SU-admin
gate (`@requires_auth` + `@requires_role('admin')`), same as
POST /api/v1/admin/provider-tokens.

New routes in `app/api/admin_tokens.py`:
  POST   /api/v1/admin/provider-tokens/<guid>/rotate
  POST   /api/v1/admin/signing-secrets
  GET    /api/v1/admin/signing-secrets?provider_org_guid=
  POST   /api/v1/admin/signing-secrets/<guid>/rotate
  DELETE /api/v1/admin/signing-secrets/<guid>
  POST   /api/v1/admin/sandbox-dispatch
  POST   /api/v1/admin/sandbox-sign

**Shared service, not a second implementation.** The ~80 lines of
sandbox-dispatch logic moved into `app/services/sandbox_service.py`; the
Flask CLI now renders that service's result rather than owning the logic, so
`flask provider sandbox-dispatch` and the HTTP route cannot drift. The CLI
keeps its own error text where it is CLI-specific (the "pass --webhook-url"
hint means nothing over HTTP). The three existing CLI tests pass unchanged.

**Design points worth keeping:**
- Rotate routes are addressed by the CURRENT record's guid, which is what a
  caller holding a provider record has; the underlying services work on
  org+contract (PAT) and org (secret), so the guid is resolved first.
- `DELETE /admin/signing-secrets/<guid>` revokes EVERY active and deprecated
  secret for that org, not just the named one — `revoke_secret`'s real
  semantics, and correct, since a half-revoked org would still verify bodies
  signed with the sibling secret. The response lists every revoked guid so
  the caller is not misled by the URL shape.
- A failing provider in sandbox-dispatch is **200 with result=FAIL**, not a
  5xx: the run succeeded, the news is bad. OB-10's go-live gate reads the
  body, not the status code.
- The secrets listing returns lifecycle timestamps but never secret material,
  so it is safe to render in an operator UI.

**Also:** `/internal/auto-provision-pat` now honours `X-Skip-Auto-Provision:
1` (OB-13 decision 1c). contract.pdhc already declines to call at all when
its own header is set (#599 item 3); honouring it here too covers any other
caller that forwards it and keeps the two services' contracts aligned.

**Bug found by the new tests:** the first cut of the secrets listing ordered
by `WebhookSigningSecret.created_at`, which does not exist — the column is
`issued_at`. Fixed, and the listing now also returns `deprecated_at`,
`revoked_at` and `rotated_to_guid`.

**Tests:** 248 passed, up from 226. New `tests/test_admin_onboarding_routes.py`
(22). The 3 `test_blocks_filter.py` isolation failures remain pre-existing and
untouched (they pass 17/17 in isolation).

**NOT DEPLOYED.** Local only. Colima is down on this laptop (macOS 27), so the
containers were not exercised; tests run on sqlite.

---

## 2026-09-23 — #690: deployed #583 + #582 + #598 to request.pdhc.se

Deployed and verified live. `request_pdhc_app` + `request_pdhc_worker`
rebuilt, both healthy, `/api/health` 200, no errors in the log.

Markers confirmed **inside the container**, not just on disk:
`sandbox_service.py` present (#598), `rt_name_map` ×7 in context_service
(#583), archive handling ×9 in provider_feed_service (#582).

### What the pre-deploy diff found

**The prod checkout has diverged from local.** Prod HEAD is `463633b`
"Auto-close: internal endpoint…", which is **not in local history at all** —
local has the same work as `0d73880`. The same change was committed
separately on both sides. A `git pull` here would have merged messily; the
deploy was done as a surgical file copy instead.

Prod also carried **two uncommitted files** — `context_service.py` and
`grant_service.py`, holding the ips patient-demographics feature. Checked
before overwriting: `grant_service.py` was byte-identical to local, and
`context_service.py` differed only by local *adding* the #583 changes on
top. Local was a clean superset, so nothing was lost. Verified explicitly
that **no file existed only on prod**.

Migrations are identical (12 vs 11 listing entries — the difference is
`__pycache__`), so no `flask db upgrade` was needed.

### Note for the next deploy

`/usr/local/www/request.pdhc/gateway/` **is** this service's application —
a legacy directory name from the gateway/request split. The real
gateway.pdhc lives at `/usr/local/www/gateway.pdhc.se/gateway_app` and was
not touched. Compose project is pinned `request`; `docker compose` v2 is
NOT available on the mini, `docker-compose` is.

Prod's git tree still reports modified files relative to its own divergent
HEAD. That is expected and was not "fixed" — reconciling the two histories
is a separate job and not worth doing during a deploy.

Predeploy tar: `~/backups/predeploy/request.pdhc/app_20260923T173027Z.tar.gz`
Rollback image: `sha256:52b5da254d8a8`

## Ticket #706 — a grant could be issued and used, never withdrawn (2026-09-29)

(Committed as "#708" — the ticket was created afterwards and came back as
#706. See ~/T7_sidewinder/docs/wiring_triage_2026-09-29.md for the mapping.)

`DataExchangeGrant.is_valid()` returns False on `revoked`, and
`validate_grant_detailed` honours it on every call. The only thing in the
codebase that could ever set that flag was `revoke_grant`, and **nothing
called `revoke_grant`** — `grant_service.py:205` was the sole assignment to
`grant.revoked` anywhere in the service.

So the check was live, the consequence was enforced, and the switch was
connected to nothing. A grant stood until `expires_at` regardless of a
patient withdrawing or a contract ending. The only available action was
revoking the PAT, which cuts the provider off from *everything* rather than
from one ServiceRequest.

**Correction to the #704 triage report.** It listed this as "redundant
rather than missing — there are CLI commands that do it". Those commands
(`revoke-pat`, `revoke-signing-secret`) revoke PATs and webhook signing
secrets, which are different objects. Nothing revoked a grant. The finding
was stronger than reported, not weaker.

**Changed**
- `revoke_grant(grant_guid, user_guid=None, ip_address=None)` reshaped onto
  the `pat_service.revoke_pat` contract: `(dict, status)`, 404 on unknown,
  400 `already_revoked` on a second call, and a `grant.revoked` audit event
  carrying `data_subject_guid` so a patient's uses and their withdrawal come
  out of one query. The old version returned the ORM row or None, which is
  why no caller could tell "not found" from "done".
- `flask provider revoke-grant --grant-guid <guid>` — the entry point,
  alongside the existing `revoke-pat`.

No HTTP route: PAT and secret revocation are CLI-only here, and this is the
same operation on a different object. Matching the precedent beats inventing
a new admin surface for it.

256 tests pass (was 248). The 3 pre-existing `test_blocks_filter.py`
TestServiceLayer failures under a full-suite run are unrelated and predate
this change — they pass when that file is run alone.

## #708 — sibling smoke for request.pdhc (2026-09-30)

`gateway/deploy/smoke_siblings.py`, run inside the container:

```
docker exec request_pdhc_app python deploy/smoke_siblings.py
docker exec request_pdhc_app python deploy/smoke_siblings.py --json
```

Read-only, exit 0 only if everything passed. **All 8 checks pass** across ips
(spärr, consent, patients), contract.pdhc, plan.pdhc and sso.

### The check this service specifically needed

`ips_client`'s own docstring records that its spärr filter sent the key as
`X-API-Key` (ips reads only `Authorization`) against the staff `/blocks` list
endpoint instead of the purpose-built predicate — so **every call 401'd and the
filter silently failed open: no ServiceRequest was ever hidden.**

That is fixed, but `check_block` returns `(False, [])` on any error *by design
and for legal reasons* (an ips outage must not hide rows). So a wrong
credential is invisible in its return value — "nothing is blocked" and "I could
not ask" are the same answer. There is therefore a second check that makes the
same authenticated call directly and fails on a 401, so the regression would be
**visible** rather than silent. It reports `-> 404 (the ApiKey is accepted)`:
404 because the probe patient does not exist, which is the right answer.

### A mistake of mine that is worth more than the smoke

Three checks did `len(rows)` on the result of `list_contracts()`,
`list_patients()` and `list_plan_definitions()`. Those return
**`(payload, status)`**, so `len` counted the tuple — always 2. It reported
"2 contract(s)" when contract.pdhc holds 8, and I nearly chased that as a
finding.

Far worse: an upstream failure returns `({'code': 'upstream_error'}, 502)`,
which is also a two-element tuple and neither empty nor None. **All three
checks would have passed on a 502.** A smoke that reports health while the
boundary is broken is worse than no smoke at all.

Now unpacked through `_unpack()`, which requires status 200 and counts the
payload. Verified against five cases — healthy, 502, 404, empty-but-200 and a
wrong shape — rather than assumed. Real numbers now: 8 contracts (matching the
database), 4 patients, 4 plandefinitions.

### Across all three smokes

analyse found two real defects (#717, #718). gateway and request found none —
both are correctly wired. In every one of the three, **the script was wrong
more often than the platform was**: an invented path, a wrong credential, a
wrong method name, and this tuple bug. That is the argument for running them
rather than reasoning about them, and for driving the service's own clients
rather than hand-writing the calls.

## Ticket #720 — every push-mode sandbox dispatch returned 500 (2026-09-30)

Found by the first push-mode onboarding run (#716). `POST
/api/v1/admin/sandbox-dispatch` returned 500:

```
psycopg2.errors.StringDataRightTruncation: value too long for varchar(36)
  INSERT INTO webhook_deliveries (... service_request_guid ...)
  → 'sandbox-c6c0b57b-d623-485d-b7a1-610ab64384ec'   (44 chars)
```

`sandbox_service.py:51` built `f'sandbox-{uuid.uuid4()}'` — a 36-character
guid plus an 8-character prefix — into a `varchar(36)` column.

That endpoint is the **go-live gate for a push provider**, so no push
onboarding could ever complete. It had never been noticed because push mode
had never been run end to end; poll is what both live providers use.

### The fix: drop the prefix, do not widen the column

Checked rather than assumed: the prefix was **constructed in exactly one
place and parsed nowhere**. Every other `sandbox-` reference in the repo is a
route or CLI command name. And every `service_request_guid` column on the
platform is `varchar(36)` — most with a foreign key to `service_requests.guid`
— because a guid is 36 characters. `webhook_deliveries`' copy is nullable with
no FK, which is the only reason a sandbox row was permitted there at all.

Widening one column would have encoded in the schema the idea that a guid
field holds something that is not a guid. What actually marks a run as a
sandbox is `'sandbox': True` in the payload, which was always the real signal.

### Why three existing tests passed throughout

`tests/test_sandbox_dispatch.py` had three tests covering this path and all
passed, before and after. **They run on SQLite, which does not enforce VARCHAR
length; Postgres does.** A backend that silently accepts an over-long value
cannot catch a column overflow.

This is the same shape as the `alembic_version` varchar(32) lesson: a
constraint that only exists in production cannot be tested by a suite that
does not run against it.

So the new tests assert the length **directly** rather than leaving it to the
database, and one asserts that every `service_request_guid` column shares the
same width — the reason the fix is to drop the prefix rather than widen one.
Verified to have teeth: restoring the prefix makes them fail.

260 tests pass (was 256). The 3 `test_blocks_filter` TestServiceLayer failures
in a full run are pre-existing and unrelated; they pass in isolation.

## 2026-10-06 — #774 resolve and snapshot the patient's organisation

#768: one organisation per datapoint, and it is the one the patient was
affiliated with in ips **at request time**.

The lookup already existed. `patient_service.get_patient_clinic_guids()` has
been calling ips `/api/v1/patients/<guid>/clinics` at every ServiceRequest
creation since #225, and `Clinic.to_dict()` returns `organisation_guid` — but
the caller keeps `[c.get('guid') for c in clinics]` and discards it. Same shape
as #776: the value arrives and nobody stores it.

Added `get_patient_clinic_orgs()` (keeps both) and `resolve_patient_org_guid()`,
which returns **None rather than a guess** when the patient has no clinic (28 of
ips's 150), when several clinics resolve to different organisations (a guard —
all 122 assigned patients have exactly one today, and `PatientIndex` has no
primary/home field to break a tie), when `Clinic.organisation_guid` is NULL, or
when ips cannot answer. Several clinics agreeing on one organisation still
resolve.

Snapshotted onto `service_requests.patient_org_guid` at creation, because ips
keeps **no assignment history** — `patient_clinic_assignments` has `assigned_at`
and no end timestamp, so asking later returns today's answer for an old request.
Exposed in the SR context so gateway carries it to the CDR row (#769/#773), read
with `getattr` for rows seen during a rolling deploy.

The audit entry records `patient_org_resolved`, so an unresolved affiliation is
visible in the log rather than only as a NULL column.

### Found, filed as #779
The authorisation gate above this compares `caller_org_ids` (sso **organisation**
guids) with `patient_clinic_guids` (ips **Clinic.guid**). Measured: **0 of ips's
9 clinics have `guid == organisation_guid`** — the intersection can never match,
so every non-SU caller is denied. It fails closed, and it has never run because
only the SU account creates ServiceRequests (#778). Kept out of this ticket
deliberately: changing an authorisation comparison is its own change with its own
risk, and bundling it into a provenance ticket would hide it.

### Also noticed
ips returns **500**, not 404, for a malformed patient guid
(`/api/v1/patients/does-not-exist/clinics`). The gate treats ≥500 as fail-closed,
so the direction is safe, but a 500 on user input is a defect in ips.

270 tests pass (10 new). Three pre-existing `test_blocks_filter` failures are
order-dependent leaks that fail identically at HEAD — verified by stashing.

## #779 — the patient-org gate compared two identifier spaces (2026-10-07)

`POST /ServiceRequest`'s PDL Ch 4 §§ 1-2 gate intersected `caller_org_ids` (sso
ORGANISATION guids, from the access blob) with ips `Clinic.guid` primary keys.
Those are never equal: 0 of ips's 9 clinics had `guid == organisation_guid` when
measured 2026-10-06. So the gate denied **every** non-SU caller.

It was invisible because all 27 ServiceRequests on the platform were created by
`martin@ingvar.com` with `is_su_admin = true`, and the gate sits inside
`if not is_su:` — 105 `service_request.create` audit entries, 0 denials (#778).

Fixed by comparing organisation to organisation via
`patient_service.get_patient_clinic_orgs()` (added in #774). Two details carry
weight:

* **NULL denies.** `{org for _clinic, org in pairs if org}` — the falsy filter
  is what stops a nullable `Clinic.organisation_guid` from acting as a
  wildcard. #780 found a live clinic pointing at an organisation sso had never
  issued, so an unbridged clinic is not hypothetical.
* **The audit row now distinguishes two causes of the same 403.**
  `patient_org_guids` plus `clinics_without_organisation` separate "you are in
  the wrong organisation" from "this patient's clinic was never bridged to
  sso". Same refusal, different operator action.

`get_patient_clinic_guids` now has zero callers. Kept, with a
NOT-FOR-AUTHORISATION warning, because the deployed tree can lag local git and
a release may still import it.

### The tests confirmed the bug rather than catching it

The module passed 12/12 against a gate that could not match a real patient,
because the fixtures put CLINIC guids into `organization_ids`:

    CLINIC_A = "clinic-a-guid"
    _blob(is_su=False, org_ids=[CLINIC_A])
    get_patient_clinic_guids → ([CLINIC_A, CLINIC_B], 200)

Both sides got the same identifier space, so the intersection matched. Rewritten
with four distinct constants (`ORG_*` vs `CLINIC_*`), and
`test_non_admin_with_matching_org_can_create` — which asserted **201** on a
clinic-guid match — is now `test_a_clinic_guid_in_caller_orgs_does_not_grant_access`
asserting **403**. Fixing this meant inverting a green assertion.

Proven, not assumed: with the gate stashed, 10 of 15 fail. With it, 15 pass.

### A unit test was calling production

When the gate moved to `get_patient_clinic_orgs`, the tests still patching the
old name left the REAL lookup in place, and it called
`https://ips.pdhc.se/api/v1/patients/.../clinics`, which answered 401. The
tests failed, so nothing passed silently — but a unit run must not depend on a
production service. New autouse `_no_real_ips_calls` fixture patches
`patient_service.requests.get` to raise with the URL in the message. It fired
during the stashed run, which is how we know it works.

### Test results

    tests/test_service_request_create_authz.py     15 passed  (was 12)
    tests/ (full suite)                           273 passed, 3 failed

The 3 failures are **pre-existing** and unrelated: `test_blocks_filter.py`
`TestServiceLayer` asserts `total == 2` and gets 10 under cross-test
pollution. Verified by stashing both changes and re-running the untouched
tree — same 3 failures, 270 passed. They pass in isolation. Not fixed here;
worth its own ticket.

### Also: the repo had no venv

`request.pdhc` could not run its own tests. Built `gateway/.venv` from
`gateway/requirements.txt`. Tests need `PYTHONPATH=.` from `gateway/`, or
`conftest.py` cannot import `app`:

    cd ~/T7_sidewinder/request.pdhc/gateway && PYTHONPATH=. .venv/bin/pytest tests/ -q

### DEPLOYED 2026-10-07 08:35 UTC

## #768/#735 decisions implemented (2026-10-07)

Operator ratified `plans/decisions_735_768.md`. Two answers changed this repo.

**No clinic → REFUSE** (was: store NULL and create the SR anyway, which was
Claude's default, not a decision). **Several clinics → ALLOW**, which needed a
tie-break after all.

The tie-break invents nothing — the objection to allowing it was that an
invented rule gets written onto every subsequent datapoint as a fact. It reuses
a choice the caller is already forced to state:

    patient_org_guid = the patient's clinic organisation that equals requesting_org_guid

Determinate in every realistic path: a single-org caller has it auto-filled, a
multi-org caller must supply it (#226 removed silent first-pick), and for a
non-SU caller the #779 gate has already established that one of the patient's
organisations is among the caller's own.

The residual case — several affiliations, requester is none of them, reachable
mainly for an SU admin who bypasses the #779 gate — still refuses. Ordering by
`assigned_at` or guid would settle it and would be exactly the invention
objected to.

**The tie-break applies only to a tie.** With one affiliation the patient's own
organisation wins even when the requester is someone else, or `patient_org_guid`
becomes a second copy of `requesting_org_guid` and they stop being two facts.

`resolve_patient_org_guid(patient_guid, *, requesting_org_guid=None)` raises
`PatientOrgUnresolved` instead of returning None:

| code | HTTP | meaning |
|---|---|---|
| `patient_not_found` | 404 | keeps the #779 gate's meaning on this route |
| `ips_unavailable` | 502 | fail closed; an outage is not permission to write no organisation |
| `patient_org_unassigned` | 409 | no clinic, or all clinics unbridged to sso (#780) |
| `patient_org_ambiguous` | 409 | the residual case |

Each writes `service_request.create.refused` with the facts, so a refusal is
diagnosable without re-querying ips, and the two 409s are different operator
actions.

### A third set of tests was calling production

`test_dispatch_trigger.py`'s `stubs` fixture never stubbed the ips clinic
lookup, so 4 tests called `https://ips.pdhc.se` every run. They passed only
because the 401 was **tolerated** — the resolver returned None and the SR was
created anyway. The refusal decision turned that into a failure, which is how it
surfaced. Two earlier passes had missed it.

`conftest.py` now has an autouse `_no_real_ips_calls` fixture, suite-wide. It
raises `requests.ConnectionError` — what a real outage raises — not a louder
custom error, because older modules are *written* to tolerate the upstream being
down (`test_patients.py`: "upstream calls are expected to fail in test
environment, which is acceptable", asserting `status in (200, 502)`). Those
assertions pass whether ips answers or not; tightening them is a separate job
and is not done here. Opt out per-test with
`@pytest.mark.allow_ips_network`.

Verified: 0 occurrences of a production ips call in a full suite run.

### Test results

    tests/test_patient_org_resolution.py        15 passed  (was 9)
    tests/ (full suite)                        278 passed, 3 failed

The 3 are the same **pre-existing** `test_blocks_filter.py::TestServiceLayer`
cross-test pollution failures (`assert total == 2` gets 10), verified against
the untouched tree. They want their own ticket.

### DEPLOYED 2026-10-07 08:35 UTC — together with #779


## Deploy of #779 + #768 to miserver (2026-10-07 08:35 UTC)

**The deploy route had to change, and the reason is worth recording.**
`/usr/local/www/request.pdhc/` is a **flat git checkout**, not the §7
release-symlink layout — and its history has **diverged from local**, not merely
drifted:

* server HEAD `463633b` ("Auto-close: internal endpoint to complete a
  ServiceRequest from gateway") **does not exist locally**;
* local `362ffa2`, `6096601`, `39a58f1`, `e85b15e` **do not exist on the
  server**;
* the server carries **15 modified-and-uncommitted files**, two of them the very
  files this change touches, plus ~15 `.env.bak*` and three `gateway.bak.*`
  trees.

So neither `git pull` nor a tarball extract was usable: both would have
destroyed server-only work. Deployed by **copying exactly the three changed
files**, after proving the divergence did not overlap them.

### The check that made it safe

Each of the three deployed files was fetched from the server and diffed against
the **local pre-change baseline** (`39a58f1`):

    service_requests.py          IDENTICAL
    patient_service.py           IDENTICAL
    service_request_service.py   IDENTICAL

All three matched byte-for-byte, so copying applied this change's diff and
nothing else. They show as "modified" in the server's `git status` only because
the server's HEAD is a different commit — the content equals this baseline.
**Had any differed, the patch would have had to be built from the deployed
file.** Tests were deliberately NOT deployed: they are not needed at runtime,
and two test modules are among the server-only edits.

### Preconditions verified before the rebuild

* `service_requests.patient_org_guid` **exists** in prod; alembic head is
  `d0e1f2a3b4c5` (#774's). **No migration shipped with this deploy.**
* 27 ServiceRequests, **0 with a patient organisation** — consistent with every
  one having been created by the SU admin before #774.
* `COMPOSE_PROJECT_NAME=request` pinned, `docker-compose` v5.1.4.

### Sequence

1. Predeploy backup → `miserver:~/backups/predeploy/request.pdhc/20261007T083356Z/`
   — tar of `gateway/app` (158 files, verified non-empty), all three originals
   as `*.before`, `git_head.txt`, `git_status.txt`, and the running image id as
   the rollback target.
2. `scp` the three files.
3. `python3 -m py_compile` each — all OK — **before** any rebuild.
4. `docker-compose up -d --build app worker`. `--build` is required: the
   Dockerfile does `COPY . .`, so a plain restart runs the old code from the
   image.
5. Verified **in-container**, not on disk: all three markers present, and
   `PatientOrgUnresolved` **imports and constructs** — proving the module loads
   rather than merely parses.
6. Health: `127.0.0.1:9060` 200, `https://request.pdhc.se/api/health` 200
   `{"database":"connected","status":"ok","version":"b0247a6"}`. Worker back up.
   Clean logs, alembic head unchanged.

### Rollback

    cd /usr/local/www/request.pdhc
    B=~/backups/predeploy/request.pdhc/20261007T083356Z
    cp $B/service_requests.py.before        gateway/app/api/service_requests.py
    cp $B/patient_service.py.before         gateway/app/services/patient_service.py
    cp $B/service_request_service.py.before gateway/app/services/service_request_service.py
    cd gateway && docker-compose up -d --build app worker

### What is now live and user-visible

A ServiceRequest for a patient with **no clinic assignment in ips refuses**
(409 `patient_org_unassigned`) where it previously succeeded with a NULL
organisation. **28 of ips's 150 patients are in that state.** Watch for
`service_request.create.refused` audit rows carrying that code — each one is a
patient needing a clinic assignment, not a bug.

The #779 gate fix is also live, so a non-SU professional can now create a
ServiceRequest for a patient in their own organisation. Before today every
non-SU caller was denied.

**Still NOT done, deliberately:** `_org_filter` in cdr still scopes Rule 24 on
the performer. Repointing it while `patient_org_guid` is NULL everywhere would
black out every non-SU read. See #782.

## 2026-10-08 — create page: organisation first, patient list from ips's record

`/service-requests/create`. DEPLOYED (`request_pdhc_app` rebuilt, `/api/health`
ok).

### What it did, and the two faults

It fetched **every** patient via `GET /fhir/Patient`, filtered them in Python
on `Patient.managingOrganization`, and offered a **separate** "Requesting
organisation" control further down the form for chain-of-custody.

1. **The two controls could disagree.** Nothing stopped a caller recording org
   A for custody while selecting a patient belonging to org B.
2. **`managingOrganization` is a projection, not the record.** ips treats
   `PatientClinicAssignment` as authoritative — it is what
   `GET /api/v1/clinics/<guid>/patients` joins on — and reports a disagreement
   as `custodian_mismatch` (#792) rather than resolving it silently, because
   the two drift. It is also single-valued where the assignment is M2M, so a
   patient in two clinics could only ever match one.

### How bad today: not at all, which is the honest answer

Measured against production **before** changing anything, over 122 assigned
patients:

| | |
|---|---|
| managingOrganization agrees with the assignment | **122** |
| absent | 0 |
| disagrees | 0 |
| assigned to more than one org | 0 |

The old filter hid **nobody**. It was wrong in the way that waits: the
generator sets `managingOrganization` from the clinic at creation and nothing
has reassigned a patient since. The first patient moved between clinics, or
assigned to two, is the one it gets wrong — and the symptom is a clinician
unable to find their own patient, which reads as "that patient isn't in the
system".

### What it does now

**One** organisation choice, at the top, doing both jobs: it scopes the patient
list and it *is* the `requesting_org_guid`. Changing it reloads via GET so the
list comes back from ips rather than being filtered in the browser.

`_clinics_for_orgs` is the single place the two identifier spaces meet — an SSO
blob names **organisations** (`affiliations[].care_unit_guid`), ips's endpoint
is keyed by **clinic**, and `clinics.guid` ≠ `clinics.organisation_guid`.
Verified live: org `7f003d04…` → clinic `2cc4e9e1…`, different values. A test
asserts they differ, because conflating them is #779 (a gate that did exactly
that denied every non-SU caller while twelve tests passed, the fixture having
fed both sides the same guid).

An organisation owning several clinics has its patients unioned and
de-duplicated — the caller picked the organisation, not a clinic.

### Unavailable ≠ empty

`PatientListUnavailable` is **raised, never returned**, and the page says so:
*"This is not 'no patients'"*. A clinician shown an empty selector concludes
there is nobody to request for; if the truth is that ips could not be asked,
that is a different problem with a different fix. Conflating them is what let
this service's own spärr filter hide nothing for months while looking healthy
(#783). A genuinely empty organisation says *"ips answered"* instead.

The GET scope also refuses an org the caller is not affiliated with, mirroring
the POST gate, so query-string tampering cannot even **show** another
organisation's patients.

### Verified live after the rebuild

```
list_clinics / list_clinic_patients present : True True
old managingOrganization matcher gone       : True
clinics from ips                            : 10
org 7f003d04 -> clinic 2cc4e9e1 (Test Clinic)  DIFFERENT values: True
assignment-based patients for that clinic   : 122
unknown clinic                              : raised (not [])
```

300 tests pass (22 new). `test_blocks_filter.py`'s three service-layer failures
are pre-existing full-suite ordering pollution — they pass in isolation and
fail identically with these changes stashed.

### Found on the way: ips #805

`GET /api/v1/clinics/<guid>/patients` answers **500** on a malformed guid, not
400/404: `Clinic.guid` is a UUID column, so `filter_by` raises at the driver
before the route's own 404 branch runs. Same shape as the `/analysis-filter`
bug ips already fixed. Our client handles it safely (any non-200 raises), so
nothing is broken here — filed as **#805**.
