# API reference — request.pdhc

Base URL: `https://request.pdhc.se` (production) / `http://127.0.0.1:9060` (local dev).

The HTTP surface follows FHIR-resource naming for first-class resources
(`/Patient`, `/ServiceRequest`, `/CarePlan`, `/PlanDefinition`, `/Form`,
`/Contract`) and a small set of operational endpoints
(`/health`, `/metadata`, `/admin/...`, `/internal/...`,
`/provider/...`).

All API routes (except `/api/health`) are under `/api/v1`.

## 1) Conventions

- All bodies are JSON unless noted.
- Dates are ISO-8601 with explicit timezone (`Z` or `+HH:MM`).
- All cross-resource references use **GUIDs** (Rule 18) — never integer IDs.
- HTTP status codes:
  - `200` / `201` — success.
  - `400` — malformed body / missing required field.
  - `401` — missing / invalid auth.
  - `403` — wrong role / scope / org mismatch.
  - `404` — resource not found.
  - `409` — duplicate / state conflict.
  - `422` — schema valid, business rule violated.

## 2) Authentication

Three credential modes; each blueprint accepts exactly one.

| Mode | Header | Used by |
|------|--------|---------|
| **SSO Bearer (session)** | session cookie set by `/auth/callback` | Browser UI + SSO-authenticated JSON callers |
| **Provider Access Token (PAT)** | `X-Provider-Token: <PAT>` | Sibling provider services pulling a feed / submitting reports |
| **Internal service-key** | `X-Service-Key: <secret>` | gateway.pdhc, contract.pdhc, sso.pdhc — never exposed publicly |

### `GET /api/v1/auth/login`

Public. Redirects to sso.pdhc OAuth 2.0 authorise endpoint with PKCE.

### `GET /api/v1/auth/callback`

Public. Receives the SSO redirect, exchanges code for tokens, sets session cookie.

### `POST /api/v1/auth/logout`

Auth required. Clears Flask session and revokes the SSO refresh token if held.

### `GET /api/v1/auth/me`

Auth required. Returns the current user's SSO blob (`user_guid`, `email`,
`organization_ids`, `is_su_admin`, role bindings).

## 3) Health and capability

### `GET /api/health`

Public. CORS-enabled for `https://www.pdhc.se` so the platform status page
can read the JSON body.

```json
{ "status": "ok", "service": "request.pdhc", "database": "connected" }
```

`status: degraded` and HTTP 503 if the DB probe (`SELECT 1`) fails.

### `GET /api/v1/metadata`

Public. FHIR R5 CapabilityStatement describing supported resources +
operations.

## 4) Patient

Local pseudonymised cache of patients known to this org. The full patient
record lives in ips.pdhc; we only persist the GUID, identifier, and the
organisation scope.

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/Patient` | any | List/search (proxies to ips.pdhc, org-filtered) |
| GET | `/api/v1/Patient/<guid>` | any | Read one |
| POST | `/api/v1/Patient` | `read_write` | Create cache entry |
| PUT | `/api/v1/Patient/<guid>` | `read_write` | Update cache entry |
| DELETE | `/api/v1/Patient/<guid>` | `read_write` | Remove cache entry |

## 5) ServiceRequest

The state-machine heart of request.pdhc.

### 5.1 Lifecycle

```
draft  ──finalize──▶  active  ──push──▶  in-flight  ──respond──▶  completed
   │                    │
   ├─── revoke ────────▶ revoked
   └─── archive ──────▶ archived
```

`draft → active` requires the referenced `Contract.status == "executed"`
(see contract.pdhc admin-manual §3 for the contract status enum).

### 5.2 Endpoints

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/ServiceRequest` | any | List (org-filtered for non-SU). Query: `status`, `page`, `per_page` |
| POST | `/api/v1/ServiceRequest` | `read_write` | Create draft. Body: `patient_guid`, `plan_definition_guid`, optional `contract_guid`, `notes` |
| GET | `/api/v1/ServiceRequest/<guid>` | any | Read one |
| PUT | `/api/v1/ServiceRequest/<guid>/snapshot` | `read_write` | Update PlanDefinition snapshot (draft only) |
| POST | `/api/v1/ServiceRequest/<guid>/finalize` | `read_write` | Build FHIR Bundle, transition to active |
| POST | `/api/v1/ServiceRequest/<guid>/archive` | `read_write` | Archive |
| POST | `/api/v1/ServiceRequest/<guid>/revoke` | `read_write` | Revoke (writes `revoke_reason` to audit) |
| POST | `/api/v1/ServiceRequest/auto-archive` | `read_write` | Bulk-archive completed SRs older than threshold |
| GET | `/api/v1/ServiceRequest/<guid>/matches` | any | List candidate provider orgs for this SR |
| POST | `/api/v1/ServiceRequest/<guid>/match` | `read_write` | Assign a provider match |
| POST | `/api/v1/ServiceRequest/<guid>/push` | `read_write` | Push to all matched providers |
| POST | `/api/v1/ServiceRequest/<guid>/push/<match_guid>` | `read_write` | Push to one specific match |
| GET | `/api/v1/ServiceRequest/<guid>/receipts` | any | List dispatch receipts for this SR |
| GET | `/api/v1/ServiceRequest/receipt/<token>` | any | Read one receipt by its token |
| POST | `/api/v1/ServiceRequest/receipt/<token>/respond` | `read_write` | Provider response inbound |
| GET | `/api/v1/ServiceRequest/<guid>/forms` | any | List forms attached to this SR |
| POST | `/api/v1/ServiceRequest/<guid>/forms` | `read_write` | Attach a form |
| DELETE | `/api/v1/ServiceRequest/<guid>/forms/<form_sr_guid>` | `read_write` | Detach a form |
| POST | `/api/v1/ServiceRequest/<guid>/forms/reorder` | `read_write` | Reorder attached forms |

