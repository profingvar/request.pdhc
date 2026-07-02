# ADR-001 — Alerting is out of scope for request.pdhc

- **Status:** Accepted
- **Date:** 2026-07-02
- **Deciders:** operator, per rollup #348 Phase B scope call
- **Ticket:** #374 (documents the scope call captured in #348 finding §3.1)

## Context

The 2026-07-01 audit (Divergencies_code_vs_docs_request.md §3.1) found
no code path that:

- reads inbound Observations,
- evaluates a PlanDefinition-authored threshold against them,
- emits a FHIR R5 `DetectedIssue` or `Flag` resource,
- dispatches it to a caregiver, patient portal, or 1177 inbox.

Memory `project_plan_request_split` at that time described
request.pdhc as *"applies thresholds and fires alerts (MDR IIa/IIb)"* —
which conflicted with what the code actually does.

Two possible dispositions were on the table:

- **A. Build the alerting layer here.** Add threshold evaluation +
  DetectedIssue/Flag emission + dispatch to request.pdhc. request.pdhc
  becomes an MDR Rule 11 device.
- **B. Move alerting out.** Alerting belongs in the analyse.pdhc layer
  (memory `project_sim_cdr6_analyse_pipeline` names it as the future
  primary consumer of `cdr_6` data). request.pdhc stays a dispatch
  envelope; it is not a device.

## Decision

**Choose path B.** Alerting is out of scope for request.pdhc.

Operator rationale (2026-07-01): **"request does not receive any data."**
That single sentence resolves the disagreement — a service that has
no observation stream cannot evaluate thresholds, so it cannot be
the firing layer regardless of what the memory said.

request.pdhc's role is therefore:

- **CarePlan CRUD** — patient CarePlan lifecycle per #310
  (`app/api/care_plans.py`, `app/models/care_plan_models.py`).
- **PlanDefinition dispatch** — canonical
  `POST /api/v1/PlanDefinition/<guid>/dispatch` accepts a signed
  submission and routes it downstream via the webhook dispatcher
  (`app/services/dispatch_service.py`).
- **ServiceRequest workflow** — draft/finalize/match/push/etc.
  (`app/api/service_requests.py`, `app/services/service_request_service.py`).
- **Consent gate at dispatch** — `ips_consent_client` + `dispatch_service`
  refuse dispatches with `code='consent_missing'` per Lag 2022:913 §5,
  BEFORE the idempotency lookup (correct ordering).
- **HMAC-signed webhook envelope** — `webhook_dispatcher.py` with
  6-attempt exponential backoff and DLQ ticket emission on
  dead-letter.
- **PDL provenance** — every dispatched row carries
  `plan_definition_guid`, `provider_guid`, `assigned_user_guid`,
  `idempotency_key`, and is audited via `audit_service.log_event`.

## Consequences

Positive:

- **request.pdhc is NOT a Rule 11 device.** No CE marking, no clinical
  evaluation, no post-market surveillance obligations attach to this
  service. The regulatory surface stays where it belongs (analyse.pdhc,
  once that service is built).
- The provenance chain
  `Observation → CarePlan → PlanDefinition → Transaction → Concept`
  documented in `care_plan_models.py:6` is correctly modelled and
  auditable — request.pdhc contributes the middle links of that chain
  even though it doesn't fire the alert.
- The CapabilityStatement rewrite in #373 truthfully advertises what
  request.pdhc does: CarePlan CRUD + `context` operation + dispatch
  + ServiceRequest workflow + Questionnaire distribution. No
  DetectedIssue or Flag interactions declared.
- Conformance CI (child ticket #377) has a narrower target to validate.

Negative / accepted:

- Memory `project_plan_request_split` is now known to be **wrong** about
  request.pdhc firing alerts. Session-end housekeeping: correct the
  memory to reflect this ADR.
- Until analyse.pdhc ships, PDHC as a whole has **no alerting**. This
  is a real functionality gap that shows up if a clinician asks
  "what happens when this patient's HbA1c comes back high?" — the
  answer today is "nothing automatic; a caregiver reads the value
  in the CDR". That gap is a roadmap item for analyse.pdhc, not a bug
  in request.pdhc.

## Reversibility

This ADR is **revocable**. A future decision could bring alerting into
request.pdhc after all (e.g. if analyse.pdhc becomes a read-only
dashboard and doesn't grow a firing engine). Record any such
reversal as **ADR-002 — bring alerting into request.pdhc**, update the
CapabilityStatement to declare `DetectedIssue` + `Flag` resources
with their interactions and operations, and revisit the MDR Rule 11
classification.

## References

- Divergencies_code_vs_docs_request.md — findings §1.6, §3.1, §3.2
- Ticket #348 — rollup this ADR lands under
- Ticket #373 — CapabilityStatement rewrite that reflects this scope
  (removes the stale CarePlan `dispatch`/`export-csv` operations,
  advertises the real `/careplans` CRUD + `context`)
- Ticket #351/plan.pdhc — plan.pdhc's ADR D3 for canonical URL scheme
  (relevant because dispatch consumes plan.pdhc's PlanDefinition)
- Memory: `project_sim_cdr6_analyse_pipeline` — analyse.pdhc is the
  future primary consumer, i.e. the natural home for alerting
- Memory: `project_pdhc_has_data_driven_alerts` — original claim that
  PDHC has data-driven alerts. Still true at platform-level; this
  ADR just relocates *where* they live.
- MDR Rule 11 (EU 2017/745, Annex VIII) — for the classification
  frame that made this scope call regulatory-relevant
