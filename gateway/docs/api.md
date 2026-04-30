# API reference — request.pdhc

All endpoints under `https://request.pdhc.se`. Public surface uses Bearer JWT from sso.pdhc; internal surface uses `X-Service-Key`.

## 1) Conventions

- All bodies are JSON unless noted.
- Dates are ISO-8601 with explicit timezone (`Z` or `+HH:MM`).
- All cross-resource references use **GUIDs** (Rule 18) — never integer IDs.
- HTTP status codes follow REST + FHIR `OperationOutcome` semantics:
  - `200` / `201` — success.
  - `400` — malformed body.
  - `401` — missing / invalid auth.
  - `403` — wrong role / scope / contract not active.
  - `404` — resource not found.
  - `409` — duplicate / state conflict.
  - `422` — schema valid, business rule violated (e.g. obligatory concept missing).

## 2) Authentication

### `GET /api/v1/auth/login`

Public. Redirects to sso.pdhc OAuth 2.0 authorise endpoint with PKCE. After SSO success, the user lands on `/api/v1/auth/callback` which sets the session cookie.

### `POST /api/v1/auth/logout`

Auth required. Clears the Flask session and (if held) revokes the SSO refresh token.

## 3) Health

### `GET /api/health`

Public. Returns:

```json
{ "status": "ok", "service": "request.pdhc", "database": "connected", "auth_mode": "sso" }
```

`status: degraded` and HTTP 503 if the DB probe (`SELECT 1`) fails.

## 4) Patients

### `GET /api/v1/patients`

Auth required. Lists patients in the caller's organisation scope.

### `GET /api/v1/patients/<guid>`

Auth required. Returns the patient + their open service requests.

### `POST /api/v1/patients`

Auth required, role `clinical-lead` or `requester`. Creates the local cache row for an externally-known patient.

```json
{
  "guid": "<patient_guid>",
  "identifier": [{ "system": "https://sim.pdhc.se/CodeSystem/synthetic", "value": "..." }],
  "organisation_guid": "<org_guid>"
}
```

## 5) Service requests

### `GET /api/v1/service-requests`

Auth required. List of SRs visible to the caller (filtered by org scope). Query params: `status`, `patient_guid`, `provider_org_guid`, `since`, `until`.

### `GET /api/v1/service-requests/<guid>`

Auth required. Full SR plus its dispatch status, grant tokens issued, and any reports received.

### `POST /api/v1/service-requests`

Auth required, role `requester`. Creates a new SR. See `admin-manual.md §3.2` for required fields and validation rules.

**Validation errors** (422):

| Issue | Cause |
|---|---|
| `contract_not_active` | The referenced `Contract.status != "executed"`. |
| `concept_out_of_scope` | A `transactions[].concept_canonical` not in the contract's return_scope. |
| `provider_mismatch` | The performer org isn't the contract's provider party. |
| `patient_not_cached` | The subject patient hasn't been created locally yet. |

### `PATCH /api/v1/service-requests/<guid>`

Auth required, role `requester`. Mutate SR status: `revoke`, `complete`, etc. Some transitions require a reason; `revoke` writes a `revoke_reason` to the audit row.

## 6) Dispatch

### `POST /api/v1/dispatch`

Auth required, role `clinical-lead`. Force-dispatches an SR (normal flow auto-dispatches on creation). Useful for retries after a provider was offline.

### `GET /api/v1/dispatch/status`

Auth required. Returns dispatch counters: queued, in-flight, succeeded, failed, retrying.

## 7) Provider feed (PAT-authenticated)

These endpoints are called by **providers**, not by the SSU operator UI. Auth header is `X-Provider-Token: <PAT>`, not the SSO Bearer.

### `GET /api/v1/provider/feed`

Lists SRs addressed to this provider (metadata only — no patient data — GDPR data-minimisation).

### `GET /api/v1/provider/download/<sr_guid>`

Returns the full FHIR Bundle for one SR. Issues a fresh `DataExchangeGrant` if none exists.

### `POST /api/v1/provider/receipt/<token>/ack`

Acknowledges a push-mode delivery. Body: optional `{ "received_at": "...", "actor": "..." }`.

For the provider's outbound report submission, see **gateway.pdhc** (`POST /api/v1/provider/report/<sr_guid>`) — that endpoint relays through gateway, not directly to request.pdhc.

## 8) Internal — gateway-to-request

Service-key auth (`X-Service-Key: <gateway secret>`). These endpoints are not for human or provider use.

### `POST /internal/grant/validate`

Body: `{ "grant_token": "<HMAC>" }`. Returns:

```json
{
  "valid": true,
  "service_request_guid": "...",
  "patient_guid": "...",
  "provider_org_guid": "...",
  "contract_guid": "...",
  "grant_type": "pull|push",
  "uses_remaining": 1
}
```

### `GET /internal/service-request/<guid>/context`

Returns the pre-extracted SR context (transactions, goals, patient_guid, contract_guid) so gateway can enrich incoming observations without re-reading the SR.

## 9) Care plans

### `GET /api/v1/careplans`

Auth required. List care plans + their nested service requests.

### `POST /api/v1/careplans`

Role `clinical-lead`. Create a CarePlan grouping multiple SRs.

## 10) Export

### `GET /api/v1/export/csv?careplan=<guid>`

Auth required. Streams the SRs + their observations as CSV. Useful for clinical-lead reporting.

---

For wire shapes of FHIR Contract references and the contract-status gate, see [contract.pdhc/api.md](https://contract.pdhc.se/docs/api.md).
