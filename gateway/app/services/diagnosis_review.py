"""#984 — diagnosis review as a PlanDefinition step (contract section 2).

Contract: `plans/984_diagnosis_review_contract.md` (operator-approved
2026-11-17; plan.pdhc and icd11.pdhc build against the same text).

A PlanDefinition action whose `definitionCanonical` is
`DIAGNOSIS_REVIEW_CANONICAL` becomes its OWN ServiceRequest, beside the
order's ServiceRequest, when the order is finalized:

  * `instantiatesCanonical` = the ActivityDefinition canonical;
  * the action's `diagnosis-code-scope` extensions, copied VERBATIM;
  * `performerType` = clinician;
  * work link `<ICD11_BASE_URL>/session/<service_request_guid>`.

It is a clinician's task. It NEVER goes to the patient app (1177), a push,
a provider endpoint, a provider feed/download, or a webhook — every one of
those paths calls `dispatch_refusal()` / `is_diagnosis_review()` first.

Why its own ServiceRequest and not part of the order's: the order's SR
instantiates the PlanDefinition and is dispatched to providers and the
patient; this one instantiates the ActivityDefinition, is performed by a
clinician, and is completed by icd11.pdhc with CDR Condition ids. Those are
two different `instantiatesCanonical`s, two performers and two lifecycles,
so they cannot be one resource. `basedOn` links the child to the order.

Completion runs through `completion_service.mark_service_request_completed`
(only for source `icd11.pdhc`), never through anything here.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from flask import current_app

DIAGNOSIS_REVIEW_CANONICAL = (
    'https://icd11.pdhc.se/fhir/ActivityDefinition/diagnosis-review')
CODE_SCOPE_EXTENSION_URL = (
    'https://plan.pdhc.se/fhir/StructureDefinition/diagnosis-code-scope')

KIND = 'diagnosis-review'
PERFORMER_TYPE = 'clinician'
COMPLETING_SERVICE = 'icd11.pdhc'
DEFAULT_ICD11_BASE_URL = 'https://icd11.pdhc.se'

#: Swedish label shown to clinicians wherever a ServiceRequest is listed.
LABEL_SV = 'Diagnosgenomgång (ICD-11)'


class DiagnosisReviewStepInvalid(ValueError):
    """A diagnosis-review step that cannot become a ServiceRequest."""

    code = 'diagnosis_review_scope_missing'


# ── Recognising the step ────────────────────────────────────────────────


def _walk_actions(actions):
    for act in actions or []:
        if not isinstance(act, dict):
            continue
        yield act
        # PlanDefinition.action nests; a step inside a group is still a step.
        yield from _walk_actions(act.get('action'))


def is_diagnosis_review_action(action) -> bool:
    return (isinstance(action, dict)
            and action.get('definitionCanonical') == DIAGNOSIS_REVIEW_CANONICAL)


def diagnosis_review_actions(snapshot) -> list:
    """The FHIR actions in a PlanDefinition snapshot that are diagnosis reviews.

    Read from the snapshot's FHIR export (`fhir_data.action`), which is where
    the contract puts `definitionCanonical`. Form actions and everything else
    are untouched.
    """
    fhir = (snapshot or {}).get('fhir_data') or {}
    if not isinstance(fhir, dict):
        return []
    return [a for a in _walk_actions(fhir.get('action'))
            if is_diagnosis_review_action(a)]


def scope_extensions(action) -> list:
    """The action's `diagnosis-code-scope` extensions, VERBATIM (deep copies)."""
    return [copy.deepcopy(e) for e in (action.get('extension') or [])
            if isinstance(e, dict) and e.get('url') == CODE_SCOPE_EXTENSION_URL]


def scope_prefixes(extensions) -> list:
    return [e.get('valueString') for e in (extensions or [])
            if isinstance(e, dict) and e.get('valueString')]


# ── The ServiceRequest ──────────────────────────────────────────────────


def is_diagnosis_review(sr) -> bool:
    if sr is None:
        return False
    kind = sr.get('kind') if isinstance(sr, dict) else getattr(sr, 'kind', None)
    return kind == KIND


def icd11_base_url() -> str:
    try:
        base = current_app.config.get('ICD11_BASE_URL')
    except RuntimeError:  # outside an app context
        base = None
    return (base or DEFAULT_ICD11_BASE_URL).rstrip('/')


