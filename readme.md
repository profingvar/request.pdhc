# request.pdhc — Deployment Plan

This document is the authoritative deployment plan for the `request.pdhc` unified service. It covers every step from environment setup through a fully operational orchestrating service that combines patient lifecycle, CarePlan readout/parse/export, and CarePlan dispatch — all under one functionally coherent contract. Numbering follows the `1.a, 1.b` convention required by Rule 3.

`request.pdhc` is an **orchestrating service** that proxies to live backends (`ips.pdhc.se` for Patient/IPS data, `plan.pdhc.se` for CarePlan/PlanDef data, `sso.pdhc.se` for authentication) and maintains its own local PostgreSQL for dispatch receipts, audit logs, and export metadata.

---

## 1) Environment and infrastructure setup

### 1.1 Prerequisites and tooling

- **1.a** Verify the development Mac has Docker Desktop installed and running. Confirm Docker Compose is available (`docker compose version`).
- **1.b** Verify Python 3.11+ is available on the host for local tooling and test execution.
- **1.c** Verify PostgreSQL client tools (`psql`) are available on the host for manual inspection.
- **1.d** Confirm ports 9060–9063 are free. Kill any processes on those ports.

### 1.2 Project directory structure

- **1.e** Create the application folder structure. All application code, venv, and database configuration live inside a dedicated subfolder (Rule 21). Target layout:

```
request.pdhc/
├── top_rules.md                          # immutable project rules
├── describe_request.pdhc.md              # functional spec reference
├── pdhc_markdown_layout_standard.md      # markdown style guide (Rule 24)
├── repo_css.md                           # frontend design system reference
├── CLAUDE.md                             # design system instructions (Rule 24)
├── readme.md                             # this deployment plan
├── progress.md                           # step-by-step progress log
├── changed_files.md                      # registry of all edited files
├── newtask.txt                           # debugging focus (created when needed)
├── start.sh                              # single entry-point script (Rule 16)
├── stop.sh                               # graceful shutdown script
├── results/                              # test output (Rule 11)
│   └── <ISO-8601>_results/
└── gateway/                              # ← application root (Rule 21)
    ├── Dockerfile
    ├── docker-compose.yml
    ├── requirements.txt
    ├── entrypoint.sh                     # runs migrations then starts gunicorn
    ├── .env                              # secrets & config (Rule 23)
    ├── .env.example                      # template (committed)
    ├── venv/
    ├── app/
    │   ├── __init__.py                   # Flask app factory
    │   ├── config.py                     # configuration from .env
    │   ├── models/
    │   │   ├── __init__.py
    │   │   ├── dispatch_models.py        # DispatchRequest, DispatchReceipt
    │   │   ├── audit_models.py           # AuditLog
    │   │   └── export_models.py          # ExportRecord
    │   ├── api/
    │   │   ├── __init__.py
    │   │   ├── auth.py                   # SSO proxy auth endpoints
    │   │   ├── patients.py               # Patient lifecycle (proxy to IPS)
    │   │   ├── careplans.py              # CarePlan readout (proxy to Plan)
    │   │   ├── dispatch.py               # CarePlan dispatch + receipts
    │   │   ├── providers.py              # Provider directory
    │   │   ├── export.py                 # CSV export endpoints
    │   │   └── capability.py             # FHIR capability statement
    │   ├── routes/
    │   │   ├── __init__.py
    │   │   ├── main.py                   # dashboard
    │   │   ├── patients.py               # patient management UI
    │   │   ├── careplans.py              # careplan readout UI
    │   │   ├── dispatch.py               # dispatch workflow UI
    │   │   └── export.py                 # CSV preview/download UI
    │   ├── services/
    │   │   ├── __init__.py
    │   │   ├── auth_service.py           # SSO token validation, access blob
    │   │   ├── patient_service.py        # proxy to ips.pdhc.se
    │   │   ├── careplan_service.py       # proxy to plan.pdhc.se
    │   │   ├── parse_service.py          # CarePlan → normalized transactions
    │   │   ├── csv_service.py            # transaction rows → CSV
    │   │   ├── dispatch_service.py       # dispatch logic + idempotency
    │   │   ├── provider_service.py       # provider directory lookup
    │   │   └── audit_service.py          # audit logging
    │   ├── middleware/
    │   │   ├── __init__.py
    │   │   ├── auth_middleware.py         # SSO token check, role enforcement
    │   │   ├── cors.py                   # CORS configuration
    │   │   └── rate_limit.py             # Flask-Limiter setup
    │   ├── static/
    │   │   └── css/
    │   │       └── pdhc.css              # design system (Rule 24)
    │   └── templates/
    │       ├── base.html                 # extends PDHC base template
    │       ├── dashboard.html
    │       ├── patients/
    │       │   ├── list.html
    │       │   ├── view.html
    │       │   ├── create.html
    │       │   └── edit.html
    │       ├── careplans/
    │       │   ├── list.html
    │       │   ├── view.html
    │       │   └── readout.html
    │       ├── dispatch/
    │       │   ├── form.html
    │       │   └── receipt.html
    │       └── export/
    │           ├── preview.html
    │           └── download.html
    ├── migrations/
    │   └── versions/
    └── tests/
        ├── conftest.py
        ├── test_auth.py
        ├── test_patients.py
        ├── test_careplans.py
        ├── test_parse.py
        ├── test_csv_export.py
        ├── test_dispatch.py
        ├── test_providers.py
        └── test_all_endpoints.py
```

