# Admin manual — request.pdhc

Audience: SU admins and clinical leads who manage users, patients, and the service-request lifecycle.

## 1) Authentication

request.pdhc gates all UI + API endpoints behind sso.pdhc. Login uses the standard SSO OAuth 2.0 + PKCE flow; the JWT lands in the Flask session and is re-validated on every request.

| Action | Surface |
|---|---|
| Login | `GET /api/v1/auth/login` → SSO redirect → `GET /api/v1/auth/callback` |
| Logout | `POST /api/v1/auth/logout` (clears session + revokes upstream refresh token if held) |

For service-to-service traffic (e.g. gateway.pdhc → request.pdhc internal endpoints), use `X-Service-Key` instead of a Bearer token. See §6.

## 2) Users

User identity is owned by sso.pdhc — request.pdhc does not store password hashes. What lives here:

- Per-user **role bindings** (e.g. `requester`, `provider-admin`, `clinical-lead`)
- Per-user **organisation associations** drawn from the SSO blob's `organization_ids`
- Audit log entries keyed on `user_guid`

To grant a new role to a user: edit their SSO record (in sso.pdhc's SU admin), then they pick up the role on next login. No request.pdhc-side action required.

## 3) Service requests

### 3.1 Lifecycle

```
draft (optional) → active → in-progress → (completed | revoked)
```

- **draft** — created but not yet routed to a provider.
- **active** — routed; appears in the provider's feed; grant token issued.
- **in-progress** — provider acknowledged + working on it.
- **completed** — provider submitted a final report; closed.
- **revoked** — withdrawn before completion.

Each state transition emits an audit row.

### 3.2 Creating a service request

```http
POST /api/v1/service-requests
Authorization: Bearer <SSO JWT>
Content-Type: application/json

{
  "subject": { "reference": "Patient/<guid>" },
  "code": { ... FHIR CodeableConcept ... },
  "occurrence": { "boundsPeriod": { "start": "...", "end": "..." } },
  "performer": [ { "reference": "Organization/<provider-org-guid>" } ],
  "based_on_contract": "Contract/<contract-guid>",
  "transactions": [
    { "concept_canonical": "https://termbank.pdhc.se/CodeSystem/loinc/4548-4",
      "requirement": "obligatory" }
  ]
}
```

**Validation gates** (all must pass before the request becomes `active`):

1. The referenced **contract must have `status: executed`** — the only state that qualifies a contract for fulfilling requests. (Contracts in `negotiable`, `terminated`, or `revoked` are rejected with 422.)
2. Every `transactions[].concept_canonical` must be in the contract's `return_scope` (obligatory_return ∪ optional_return).
3. The performer organisation must be the contract's provider party.
4. The patient must exist in request.pdhc's local cache (auto-synced from upstream).

### 3.3 Dispatch

When a service request goes `active`, request.pdhc dispatches it:

1. Mints a `DataExchangeGrant` (HMAC-signed composite key: `service_request_guid` + `patient_guid` + `provider_org_guid` + `contract_guid` + `expires_at`).
2. Pushes a FHIR Bundle to the provider's inbound endpoint OR exposes it via the provider feed (depending on `delivery_mode` on the provider's PAT).
3. Provider responds 202; request.pdhc marks the SR as `dispatched`.

If the provider doesn't ack within the timeout, request.pdhc retries with exponential backoff (5 attempts, then parks the SR and alerts ops).

### 3.4 Receiving the report

Providers POST observation/report bundles to `gateway.pdhc/api/v1/provider/report/<sr_guid>` using their PAT. Gateway validates the grant token via request.pdhc's internal endpoint (`POST /internal/grant/validate`) and forwards the report. request.pdhc updates the SR status and stores observations.

## 4) Patients

Patients are pseudonymised at the platform level (stable `patient_guid`). request.pdhc keeps a local cache of Patient resources for the SRs it manages — never the source of truth for the person, just a linkage table.

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/patients` | List patients in scope |
| `POST /api/v1/patients` | Create local cache row (auto-called by SR creation) |
| `GET /api/v1/patients/<guid>` | Patient details + their open SRs |

## 5) Care plans

Service requests can be grouped into a CarePlan. The CarePlan layer:

- Adds a longitudinal goal (e.g. "diabetes review every 6 months")
- Coordinates multiple SRs against the same patient
- Provides export and reporting at the cohort level

See `service_request_user_guide.md` (in the source repo, alongside this manual) for the clinical workflow.

## 6) Service-key auth (internal callers)

Trusted siblings call request.pdhc's `/internal/*` endpoints with the headers:

```
X-Source-Service: gateway.pdhc
X-Service-Key: <secret>
```

Known callers and their secret env-var names live in `gateway/app/auth.py:KNOWN_FHIR_SERVICES`. Adding a new caller is a code change reviewed in PR.

## 7) Audit log

Every state-changing action records `(actor_user_guid, action, resource_type, resource_guid, before, after, at)`. Visible at `GET /api/v1/audit` (admin only). Log retention: indefinite (Rule 24 / GDPR audit obligation).

---

For technical detail, see `architecture.md` and `api.md`. For procedures, see `runbooks/`.
