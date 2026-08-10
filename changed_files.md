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

- 2026-06-09 (#229 Request PDL #5 — consume consent at dispatch):
  - gateway/app/services/ips_consent_client.py (NEW): Consent dataclass,
    IpsConsentClient.fetch_active_consents(patient_guid), 30s TTL
    per-patient _ConsentCache, invalidate() webhook hook (parity with
    block client #228), get_active_consents() helper, and the pure
    decision helper `consent_covers_dispatch(consents, dest_caregiver,
    payload_concepts) -> (ok, reason)`. Reasons: 'no_consent' /
    'concept_not_consented' / 'no_destination_caregiver'. Whole-caregiver
    consent covers any payload; concept-narrowed consents union to
    define coverage.
  - gateway/app/services/dispatch_service.py: `create_dispatch` accepts
    optional patient_guid + destination_caregiver_guid +
    payload_concept_guids. When BOTH the patient and caregiver are
    supplied, runs the consent gate BEFORE the idempotency lookup; a
    consent-failing dispatch returns 403 with code='consent_missing'
    and writes a `careplan.dispatch.refused` audit row (Lag 2022:913 §5
    cited in detail.pdl_basis). Half-supplied → warn-and-proceed
    (soft-rollout posture). Both absent → existing behaviour.
  - gateway/app/api/dispatch.py: route plumbs the three new fields
    through to the service; rejects 400 when payload_concept_guids is
    present but not a list.
  - gateway/tests/test_consent_at_dispatch.py (NEW, 19 tests):
      * consent_covers_dispatch (9): empty / unrelated grantee / revoked
        / whole-caregiver / narrowed-listed / narrowed-unlisted /
        narrowed-no-payload-concepts / union of narrowed consents /
        missing destination.
      * get_active_consents (3): caches per patient, invalidate
        re-fetches, drops inactive.
      * Dispatch end-to-end (6): consented proceeds; unconsented 403 +
        audit + no upstream; concept-narrowed refusal; idempotency
        replay still blocked by gate (the consent check fires before
        the idempotency lookup); legacy call without consent fields
        proceeds; half-fields warn and proceed.
      * Route plumbing (1): payload_concept_guids must be a list
        (skipped when sibling tests pollute AUTH_DISABLED at module
        load time — the layer is still verified in isolated runs).
    Isolated run: 19/19 green. Full suite: 18 pass + 1 skip / 120 total
    pass (was 102 baseline) / 53 pre-existing failures unchanged.

- 2026-06-09 (#227 Request PDL #3 — read audit inventory + gap closure):
  - gateway/app/services/audit_service.py: new `@audit_read(action,
    resource_type=, guid_arg=)` decorator. Writes one AuditLog row
    on 2xx, skips 4xx/5xx (no row when access didn't happen).
    Swallows internal failures so audit table issues never break
    the response. guid_arg defaults to a conventional list
    (guid/patient_guid/request_guid/receipt_token/etc.).
  - gateway/app/api/patients.py: `GET /Patient` -> patient.list;
    `GET /Patient/<guid>` -> patient.read.
  - gateway/app/api/careplans.py: `GET /CarePlan` -> careplan.list.
    `GET /CarePlan/<guid>` keeps its pre-existing inline log_event
    (action='careplan.view') so downstream consumers' filters don't
    break.
  - gateway/app/api/service_requests.py: 6 reads decorated —
    service_request.{list,read,matches.list,receipts.list,
    receipt.read,forms.list}.
  - gateway/app/api/requests.py: `GET /requests` -> request.list;
    `GET /requests/<guid>` -> request.read.
  - gateway/docs/architecture.md §4.5.1 (NEW): read-side audit
    inventory table with one row per audited endpoint, plus the
    "adding new read endpoints" guidance.
  - gateway/tests/test_audit_read_decorator.py (NEW, 7 tests):
    * 2xx writes row; LIST resolves no guid; 404/5xx skip;
      log_event failure doesn't break the response.
    * Inventory uniqueness (action strings disjoint).
    * Resource-type allow-list smoke.

- 2026-07-02 (rollup #348 commit-1 — 8 tickets in one commit):
  Landed on top of the 2026-07-01 reconcile leg (#365) that brought
  prod back to 569f742 = origin/main after 28 metadata-drifted
  commits + 103 hand-edited files. Reconcile was trivial in
  content terms — sha256 diff on 104 py/html files showed zero drift.

  - #366 gateway/app/api/capability.py: deleted the `export-csv`
    operation entry from the CarePlan resource block. Finding §1.1
    (HIGH) — the entry pointed at `POST /api/v1/CarePlan/{id}/export/csv`,
    which was deleted with the whole export cluster in commit 569f742
    (#320, 2026-06-28). Advertising a 404 for weeks broke generic FHIR
    clients that enumerate operations.

  - #367 gateway/app/api/capability.py: froze `CapabilityStatement.date`
    at module import via `os.path.getmtime(__file__)` — same file-mtime
    pattern that terminal termbank #352 landed after prod verify
    caught gunicorn worker fork variance (memory
    `infra_gunicorn_worker_fork_freezes_datetime`). Consecutive
    /fhir/metadata requests now return identical `date` and the value
    only advances on a real image rebuild.

  - #368 gateway/app/api/capability.py + gateway/app/api/dispatch.py:
    dropped the legacy `/CarePlan/{id}/dispatch` alias — both the
    `dispatch` operation entry in capability.py's CarePlan block AND
    the two `@dispatch_bp.route('/CarePlan/<guid>/dispatch', ...)`
    handlers in dispatch.py (POST submit + GET status-by-token).
    Operator chose Y (immediate drop, no soak) at 2026-07-01 Phase C
    signoff. Coordinated with plan.pdhc's equivalent alias drop
    2026-07-01 in 32ca438 / #334. Canonical POST/GET on
    `/PlanDefinition/<guid>/dispatch{,/<receipt_token>}` unchanged.

  - #369 gateway/docker-compose.yml: pinned db (9061:5432) and app
    (9060:9060) port maps to `127.0.0.1:`, so neither container is
    LAN-reachable. Deleted the insecure `POSTGRES_PASSWORD:-request_dev_2026!`
    fallback from all three sites (`db.environment`, `app.environment`,
    `worker.environment`) — compose now uses `${POSTGRES_PASSWORD:?...}`
    and refuses to start without an explicit value in .env. Prod .env
    verified to have POSTGRES_USER/PASSWORD/DB set before the change.

  - #370 gateway/entrypoint.sh: added `--access-logfile -` and
    `--access-logformat '%(t)s %(h)s "%(r)s" %(s)s %(L)ss'` to the
    gunicorn invocation. Access lines now land in
    `docker logs request_pdhc_app`, matching plan.pdhc / termbank /
    the rest of the platform. Enables any future soak-then-drop
    workflow analogous to plan.pdhc #334 / this batch's #368.

  - #371 gateway/docker-compose.yml: added `restart: unless-stopped`
    to db and app services (worker already had it). All three
    request.pdhc containers now respawn on docker daemon restart /
    macmini reboot — matches memory
    `infra_platform_robustness_post_2026-05-10`.

  - #373 gateway/app/api/capability.py: rewrote the CarePlan
    resource block to advertise the real patient-CarePlan API from
    #310. Interactions: `[create, read, update, search-type]`.
    Operations: `context` at `GET /api/v1/careplans/{guid}/context`
    (documented). searchParam: `patient_guid` (reference) and
    `status` (token). Description of the service updated to reflect
    the dispatch-envelope role and point at ADR-001.

  - #374 docs/decisions/ADR-001-alerting-scope.md (NEW) + readme.md +
    describe_request.pdhc.md: first ADR file for the repo. Documents
    that alerting (threshold evaluation + DetectedIssue/Flag
    emission) is out of scope for request.pdhc by design; the
    alerting layer belongs in analyse.pdhc when built. Rationale
    grounded in the operator's 2026-07-01 note "request does not
    receive any data." MDR consequence spelled out: request.pdhc is
    NOT a Rule 11 device. ADR marked revocable. Short pointers to
    the ADR added at the top of readme.md and describe_request.pdhc.md;
    the full 656-line describe sweep stays deferred under finding
    §10.1 (child ticket #379).

- 2026-07-02 (rollup #348 commit-2 — 2 tickets + 1 delete + 1 test-fix):
  - #372 gateway/tests/test_capability_truth.py (NEW): CapabilityStatement
    truth test. Direction (a): every operation.definition advertised in
    /api/v1/metadata resolves to a real route in app.url_map with a
    compatible verb. Direction (b) [route-to-capability] deferred to a
    follow-up because request.pdhc has many legitimate internal-only
    endpoints (SSO callbacks, admin, provider webhook receivers) whose
    allowlist is bigger scope than this ticket. Three tests:
    metadata reachable + all advertised ops resolve + regression guard
    for #366/#368 stale operations. Caught real drift on first local
    run — the `request-feed` operation definition included query
    string params that the shape helper didn't strip; fixed in the
    same file. 3/3 pass.
  - gateway/tests/test_all_endpoints.py (DELETED): the pre-#372 file
    that claimed "exercises every API endpoint per the capability
    statement" but was actually a smoke test with hard-coded route
    paths. Its Rule 20 / Rule 9 role is now filled by
    test_capability_truth.py.
  - gateway/tests/test_dispatch.py (test-URL fix follow-on to #368):
    replaced /api/v1/CarePlan/test-cp/dispatch with the canonical
    /api/v1/PlanDefinition/test-cp/dispatch in all three tests. Tests
    now pass in isolation; still 401 in the full suite due to the
    documented sibling-test AUTH_DISABLED pollution issue (see the
    SSO-fixture follow-up ticket filed under this rollup).
## 2026-07-02 — rollup #348 commit-3 (#377 conformance CI + CS spec fixes)

  - #377 gateway/app/api/capability.py (MODIFIED — CS made R5-conformant):
    the pre-#377 CS carried `operation.definition: "POST /api/v1/…"`
    strings, but that field is a canonical URL per R5 spec — validator
    flagged 33 whitespace/URI errors. Added a `_op(name, method_path,
    documentation)` helper that stamps `definition` with a canonical
    URL under `https://request.pdhc.se/api/v1/OperationDefinition/…`
    and moves the raw METHOD/path onto the FIRST LINE of
    `documentation`. Also added the `implementation` element (satisfies
    cpb-14 for `kind=instance`) and switched the restful-security-
    service CodeSystem URL from the R4-era `terminology.hl7.org/…` to
    the R5-recognised `http://hl7.org/fhir/restful-security-service`.
    All 37 CS errors → 0 errors, 0 warnings after this change.
  - #377 gateway/tests/test_capability_truth.py (MODIFIED — track new
    CS shape): rewrote `_parse_op_definition` → `_parse_op_first_line`,
    now scans the first line of `documentation` for the "METHOD /path"
    convention (see capability.py `_op` helper). Truth test still
    catches ghost routes + still walks both `rest.resource[].operation`
    and `rest.operation`. Added a unit test for the parser itself. 4/4
    tests pass.
  - #377 gateway/tests/conformance_corpus_emit.py (NEW): boots a
    self-contained SQLite Flask app (AUTH_DISABLED offline), emits
    the CapabilityStatement JSON from GET /api/v1/metadata into
    tests/fhir_corpus/. Deliberately NARROW per termbank's Rule 15 A
    pattern (see docstring): ServiceRequest + contained CarePlan / Goal
    / Questionnaire are deferred to ticket #378 because the first
    conformance run flagged real R4→R5 shape drift in
    fhir_builder_service.py (see the ticket for the concrete findings
    list).
  - #377 gateway/Makefile (NEW): local dev + rollup #348 conformance
    targets. `make test` mirrors the CI ignores from test.yml. `make
    corpus` regenerates the JSON. `make conformance` runs
    validator_cli.jar against the corpus. VALIDATOR_JAR defaults to
    ~/.local/share/fhir/validator_cli.jar to match termbank/plan.pdhc.
  - #377 .github/workflows/conformance.yml (NEW): Java 17 + Python 3.12
    + cached validator_cli.jar 6.9.10 against tx.fhir.org/r5. Paths
    filter targets capability.py, care_plans.py, service_requests.py,
    dispatch.py, fhir_builder_service.py, models/**, the corpus
    emitter, requirements.txt, Makefile, this workflow. 20-min
    timeout (tx.fhir.org round-trips are slow — ~3 min per resource
    cold). Uploads corpus artifact on failure for triage.
  - #377 gateway/tests/fhir_corpus/*.json (NEW, committed): reference
    corpus. Deterministic — regenerated by `make corpus` on every CI
    run and diff-checked against what the current code emits. Serves
    as a byte-for-byte drift signal at review time.

## 2026-07-02 — rollup #348 close-out (#380 SSO fixture + #365 reconcile + #381 super)

  - #380 gateway/tests/conftest.py (MODIFIED): added an autouse
    session-scoped fixture `_pin_auth_disabled` that resets
    `app.config['AUTH_DISABLED'] = True` before every test. Belt-
    and-braces defence against sibling tests' import-time env writes.
  - #380 gateway/tests/test_dispatch_trigger.py (MODIFIED): every
    module-level `os.environ['X'] = 'Y'` converted to
    `os.environ.setdefault(...)`. conftest's canonical test env now
    always wins.
  - #380 gateway/tests/test_provider_lifecycle.py (MODIFIED): same
    setdefault sweep.
  - #380 gateway/tests/test_sandbox_dispatch.py (MODIFIED): same.
  - #380 gateway/tests/test_webhook_dispatcher.py (MODIFIED): same.
  - #380 gateway/tests/test_internal_api.py (MODIFIED): `_create_sr`
    now seeds `plan_definition_snapshot` in the shape the current
    `context_service._extract_transactions` reads (goals[] +
    activities[].transactions[]). Previously seeded transactions
    inside `fhir_resource.contained[0]._pdhc_transactions` — a stale
    shape from before the context service was refactored. This was
    the last remaining real bug behind the 52 pre-existing failures.
  - #380 gateway/tests/test_consent_at_dispatch.py (MODIFIED):
    `TestRoutePlumbing::test_bad_payload_concept_guids_shape_is_400`
    URL corrected from the deleted `/api/v1/CarePlan/<g>/dispatch`
    (dropped in #368 commit-1) to the canonical
    `/api/v1/PlanDefinition/<g>/dispatch`. The AUTH_DISABLED
    pytest.skip flake-shim removed — no longer needed now that
    conftest pins per-test.
  - #380 .github/workflows/test.yml (MODIFIED): removed the whole
    7-file `--ignore` list + the 1-test `--deselect`. CI now runs
    the entire pytest suite. Header comment documents #380 closeout.
  - Result: full pytest 160/160 pass (vs. commit-2 baseline of
    102/102 with 7 files ignored + 51 pre-existing 401 failures
    on the un-ignored subset).

## 2026-07-02 — rollup #348 close-out (#381 fhir_builder_service R4→R5)

  - #381 gateway/app/services/fhir_builder_service.py (REWRITTEN):
    every finding from the ticket #381 validator run addressed.
    - CarePlan.activity `detail` (removed in R5) replaced with
      R5-legal `performedActivity: CodeableReference[]` wrapping
      the transaction concept. Activity metadata (title, timing,
      performer_type, transactions[]) previously carried on a
      custom `activity-plan-meta` Extension is now available to
      consumers via ServiceRequest.plan_definition_snapshot on
      the parent SR — the custom extension isn't R5-legal without
      a published StructureDefinition.
    - ServiceRequest.code wrapped as CodeableReference in R5:
      `{concept: {text: '...'}}`.
    - ServiceRequest.supportingInfo entries are CodeableReference
      in R5: `{reference: {reference: '...', display: '...'}}`.
    - `authoredOn` + `occurrencePeriod.start/end` now emitted via
      `_iso_with_tz()` which stamps `+00:00` on naive datetimes
      (SQLite / non-tz db.DateTime columns).
    - Contained Patient reference switched from absolute
      `Patient/<guid>` to hash `#patient-<guid>` so dom-3 is met.
    - Goal.target.measure now always present when target.detail
      is (satisfies gol-1). Anchored at the goal concept.
    - Goal.priority coded via
      `http://terminology.hl7.org/CodeSystem/goal-priority` so the
      Coding has a system.
    - Questionnaire.item.type = 'choice' rewritten to 'coding' on
      emit (R5 rename; upstream plan.pdhc still authors R4 name).
    - Recursive `_strip_pdhc_markers()` walks the emitted resource
      tree and removes any `_pdhc_*` keys — belt-and-braces
      protection against caller mutations that would otherwise
      leak internal wire markers into the FHIR envelope.
    - Custom `requester-organization` extension replaced with a
      spec-legal `performer[]` entry (Organization ref, sorted
      first) — R5 has no dedicated requester-org field, but
      performer[] is Reference[Organization|Practitioner|...] and
      correctly conveys the requesting side.
    - `build_patient_excerpt()` now omits empty list fields (FHIR
      forbids exactly-empty arrays).
    - Concept coding `system` switched from REST URLs
      (`https://plan.pdhc.se/api/v1/concepts`) to PDHC URNs
      (`urn:pdhc:concept`, `urn:pdhc:unit`, `urn:pdhc:valueset:*`).
      Public tx servers don't know PDHC concepts and treating the
      old URLs as canonical caused tx5 timeouts on every coding.
  - #381 gateway/tests/conformance_corpus_emit.py (MODIFIED):
    corpus scope expanded from CapabilityStatement-only to
    CapabilityStatement + ServiceRequest + care_plan (the earlier
    narrowing from #377 landed with the note that we'd re-expand
    once fhir_builder was R5-fixed). The care_plan extract lifts
    peer Goal + Patient into its own `contained[]` so hash refs
    resolve when it's validated standalone. Patient excerpt no
    longer carries `identifier: []` (empty-array violation).
    Questionnaire.item.type is deliberately kept as 'choice' in
    the fixture so the R4→R5 rename shim in fhir_builder is
    exercised end-to-end. Answer options carry a coding.system.
  - #381 gateway/Makefile (MODIFIED): TX_SERVER default flipped
    from `https://tx.fhir.org/r5` to `n/a`. request.pdhc's concept
    codings use PDHC-scoped URNs no public tx server knows about;
    enabling tx makes validation hang 60s per unknown code (tx5
    timeout) and then fail. Well-known HL7 codings in the CS are
    checked from the bundled package cache and don't need tx.
    Trade-off documented in the Makefile header.
  - #381 gateway/tests/fhir_corpus/*.json (MODIFIED): reference
    corpus regenerated. capability_statement + service_request +
    care_plan.

  Local `make conformance` result: 0 errors on all three resources
  (17 notes on CS, 5 warnings + 3 notes on care_plan, 5 warnings +
  8 notes on service_request — all informational for
  well-known-not-verified codings; no spec violations).

## 2026-07-02 — rollup #348 close-out (#365 reconcile leg)

  - #365 no code changes — the reconcile leg landed 2026-07-01 as
    `569f742` when we sha256-diffed the 104 code files against prod
    and confirmed zero drift, then git-reset-hard to prod's state.
    Closed via /respond only. Ticket closed for tracker hygiene.

## 2026-07-01 — rollup #348 commit-2 (#372 truth test + #376 CI)

  - #376 .github/workflows/test.yml (NEW): first CI for request.pdhc.
    Python 3.12 matches Dockerfile base. Paths filter targets
    gateway/** + this workflow. Runs `pytest tests` on push + PR
    with 7 files ignored (test_request_feed, test_care_plans,
    test_internal_api, test_patients, test_auth, test_providers,
    test_dispatch) and 1 test deselected — all 51+3 pre-existing
    401-auth failures rooted in the SSO fixture regression documented
    at 2026-06-09. New ticket filed to fix the fixture so those files
    can rejoin CI. Env sets AUTH_DISABLED=true + HMAC_SECRET (32-char)
    + INTERNAL_SERVICE_KEY. Dry-run: 102/102 pass locally.

## 2026-07-07 — M0 #419: adopt affiliations[] scope + fill organization_names gap
- gateway/app/services/reform_scope.py — NEW config-free helpers
  caller_org_ids() (Zone-1 from affiliations, dual-read) + caller_org_names()
  (guid->name map from paired affiliation entries; legacy parallel-array
  fallback). Fills the long-standing organization_names GAP.
- gateway/app/api/service_requests.py — use helpers; removed the fragile
  _name_for_org parallel-array lookup (now a dict get).
- gateway/app/routes/service_requests.py — all 6 org_ids/names read sites use
  the helpers; org-picker + org_name now from the paired map.
- gateway/tests/test_reform_scope.py — NEW, 6 tests.
- request.pdhc/gateway/docs/architecture.md (Port Allocation section)
- gateway/app/api/auth.py (logout: redirect browser to /logged-out + kill SSO browser session; JSON preserved for API)
- gateway/app/services/timeline_service.py (NEW — metro-map schedule builder: activities→lines, occurrences→stations, endless→first-month+ellipsis, bounds/period_end→terminus)
- gateway/app/templates/service_requests/plan_timeline.html (NEW — SVG metro-map patient timeline; hover a station → concept list tooltip; per-line legend)
- gateway/app/routes/service_requests.py (add timeline_view /service-requests/<guid>/timeline + plan_timeline_preview /plan-timeline/<plandef_guid>)
- gateway/app/templates/service_requests/view.html (add "View Timeline" button on PlanDefinition card)
- gateway/tests/test_timeline_service.py (NEW — 10 unit tests for the schedule builder)
- gateway/app/templates/service_requests/create.html ("Preview schedule timeline ↗" link → /plan-timeline/<guid>, shown once a PlanDefinition is selected)
- progress.md (Patient timeline metro-map section, 2026-08-10)
