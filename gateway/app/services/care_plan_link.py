"""One CarePlan per (patient, PlanDefinition); every ServiceRequest is based on it.

Operator decision 2026-11-19: a ServiceRequest is grounded in the patient's
CarePlan, and the CarePlan references the PlanDefinition. Before this the
CarePlan layer (#310) existed but no creation path filled
ServiceRequest.care_plan_guid -- 0 of 21 production requests had one -- and the
FHIR resource carried only a per-request CONTAINED CarePlan.

Chain:  ServiceRequest.basedOn -> CarePlan/<guid>
        CarePlan.instantiatesCanonical -> plan.pdhc PlanDefinition

The CarePlan is SHARED: all requests for the same patient and PlanDefinition
attach to the one OPEN plan (draft / active / on-hold). A plan that is
completed, revoked or entered-in-error is not reused; the next request opens a
new one, so a finished course of care is not silently extended.
"""
from __future__ import annotations

from app import db
from app.models.care_plan_models import CarePlan

OPEN_STATUSES = ('draft', 'active', 'on-hold')


def open_care_plan(patient_guid: str, plan_definition_guid: str):
    """The patient's open CarePlan for this PlanDefinition (oldest first), or None."""
    return (CarePlan.query
            .filter(CarePlan.patient_guid == patient_guid,
                    CarePlan.plan_definition_guid == plan_definition_guid,
                    CarePlan.status.in_(OPEN_STATUSES))
            .order_by(CarePlan.created_at.asc(), CarePlan.id.asc())
            .first())


def ensure_care_plan(*, patient_guid: str, plan_definition_guid: str,
                     snapshot: dict | None, created_by: str | None):
    """Return (care_plan, created). Reuses the open plan; else creates one,
    `active`, from the request's own PlanDefinition snapshot (the same
    snapshot, so the plan and the request describe the same template version).
    Flushes, does not commit: the caller commits it with the request."""
    cp = open_care_plan(patient_guid, plan_definition_guid)
    if cp is not None:
        return cp, False
    from app.services import action_limits
    snap = snapshot or {}
    cp = CarePlan(
        patient_guid=patient_guid,
        plan_definition_guid=plan_definition_guid,
        status='active',
        intent='plan',
        title=snap.get('title'),
        description=snap.get('description'),
        plan_definition_snapshot=snapshot,
        goals=action_limits.stamp_recommended_goals(snap.get('goals') or [],
                                                    from_plan=True),
        care_team_user_guids=[],
        created_by_user_guid=created_by,
    )
    db.session.add(cp)
    db.session.flush()
    return cp, True


def link_existing(apply: bool = False) -> dict:
    """Backfill: attach every ServiceRequest without a CarePlan to its
    (patient, PlanDefinition) plan, creating plans as needed. Dry run unless
    apply=True. Requests are taken oldest first, so the plan created for a
    group is created from its oldest request's snapshot."""
    from app.models.service_request_models import ServiceRequest
    rows = (ServiceRequest.query.filter(ServiceRequest.care_plan_guid.is_(None))
            .order_by(ServiceRequest.created_at.asc(), ServiceRequest.id.asc()).all())
    groups = {}
    for sr in rows:
        groups.setdefault((sr.patient_guid, sr.plan_definition_guid), []).append(sr)
    out = {'requests': len(rows), 'groups': len(groups),
           'plans_reused': 0, 'plans_created': 0, 'apply': apply}
    for (patient, plandef), srs in groups.items():
        existing = open_care_plan(patient, plandef)
        out['plans_reused' if existing else 'plans_created'] += 1
        if not apply:
            continue
        cp, _ = ensure_care_plan(patient_guid=patient, plan_definition_guid=plandef,
                                 snapshot=srs[0].plan_definition_snapshot,
                                 created_by=srs[0].requester_user_guid)
        from app.services.versioning import note_change
        for sr in srs:
            note_change(sr, None, f'linked to CarePlan/{cp.guid}', 'link_care_plans')
            sr.care_plan_guid = cp.guid
    if apply:
        db.session.commit()
    return out