def work_link(sr_guid) -> str:
    return f'{icd11_base_url()}/session/{sr_guid}'


def display_label(code_scope) -> str:
    """'Diagnosgenomgång (ICD-11) — 5A1, 5A2' for lists and timelines."""
    area = ', '.join(scope_prefixes(code_scope))
    return f'{LABEL_SV} — {area}' if area else LABEL_SV


def dispatch_refusal(sr):
    """(body, 409) if `sr` is a diagnosis review, else None.

    Every outbound path (push, 1177, provider match/dispatch/download, webhook)
    asks this first. A diagnosis review is a clinician's task in icd11.pdhc.
    """
    if not is_diagnosis_review(sr):
        return None
    return {
        'code': 'diagnosis_review_not_dispatchable',
        'message': ('A diagnosis-review ServiceRequest is performed by a '
                    'clinician in icd11.pdhc; it is never sent to the patient '
                    'app, a provider or a webhook.'),
        'work_link': work_link(sr.guid),
    }, 409


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def build_fhir_resource(sr) -> dict:
    """FHIR R5 ServiceRequest for a diagnosis-review SR.

    No contained Patient: the reader (icd11.pdhc) resolves the patient itself
    and checks the caller may open it.
    """
    resource = {
        'resourceType': 'ServiceRequest',
        'id': sr.guid,
        'status': sr.status,
        'intent': sr.intent or 'order',
        'priority': sr.priority or 'routine',
        'instantiatesCanonical': [sr.instantiates_canonical],
        'code': {'concept': {'text': LABEL_SV}},
        'subject': {'reference': f'Patient/{sr.patient_guid}'},
        'requester': {'reference': f'Practitioner/{sr.requester_user_guid}'},
        'performerType': {'text': sr.performer_type or PERFORMER_TYPE},
        'authoredOn': _iso(sr.created_at) or _iso(datetime.now(timezone.utc)),
    }
    if sr.code_scope:
        resource['extension'] = copy.deepcopy(sr.code_scope)
    if sr.requester_user_name:
        resource['requester']['display'] = sr.requester_user_name
    if sr.based_on_guid:
        resource['basedOn'] = [{'reference': f'ServiceRequest/{sr.based_on_guid}'}]
    if sr.care_plan_guid:
        resource.setdefault('basedOn', []).append(
            {'reference': f'CarePlan/{sr.care_plan_guid}', 'type': 'CarePlan'})
    action = (sr.plan_definition_snapshot or {}).get('action') or {}
    if isinstance(action.get('timingTiming'), dict):
        resource['occurrenceTiming'] = copy.deepcopy(action['timingTiming'])
    record = sr.completion_record or {}
    refs = []
    for c in record.get('conditions') or []:
        refs.append({'reference': {
            'reference': f"Condition/{c['id']}/_history/{c['version_id']}"}})
    if refs:
        resource['supportingInfo'] = refs
    return resource


def read_view(sr) -> dict:
    """What icd11.pdhc reads: the FHIR resource plus the plain fields it needs
    (patient, status, canonical, code scope) so it does not have to parse it."""
    return {
        'service_request_guid': sr.guid,
        'kind': KIND,
        'status': sr.status,
        'patient_guid': sr.patient_guid,
        'instantiates_canonical': sr.instantiates_canonical,
        'code_scope': scope_prefixes(sr.code_scope),
        'performer_type': sr.performer_type,
        'requester_org_guid': sr.requester_org_guid,
        'patient_org_guid': sr.patient_org_guid,
        'based_on_guid': sr.based_on_guid,
        'work_link': work_link(sr.guid),
        'fhir_resource': build_fhir_resource(sr),
    }


