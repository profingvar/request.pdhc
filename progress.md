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

## 18) Remaining steps — PENDING

- Server deployment preparation (`safe_restart.sh`, nginx config)
- Transfer procedure per Rule 12 (when deploying to Mac Mini)