- **1.f** Create `progress.md` (empty template with header).
- **1.g** Create `changed_files.md` (empty template with header).
- **1.h** Create `CLAUDE.md` with design system instructions (Rule 24).
- **1.i** Copy `pdhc.css` from `css_instrux/` into `gateway/app/static/css/` (Rule 24).
- **1.j** Copy `pdhc_markdown_layout_standard.md` and `repo_css.md` into project root.

### 1.3 Git initialisation

- **1.k** Initialise a Git repository in `request.pdhc/`. Add a `.gitignore` covering `venv/`, `__pycache__/`, `.env`, `.DS_Store`, `*.pyc`, `results/`.
- **1.l** Make an initial commit with all source documents and scaffolding files.

---

## 2) Docker and database setup

### 2.1 Port allocation (Rule 16)

All services use ports 9060–9063 exclusively:

| Port | Service                    |
|------|----------------------------|
| 9060 | Flask application (gunicorn) |
| 9061 | PostgreSQL database        |
| 9062 | Reserved                   |
| 9063 | Reserved                   |

### 2.2 PostgreSQL in Docker

The local database stores dispatch receipts, audit logs, and export metadata. Patient and CarePlan data live on the upstream backends — they are **not** replicated locally.

- **2.a** Create `gateway/docker-compose.yml` defining:
  - A `db` service running PostgreSQL 16-Alpine, mapped to `localhost:9061`.
  - A named volume `request_pdhc_pgdata` for persistence.
  - Health check on the `db` service.
  - Environment variables sourced from `gateway/.env`.
- **2.b** Create `gateway/.env` with at minimum:

```
POSTGRES_USER=request_admin
POSTGRES_PASSWORD=<strong-generated-password>
POSTGRES_DB=request_pdhc
DATABASE_URL=postgresql://request_admin:<password>@localhost:9061/request_pdhc
FLASK_SECRET_KEY=<generated>
FLASK_ENV=development
FLASK_PORT=9060

# Upstream service URLs
IPS_BASE_URL=https://ips.pdhc.se
PLAN_BASE_URL=https://plan.pdhc.se
SSO_BASE_URL=https://sso.pdhc.se

# SSO integration
SSO_CALLBACK_URL=http://localhost:9060/auth/callback
JWT_SECRET_KEY=<generated>

# Bootstrap superuser (Rule 23)
BOOTSTRAP_SU_USERNAME=admin
BOOTSTRAP_SU_PASSWORD=<strong-generated-password>
```

- **2.c** Create `gateway/.env.example` with placeholder values (committed to Git).
- **2.d** Verify the database starts: `docker compose up db -d` and confirm connectivity via `psql -h localhost -p 9061 -U request_admin -d request_pdhc`.

### 2.3 Flask application container

- **2.e** Create `gateway/Dockerfile`:
  - Base image `python:3.11-slim`.
  - Copy `requirements.txt`, install dependencies.
  - Copy application code.
  - Expose port 9060.
  - Entry point via `entrypoint.sh`.
- **2.f** Create `gateway/entrypoint.sh`:
  - Run `flask db upgrade` (apply pending migrations).
  - Start `gunicorn` bound to `0.0.0.0:9060`.
- **2.g** Add the `app` service to `docker-compose.yml`:
  - Depends on `db` (health check condition).
  - Maps `localhost:9060` to container port 9060.
  - Sources `gateway/.env`.
- **2.h** Verify the full stack starts: `docker compose up -d` — both `db` and `app` healthy.

