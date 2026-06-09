# Architecture — request.pdhc

Audience: integrators, infra reviewers, anyone tracing a request end-to-end.

## 1) What this service is

**request.pdhc** is the patient-record + service-request layer of the PDHC platform. It owns:

- Local pseudonymised patient cache.
- The `ServiceRequest` lifecycle (create → active → dispatched → completed/revoked).
- The `DataExchangeGrant` HMAC-signed composite key that lets a specific provider report on a specific SR.
- Care-plan grouping and clinical-lead reporting.
- The audit trail for every state-changing action.

It does **not** own:

- Identity (sso.pdhc).
- Contract terms (contract.pdhc).
- Inbound observation routing (gateway.pdhc).
- Terminology / canonical URIs (termbank.pdhc).

## 2) Container topology

```
                                                                
  Browser ──HTTPS──▶ nginx (miserver) ──▶ request_pdhc_app:9060 ──▶ request_pdhc_db:9061
                              │                       │
                              │                       └─▶ contract.pdhc:9021 (status check)
                              │                       └─▶ sso.pdhc:9000 (token validation)
                              │
                              └────▶ provider feed / push to provider1.pdhc, cgm.pdhc, ...
                                                              │
                                          ◀── reports via gateway.pdhc:9050 ◀──┘
```

- `request_pdhc_app` — Flask + gunicorn, in Docker.
- `request_pdhc_db` — PostgreSQL 16, in Docker, host port 9061 forwarded.
- All non-trivial cross-service calls go via `host.docker.internal` from inside Colima.

## 3) Data flow — happy path

```
Requester               request.pdhc        contract.pdhc       provider              gateway.pdhc
─────────              ─────────────       ──────────────      ──────────            ──────────────
POST /service-requests
  body: SR + contract_guid
   ─────────▶
                       validate contract
                          ─────────────────▶ GET /Contract/<guid>
                          status==executed?
                          ◀──── 200 ────────
                       persist SR (active)
                       mint DataExchangeGrant
                       push FHIR Bundle ───────────────────────▶ POST /inbound/push
                                                                  202 Accepted
                       mark dispatched
   ◀──── 201 ────────
                                                                  ... fulfill ...
                                                                POST /report/<sr_guid>
                                                                  X-Provider-Token + grant
                                                                                      ────────────▶
                                                                                      validate PAT
                                                                                      validate grant
                                                                                      ◀── /internal/grant/validate
                                                                                      enrich + persist obs
                       observation pushed back     ◀────────────────────────────────────
                       SR → completed
```

## 4) Data model

### 4.1 Patient (cached)

| Column | Type |
|---|---|
| `guid` | UUID v4 (matches upstream pseudonym) |
| `identifier` | JSONB |
| `organisation_guid` | FK to upstream org GUID (no FK constraint — sso.pdhc is the source of truth) |
| `created_at`, `updated_at` | timestamptz |

### 4.2 ServiceRequest

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `subject_patient_guid` | UUID v4 | |
| `performer_org_guid` | UUID v4 | |
| `based_on_contract_guid` | UUID v4 | required; gates SR validity |
| `status` | enum | `draft / active / in-progress / completed / revoked` |
| `transactions` | JSONB | `[{concept_canonical, requirement, value_constraints}]` |
| `occurrence_start`, `occurrence_end` | timestamptz | |
| `dispatched_at`, `completed_at`, `revoked_at` | timestamptz | |
| `revoke_reason` | text | |
| `created_at`, `updated_at` | timestamptz | |

### 4.3 DataExchangeGrant

HMAC-signed composite key allowing one provider to report on one SR.

| Column | Type | Notes |
|---|---|---|
| `grant_token` | text | HMAC-SHA256 of (SR + patient + provider_org + contract + expires_at) |
| `service_request_guid` | UUID v4 | |
| `patient_guid` | UUID v4 | |
| `provider_org_guid` | UUID v4 | |
| `contract_guid` | UUID v4 | empty string if direct delivery (no Contract) |
| `grant_type` | enum | `pull` (provider polls) / `push` (gateway delivers) |
| `expires_at` | timestamptz | |
| `uses_remaining` | int | 1 by default; bump for re-fetch / replay |

The HMAC secret (`HMAC_SECRET`) is held **only** by request.pdhc. Gateway.pdhc never sees the secret — it delegates validation to request.pdhc's `/internal/grant/validate`.

### 4.4 CarePlan

Optional grouping layer over multiple SRs (longitudinal goals, cohort reporting).

### 4.5 AuditLog

Append-only. Columns: `actor_user_guid, action, resource_type, resource_guid, before_json, after_json, at`.

#### 4.5.1 Read-side audit inventory (ticket #227, PDL Ch 4 §3)

