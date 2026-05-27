# request.pdhc — Changed Files Registry

All edited files are noted here with full path, per Rule 17.

---

| Date       | File | Action |
|------------|------|--------|
| 2026-04-21 | `/usr/local/www/request.pdhc/gateway/.env` (server) | Ticket #94 Fix 1: `SSO_CALLBACK_URL` changed from `http://localhost:9060/api/v1/auth/callback` (dev default) to `https://request.pdhc.se/api/v1/auth/callback` (matches SSO's `ALLOWED_CALLBACK_URLS`). Backup at `.env.bak.20260421T064416Z`. Container recreated with `docker-compose up -d app`. |
| 2026-04-21 | `/usr/local/www/request.pdhc/gateway/.env` (server) | Ticket #94 Fix 2: added missing `SSO_CLIENT_ID` / `SSO_CLIENT_SECRET` (mirror of SSO's `SSO_CLIENT_ID_REQUEST` / `SSO_CLIENT_SECRET_REQUEST`) — without these, `/api/auth/me/service` re-validation returned 401 and the callback rejected every token. Backup at `.env.bak.20260421T074242Z`. Container recreated. |
| 2026-04-19 | `gateway/app/services/provider_feed_service.py` | Ticket #90: include archived SRs in provider feed; expose `period_end`/`sr_status`; allow archived downloads. |
| 2026-04-19 | `gateway/tests/test_provider_feed_archived.py` | Ticket #90: new test covering archived-inclusion, period_end exposure, and archived-downloadable behavior. |
| 2026-04-16 | `gateway/app/api/provider.py` | Ticket #78 (#75 reconcile, request service): pulled SERVER→LOCAL. Server version is stricter: requires `organisation_guid` + `contract_guid` explicitly in body (local was deriving from PAT). Security improvement already running in prod; accepting into local. Backup at /tmp/request_provider.local.bak.20260416T195754Z. |
| 2026-04-16 | `gateway/app/_staged/{contract_service,match_service,service_requests}.py` | Ticket #78: pulled SERVER→LOCAL as archive. Orphan files on server (no imports anywhere, dated 2026-04-07) — appear to be refactor leftovers. Pulled down for reference only; no behavioral change. |
| 2026-04-16 | `gateway/app/services/fhir_builder_service.py` | Ticket #78: DEFERRED — local is ahead (emits `_pdhc_activity_guid`, `_pdhc_transactions` with transaction_guid/unit fields on every activity). Server is simpler (only emits for multi-txn activities). gateway.pdhc requires `transaction_guid` but has a `concept_guid` fallback path (see gateway_app/app/services/report_ingestion.py:196-214), so server is currently viable. Need operator greenlight before deploying local's richer payload to prod. |
| 2026-04-16 | `request.pdhc/gateway/docker-compose.yml` | Ticket #76: pinned `127.0.0.1:` on 9060/9061 so app/db ports are localhost-only (were binding to 0.0.0.0 → LAN-exposed via colima ssh-mux). Containers recreated on macmini; LAN refuses; https://request.pdhc.se/api/health returns 200. |
| 2026-03-20 | `request.pdhc/readme.md` | Created |
| 2026-03-20 | `request.pdhc/progress.md` | Created |
| 2026-03-20 | `request.pdhc/changed_files.md` | Created |
| 2026-03-20 | `request.pdhc/CLAUDE.md` | Created |
| 2026-03-20 | `request.pdhc/.gitignore` | Created |
| 2026-03-20 | `request.pdhc/start.sh` | Created |
| 2026-03-20 | `request.pdhc/stop.sh` | Created |
| 2026-03-20 | `request.pdhc/pdhc_markdown_layout_standard.md` | Copied |
| 2026-03-20 | `request.pdhc/repo_css.md` | Copied |
| 2026-03-20 | `gateway/.env` | Created |
| 2026-03-20 | `gateway/.env.example` | Created |
| 2026-03-20 | `gateway/requirements.txt` | Created |
| 2026-03-20 | `gateway/Dockerfile` | Created |
| 2026-03-20 | `gateway/docker-compose.yml` | Created |
| 2026-03-20 | `gateway/entrypoint.sh` | Created |
| 2026-03-20 | `gateway/app/__init__.py` | Created |
| 2026-03-20 | `gateway/app/config.py` | Created |
| 2026-03-20 | `gateway/app/models/__init__.py` | Created |
| 2026-03-20 | `gateway/app/models/dispatch_models.py` | Created |
| 2026-03-20 | `gateway/app/models/audit_models.py` | Created |
| 2026-03-20 | `gateway/app/models/export_models.py` | Created |
| 2026-03-20 | `gateway/app/services/__init__.py` | Created |
| 2026-03-20 | `gateway/app/services/auth_service.py` | Created |
| 2026-03-20 | `gateway/app/services/patient_service.py` | Created |
| 2026-03-20 | `gateway/app/services/careplan_service.py` | Created |
| 2026-03-20 | `gateway/app/services/parse_service.py` | Created |
| 2026-03-20 | `gateway/app/services/csv_service.py` | Created |
| 2026-03-20 | `gateway/app/services/dispatch_service.py` | Created |
| 2026-03-20 | `gateway/app/services/provider_service.py` | Created |
| 2026-03-20 | `gateway/app/services/audit_service.py` | Created |
| 2026-03-20 | `gateway/app/middleware/__init__.py` | Created |
| 2026-03-20 | `gateway/app/middleware/auth_middleware.py` | Created |
| 2026-03-20 | `gateway/app/middleware/cors.py` | Created |
| 2026-03-20 | `gateway/app/middleware/rate_limit.py` | Created |
| 2026-03-20 | `gateway/app/api/__init__.py` | Created |
| 2026-03-20 | `gateway/app/api/auth.py` | Created |
| 2026-03-20 | `gateway/app/api/patients.py` | Created |
| 2026-03-20 | `gateway/app/api/careplans.py` | Created |
| 2026-03-20 | `gateway/app/api/dispatch.py` | Created |
| 2026-03-20 | `gateway/app/api/providers.py` | Created |
| 2026-03-20 | `gateway/app/api/export.py` | Created |
| 2026-03-20 | `gateway/app/api/capability.py` | Created |
| 2026-03-20 | `gateway/app/routes/__init__.py` | Created |
| 2026-03-20 | `gateway/app/routes/main.py` | Created |
| 2026-03-20 | `gateway/app/routes/patients.py` | Created |
| 2026-03-20 | `gateway/app/routes/careplans.py` | Created |
| 2026-03-20 | `gateway/app/routes/dispatch.py` | Created |
| 2026-03-20 | `gateway/app/routes/export.py` | Created |
| 2026-03-20 | `gateway/app/static/css/pdhc.css` | Copied |
| 2026-03-20 | `gateway/app/templates/base.html` | Created |
| 2026-03-20 | `gateway/app/templates/dashboard.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/list.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/view.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/create.html` | Created |
| 2026-03-20 | `gateway/app/templates/patients/edit.html` | Created |
| 2026-03-20 | `gateway/app/templates/careplans/list.html` | Created |
| 2026-03-20 | `gateway/app/templates/careplans/view.html` | Created |
| 2026-03-20 | `gateway/app/templates/careplans/readout.html` | Created |
| 2026-03-20 | `gateway/app/templates/dispatch/form.html` | Created |
| 2026-03-20 | `gateway/app/templates/dispatch/receipt.html` | Created |
| 2026-03-20 | `gateway/app/templates/export/preview.html` | Created |
| 2026-03-20 | `gateway/app/templates/export/download.html` | Created |
| 2026-03-20 | `gateway/tests/conftest.py` | Created |
| 2026-03-20 | `gateway/tests/test_app_factory.py` | Created |
| 2026-03-20 | `gateway/tests/test_auth.py` | Created |
| 2026-03-20 | `gateway/tests/test_parse.py` | Created |
| 2026-03-20 | `gateway/tests/test_csv_export.py` | Created |
| 2026-03-20 | `gateway/tests/test_patients.py` | Created |
| 2026-03-20 | `gateway/tests/test_careplans.py` | Created |
| 2026-03-20 | `gateway/tests/test_dispatch.py` | Created |
| 2026-03-20 | `gateway/tests/test_providers.py` | Created |
| 2026-03-20 | `gateway/tests/test_all_endpoints.py` | Created |
| 2026-03-20 | `gateway/app/api/requests.py` | Created |
| 2026-03-20 | `gateway/app/services/request_feed_service.py` | Created |
| 2026-03-20 | `gateway/tests/test_request_feed.py` | Created |
| 2026-03-20 | `gateway/app/models/dispatch_models.py` | Modified — added `provider_status`, `provider_status_updated_at`, index on `provider_guid` |
| 2026-03-20 | `gateway/app/middleware/auth_middleware.py` | Modified — added X-API-Key authentication |
| 2026-03-20 | `gateway/app/services/auth_service.py` | Modified — added `validate_api_key()` |
| 2026-03-20 | `gateway/app/api/capability.py` | Modified — added request-feed and status-update operations |
| 2026-03-20 | `gateway/app/__init__.py` | Modified — registered `requests_bp` blueprint |
| 2026-03-20 | `gateway/migrations/versions/837810485062_*.py` | Generated — provider_status fields and provider_guid index |
| 2026-03-20 | `subscription_design copy.md` | Modified — annotated with implementation details |
| 2026-03-24 | `gateway/app/routes/service_requests.py` | Updated — added org guard to `create_view` blocking org-less professionals |
| 2026-03-24 | `gateway/app/models/security_models.py` | Created — ProviderAccessToken (bcrypt-hashed PAT) and DataExchangeGrant (HMAC composite key) models |
| 2026-03-24 | `gateway/app/services/pat_service.py` | Created — PAT lifecycle: issue, validate, revoke, list |
| 2026-03-24 | `gateway/app/services/grant_service.py` | Created — HMAC grant lifecycle: issue, validate, use, revoke |
| 2026-03-24 | `gateway/app/services/provider_feed_service.py` | Created — metadata-only feed listing + FHIR bundle download with auto-grant |
| 2026-03-24 | `gateway/app/services/report_service.py` | Created — report submission with full composite key validation chain |
| 2026-03-24 | `gateway/app/api/provider.py` | Created — provider-facing API: feed, download, report, receipt ack |
| 2026-03-24 | `gateway/app/api/admin_tokens.py` | Created — admin PAT management API: issue, list, revoke |
| 2026-03-24 | `gateway/app/models/audit_models.py` | Modified — added `data_subject_guid` column (indexed) for GDPR patient tracking |
| 2026-03-24 | `gateway/app/services/audit_service.py` | Modified — added `data_subject_guid` param, auto-extract from details |
| 2026-03-24 | `gateway/app/middleware/auth_middleware.py` | Modified — added `_check_provider_token()`, `requires_provider_token()` decorator, PAT auth in `requires_auth` |
| 2026-03-24 | `gateway/app/services/push_service.py` | Modified — resolves endpoint from PAT records, issues grant before push, adds grant_token in bundle meta |
| 2026-03-24 | `gateway/app/config.py` | Modified — added HMAC_SECRET, PAT_DEFAULT_EXPIRY_DAYS, PROVIDER_GRANT_EXPIRY_HOURS, PROVIDER_GRANT_MAX_USES, PUSH_TIMEOUT_SECONDS |
| 2026-03-24 | `gateway/requirements.txt` | Modified — added `bcrypt>=4.1` |
| 2026-03-24 | `gateway/app/__init__.py` | Modified — registered security_models import, provider_bp and admin_tokens_bp blueprints |
| 2026-03-25 | `gateway/app/__init__.py` | Modified — enhanced /api/health to return DB status (connected/unavailable) |
| 2026-04-05 | `gateway/app/api/internal.py` | Modified — added POST /internal/auto-provision-pat endpoint |
| 2026-04-05 | `gateway/app/services/push_service.py` | Modified — added X-Push-Secret header alongside X-API-Key |
| 2026-04-11 | `miserver:/usr/local/www/request.pdhc/gateway/.env` | Server-side — appended missing `IPS_API_KEY=NP_cT6G4n3S…` (value recovered from `gateway.bak.2026-03-26*/.env`). Backup saved as `.env.bak-2026-04-11T08-34-54Z`. App container recreated via `docker-compose up -d --no-deps app`. Fixes empty patient dropdown on `/service-requests/create`. |
| 2026-04-11 | `miserver:/usr/local/www/request.pdhc/gateway/.env` | Server-side — flipped `AUTH_DISABLED=true→false` during diagnosis, reverted within minutes to `true` once user clarified the Mar-26 backup is stale. Backups `.env.bak-2026-04-11T08-40-08Z` kept. Net change: zero. |
| 2026-04-11 | `miserver:/usr/local/www/request.pdhc/gateway/.env` | Server-side — `PLAN_BASE_URL=http://localhost:9030 → https://plan.pdhc.se`. `localhost` inside the app container resolves to the container itself, not the host, so `list_plan_definitions()` and `list_forms()` were both ConnectionError'ing silently → empty dropdowns on `/service-requests/create`. Backup `.env.bak-2026-04-11T08-48-38Z` kept. App recreated via `docker-compose up -d --no-deps app`. |
| 2026-04-11 | `miserver:/usr/local/www/request.pdhc/gateway/.env` | Server-side — `CONTRACT_BASE_URL=http://localhost:9021 → https://contract.pdhc.se`. Same localhost-in-container bug. Symptom: `find_eligible_providers()` on finalized/active SRs returned 502, so the provider list was empty in `view_detail` after hitting Finalize. Backup `.env.bak-2026-04-11T08-55-19Z` kept. Verified end-to-end — 4 live contracts reachable, live active SRs correctly matched to 1-2 eligible providers each. |
| 2026-04-11 | `miserver:/usr/local/www/request.pdhc/gateway/.env` | Server-side — appended missing `INTERNAL_SERVICE_KEY=<64-char>` (copied from gateway's `REQUEST_INTERNAL_SERVICE_KEY` without exposing value). Backup `.env.bak-2026-04-11T10-20-15Z`. App container recreated. Clears gateway's repeating `ERROR in grant_validation: Grant validation auth rejected — check REQUEST_INTERNAL_SERVICE_KEY` on every CGM POST. |
| 2026-04-11 | `gateway/app/services/grant_service.py` | Modified locally AND deployed to `miserver:/usr/local/www/request.pdhc/gateway/app/services/grant_service.py` (backup `grant_service.py.bak-2026-04-11T10-51-05Z`). `validate_grant()` now treats `contract_guid` as an optional filter — gateway's `GrantValidationService.validate()` doesn't pass it (it derives `contract_guid` from the validated grant response), so the old `filter_by(contract_guid='')` never matched and every gateway-initiated grant check returned `None` → `GRANT_TOKEN_INVALID`. HMAC `grant_token` + patient/org/sr uniqueness is already sufficient; the contract_guid filter was redundant when present and broken when absent. Image rebuilt via `docker-compose up -d --no-deps --build app`. Confirmed live via audit_log cutover: CGM POSTs to `/provider/report/...` flipped from `403 GRANT_TOKEN_INVALID` (10:50 UTC) to `422 VALIDATION_ERROR` (10:51 UTC) — the grant auth path is fully clear. Remaining 422 is a CGM-side data issue (`concept_guid` and `response_type` missing from observations), not in scope for this hotfix. |
| 2026-04-11 | `gateway/app/services/context_service.py` | Modified locally AND deployed — `_extract_transactions` now carries `goal_guid` / `goal_concept_guid` / `goal_concept_name` on every transaction, reading them from (1) the transaction itself (if plan.pdhc emitted them), (2) the activity (ditto), or (3) falling back to single-goal inference from the snapshot's top-level `goals[]`. This is what lets gateway enrich an observation with the *measurement* concept (B-glucos) rather than the transaction's *procedure* concept (CGM), so contract-scope validation passes. |
| 2026-04-11 | `gateway/app/api/provider.py` | Modified locally AND deployed — `/provider/validate-token` response now includes `push_endpoint_url` and `push_auth_key` from the PAT record, so gateway can route receipts per-PAT without a global `PROVIDER_SERVICE_URL` config. |
| 2026-04-11 | `miserver:/usr/local/www/request.pdhc/gateway/app/services/context_service.py` + `gateway/app/api/provider.py` | Server deploy — both files `cp`'d over existing, app image rebuilt via `docker-compose up -d --build app`. Verified via `curl http://127.0.0.1:9060/api/v1/internal/service-request/523d1227-132b-4d2a-8129-fdbb1519b039/context` — transaction now emits `goal_concept_guid = 1c34a590-... (B-glucos)` and `goal_concept_name = B-glucos` via fallback inference (single top-level goal, activity has no goal_guid). |
| 2026-04-11 | `gateway/app/services/context_service.py` | Modified locally AND deployed — `_extract_transactions` now falls back to `concept_guid` as `transaction_guid` when snapshot transactions lack a `guid` field (common in older plan.pdhc snapshots). Without this, SRs like test_medituner (`be7d3f24-...`) returned empty transactions, causing gateway enrichment to fail → 422 VALIDATION_ERROR. Also invalidated gateway's `guid_resolution_cache` for this SR so the stale empty-transactions entry is replaced. App container rebuilt via `docker-compose up -d --build app`. Verified: sr_context returns 2 transactions (Testconcept_numerical + Test_slider) using concept_guid as key. |
| 2026-04-15 | `gateway/app/services/auth_service.py` | Ticket #50 — `get_current_access_blob()` now re-validates the stored bearer against `sso.pdhc /api/auth/me/service` on every call (no blob caching). On SSO rejection the new `_clear_sso_session()` drops `sso_token`/`access_blob` and calls `flask_login.logout_user()`, so an SSO-side session flush (SSO #44) or forced password reset (SSO #43) takes effect immediately on the next request. `session['access_blob']` retained only as display-only cache, refreshed from each fresh `/me/service` response — never trusted for authz. |
| 2026-04-15 | `gateway/app/middleware/auth_middleware.py` | Ticket #50 — added `_sso_change_password_url()` + `_must_change_password_response()` helpers (JSON 403 for `/api/`, redirect otherwise). `requires_auth` now routes the session-auth path through `get_current_access_blob()` (replacing the Flask-Login pre-check) and gates both the X-API-Key and session-auth paths on `must_change_password`. `requires_role` gets the same gate before the role check so a user flagged for password reset can't slip through with an admin role. Dropped unused `flask_login.current_user` import. Deployed to macmini via `docker-compose up -d --build app` in `/usr/local/www/request.pdhc/gateway`. Backups `.bak-2026-04-15T17-36-40Z` on server. Verified: https://request.pdhc.se/api/health returns 200 `{database:connected,status:ok}`, app container `(healthy)`. |
- 2026-04-16: gateway/app/__init__.py — ticket #70 adds Access-Control-Allow-Origin https://www.pdhc.se + Methods GET + Vary: Origin + Cache-Control: no-store on /api/health so services.html can use mode:'cors'.
- 2026-04-16: gateway/app/services/fhir_builder_service.py — ticket #78 reconcile (request): scp'd LOCAL→SERVER (server was older; local's version is the "long-term fix" that server gateway.pdhc's sr_context.py already expects — its comments call out "long-term fix is to surface transaction_guids in the FHIR CarePlan"). Additive changes: (1) broadened `if len(txns) > 1:` → `if txns:` so single-txn activities emit `_pdhc_transactions` too, (2) added `_pdhc_activity_guid` on the activity, (3) added `transaction_guid` (falls back to concept_guid) + `activity_guid` on each txn, (4) added `unit` passthrough. Server backup `/tmp/request_fhir_builder.server.bak.20260416T202536Z.py`. **RUNTIME IMPACT:** request.pdhc's app container is image-baked (no volume mount) — on-disk reconciliation is complete but deploying to the live container needs operator-approved `docker compose up -d --build app` in `/usr/local/www/request.pdhc/gateway/`. Until that rebuild, the running container still serves the older behavior (which is fine — gateway falls back to concept_guid correctly).

## 2026-04-30 — Documentation page upgrade + 7 docs added

| File | Change |
|------|--------|
| `gateway/app/routes/docs.py` | Rewrote to mirror contract.pdhc's card-grid layout. Curated MANUAL_META + RUNBOOK_META dicts give icon/title/description per known file; uncurated `.md` files still appear under "Other documents". `download_doc(filename: <path>)` accepts a relative path so runbooks at `runbooks/foo.md` are downloadable too, with strict realpath check that the target stays under DOCS_DIR. |
| `gateway/app/templates/docs.html` | Replaced inline endpoint-table dump with a clean card-grid identical in shape to contract.pdhc/docs: Manuals section + Runbooks section, each rendered via a Jinja macro for one card. |
| `gateway/docs/operator-manual.md` | NEW — start/stop, env vars, backup/restore, common failures (port conflicts, DB-unreachable, SSO callback silent fail, contract validation 422). |
| `gateway/docs/admin-manual.md` | NEW — auth, users, service-request lifecycle (draft → active → in-progress → completed/revoked), creation request shape + validation gates (contract must be `executed`, concept in scope, performer matches, patient cached), dispatch flow, receipt path, patients cache, care plans, service-key auth, audit log. |
| `gateway/docs/api.md` | NEW — endpoint reference: auth, health, patients, service-requests, dispatch, provider feed (PAT-authenticated), internal grant validate + SR context, care plans, export. Cross-references contract.pdhc for status semantics. |
| `gateway/docs/architecture.md` | NEW — what request.pdhc owns vs what it doesn't, container topology diagram, happy-path data flow ASCII, data model (Patient cache + ServiceRequest + DataExchangeGrant + CarePlan + AuditLog), security (Bearer/service-key/PAT), validation chain (defense in depth), operational dependencies, why-this-split. |
| `gateway/docs/runbooks/credential-rotation.md` | NEW — what to rotate (JWT, Flask, HMAC, SSO client, DB password, PATs), procedures, the docker-restart-keeps-create-time-env trap, PAT rotation flow with secure-channel delivery. |
| `gateway/docs/runbooks/incident-response.md` | NEW — triage tree (DB-unavailable / app-not-reachable / 5xx other), Colima port-forward wedge recovery, silent credential drift recovery, provider report rejection causes, audit-chain compromise procedure, alerting/escalation, known recurring incidents. |
| `gateway/docs/runbooks/upgrade-procedure.md` | NEW — pre-flight checklist, pack/transfer/apply via release-symlink layout, venv rebuild rule (no copy across releases), migration handling, smoke testing, rollback, cleanup, notify. |
| (server) request_pdhc_app `/app/docs/*` | All 7 docs `docker cp`'d into the running container at `/app/docs/` + `/app/docs/runbooks/`. Container restarted; `/api/health` 200; `/docs` route serves the new card grid; download links work for both manuals and runbooks. |

## 2026-04-30 — Refresh api.md + add rendered `/api` page

| File | Change |
|------|--------|
| `gateway/docs/api.md` | Full rewrite. The previous version described a REST-style kebab surface (`/api/v1/patients`, `/api/v1/service-requests`, ...) that doesn't exist. Reality: FHIR-resource-style PascalCase paths (`/api/v1/Patient`, `/api/v1/ServiceRequest`, `/api/v1/CarePlan`, `/api/v1/PlanDefinition`, `/api/v1/Form`, `/api/v1/Contract`) plus `/provider/*` (PAT-auth), `/admin/provider-tokens`, `/internal/*` (service-key), `/auth/*`, `/metadata`, and `/api/health`. Documents three credential modes (SSO session cookie / X-Provider-Token / X-Service-Key), the SR lifecycle, validation-error codes (`contract_not_active`, `concept_out_of_scope`, `provider_mismatch`, `patient_not_cached`), and every endpoint actually registered in `app/api/*.py` (~56 routes). |
| `gateway/docs/admin-manual.md` | §3.2 SR-creation example updated to the real POST body shape (`patient_guid` / `plan_definition_guid` / `contract_guid` / `notes`) and SSO session cookie (was: a fictional FHIR Bundle body + Bearer header). §4 Patients table retitled to FHIR resource paths (`/Patient`, `/Patient/<guid>`) and PUT/DELETE rows added. |
| `gateway/app/routes/api_docs.py` | NEW — single-route blueprint serving `/api` (login_required). |
| `gateway/app/templates/api_reference.html` | NEW — hand-written rendered API reference. Same content as `api.md` but as HTML: sticky table-of-contents on the left, 13 sections in cards, method-coloured pills (GET green / POST blue / PUT amber / DELETE red), inline scope pills, code blocks for body shapes. Uses `pdhc.css` design tokens; extends `base.html`. Has a "Download as Markdown" link at top so users have both the rendered and downloadable versions. |
| `gateway/app/templates/base.html` | Added "API" nav link between "Docs" and the separator. Active when `request.blueprint == 'api_docs'`. |
| `gateway/app/__init__.py` | Registered the new `api_docs_bp` blueprint. |
| (server) request_pdhc_app | All 6 files `docker cp`'d into the live container; restarted. Verified: `/api/health` 200, `/docs` 200, `/api` redirects to `/api/v1/auth/login?next=%2Fapi` for unauthenticated callers (correct — the page is login_required, so anonymous traffic gets sent through SSO). Template parses cleanly (would have been a 500 otherwise). |
| `gateway/app/api/provider.py` | 2026-05-13 — Renamed `/provider/report/<sr_guid>` → `/provider/status/<sr_guid>` (canonical). Old path kept as deprecation alias; logs `report.deprecated_alias_used` audit event. Extracted shared handler `_handle_status_update`. Reason: the path collided with `gateway.pdhc /provider/report/<sr_guid>` (the actual observation endpoint), causing silent data loss when providers POSTed observations to the wrong host. |
| `gateway/app/templates/api_reference.html` | 2026-05-13 — Documented `/provider/status` as canonical; `/provider/report` marked deprecated. Added note: request.pdhc's path stores `report_payload` for audit only — observations need gateway.pdhc. |
| `gateway/docs/api.md` | 2026-05-13 — Same rename + clarification as the HTML reference. |
| `gateway/docs/runbooks/incident-response.md` | 2026-05-13 — §4: clarified that 4xx triage assumes provider is on gateway.pdhc; added note to check request.pdhc audit for `report.deprecated_alias_used` events that indicate provider is on the wrong host. |
| `gateway/app/services/fhir_builder_service.py` | 2026-05-16 — When snapshot has `timing_bounds_mode = 'count'`, emit `CarePlan.activity[].detail.scheduledTiming.repeat.count`. When `'duration'`, emit `boundsDuration` (UCUM). Pass-through only — depends on plan.pdhc bounded-recurrence rollout (its `2026-05-16` entry in plan.pdhc/changed_files.md). |
| `gateway/app/services/fhir_builder_service.py` | 2026-05-18 — CarePlan Goal target emission now produces fully-coded FHIR shapes when plan.pdhc's enriched snapshot is present: `detailQuantity` and `detailRange.low/high` include UCUM `system="http://unitsofmeasure.org"` + `code` (from `target_unit_name`); `detailCodeableConcept` includes `coding[0].system="https://plan.pdhc.se/api/v1/valuesets/<vs_guid>"` + `code` + `display` (from `target_categorical_valueset/_code/_display`). Falls back gracefully to text-only when enrichment is missing (e.g. SRs created before the plan.pdhc 2026-05-18 rollout). |
| `gateway/app/services/fhir_builder_service.py` | 2026-05-18 — Route clinical Quantity unit through plan.pdhc per platform principle: `_qty()` helper now emits `system="https://plan.pdhc.se/api/v1/lookup/units"` instead of UCUM directly. `unit_name` (UCUM-compatible) is the code, so consumers can still interpret without resolving plan.pdhc, but the identity is anchored there. `Timing.repeat.boundsDuration` left as UCUM — those codes (d/wk/mo) are FHIR-intrinsic time-unit enums that plan.pdhc's catalog doesn't currently mirror. |

## 2026-05-27T08:09:04Z — UI: allow Revoke on archived SRs (+ per-row Revoke in archived list)
- gateway/app/templates/service_requests/view.html
- gateway/app/templates/service_requests/archived.html
- gateway/app/routes/service_requests.py