### 2.4 The `start.sh` entry-point script (Rule 16)

- **2.i** Create `start.sh` at project root. The script must:
  1. Kill any processes on ports 9060–9063 (previous run cleanup).
  2. Ensure Docker is running (check and start Docker Desktop if needed; try Colima as fallback).
  3. Activate the Python virtual environment (`gateway/venv`).
  4. Start the database and application via `docker compose up -d --build`.
  5. Wait for health checks to pass.
  6. Tail logs.
  7. On `Ctrl+C`: `docker compose down`, deactivate venv, exit gracefully.
- **2.j** Create `stop.sh` for standalone graceful shutdown.
- **2.k** Make both scripts executable and test the full lifecycle.

---

## 3) Application foundation (Flask + SQLAlchemy)

### 3.1 Virtual environment and dependencies

- **3.a** Create `gateway/venv` via `python3 -m venv gateway/venv`.
- **3.b** Create `gateway/requirements.txt`:

```
Flask>=3.0
Flask-SQLAlchemy>=3.1
Flask-Migrate>=4.0
Flask-Login>=0.6
Flask-Limiter>=3.5
psycopg2-binary>=2.9
gunicorn>=21.2
python-dotenv>=1.0
requests>=2.31
bleach>=6.1
pytest>=8.0
pytest-cov>=4.1
```

- **3.c** Install dependencies: `pip install -r gateway/requirements.txt`.

### 3.2 Flask app factory

- **3.d** Implement `gateway/app/__init__.py` — the application factory (`create_app()`):
  - Load configuration from `config.py` (reads `.env`).
  - Initialise SQLAlchemy, Flask-Migrate, Flask-Login, Flask-Limiter.
  - Register API blueprints (prefix `/api/v1/`).
  - Register web UI route blueprints.
  - Register error handlers (JSON for API, HTML for web).
  - Register CORS middleware.
- **3.e** Implement `gateway/app/config.py`:
  - `DATABASE_URL` from env.
  - `SECRET_KEY`, `JWT_SECRET_KEY` from env.
  - `IPS_BASE_URL`, `PLAN_BASE_URL`, `SSO_BASE_URL` from env.
  - `FLASK_ENV`, debug flag.

### 3.3 Database migrations

- **3.f** Initialise Flask-Migrate: `flask db init`.
- **3.g** Confirm migration directory is created inside `gateway/`.

### 3.4 Tests for foundation

- **3.h** Write `tests/test_app_factory.py`:
  - App creates without error.
  - Config values loaded correctly (including upstream URLs).
  - Database connection succeeds.
- **3.i** Run tests via pytest. Store results in `./results/<timestamp>_results/` (Rule 11).
- **3.j** Update `progress.md` with results.

---

## 4) Data models (local database)

The local database stores **only** dispatch, audit, and export data. Patient and CarePlan entities are fetched from upstream backends and are never persisted locally.

### 4.1 Dispatch models

- **4.a** Implement `gateway/app/models/dispatch_models.py`:
  - `DispatchRequest` — `dispatch_requests` table:
    - `id`, `guid` (UUID, unique), `careplan_guid` (VARCHAR, references upstream), `provider_guid` (VARCHAR, references upstream), `assigned_user_guid` (VARCHAR, optional), `dispatch_notes` (TEXT, optional), `status` (ENUM: `pending`, `submitted`, `acknowledged`, `failed`), `idempotency_key` (VARCHAR, unique), `created_at`, `updated_at`.
  - `DispatchReceipt` — `dispatch_receipts` table:
    - `id`, `guid` (UUID, unique), `dispatch_request_guid` (FK to `dispatch_requests.guid`), `receipt_token` (VARCHAR, unique), `status` (ENUM: `accepted`, `rejected`, `error`), `response_payload` (JSONB), `created_at`.
  - All matching by GUID, not ID (Rule 18).

### 4.2 Audit model

- **4.b** Implement `gateway/app/models/audit_models.py`:
  - `AuditLog` — `audit_logs` table:
    - `id`, `guid` (UUID), `correlation_id` (VARCHAR), `user_guid` (VARCHAR), `action` (VARCHAR — e.g. `patient.create`, `careplan.dispatch`, `export.csv`), `resource_type` (VARCHAR), `resource_guid` (VARCHAR), `details` (JSONB), `ip_address` (VARCHAR), `created_at`.

### 4.3 Export metadata model

