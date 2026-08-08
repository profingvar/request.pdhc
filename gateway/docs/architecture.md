# Architecture — request.pdhc

Audience: integrators, infra reviewers, anyone tracing a request end-to-end.

## 1) What this service is

**request.pdhc** is the ServiceRequest + care-plan orchestration layer of the
PDHC platform. It turns a clinician's intent — "collect these measurements for
this patient under this contract" — into a durable, auditable
`ServiceRequest`, matches it to providers, and brokers the credentials a
provider needs to report back. It owns:

- The `ServiceRequest` lifecycle. An SR is a **PlanDefinition snapshot for a
  patient**: it captures the patient excerpt, the edited PlanDefinition (and
  optionally the CarePlan) at create time so later template edits never
  silently mutate an issued request.
- `CarePlan` — the patient-specific instance of a PlanDefinition (since #310).
- Provider matching + delivery: `ServiceRequestContractMatch`,
  `ServiceRequestReceipt`, and the outbound webhook subsystem.
- `ProviderAccessToken` (PAT) issuance and the `DataExchangeGrant` HMAC-signed
  composite key that lets a specific provider report on a specific SR.
- `DispatchRequest` — forwarding a PlanDefinition to a provider via plan.pdhc.
- The audit trail (`AuditLog`) for every state-changing action **and** every
  patient-identified read.

It does **not** own:

- **Identity** (sso.pdhc).
- **The patient registry** — patients live in **ips.pdhc**. request.pdhc holds
  **no `Patient` table**; it *proxies* IPS via `patient_service.py`
  (`IPS_BASE_URL`) and stores only a JSON `patient_excerpt` snapshot on the SR.
- **Contract terms** (contract.pdhc).
- **PlanDefinition / CarePlan templates authoring** (plan.pdhc — request.pdhc
  snapshots them).
- **Inbound observation routing** (gateway.pdhc).
- **Terminology / canonical URIs** (termbank.pdhc).

## 2) Container topology

Three containers in the `request` compose project (`docker-compose.yml`):

```
                                                                
  Browser ──HTTPS──▶ nginx (miserver) ──▶ request_pdhc_app:9060 ──▶ request_pdhc_db:9061
                              │                       │
                              │                       ├─▶ ips.pdhc        (patient proxy + consent)
                              │                       ├─▶ plan.pdhc:9030  (PlanDefinition dispatch)
                              │                       ├─▶ contract.pdhc:9021 (status check)
                              │                       └─▶ sso.pdhc:9000   (token validation)
                              │
  request_pdhc_worker ──▶ outbound webhooks ──▶ provider webhook URLs (1177.pdhc, cgm.pdhc, ...)
   (flask webhook run-worker)
```

- **`request_pdhc_app`** — Flask + gunicorn (2 workers, port 9060). Runs
  `flask db upgrade` on start via `entrypoint.sh`. Loopback-bound
  `127.0.0.1:9060`.
- **`request_pdhc_db`** — PostgreSQL 16-alpine. DB user `request_admin`,
  database `request_pdhc`. Loopback-bound `127.0.0.1:9061 → 5432`. Named
  external volume `request_pdhc_pgdata`.
- **`request_pdhc_worker`** — same image/env as the app, but its entrypoint is
  overridden to `flask webhook run-worker --interval 5`. It runs **no
  migrations and binds no port**; it just ticks the outbound
  `WebhookDelivery` queue (backoff + dead-letter, see §5.4). `restart:
  unless-stopped`, depends on both `db` (healthy) and `app` (healthy).

All cross-service HTTP uses the `*_BASE_URL` config values
(`IPS_BASE_URL`, `PLAN_BASE_URL`, `CONTRACT_BASE_URL`, `SSO_BASE_URL`); on the
macmini these resolve through nginx / `host.docker.internal`.

## 3) Data flow — happy path

```
Requester            request.pdhc          plan/contract/ips        provider           gateway.pdhc
─────────           ─────────────         ─────────────────       ──────────         ──────────────
POST /ServiceRequest
  body: patient_guid,
  plan_definition_guid,
  contract_guid ─────▶
                     fetch patient excerpt (ips)
                     snapshot PlanDefinition (plan)
                     validate contract (contract)
                     persist SR (+ forms)
                     match to providers ──────────────────────────────────────────────────────────
                     enqueue webhook  ─── worker ──────────────▶ POST provider webhook URL
                                                                  (metadata only + download_url)
                     mint DataExchangeGrant
   ◀── 201 ──────────
                                          provider pulls bundle ◀─ GET /provider/download/<sr>
                                                                  (issues/returns grant_token)
                                                                  ... fulfils ...
                                                                POST report ─────────▶ /api/v1/provider/report/<sr>
                                                                  X-Provider-Token + grant
                                                                                      validate PAT ─┐
                                                                                      validate grant│
                                                                        ◀─ /api/v1/internal/grant/validate
                                                                                      enrich + persist obs
```

Note the deliberate split: **observation data** is POSTed to
**gateway.pdhc** `/api/v1/provider/report/<sr>` (which writes inbound
observations after full validation). request.pdhc's own
`/api/v1/provider/status/<sr>` (and its deprecated `/provider/report/<sr>`
alias) record only **SR lifecycle state** on the contract-match — a payload
sent there never reaches inbound observations (see `provider.py`).

## 4) Data model

13 tables. Cross-service references are stored as **GUID strings**, never
enforced FKs — the owning service (sso / ips / plan / contract) is the source
of truth (Rule 18). Verified against the model files under `app/models/`.

### 4.1 There is no Patient table

Patients live in **ips.pdhc**. `app/services/patient_service.py` proxies
`GET/POST/PUT/DELETE {IPS_BASE_URL}/fhir/Patient[...]` and
`{IPS_BASE_URL}/api/v1/patients/<guid>/clinics` (need-to-know check). The only
patient data at rest here is the JSON `patient_excerpt` captured onto a
`ServiceRequest` at create time.

### 4.2 ServiceRequest (`service_requests`)

FHIR R5 ServiceRequest — a patient excerpt + an edited **PlanDefinition
snapshot**.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `status` | str(30) | default `draft` |
| `intent` | str(20) | default `order` |
| `priority` | str(20) | default `routine` |
| `patient_guid` | UUID v4 | indexed; references ips.pdhc |
| `patient_excerpt` | JSON | snapshot pulled from IPS at create |
| `plan_definition_guid` | UUID v4 | references plan.pdhc |
| `plan_definition_snapshot` | JSON | frozen template — later edits don't leak in |
| `care_plan_guid` | UUID v4, nullable | since #310; NULL for legacy/direct SRs |
| `fhir_resource` | JSON | assembled FHIR R5 ServiceRequest |
| `contract_guid` | UUID v4, nullable | indexed |
| `requester_user_guid` | UUID v4 | required |
| `requester_user_name` | str(255), nullable | |
| `requester_org_guid` | UUID v4, nullable | indexed (canonical alias `requesting_org_guid` in `to_dict`, #294) |
| `requester_org_name` | str(255), nullable | (alias `requesting_org_name`) |
| `notes` | text | |
| `period_start`, `period_end` | datetime, nullable | validity period |
| `created_at`, `updated_at` | datetime | |

Relationships: `contract_matches` → `ServiceRequestContractMatch`; `forms` →
`ServiceRequestForm` (ordered by `sort_order`).

### 4.3 ServiceRequestForm (`service_request_forms`)

Links an SR to one or more forms from the Plan catalogue. Unique on
`(service_request_guid, form_guid)`.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `service_request_guid` | UUID v4 | FK → `service_requests.guid` |
| `form_guid` | UUID v4 | references plan.pdhc form |
| `form_version` | str(50), nullable | |
| `form_snapshot`, `render_ready_snapshot` | JSON | |
| `display_title` | str(255), nullable | |
| `sort_order` | int | default 0 |
| `created_at`, `updated_at` | datetime | |

### 4.4 ServiceRequestContractMatch (`service_request_contract_matches`)

Links an SR to a matching contract/provider.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `service_request_guid` | UUID v4 | FK → `service_requests.guid` |
| `contract_guid` | UUID v4 | |
| `provider_org_guid` | UUID v4 | indexed |
| `provider_name` | str(255), nullable | |
| `match_type` | str(20) | `offer` \| `push`, default `offer` |
| `status` | str(30) | default `pending` |
| `sent_at`, `response_at` | datetime, nullable | |
| `response_payload` | JSON | |
| `created_at`, `updated_at` | datetime | |

Relationship: `receipts` → `ServiceRequestReceipt`.

### 4.5 ServiceRequestReceipt (`service_request_receipts`)

Delivery receipt for a pushed SR.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `service_request_guid` | UUID v4 | FK → `service_requests.guid` |
| `contract_match_guid` | UUID v4 | FK → `service_request_contract_matches.guid` |
| `receipt_token` | str(255) | unique |
| `delivery_method` | str(20) | default `push` |
| `delivery_status` | str(30) | default `pending` |
| `delivery_payload`, `response_payload` | JSON | |
| `response_received` | bool | default `false` |
| `created_at` | datetime | |

### 4.6 CarePlan (`care_plans`)

FHIR R5 CarePlan — the patient-specific instance of a PlanDefinition (since
#310). Observations reference a CarePlan via `basedOn[]`; the chain
`Observation → CarePlan → PlanDefinition → Transaction → Concept` is the
canonical provenance.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | (canonical alias `care_plan_guid` in `to_dict`) |
| `patient_guid` | UUID v4 | indexed |
| `plan_definition_guid` | UUID v4 | indexed |
| `status` | str(20) | FHIR CarePlan.status, default `draft` |
| `intent` | str(20) | FHIR CarePlan.intent, default `plan` |
| `title`, `description` | str/text, nullable | |
| `period_start`, `period_end` | timestamptz, nullable | |
| `plan_definition_snapshot` | JSON | frozen template at create |
| `goals` | JSON | list of `{concept_guid, target_value, target_comparator, description}` |
| `care_team_user_guids` | JSON | list of user guids |
| `created_by_user_guid` | UUID v4, nullable | |
| `created_at`, `updated_at` | timestamptz | |

### 4.7 DispatchRequest (`dispatch_requests`)

A request to forward a PlanDefinition to a provider via plan.pdhc.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `plan_definition_guid` | UUID v4 | renamed from `careplan_guid` in #318; `to_dict` still emits the legacy alias |
| `provider_guid` | UUID v4 | indexed |
| `assigned_user_guid` | UUID v4, nullable | |
| `dispatch_notes` | text | |
| `status` | str(20) | `pending` → `submitted` \| `failed` |
| `idempotency_key` | str(255) | unique — replays return the existing receipt |
| `provider_status` | str(50), nullable | provider-reported status |
| `provider_status_updated_at` | datetime, nullable | |
| `created_at`, `updated_at` | datetime | |

Relationship: `receipts` → `DispatchReceipt`.

### 4.8 DispatchReceipt (`dispatch_receipts`)

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `dispatch_request_guid` | UUID v4 | FK → `dispatch_requests.guid` |
| `receipt_token` | str(255) | unique |
| `status` | str(20) | `accepted` \| `error`, default `accepted` |
| `response_payload` | JSON | upstream body |
| `created_at` | datetime | |

### 4.9 ProviderAccessToken — PAT (`provider_access_tokens`)

Binds a **bcrypt-hashed** API token to a provider org + contract. Three-state
lifecycle (#136): `active` / `deprecated` / `revoked`, with a rotation grace
window (`PAT_DEPRECATED_GRACE_DAYS`, default 14) during which a deprecated
token is still accepted.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `token_hash` | str(255) | bcrypt (12 rounds); raw token shown once at issue |
| `provider_org_guid` | UUID v4 | indexed |
| `contract_guid` | UUID v4 | indexed |
| `scopes` | str(255) | comma list, default `read` |
| `delivery_mode` | str(20) | `push` \| `poll`, default `poll` |
| `push_endpoint_url` | str(512), nullable | provider's inbound URL |
| `push_auth_key_encrypted` | str(512), nullable | Fernet-encrypted (#151) |
| `expires_at` | datetime | |
| `revoked` | bool | legacy flag, still honoured |
| `revoked_at` | datetime, nullable | |
| `status` | str(20) | `active`/`deprecated`/`revoked`, indexed |
| `deprecated_at` | datetime, nullable | grace clock start |
| `rotated_to_guid` | UUID v4, nullable | successor PAT |
| `created_by_user_guid` | UUID v4 | |
| `created_at` | datetime | |

### 4.10 DataExchangeGrant (`data_exchange_grants`)

HMAC-signed composite key authorizing data exchange for **one**
ServiceRequest. The HMAC secret (`HMAC_SECRET`) is held **only** by
request.pdhc; gateway.pdhc never sees it and delegates validation to
`/api/v1/internal/grant/validate`.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `service_request_guid` | UUID v4 | FK → `service_requests.guid` |
| `patient_guid` | UUID v4 | indexed |
| `provider_org_guid` | UUID v4 | indexed |
| `contract_guid` | UUID v4 | |
| `grant_token` | str(128) | HMAC token |
| `grant_type` | str(20) | `download` \| `upload` \| `bidirectional` (default `bidirectional`) |
| `expires_at` | datetime | |
| `used_count` | int | default 0 (incremented on each use) |
| `max_uses` | int, nullable | **NULL = unlimited** |
| `revoked` | bool | |
| `created_at` | datetime | |

`is_valid()` fails on revoked, expired, or `max_uses` reached. The internal
validate endpoint derives `uses_remaining = max_uses - used_count` (or `null`
when unlimited) for the caller's convenience.

### 4.11 WebhookSigningSecret (`webhook_signing_secrets`)

Per-provider-org HMAC key for signing outbound webhook bodies (#136). Secret
is **Fernet-encrypted** (`WEBHOOK_SECRETS_KEY`) at rest. Same three-state
lifecycle as PATs: **only `active` signs new bodies**; `active` +
grace-period `deprecated` are accepted for verification.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `provider_org_guid` | UUID v4 | indexed |
| `secret_encrypted` | text | Fernet ciphertext |
| `status` | str(20) | `active`/`deprecated`/`revoked`, indexed |
| `issued_at`, `deprecated_at`, `revoked_at` | datetime | |
| `rotated_to_guid` | UUID v4, nullable | |
| `created_by_user_guid` | UUID v4 | |

### 4.12 WebhookDelivery (`webhook_deliveries`)

One scheduled outbound webhook (#140). Payload is **metadata only, never
PHI** — the body carries a `download_url`, and the provider pulls the FHIR
Bundle from the authenticated download endpoint. Lifecycle: `pending →
in_flight → (succeeded | dead_letter)`.

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `event_id` | UUID v4 | unique; sent as `X-PDHC-Event-Id` |
| `event_type` | str(64) | e.g. `service_request.dispatched` |
| `provider_org_guid` | UUID v4 | indexed |
| `service_request_guid` | UUID v4, nullable | indexed |
| `webhook_url` | str(1024) | provider endpoint |
| `payload_json` | text | exact signed body |
| `signature` | str(128), nullable | `sha256=<hex>`, sent as `X-PDHC-Signature` |
| `signing_secret_guid` | UUID v4, nullable | which secret signed it |
| `attempt_count` | int | |
| `next_attempt_at` | datetime | indexed; drives the due query |
| `status` | str(20) | `pending`/`in_flight`/`succeeded`/`dead_letter`, indexed |
| `last_response_code` | int, nullable | |
| `last_response_body_excerpt` | str(1024), nullable | |
| `last_error` | str(512), nullable | |
| `last_attempt_at`, `succeeded_at` | datetime, nullable | |
| `created_at` | datetime | |

### 4.13 AuditLog (`audit_logs`)

Append-only. Written for every state-changing action **and** every
patient-identified read (see §4.13.1).

| Column | Type | Notes |
|---|---|---|
| `guid` | UUID v4 | |
| `correlation_id` | str(255), nullable | request/session correlation |
| `user_guid` | UUID v4, nullable | actor |
| `action` | str(100) | e.g. `service_request.create.requested`, `feed.accessed` |
| `resource_type` | str(50), nullable | e.g. `ServiceRequest`, `WebhookDelivery` |
| `resource_guid` | UUID v4, nullable | |
| `details` | JSON | free-form context |
| `ip_address` | str(45), nullable | |
| `data_subject_guid` | UUID v4, nullable | indexed — the patient the row is about |
| `created_at` | datetime | |

#### 4.13.1 Read-side audit inventory (ticket #227, PDL Ch 4 §3)

Every GET endpoint that returns patient-identified data writes one `AuditLog`
row on success (HTTP 2xx). Failed reads (4xx / 5xx) skip the row — the
underlying access didn't happen. Wired via the `@audit_read(...)` decorator
from `app.services.audit_service` (or inline `log_event` for a few
pre-#227 routes).

| Method | URL rule (`/api/v1` prefix) | `action` | `resource_type` |
|---|---|---|---|
| GET | `/Patient` | `patient.list` | `Patient` |
| GET | `/Patient/<guid>` | `patient.read` | `Patient` |
| GET | `/CarePlan` | `careplan.list` | `CarePlan` |
| GET | `/CarePlan/<guid>` | `careplan.view` | `CarePlan` |
| GET | `/ServiceRequest` | `service_request.list` | `ServiceRequest` |
| GET | `/ServiceRequest/<guid>` | `service_request.read` | `ServiceRequest` |
| GET | `/ServiceRequest/<guid>/matches` | `service_request.matches.list` | `ServiceRequest` |
| GET | `/ServiceRequest/<guid>/receipts` | `service_request.receipts.list` | `ServiceRequest` |
| GET | `/ServiceRequest/<guid>/forms` | `service_request.forms.list` | `ServiceRequest` |
| GET | `/ServiceRequest/receipt/<token>` | `service_request.receipt.read` | `ServiceRequestReceipt` |
| GET | `/requests` | `request.list` | `ServiceRequest` |
| GET | `/requests/<guid>` | `request.read` | `ServiceRequest` |
| GET | `/provider/feed` | `feed.accessed` | (metadata only) |

Catalogue / metadata reads that carry no patient identifiers (`/Form`,
`/PlanDefinition`, `/Contract`, `/providers`, `/metadata`,
`/admin/provider-tokens`, `/docs/*`, `/api`) are intentionally out of scope.
Authoring routes (POST/PUT/DELETE) write their own inline `log_event` rows.

When adding a new GET that returns patient-identified data, decorate it with
`@audit_read('<action>', resource_type='<Type>', guid_arg='<view_arg>')`. The
decorator writes one row on 2xx, none on 4xx/5xx, and swallows internal
failures so a flaky audit table can't break the response.

### 4.14 LocalUser (`local_users`)

Minimal Flask-Login session state. Real auth is SSO; this stores
`sso_user_guid`, `email`, `display_name`, `role` (default `read_only`),
`is_active`, the cached `access_blob`, and `last_login`. Not a source of
identity truth.

## 5) Security

### 5.1 Auth surfaces

- **Public surface**: SSO Bearer JWT, validated on **every** request against
  sso.pdhc — the access blob is **never cached** client-side, so an SSO-side
  logout takes effect immediately. `AUTH_DISABLED=true` is honoured **only**
  when `FLASK_ENV=development` (config.py refuses to start otherwise, #91).
- **Internal surface**: `X-Service-Key` (`INTERNAL_SERVICE_KEY`), validated by
  `@requires_service_key`. Blueprint: `app/api/internal.py`, mounted under
  `/api/v1`.
- **Provider surface**: `X-Provider-Token` (PAT), validated by
  `@requires_provider_token`. Provider org identity is derived from the token,
  **never** from request params.

### 5.2 Provider endpoints (`app/api/provider.py`, `/api/v1` prefix)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/provider/feed` | PAT `read` | List SRs for this provider — **metadata only** (data minimisation); audited `feed.accessed`. |
| GET | `/provider/download/<sr_guid>` | PAT `read` | Download the full FHIR Bundle; issues a `DataExchangeGrant` if none exists and returns `grant_token`. |
| POST | `/provider/status/<sr_guid>` | PAT `write` | Canonical **lifecycle status** update; requires the composite key (`patient_guid`, `contract_guid`, `provider_org_guid`, `grant_token`). Body org must match the PAT. |
| POST | `/provider/report/<sr_guid>` | PAT `write` | **DEPRECATED alias** of `/status`. Logs `report.deprecated_alias_used`. Observation *data* goes to **gateway.pdhc** `/provider/report`, not here. |
| POST | `/provider/validate-token` | none (token is the credential) | Called by gateway.pdhc to resolve a raw PAT → org/contract/scopes/delivery-mode + decrypted push key. |
| POST | `/provider/receipt/<receipt_token>/ack` | PAT `write` | Acknowledge a push-delivery receipt. |

### 5.3 Internal endpoints (`app/api/internal.py`, `X-Service-Key`)

- `GET /api/v1/internal/service-request/<sr_guid>/context` — pre-extracted SR
  context for gateway observation reconstruction (transaction→concept, patient
  cross-check).
- `POST /api/v1/internal/grant/validate` — validate a `DataExchangeGrant`
  token. Returns `contract_guid`, `grant_type`, `uses_remaining`; distinguishes
  `GRANT_EXPIRED` from `GRANT_TOKEN_INVALID`. **This is how the HMAC secret
  stays inside request.pdhc.**
- `POST /api/v1/internal/auto-provision-pat` — called by contract.pdhc on
  contract create/update; fetches push-config from SSO and issues a PAT if none
  exists (poll vs push decided by whether SSO returned a push endpoint).

### 5.4 Outbound webhook subsystem (`request_pdhc_worker`)

`app/services/webhook_dispatcher.py` + the `flask webhook` CLI group
(`app/__init__.py`). The worker container runs `flask webhook run-worker
--interval 5`, which calls `tick()` on a loop:

1. `enqueue(...)` writes a `WebhookDelivery`. The body is signed with the
   org's **active** `WebhookSigningSecret` (`X-PDHC-Signature: sha256=<hex>`).
   No active secret → the row goes **straight to `dead_letter`** and a ticket
   is filed (never silently retried).
2. `tick()` picks up `pending` rows whose `next_attempt_at <= now` and POSTs
   them. Non-2xx / transport error → `attempt_count++` and reschedule per
   `BACKOFF_SECONDS = [5, 25, 120, 600, 3600]` (6 attempts total).
3. After the last attempt the row becomes `dead_letter` and a **high-priority
   ops ticket** is filed on `ticket.mitidbok.se` (best-effort; DB row is the
   authority). Requeue with `flask webhook requeue --guid <guid>`.

Other `flask webhook` subcommands: `tick`, `list-pending`, `requeue`.

### 5.5 Consent-at-dispatch PDL gate (`dispatch_service.py`, #229)

Before forwarding a dispatch upstream to plan.pdhc, `create_dispatch()`
enforces cohesive-care consent (**Lag 2022:913 §5**) via
`ips_consent_client.py`:

- When the caller supplies **both** `patient_guid` and
  `destination_caregiver_guid`, request.pdhc fetches the patient's active
  consents from ips.pdhc (`/api/v1/patients/<guid>/consents`, 30 s TTL cache)
  and checks `consent_covers_dispatch()`:
  - at least one active consent must name the destination caregiver
    (`no_consent` otherwise);
  - a whole-caregiver consent covers any payload; a concept-narrowed consent
    covers only its listed `consented_concept_guids` — a payload concept
    outside that set is refused (`concept_not_consented`).
- A refusal returns **403 `consent_missing`** and writes a
  `careplan.dispatch.refused` audit row (with `pdl_basis: Lag (2022:913) §5`).
  The gate runs **before** the idempotency check so a consent-failing dispatch
  can't "succeed" by replaying a prior idempotency key.
- Supplying only one of the two fields logs a warning but does **not** refuse
  (soft-rollout posture).

### 5.6 Report validation chain (defense in depth)

For a provider report arriving at gateway.pdhc and validated back through
request.pdhc:

1. PAT validates provider identity → derives `provider_org_guid`.
2. Grant token validated via `/internal/grant/validate` → `contract_guid`,
   `grant_type`, `uses_remaining`.
3. SR context fetched via `/internal/service-request/<sr>/context`.
4. Patient cross-check — body's `patient_guid` must match the SR subject.
5. Concept enrichment + range checks (gateway side, from SR context).
6. Grant use recorded (`used_count++`) for audit.

Any failure aborts with 4xx + `OperationOutcome`.

## 6) Operational dependencies

| Dependency | Purpose | Failure mode |
|---|---|---|
| sso.pdhc | JWT validation, login | All UI + API auth fails. |
| ips.pdhc | Patient proxy (`patient_service`), clinic need-to-know, and **consent-at-dispatch** (`ips_consent_client`) | Patient reads 502; dispatch consent fetch fails **open-to-refuse** only when both consent fields are supplied (empty consents → `no_consent`). |
| plan.pdhc | PlanDefinition snapshot + dispatch (`/api/v1/PlanDefinition/<guid>/dispatch`) | SR create / dispatch degrades; dispatch marked `failed`. |
| contract.pdhc | Contract status lookup + PAT auto-provision | New SR creation gated on contract status. |
| provider webhook URLs | Outbound `service_request.dispatched` notifications | Retried with backoff; `dead_letter` + ops ticket after 6 attempts. |
| ticket.mitidbok.se | Webhook DLQ ops tickets | Best-effort; DB row still records the dead-letter. |

## 7) Why this split

- **Identity** in sso.pdhc → one login authority.
- **Patients** in ips.pdhc → one patient registry + consent store; request.pdhc
  proxies, never copies.
- **Contract** in contract.pdhc → governance boundary.
- **Templates** (PlanDefinition/CarePlan) authored in plan.pdhc → request.pdhc
  snapshots them so issued SRs are immutable against later template edits.
- **Gateway** in gateway.pdhc → single ingestion choke-point for provider
  observation traffic; the HMAC secret stays in request.pdhc via delegated
  grant validation.

`request.pdhc` is the orchestrator that ties them together for the
clinical-lead UX.