Every GET endpoint that returns patient-identified data writes one
`AuditLog` row on success (HTTP 2xx). Failed reads (4xx / 5xx) skip
the row — the underlying access didn't happen.

| Method | URL rule | `action` | `resource_type` | Wired via |
|---|---|---|---|---|
| GET | `/api/v1/Patient` | `patient.list` | `Patient` | `@audit_read` (#227) |
| GET | `/api/v1/Patient/<guid>` | `patient.read` | `Patient` | `@audit_read` (#227) |
| GET | `/api/v1/CarePlan` | `careplan.list` | `CarePlan` | `@audit_read` (#227) |
| GET | `/api/v1/CarePlan/<guid>` | `careplan.view` | `CarePlan` | inline `log_event` (pre-#227) |
| GET | `/api/v1/ServiceRequest` | `service_request.list` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/ServiceRequest/<guid>` | `service_request.read` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/ServiceRequest/<guid>/matches` | `service_request.matches.list` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/ServiceRequest/<guid>/receipts` | `service_request.receipts.list` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/ServiceRequest/<guid>/forms` | `service_request.forms.list` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/ServiceRequest/receipt/<token>` | `service_request.receipt.read` | `ServiceRequestReceipt` | `@audit_read` (#227) |
| GET | `/api/v1/requests` | `request.list` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/requests/<guid>` | `request.read` | `ServiceRequest` | `@audit_read` (#227) |
| GET | `/api/v1/provider/feed` | `feed.accessed` | (none — metadata only) | inline `log_event` |

Catalogue / metadata reads that don't carry patient identifiers
(`/Form`, `/PlanDefinition`, `/Contract`, `/providers`, `/metadata`,
`/admin/provider-tokens`, `/docs/*`, `/api`) are intentionally
out of scope — no patient-shaped data crosses them.

Authoring routes (POST / PUT / DELETE) already write inline
`log_event` rows with the matching action prefixes (`patient.create`,
`service_request.create.requested`, etc.).

##### Adding new read endpoints

When you add a new GET that returns patient-identified data, decorate
it with `@audit_read('<action>', resource_type='<Type>',
guid_arg='<view_arg>')` from `app.services.audit_service`. The
decorator writes one audit row on 2xx, no row on 4xx/5xx, and
swallows internal failures so a flaky audit table can't break the
response.

## 5) Security

### 5.1 Auth

- **Public surface**: SSO Bearer JWT, validated on every request (no client-side caching).
- **Internal surface**: `X-Source-Service` + `X-Service-Key` pair, validated against `KNOWN_FHIR_SERVICES` config.
- **Provider surface**: `X-Provider-Token` (PAT) — opaque bearer issued by request.pdhc's PAT service, bound to (provider_org_guid, contract_guid).

### 5.2 Validation chain (defense in depth)

For a provider report submission via gateway.pdhc:

1. PAT validates provider identity → derives `organisation_guid`.
2. Grant token validated (request.pdhc) → returns `contract_guid`, `grant_type`.
3. SR context fetched (request.pdhc) → transactions, patient, goals.
4. Patient cross-check — body's `patient_guid` must match SR subject.
5. Concept enrichment — `concept_guid`/`unit` derived from SR transaction map.
6. Range check — observation values vs transaction definitions.
7. Contract scope enforcement — concepts vs `Contract.return_scope`.
8. Grant use recorded for audit.

Any failure aborts the chain with 4xx + `OperationOutcome`.

### 5.3 Data minimisation

The provider feed (`GET /provider/feed`) returns SR metadata only — no patient data. The full Bundle is delivered only after the provider downloads it (creating a Grant) or on a push, both of which are audited.

## 6) Operational dependencies

| Dependency | Purpose | Failure mode |
|---|---|---|
| sso.pdhc | JWT validation, login | All UI + API auth fails (503 on health). |
| contract.pdhc | Contract status + return_scope lookup | New SR creation fails with 422 `contract_unavailable`. Existing SRs unaffected. |
| termbank.pdhc | Canonical concept URIs (read-only) | Optional — concept lookup degrades to "unverified" but doesn't block. |
| gateway.pdhc | Inbound provider reports | Reports queue up at gateway side; request.pdhc only sees the relayed call. |

## 7) Why this split

- **Identity** in sso.pdhc → one login authority, easier compliance.
- **Contract** in contract.pdhc → governance boundary; legal review can iterate on contract template without touching SR code.
- **Gateway** in gateway.pdhc → single ingestion choke-point for all provider traffic; rate limiting / abuse detection lives there.
- **Termbank** in termbank.pdhc → terminology releases (LOINC / SNOMED / ATC) update on a different cadence than service code.

`request.pdhc` is the orchestrator that ties them together for the clinical-lead UX.