- **4.c** Implement `gateway/app/models/export_models.py`:
  - `ExportRecord` — `export_records` table:
    - `id`, `guid` (UUID, unique), `careplan_guid` (VARCHAR), `user_guid` (VARCHAR), `export_type` (VARCHAR — `csv`), `row_count` (INTEGER), `file_name` (VARCHAR), `schema_version` (VARCHAR), `created_at`.

### 4.4 Migrations and tests

- **4.d** Generate migration: `flask db migrate -m "initial models — dispatch, audit, export"`.
- **4.e** Apply migration: `flask db upgrade`.
- **4.f** Write `tests/test_models.py`:
  - Each model can be instantiated and persisted.
  - FK constraints hold (DispatchReceipt → DispatchRequest).
  - GUID uniqueness enforced.
  - Idempotency key uniqueness on DispatchRequest.
- **4.g** Run tests. Store results. Update `progress.md`.

---

## 5) Authentication and SSO integration

### 5.1 SSO consumer service

`request.pdhc` does **not** manage its own users/passwords. It delegates authentication to `sso.pdhc.se` using the same handshake pattern as `plan.pdhc`.

- **5.a** Implement `gateway/app/services/auth_service.py`:
  - `initiate_login(next_url, state)` — redirects to `SSO_BASE_URL/auth/login?next=<callback>&state=<state>`.
  - `validate_token(token)` — calls `SSO_BASE_URL/api/auth/me` with Bearer token, returns access blob.
  - `get_access_blob(token)` — parses access blob into role/permissions structure.
  - Cache access blob per-session to reduce upstream calls.

- **5.b** Implement `gateway/app/middleware/auth_middleware.py`:
  - `@requires_auth` decorator — validates SSO token from session or `Authorization` header.
  - `@requires_role(role)` decorator — checks access blob for required role.
  - Role mapping (same as plan.pdhc):
    - `read_only`: any authenticated session.
    - `read_write`: professional with effective phases.
    - `admin`: `is_su_admin` in access blob.
  - Support both session-based (`credentials: include`) and API key (`X-API-Key`) contexts.

### 5.2 Auth endpoints

- **5.c** Implement `gateway/app/api/auth.py`:
  - `GET /auth/login` — initiates SSO handshake redirect.
  - `GET /auth/callback` — receives token from SSO, stores in session.
  - `POST /api/v1/auth/logout` — clears local session, calls SSO logout.
  - `GET /api/v1/auth/me` — returns access blob for current session.
- **5.d** Implement bootstrap superuser logic for local development:
  - When `AUTH_DISABLED=true` in `.env`, auto-authenticate with a mock access blob (Rule 23).

### 5.3 Tests

- **5.e** Write `tests/test_auth.py`:
  - SSO redirect contains correct `next` and `state` parameters.
  - Callback stores token in session.
  - `/api/v1/auth/me` returns access blob.
  - Protected endpoint without token returns 401.
  - Protected endpoint with wrong role returns 403.
  - `AUTH_DISABLED=true` bypasses SSO in development.
- **5.f** Run tests. Store results. Update `progress.md`.

---

## 6) Patient lifecycle service (proxy to IPS)

### 6.1 Patient service layer

- **6.a** Implement `gateway/app/services/patient_service.py`:
  - `list_patients(params)` — proxies `GET` to `IPS_BASE_URL/api/v1/Patient` with query params (search, pagination, filters).
  - `get_patient(guid)` — proxies `GET` to `IPS_BASE_URL/api/v1/Patient/{guid}`.
  - `create_patient(payload)` — proxies `POST` to `IPS_BASE_URL/api/v1/Patient` with validated FHIR Patient resource.
  - `update_patient(guid, payload)` — proxies `PUT` to `IPS_BASE_URL/api/v1/Patient/{guid}`.
  - `delete_patient(guid)` — proxies `DELETE` to `IPS_BASE_URL/api/v1/Patient/{guid}`.
  - All operations forward the SSO token for upstream authentication.
  - Robust handling of FHIR `Bundle` and `OperationOutcome` responses.
  - All references by GUID (Rule 18).

### 6.2 Patient API endpoints

- **6.b** Implement `gateway/app/api/patients.py`:
  - `GET /api/v1/Patient` — list/search patients.
  - `GET /api/v1/Patient/{guid}` — read single patient.
  - `POST /api/v1/Patient` — create patient (requires `read_write` role).
  - `PUT /api/v1/Patient/{guid}` — update patient (requires `read_write` role).
  - `DELETE /api/v1/Patient/{guid}` — delete patient (requires `read_write` role).
  - Strict validation for create/update payloads (FHIR R5 Patient structure).
  - Consistent error responses (`400`, `401`, `403`, `404`, `422`, `500`).

