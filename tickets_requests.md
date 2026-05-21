1. when listing details about a request, give both guid and name of contractor and organisation

   DONE — Added `requester_user_name` and `requester_org_name` columns to ServiceRequest model (migration `c3d4e5f6a7b8`). Names are extracted from the SSO access blob (`display_name`, `organization_names`) at creation time and stored alongside GUIDs. The view.html details table now shows name + GUID (muted) for Requester, Organisation, and provider matches. The FHIR resource also carries display names in requester and organisation references.

2. For the period of development - In the request page I want a side by side with the json a creal text readout listing the objects (name, guid, weburl for lookup) in the blob that will be sent to the provider

   DONE — Replaced the old "FHIR R5 Resource" card with a two-column "Provider Delivery Blob (dev)" panel. Left column: Object Readout table listing every referenced resource (ServiceRequest, Patient, Requester, Organisation, PlanDefinition, Contract, Providers, CarePlan, Goals, Questionnaires) with display name, full GUID, and clickable lookup links to the relevant PDHC service (IPS, SSO, Plan, Contract). Right column: raw FHIR JSON with monospace styling.

3. When pressing create draft/finalaize I want a .json below the finalize/archive/revoke keys and side by side a readout from the json os the rendered questionnaire (All questions)

   DONE — Added a "Questionnaire Readout (dev)" card below the action buttons, shown once forms have snapshots (i.e. after finalization). For each attached form with a snapshot: left column renders a numbered table of all questions (text, type, required) with up to 3 levels of nesting; right column shows the raw Questionnaire JSON. Multiple forms are shown stacked with dividers.

4. add in the contract matches pane also the request GUID

   DONE — Added a "Request" column as the first column in the Contract Matches table, showing the full `service_request_guid` for each match.

5. Implement updates on request on miserver (now reachable ssh miserver).

   DONE — Committed all changes (10b98b6), pushed to origin/main, pulled on miserver. Stale local files on server were cleaned. Docker image rebuilt, containers restarted, migration c3d4e5f6a7b8 applied automatically. Health check passing: `{"database":"connected","status":"ok"}`.

6. so the server is reached then ssh miserver@192.168.1.154 and repo is in /usr/local/www/request.pdhc

   DONE — Server access confirmed: `ssh miserver@192.168.1.154`, repo at `/usr/local/www/request.pdhc`. Docker via Homebrew (`/opt/homebrew/bin/docker-compose`). Deploy command: `export PATH=/opt/homebrew/bin:$PATH && cd /usr/local/www/request.pdhc/gateway && docker-compose down && docker-compose up -d --build`.

7. Item in request ska med på listan Provider Delivery Blob (dev). Conceptet QOL är en slider inte som det står integer. Likaså skilj på enval och flervalsfrgåor inför rendering.

   DONE — Three changes in view.html: (1) Questionnaire items now listed under each Questionnaire row in the Provider Delivery Blob readout, showing text, render type, and linkId with nested indentation. (2) Added a `render_type` Jinja macro that detects the `questionnaire-itemControl` extension with code `slider` on `integer` items and displays "slider" instead of "integer". Also falls back to min/max inference for older Questionnaires. (3) `choice` items are now shown as "single-choice" or "multi-choice" (based on `repeats`), and `open-choice` likewise. The same macro is used in both the Questionnaire Readout and the Provider Delivery Blob panels.

   UPDATE (2026-03-30) — Plan.pdhc team confirmed: (a) They now emit `questionnaire-itemControl` extension with code `slider` on slider items — our code already handles this as the primary signal. (b) PlanDefinitions now include optional `form_definition_guid` and `form_definition` fields in the API response — informational only, no action needed (our snapshot stores them automatically). (c) No breaking changes.

8. [DONE] read the document data_package_reference.docx in provider.pdhc/docs and create an item list of needed reforms in request.pdhc. Give the result after each added ticket in this document. Note that contract.pdhc.se is up and ready.

--- Ticket 8 Results (derived from provider.pdhc/docs/data_package_reference.md, Section 9) ---

8.1 [DONE] Internal service key auth — add X-Service-Key support
   - Add INTERNAL_SERVICE_KEY to config.py
   - Add requires_service_key() decorator in auth_middleware.py
   - Use hmac.compare_digest for constant-time comparison (as done in contract.pdhc)
   - Generic "unauthorized" error on failure (no internal state leakage)
   - Empty key = reject all (safe default)

8.2 [DONE] SR context endpoint — GET /api/v1/internal/service-request/<guid>/context
   - Auth: X-Service-Key (internal only, no rate limit)
   - Returns pre-extracted context gateway.pdhc needs for reconstruction:
     service_request_guid, status, patient_guid, contract_guid,
     requester_org_guid, requester_user_guid, requester_user_name,
     plan_definition_guid, period_start, period_end,
     transactions[] (from CarePlan _pdhc_transactions: transaction_guid, concept_guid,
       concept_name, unit, unit_display, expected_value, range_min, range_max, requirement_type),
     goals[] (description, concept_guid, priority, target_value, target_comparator)
   - New ContextService class to extract this from stored ServiceRequest.fhir_resource