### 5.3 Validation errors (422)

| `code` | Cause |
|--------|-------|
| `contract_not_active` | Referenced contract has `status != "executed"` |
| `concept_out_of_scope` | A `transactions[].concept_canonical` not in the contract's return_scope |
| `provider_mismatch` | Performer org isn't the contract's provider party |
| `patient_not_cached` | Subject patient hasn't been cached locally yet |

## 6) Form, PlanDefinition, Contract (read-only proxies)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/Form` | List forms |
| GET | `/api/v1/Form/<guid>` | Read one form |
| GET | `/api/v1/PlanDefinition` | List plan-definitions known to this gateway |
| GET | `/api/v1/Contract` | List contracts (auth-filtered; full source in contract.pdhc) |

## 7) CarePlan

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/CarePlan` | any | List care plans (org-filtered) |
| GET | `/api/v1/CarePlan/<guid>` | any | Full care plan + nested SRs |
| POST | `/api/v1/CarePlan/<guid>/dispatch` | `clinical-lead` | Force-dispatch all SRs in this care plan |
| GET | `/api/v1/CarePlan/<guid>/dispatch/<receipt_token>` | any | Read a single dispatch receipt by token |

## 8) Export

| Method | Path | Role | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/CarePlan/<guid>/export/preview` | any | Preview rows (no download) |
| POST | `/api/v1/CarePlan/<guid>/export/csv` | `read_write` | Stream CSV (clinical-lead reporting) |

## 9) Requests (queue / reporting)

Lightweight read-only listing that joins ServiceRequest + dispatch
state for the UI's "Requests" tab.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/requests` | List with status + dispatch summary |
| GET | `/api/v1/requests/<guid>` | One row, expanded |
| PUT | `/api/v1/requests/<guid>/status` | Mutate status (limited transitions) |

## 10) Provider feed (PAT-authenticated)

Called by **providers**, not by the SSU operator UI.
Auth header: `X-Provider-Token: <PAT>` — never the SSO Bearer.

### `GET /api/v1/provider/feed`

Lists SRs addressed to this provider — **metadata only**, no patient data
(GDPR data minimisation). Query params: `since`, `limit` (max 200).

### `GET /api/v1/provider/download/<sr_guid>`

Returns the full FHIR Bundle for one SR. Issues a fresh
`DataExchangeGrant` if none exists.

### `POST /api/v1/provider/status/<sr_guid>`

Submit a ServiceRequest **lifecycle status update** (acknowledged /
in-progress / completed). Required body fields: `patient_guid`,
`organisation_guid`, `grant_token`, `contract_guid`, plus optional
`status` (default `completed`) and `report_payload`. Returns 403
if `organisation_guid` doesn't match the PAT's provider.

**Not for observation data.** Any `report_payload` sent here is
stored on the contract-match for audit only — it does NOT reach
`inbound_observations`. For observation data, POST to
`gateway.pdhc/api/v1/provider/report/<sr_guid>` instead.

### `POST /api/v1/provider/report/<sr_guid>` — *deprecated alias*

Deprecated alias for `/api/v1/provider/status/<sr_guid>` — same
behaviour, logs a `report.deprecated_alias_used` audit event. Kept
so existing integrations don't break. New integrations should use
`/provider/status` here and `/provider/report` on **gateway.pdhc**
for actual observations.

### `POST /api/v1/provider/validate-token`

Public — the token *is* the credential. Called by gateway.pdhc to
resolve a raw PAT into provider identity (org_guid, contract_guid,
delivery_mode, push_endpoint_url, push_auth_key).

### `POST /api/v1/provider/receipt/<token>/ack`

Acknowledges a push-mode delivery receipt.

## 11) Providers (directory)

### `GET /api/v1/providers`

Lists provider organisations registered with this gateway. SU-admin
unrestricted; non-SU sees only providers their org has contracts with.

## 12) Admin — provider tokens

SU-admin or org-admin only.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/admin/provider-tokens` | Issue new PAT |
| GET | `/api/v1/admin/provider-tokens` | List PATs (filter by provider/contract) |
| DELETE | `/api/v1/admin/provider-tokens/<guid>` | Revoke a PAT |

## 13) Internal — service-to-service

Service-key auth only (`X-Service-Key`). Never exposed externally.

### `GET /api/v1/internal/service-request/<sr_guid>/context`

Returns the pre-extracted SR context (transactions, goals, patient_guid,
contract_guid) so gateway.pdhc can enrich incoming observations without
re-reading the SR.

### `POST /api/v1/internal/grant/validate`

Body: `{ "sr_guid", "org_guid", "patient_guid", "grant_token",
"contract_guid"? }`. Returns:

```json
{
  "valid": true,
  "contract_guid": "...",
  "grant_type": "pull|push",
  "uses_remaining": 1
}
```

Used by gateway.pdhc to validate inbound observations without ever
holding `HMAC_SECRET` itself.

### `POST /api/v1/internal/auto-provision-pat`

Called by contract.pdhc when a contract is created/updated; provisions
a PAT for the provider org if one doesn't already exist.
Required body: `provider_org_guid`, `contract_guid`. Pulls push-config
from sso.pdhc and decides delivery_mode (push vs poll) accordingly.

---

For the wire shapes of FHIR Contract references and the contract-status
gate, see [contract.pdhc/api.md](https://contract.pdhc.se/docs/download/api.md).
For terminology canonical URIs, see
[termbank.pdhc/fhir/metadata](https://termbank.pdhc.se/fhir/metadata).