def create_for_order(parent, user_guid=None, ip_address=None) -> list:
    """Create one active diagnosis-review SR per step in the order's snapshot.

    Called from `finalize_service_request`, inside its transaction (the caller
    commits). Idempotent: an order that already has its children gets no more.
    Raises DiagnosisReviewStepInvalid — before creating anything — when a step
    carries no scope; the contract makes the scope required, and a review with
    no code area would let icd11.pdhc write nothing, silently.
    """
    from app import db
    from app.models.service_request_models import ServiceRequest
    from app.services.audit_service import log_event

    actions = diagnosis_review_actions(parent.plan_definition_snapshot)
    if not actions:
        return []
    for act in actions:
        if not scope_prefixes(scope_extensions(act)):
            raise DiagnosisReviewStepInvalid(
                f"diagnosis-review step {act.get('title')!r} has no "
                f"{CODE_SCOPE_EXTENSION_URL} extension; the code area is required")

    existing = ServiceRequest.query.filter_by(
        based_on_guid=parent.guid, kind=KIND).count()
    if existing:
        return []

    parent_title = (parent.plan_definition_snapshot or {}).get('title')
    created = []
    for act in actions:
        exts = scope_extensions(act)
        child = ServiceRequest(
            # #1054: guid and created_at set here so the resource is built
            # BEFORE the insert - otherwise the version written at creation
            # has no fhir_resource and the first real version is a v2.
            guid=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            status='active',
            intent=parent.intent or 'order',
            priority=parent.priority or 'routine',
            kind=KIND,
            instantiates_canonical=DIAGNOSIS_REVIEW_CANONICAL,
            code_scope=exts,
            performer_type=PERFORMER_TYPE,
            based_on_guid=parent.guid,
            patient_guid=parent.patient_guid,
            patient_excerpt=parent.patient_excerpt,
            patient_org_guid=parent.patient_org_guid,
            plan_definition_guid=parent.plan_definition_guid,
            plan_definition_snapshot={
                'kind': KIND,
                'title': act.get('title') or LABEL_SV,
                'description': act.get('description') or '',
                'parent_title': parent_title,
                'action': copy.deepcopy(act),
            },
            care_plan_guid=parent.care_plan_guid,
            # Deliberately NO contract_guid: a contract is a provider
            # relationship, and this request never goes to a provider.
            requester_user_guid=parent.requester_user_guid,
            requester_user_name=parent.requester_user_name,
            requester_org_guid=parent.requester_org_guid,
            requester_org_name=parent.requester_org_name,
            period_start=parent.period_start,
            period_end=parent.period_end,
        )
        child.fhir_resource = build_fhir_resource(child)
        from app.services.versioning import note_change
        note_change(child, user_guid, f'created at finalize of ServiceRequest/{parent.guid}',
                    'diagnosis_review.create')
        db.session.add(child)
        db.session.flush()
        created.append(child)
        log_event(
            user_guid=user_guid,
            action='service_request.diagnosis_review.create',
            resource_type='ServiceRequest',
            resource_guid=child.guid,
            data_subject_guid=child.patient_guid,
            details={'based_on': parent.guid,
                     'code_scope': scope_prefixes(exts),
                     'work_link': work_link(child.guid)},
            ip_address=ip_address,
        )
    return created


# ── Timeline ─────────────────────────────────────────────────────────────


def _timing_fields(timing):
    """FHIR timingTiming -> the flat timing_* keys timeline_service reads."""
    rep = (timing or {}).get('repeat') if isinstance(timing, dict) else None
    if not isinstance(rep, dict) or not rep.get('frequency'):
        # 'once' (plan exports no repeat for it): a single station.
        return {'timing_bounds_mode': 'count', 'timing_bounds_count': 1}
    out = {
        'timing_frequency': rep.get('frequency'),
        'timing_period': rep.get('period', 1),
        'timing_period_unit': rep.get('periodUnit', 'd'),
    }
    if rep.get('count'):
        out.update(timing_bounds_mode='count', timing_bounds_count=rep['count'])
    elif isinstance(rep.get('boundsDuration'), dict):
        bd = rep['boundsDuration']
        out.update(timing_bounds_mode='duration',
                   timing_bounds_duration_value=bd.get('value'),
                   timing_bounds_duration_unit=bd.get('unit') or bd.get('code'))
    return out


def timeline_activities(snapshot) -> list:
    """Diagnosis-review steps as timeline lines (title in Swedish + code area).

    Works on an order's snapshot (its FHIR actions) and on a diagnosis-review
    SR's own snapshot (its single stored action).
    """
    snapshot = snapshot or {}
    if snapshot.get('kind') == KIND:
        actions = [snapshot.get('action') or {}]
    else:
        actions = diagnosis_review_actions(snapshot)
    out = []
    for act in actions:
        exts = scope_extensions(act)
        line = {
            'title': display_label(exts),
            'description': act.get('title') or '',
            'transactions': [],
        }
        line.update(_timing_fields(act.get('timingTiming')))
        out.append(line)
    return out