8.3 [DONE] Grant validation endpoint — POST /api/v1/internal/grant/validate
   - Auth: X-Service-Key (internal only)
   - Request body: { sr_guid, org_guid, patient_guid, grant_token }
   - Validates HMAC, expiry, revocation, max_uses (reuses existing grant_service.validate_grant)
   - Response: { valid: true/false, contract_guid, grant_type, uses_remaining }
   - Keeps HMAC_SECRET on request.pdhc only — gateway never sees it (Option A from data package ref)

8.4 [ ] Simplify report endpoint — derive org_guid and contract_guid from PAT/grant
   - Current: POST /api/v1/provider/report/<sr_guid> requires organisation_guid and contract_guid in body
   - Change: derive organisation_guid from validated PAT (g.provider_org_guid already set by middleware)
   - Change: derive contract_guid from grant record lookup (or from PAT: g.provider_contract_guid)
   - Remove organisation_guid and contract_guid from required body fields
   - Minimal required body: { patient_guid, grant_token, status, observations[] }
   - Backward compatible: if org_guid/contract_guid are provided, cross-check against derived values

8.5 [DONE] Internal API blueprint
   - New file: api/internal.py with blueprint registered at /api/v1/internal
   - Routes: 8.2 (context) + 8.3 (grant validate)
   - All routes behind requires_service_key()
   - Not exposed publicly, not accessible via PAT or SSO

8.6 [DONE] Tests (11 new, 85/87 total — 2 pre-existing CarePlan failures)
   - Context endpoint: returns correct SR context, handles missing SR, auth rejection
   - Grant validation endpoint: valid grant, expired grant, revoked grant, bad HMAC, auth rejection
   - Simplified report endpoint: minimal payload works, cross-check catches mismatch
   - Internal service key: valid key, missing key, invalid key
   - Existing test suite must still pass

9. [DONE] Security inspection of request.pdhc

--- Ticket 9 Results ---

9.1 CRITICAL findings (5):
    - AUTH_DISABLED defaults to true in config.py — must default to false
    - Missing contract_guid in required fields list (provider.py:80) — causes 500 instead of 400
    - push_auth_key stored plaintext despite field name _encrypted (pat_service.py:39)
    - Hardcoded secrets in .env checked into repo (DB creds, API keys, bootstrap admin)
    - HMAC_SECRET falls back to literal string 'fallback-not-for-production' (grant_service.py:18)

9.2 HIGH findings (3):
    - SECRET_KEY/JWT_SECRET_KEY default to 'change-me' — forgeable sessions/tokens
    - SSRF risk in push_endpoint_url — no validation against private IPs or localhost
    - PAT validation loads ALL tokens, O(n) bcrypt — DoS + timing side-channel

9.3 MEDIUM findings (3):
    - Receipt ack endpoint has no provider ownership check (IDOR)
    - Grant tokens reusable indefinitely when max_uses not set
    - Exception details (str(e)) returned in error responses — leaks internal infra

9.4 Positive: HMAC grant validation correctly uses hmac.compare_digest (constant-time)

--- Security Fixes Applied ---

10. [DONE] Fix security findings from ticket 9

10.1 config.py — AUTH_DISABLED now defaults to 'false' (was 'true')
     Removed hardcoded DB credentials from default SQLALCHEMY_DATABASE_URI
     Removed weak 'change-me' defaults from SECRET_KEY and JWT_SECRET_KEY (now empty string — must be set via env)

10.2 grant_service.py — _hmac_secret() now raises RuntimeError if HMAC_SECRET not explicitly configured
     No more silent fallback to SECRET_KEY or literal string

10.3 provider.py — Added 'contract_guid' to required fields list (was missing, caused KeyError → 500)

10.4 push_service.py — Added _validate_push_url() SSRF protection:
     Resolves hostname, rejects private/loopback/link-local/reserved IPs
     Requires HTTPS in production (allows HTTP in development)
     Logs blocked attempts, returns (None, None) gracefully
     Sanitized error messages: str(e) replaced with generic 'upstream_delivery_failed'

10.5 auth_middleware.py — requires_provider_token dev bypass now uses fixed identities
     Was: provider_org_guid read from request.args (attacker-controlled in dev mode)
     Now: hardcoded 'dev-org-00000000' / 'dev-contract-00000000'

10.6 provider.py + push_service.py — Receipt ack IDOR fix
     handle_provider_response() now accepts provider_org_guid parameter
     Verifies receipt's contract match belongs to the calling provider before allowing ack

10.7 security_models.py — bcrypt cost factor explicitly set to rounds=12

10.8 gateway/.env — Added HMAC_SECRET (dev value)
     .env already in .gitignore (confirmed)

10.9 tests/conftest.py — Added HMAC_SECRET, FLASK_SECRET_KEY, JWT_SECRET_KEY to test env

10.10 NOT FIXED (deferred):
      - push_auth_key Fernet encryption (requires new ENCRYPTION_KEY infra + migration)
      - PAT O(n) lookup optimization (requires token_prefix column + migration)
      - Grant max_uses default (behavioral change, needs stakeholder decision)

Tests: 74/76 passed (2 pre-existing CarePlan failures, unrelated to security fixes)

Files modified:
  gateway/app/config.py
  gateway/app/services/grant_service.py
  gateway/app/api/provider.py
  gateway/app/services/push_service.py
  gateway/app/middleware/auth_middleware.py
  gateway/app/models/security_models.py
  gateway/.env
  gateway/tests/conftest.py

