"""May this caller reach this patient? ONE answer, for every route (#981).

PDL Ch 4 §§ 1-2 need-to-know, as `POST /ServiceRequest` has enforced it since
#225 and corrected in #779: a non-SU caller reaches a patient only when one of
the caller's ORGANISATIONS is the organisation of one of the patient's
clinics. SU admins bypass, and the bypass is the caller's to audit.

It was written inline in that one route. The CarePlan routes then shipped with
no check at all (#981) — the shape a second, missing copy of an access rule
takes. This module is the single implementation; the routes keep their own
audit actions and messages, because "create denied" and "read denied" are
different events to an auditor.

Pure of Flask request state: the caller passes the access blob, so a test can
drive it directly and the route that already fetched the blob does not fetch
it twice.

#779 IS THE TRAP THIS GUARDS: ORGANISATION is compared to ORGANISATION. ips's
`Clinic.guid` is a different identifier space (0 of 9 clinics have
guid == organisation_guid), and comparing the two denied every non-SU caller
while the tests passed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services import patient_service
from app.services.reform_scope import caller_org_ids as _caller_org_ids


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    #: HTTP status when refused: 403 no overlap, 404 patient unknown to ips,
    #: 502 ips could not be asked (FAIL CLOSED — never allow on an outage).
    status: int = 200
    code: str | None = None
    #: The audit `reason`: caller_is_su_admin | org_match | patient_not_found |
    #: ips_lookup_failed | patient_org_mismatch
    reason: str = ""
    is_su: bool = False
    #: Everything an auditor needs to tell the refusals apart; no clinical data.
    details: dict = field(default_factory=dict)


def evaluate(blob: dict | None, patient_guid: str) -> AccessDecision:
    is_su = bool(blob.get('is_su_admin', False)) if blob else False
    if is_su:
        return AccessDecision(True, reason='caller_is_su_admin', is_su=True)

    caller_orgs = set(_caller_org_ids(blob) if blob else [])
    clinic_org_pairs, ips_status = patient_service.get_patient_clinic_orgs(patient_guid)
    if ips_status == 404:
        return AccessDecision(False, 404, 'not_found', 'patient_not_found',
                              details={'caller_org_ids': sorted(caller_orgs)})
    if ips_status >= 500:
        return AccessDecision(False, 502, 'upstream_error', 'ips_lookup_failed',
                              details={'ips_status': ips_status})
    # A clinic whose organisation_guid is NULL can never match: the falsy
    # filter makes NULL DENY rather than act as a wildcard (#780).
    patient_orgs = {org for _clinic, org in clinic_org_pairs if org}
    if caller_orgs & patient_orgs:
        return AccessDecision(True, reason='org_match')
    return AccessDecision(False, 403, 'forbidden', 'patient_org_mismatch', details={
        'caller_org_ids': sorted(caller_orgs),
        'patient_org_guids': sorted(patient_orgs),
        'patient_clinic_guids': sorted(c for c, _org in clinic_org_pairs if c),
        'clinics_without_organisation': sorted(c for c, org in clinic_org_pairs if not org),
    })