### 6.3 Patient web UI routes

- **6.c** Implement `gateway/app/routes/patients.py`:
  - `GET /patients` — list page with search/filter.
  - `GET /patients/<guid>` — view single patient.
  - `GET /patients/create` — create form.
  - `POST /patients/create` — submit new patient.
  - `GET /patients/<guid>/edit` — edit form.
  - `POST /patients/<guid>/edit` — submit update.
  - `POST /patients/<guid>/delete` — delete with confirmation.
  - Duplicate patient flow: read existing + pre-populate create form with field carry-over.

### 6.4 Patient key fields (FHIR R5)

Fields used in flows (per spec section 3.1):

- `id`, `name[]` (`family`, `given`), `gender`, `birthDate`, `active`
- `maritalStatus`, `telecom[]`, `address[]`, `identifier[]`

### 6.5 Tests

- **6.d** Write `tests/test_patients.py`:
  - List patients returns FHIR Bundle.
  - Read patient by GUID returns Patient resource.
  - Create patient with valid payload succeeds.
  - Create patient with invalid payload returns 400/422.
  - Update patient modifies upstream.
  - Delete patient removes upstream.
  - Auth enforcement on write operations.
  - `OperationOutcome` responses handled correctly.
- **6.e** Run tests. Store results. Update `progress.md`.

---

## 7) CarePlan readout service (proxy to Plan)

### 7.1 CarePlan service layer

- **7.a** Implement `gateway/app/services/careplan_service.py`:
  - `list_careplans(params)` — proxies `GET` to `PLAN_BASE_URL/api/v1/CarePlan` with filters (`subject`, `status`, query text, `_count=100`).
  - `get_careplan(guid)` — proxies `GET` to `PLAN_BASE_URL/api/v1/CarePlan/{guid}`.
  - Forward SSO token for upstream authentication.
  - Handle variable CarePlan structures (missing optional fields).
  - Return structured content consumable by parse service.

### 7.2 CarePlan API endpoints

- **7.b** Implement `gateway/app/api/careplans.py`:
  - `GET /api/v1/CarePlan` — list/search careplans with filters.
  - `GET /api/v1/CarePlan/{guid}` — read single careplan in full detail.
  - Consistent error responses.

### 7.3 CarePlan web UI routes

- **7.c** Implement `gateway/app/routes/careplans.py`:
  - `GET /careplans` — list page with filters (subject, status, text search).
  - `GET /careplans/<guid>` — detail view showing activity/goal/transaction data.
  - `GET /careplans/<guid>/readout` — full readout page with parsed transaction rows.

### 7.4 Tests

- **7.d** Write `tests/test_careplans.py`:
  - List careplans returns filtered results.
  - Read careplan by GUID returns full detail.
  - Missing optional fields handled gracefully.
  - Auth enforcement.
- **7.e** Run tests. Store results. Update `progress.md`.

---

## 8) CarePlan parse and normalization service

### 8.1 Parse service

- **8.a** Implement `gateway/app/services/parse_service.py`:
  - `parse_careplan(careplan_data)` — transforms CarePlan structure into normalized transaction rows.
  - Parse `activity[]`, nested details/extensions, and goals.
  - Normalize concept metadata, requirement metadata, expected values/ranges.
  - Preserve order (`sort_order` or equivalent).
  - Produce flat, deterministic row model.
  - **Idempotent**: same input always produces identical output.
  - Strict fallback defaults for missing fields.
  - Explicit parse error reporting with partial-success handling.

### 8.2 Transaction row model

Each normalized row contains:

- `row_guid` (generated, deterministic from source data)
- `careplan_guid`, `activity_guid`, `transaction_guid`
- `concept_guid`, `concept_name`, `concept_display`
- `goal_guid`, `goal_description`, `goal_priority`
- `expected_value`, `expected_unit`, `range_low`, `range_high`
- `requirement_type`, `performer_type`
- `sort_order`

### 8.3 Tests

- **8.b** Write `tests/test_parse.py`:
  - Parse produces expected number of rows.
  - Idempotent — parsing same input twice yields identical output.
  - Missing fields produce fallback defaults, not errors.
  - Parse errors reported with partial success.
  - Sort order preserved.
  - All GUIDs present and consistent.
- **8.c** Run tests. Store results. Update `progress.md`.

---

## 9) CSV export service

### 9.1 CSV service

- **9.a** Implement `gateway/app/services/csv_service.py`:
  - `generate_csv(transaction_rows, schema_version)` — builds CSV from normalized rows.
  - UTF-8 encoding.
  - Stable header order (defined by schema version).
  - Proper escaping for commas, quotes, newlines.
  - Deterministic file naming: `careplan_{guid}_{timestamp}.csv`.
  - `preview_csv(transaction_rows, max_rows)` — returns preview data (headers + first N rows).

### 9.2 CSV API and routes

- **9.b** Implement `gateway/app/api/export.py`:
  - `POST /api/v1/CarePlan/{guid}/export/csv` — generate and download CSV.
  - `GET /api/v1/CarePlan/{guid}/export/preview` — preview parsed data before download.
- **9.c** Implement `gateway/app/routes/export.py`:
  - `GET /careplans/<guid>/export/preview` — preview page showing parsed rows.
  - `POST /careplans/<guid>/export/download` — trigger CSV download.
- **9.d** Record every export in `export_records` table (audit trail).

### 9.3 Schema versioning

- **9.e** Define CSV schema version `1.0.0` with documented header list.
- **9.f** Backwards compatibility policy: new columns may be appended; existing columns never removed or reordered within a major version.

### 9.4 Tests

- **9.g** Write `tests/test_csv_export.py`:
  - CSV output is valid UTF-8.
  - Headers match schema version.
  - Escaping handles commas, quotes, newlines correctly.
  - File naming follows convention.
  - Preview returns correct subset.
  - Export record created in database.
  - Same input produces identical CSV (reproducibility).
- **9.h** Run tests. Store results. Update `progress.md`.

---

## 10) Provider directory service

### 10.1 Provider service

- **10.a** Implement `gateway/app/services/provider_service.py`:
  - `list_providers(params)` — proxies `GET` to `PLAN_BASE_URL/api/v1/providers` (or the appropriate upstream endpoint).
  - Filter active/inactive providers.
  - Return stable GUIDs used by dispatch contract.

### 10.2 Provider API endpoints

- **10.b** Implement `gateway/app/api/providers.py`:
  - `GET /api/v1/providers` — list providers with optional active/inactive filter.

### 10.3 Tests

- **10.c** Write `tests/test_providers.py`:
  - List providers returns results with GUIDs.
  - Active/inactive filter works.
  - Auth enforcement.
- **10.d** Run tests. Store results. Update `progress.md`.

---

## 11) CarePlan dispatch service

### 11.1 Dispatch service layer

- **11.a** Implement `gateway/app/services/dispatch_service.py`:
  - `create_dispatch(careplan_guid, provider_guid, assigned_user_guid, notes, idempotency_key)`:
    1. Validate careplan exists (call upstream).
    2. Validate provider exists and is active.
    3. Check idempotency key — if duplicate, return existing receipt.
    4. Create `DispatchRequest` record (status: `pending`).
    5. Submit to upstream: `POST PLAN_BASE_URL/api/v1/CarePlan/{guid}/dispatch`.
    6. Store response as `DispatchReceipt`.
    7. Log to audit trail.
    8. Return receipt with token and status.
  - `get_dispatch_status(receipt_token)` — look up receipt by token.
  - Clear failure taxonomy: validation error, auth failure, provider not found, careplan not found, upstream error.

### 11.2 Dispatch API endpoints

- **11.b** Implement `gateway/app/api/dispatch.py`:
  - `POST /api/v1/CarePlan/{guid}/dispatch` — submit dispatch request (requires `read_write` role).
  - `GET /api/v1/CarePlan/{guid}/dispatch/{receipt_token}` — check dispatch status.
  - Input validation: careplan GUID, provider GUID required; optional assigned user GUID and notes.

### 11.3 Dispatch web UI routes

- **11.c** Implement `gateway/app/routes/dispatch.py`:
  - `GET /careplans/<guid>/dispatch` — dispatch form (provider selector, notes field).
  - `POST /careplans/<guid>/dispatch` — submit dispatch.
  - `GET /dispatch/<receipt_token>` — receipt/status page.

### 11.4 Tests

- **11.d** Write `tests/test_dispatch.py`:
  - Dispatch with valid inputs creates request + receipt.
  - Duplicate idempotency key returns existing receipt (not double-dispatch).
  - Invalid provider GUID returns 404.
  - Invalid careplan GUID returns 404.
  - Missing required fields return 400.
  - Receipt token lookup works.
  - Audit log entry created.
  - Auth enforcement.
- **11.e** Run tests. Store results. Update `progress.md`.

---

## 12) Audit and observability service

### 12.1 Audit service

- **12.a** Implement `gateway/app/services/audit_service.py`:
  - `log_event(user_guid, action, resource_type, resource_guid, details, correlation_id, ip_address)`.
  - Actions logged:
    - `patient.create`, `patient.update`, `patient.delete`
    - `careplan.view`, `careplan.readout`
    - `careplan.dispatch`
    - `export.csv`
    - `auth.login`, `auth.logout`
  - Correlation ID passed through from request headers or generated.

### 12.2 Audit API endpoint

- **12.b** Implement audit query endpoint (admin only):
  - `GET /api/v1/audit` — list audit entries with filters (user, action, resource, date range). Requires `admin` role.

### 12.3 Tests

- **12.c** Write `tests/test_audit.py`:
  - Audit events persisted with correct fields.
  - Correlation ID propagated.
  - Admin-only access enforced.
- **12.d** Run tests. Store results. Update `progress.md`.

---

## 13) FHIR capability statement (Rule 15)

### 13.1 Capability statement endpoint

- **13.a** Implement `gateway/app/api/capability.py`:
  - `GET /api/v1/metadata` — returns FHIR R5 CapabilityStatement describing all supported resources and operations:
    - Patient: read, search, create, update, delete
    - CarePlan: read, search
    - CarePlan dispatch: custom operation
    - Provider: search
  - Include supported search parameters per resource.
  - Include security description (SSO/token-based).

### 13.2 FHIR compliance validation (Rule 15)

- **13.b** All FHIR endpoints return resources conformant to FHIR R5:
  - Correct `resourceType` on all responses.
  - Valid Bundle structure for search results.
  - Proper `OperationOutcome` for errors.
  - `meta` element with version info.

### 13.3 Tests

- **13.c** Write capability statement validation tests.
- **13.d** Run tests. Store results. Update `progress.md`.

---

## 14) Comprehensive API endpoint test script (Rules 9 and 20)

- **14.a** Create `gateway/tests/test_all_endpoints.py` — a single script exercising every API endpoint:
  - Auth endpoints (login redirect, callback, me, logout).
  - Patient lifecycle (list, read, create, update, delete).
  - CarePlan readout (list, read).
  - Parse/export (preview, CSV download).
  - Dispatch (submit, status check).
  - Provider directory (list).
  - Capability statement (metadata).
  - Audit query (admin).
- **14.b** Script logs results with timestamps and stores in `./results/<timestamp>_results/` (Rule 11).
- **14.c** Run the full endpoint test script. Update `progress.md`.

---

## 15) Web UI templates and frontend (Rule 24)

### 15.1 Base template

- **15.a** Create `gateway/app/templates/base.html`:
  - Extends PDHC design system (`pdhc.css`).
  - Sticky navbar with primary colour, left-aligned logo, right-aligned nav links.
  - Flash message display.
  - CSRF token injection.
  - Lucide icon CDN loaded.
  - Base font 12px per design system.

### 15.2 Dashboard

- **15.b** Create `gateway/app/templates/dashboard.html`:
  - Overview cards: patient count, careplan count, recent dispatches, recent exports.
  - Quick links to main workflows.

### 15.3 Patient management pages

- **15.c** Implement patient templates (list, view, create, edit):
  - List: search bar, filter controls, paginated table.
  - View: full patient detail with FHIR fields.
  - Create/Edit: forms with validation feedback.
  - Delete confirmation dialog.

### 15.4 CarePlan readout pages

- **15.d** Implement careplan templates (list, view, readout):
  - List: filters for subject, status, text search.
  - View: careplan summary with activity/goal overview.
  - Readout: full parsed transaction table with export/dispatch actions.

### 15.5 Dispatch and export pages

- **15.e** Implement dispatch templates (form, receipt).
- **15.f** Implement export templates (preview, download).

### 15.6 Design compliance

- **15.g** All templates follow PDHC colour tokens, spacing scale, component patterns from `repo_css.md`.
- **15.h** Responsive: collapse to single column at 768px breakpoint.
- **15.i** Tables: header in code-bg, horizontal borders, 0.4rem cell padding.
- **15.j** Status badges: coloured by status (pending/submitted/acknowledged/failed).

---

## 16) API key management (Rule 8)

### 16.1 Key storage rules

- **16.a** All API keys and secrets stored exclusively in `gateway/.env`. Never committed to Git.
- **16.b** `gateway/.env.example` committed with placeholder values.

### 16.2 Key rotation procedure

- **16.c** Rotation steps:
  1. Generate new key/secret values.
  2. Update `gateway/.env` on the target environment.
  3. Restart the application (`./start.sh` or `docker compose restart app`).
  4. Verify via `GET /api/v1/auth/me` with a fresh session.

### 16.3 Key expiry and revocation

- **16.d** SSO tokens: expiry managed by `sso.pdhc.se` (default 24h).
- **16.e** Local session: configurable timeout (default 8 hours).
- **16.f** Emergency revocation: change `JWT_SECRET_KEY` in `.env` and restart.

### 16.4 Maintenance schedule

- **16.g** Recommended rotation cadence:
  - `FLASK_SECRET_KEY`: every 90 days.
  - `JWT_SECRET_KEY`: every 90 days or on suspected compromise.
  - `POSTGRES_PASSWORD`: every 180 days (requires DB user password update + `.env` update + restart).
  - `BOOTSTRAP_SU_PASSWORD`: change immediately after first login; remove from `.env` after bootstrap.

---

## 17) Server deployment preparation

### 17.1 Reverse proxy safety (Rule 22)

- **17.a** Document the reverse proxy configuration for the Mac Mini server:
  - Application listens only on `localhost:9060`.
  - Reverse proxy routes only the designated path prefix (`/request/` or subdomain) to the application.
  - No interference with other services (SSO on 9000, Plan on 9030, IPS on its port).
- **17.b** Create `safe_restart.sh` for the server instance (Rule 19):
  1. Gracefully stop the application.
  2. Pull latest code/config.
  3. Rebuild containers if needed.
  4. Start application.
  5. Health check.

### 17.2 Transfer procedure (Rule 12)

- **17.c** All web-level changes follow Rule 12:
  1. Download current server state to a temporary local archive.
  2. Compare with local version.
  3. Present comparison results — no code changes until reviewed.
  4. Operator manually applies changes based on instructions.
  5. No SSH/SCP from this plan.

### 17.3 Bootstrap on server (Rule 23)

- **17.d** `.env` must be fully prepared before first server deployment.
- **17.e** On first start with `AUTH_DISABLED=false`, SSO handles all authentication.
- **17.f** Operator verifies SSO handshake works from the server domain.

---

## 18) Final validation and sign-off

- **18.a** Run the full test suite (`pytest gateway/tests/ -v`). All tests must pass.
- **18.b** Run the comprehensive endpoint test script (step 14.a).
- **18.c** Verify FHIR compliance: all responses validate against FHIR R5 structure (Rule 15).
- **18.d** Cross-reference each rule in `top_rules.md` against implementation — verify all satisfied.
- **18.e** Final update to `progress.md` with complete status.
- **18.f** Commit all work. Tag the release.

---

## Appendix A) File tracking requirements

Per Rules 2, 4, 11, and 17:

- **`progress.md`**: Updated after every numbered step with status and test results.
- **`changed_files.md`**: Updated whenever any file is created or edited, with full path.
- **`results/`**: Test outputs stored in `./results/<ISO-8601-UTC>_results/` subdirectories.
- **`newtask.txt`**: Created when entering debugging phase (Rule 13).

---

## Appendix B) Port allocation summary (Rule 16)

| Port | Service                      |
|------|------------------------------|
| 9060 | Flask application (gunicorn) |
| 9061 | PostgreSQL database          |
| 9062 | Reserved                     |
| 9063 | Reserved                     |

Kill targets before startup: ports 9060–9063 (previous run).

---

## Appendix C) Upstream service dependencies

| Service       | URL                      | Purpose                          |
|---------------|--------------------------|----------------------------------|
| SSO           | `https://sso.pdhc.se`    | Authentication, access blobs     |
| IPS           | `https://ips.pdhc.se`    | Patient/IPS data (FHIR R5)      |
| PlanDef       | `https://plan.pdhc.se`   | CarePlan/PlanDef data (FHIR R5) |

---

## Appendix D) Error model (consistent across all endpoints)

| Code | Meaning                                    |
|------|--------------------------------------------|
| 400  | Invalid input / contract violation         |
| 401  | Unauthenticated                            |
| 403  | Authenticated but unauthorized             |
| 404  | Entity not found                           |
| 409  | Conflict / idempotency collision           |
| 422  | Semantic validation failure                |
| 500  | Internal error                             |

All errors include machine-readable `code` + human-readable `message`. FHIR routes additionally return `OperationOutcome` when applicable.
