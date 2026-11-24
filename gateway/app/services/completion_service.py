"""Completion service — auto-close a ServiceRequest's provider contract-match.

Called by gateway.pdhc via the internal API when an accepted provider report
marks a ServiceRequest completed. Flipping the ServiceRequestContractMatch to
'completed' makes the provider feed on request.pdhc reflect clinical completion
rather than only the distribution status ('sent'). Idempotent.

Design note: the provider feed's `status` is ServiceRequestContractMatch.status
(a distribution status: pending -> sent -> accepted). Observation reporting goes
to gateway.pdhc and never touches this match. This service is the propagation
path that closes that gap — gateway calls it once it marks the SR completed.
"""
from datetime import datetime, timezone

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch,
)
from app.services.audit_service import log_event

# Terminal match states we must not overwrite when auto-completing.
_TERMINAL = ('completed', 'rejected')


def archive_if_provider_work_complete(sr, source='gateway.pdhc',
                                      ip_address=None):
    """Archive an active ServiceRequest once no provider has open work (#582).

    "When a provider says the patient is finished, the request is archived
    automatically." One provider finishing is not enough on its own: an SR can
    be matched to several providers, and archiving while another is still
    working would pull live work out of that provider's feed. So the SR is
    archived only when EVERY match is terminal (completed or rejected).

    Only 'active' SRs are archived — a draft was never dispatched, and
    'archived'/'revoked' are already terminal. Caller commits.

    Returns True if this call archived the SR.
    """
    if sr is None or sr.status != 'active':
        return False

    matches = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=sr.guid,
    ).all()
    # No matches at all means nothing was ever dispatched to a provider;
    # that is the auto-archive-on-expiry case, not this one.
    if not matches:
        return False
    if any(m.status not in _TERMINAL for m in matches):
        return False

    from app.services.versioning import note_change
    note_change(sr, None, 'all provider matches terminal', f'auto_archive:{source}')
    sr.status = 'archived'
    log_event(
        action='servicerequest.auto_archived',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        details={
            'source': source,
            'reason': 'all provider matches terminal',
            'match_count': len(matches),
            'data_subject_guid': sr.patient_guid,
        },
        ip_address=ip_address,
    )
    return True


def mark_service_request_completed(service_request_guid, source='gateway.pdhc',
                                   ip_address=None, cdr_conditions=None):
    """Flip this SR's open provider contract-match(es) to 'completed'.

    Returns (result_dict, status_code):
      - 404 if the ServiceRequest is unknown (gateway tolerates this).
      - 200 otherwise, with `matches_updated` = number of matches flipped
        (0 if already completed, none present, or only terminal matches).
    Idempotent: re-calling on an already-completed SR is a 200 no-op.

    #984: a diagnosis-review SR has no provider matches. It is completed here
    too, but ONLY by `source='icd11.pdhc'` and only with the CDR Condition ids
    and version ids it wrote (`cdr_conditions`) — see
    `_complete_diagnosis_review`. Every other source is refused by name, which
    closes gateway's /internal/.../complete door for this kind as well.
    """
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if sr is None:
        return {'code': 'not_found',
                'message': 'ServiceRequest not found'}, 404

    from app.services import diagnosis_review
    if diagnosis_review.is_diagnosis_review(sr):
        return _complete_diagnosis_review(sr, source, cdr_conditions, ip_address)
    if source == diagnosis_review.COMPLETING_SERVICE:
        return {'code': 'not_diagnosis_review',
                'message': 'icd11.pdhc may complete only a diagnosis-review '
                           'ServiceRequest'}, 409

    now = datetime.now(timezone.utc)
    matches = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid,
    ).all()

    updated = 0
    for match in matches:
        # Skip terminal matches — never resurrect a rejected match or
        # re-stamp an already-completed one.
        if match.status in _TERMINAL:
            continue
        match.status = 'completed'
        match.response_at = now
        match.response_payload = {
            'status': 'completed',
            'source': source,
            'received_at': now.isoformat(),
        }
        updated += 1

    # #582: the provider reporting clinical completion is exactly the
    # "provider says the patient is finished" signal. Archive the SR if that
    # was the last provider still working on it.
    archived = archive_if_provider_work_complete(
        sr, source=source, ip_address=ip_address,
    )

    if updated or archived:
        db.session.commit()

    log_event(
        action='report.auto_completed',
        resource_type='ServiceRequest',
        resource_guid=service_request_guid,
        details={
            'source': source,
            'matches_updated': updated,
            'archived': archived,
            'data_subject_guid': sr.patient_guid,
        },
        ip_address=ip_address,
    )

    return {
        'status': 'completed',
        'service_request_guid': service_request_guid,
        'matches_updated': updated,
        'archived': archived,
    }, 200


# ── #984: diagnosis-review completion ───────────────────────────────────


def normalise_cdr_conditions(raw):
    """[{'id': str, 'version_id': str}, ...] or raise ValueError naming the fault.

    `versionId` (FHIR meta spelling) is accepted as an alias of `version_id`.
    An EMPTY list is valid: a review that confirmed every diagnosis and wrote
    nothing is still a completed review.
    """
    if not isinstance(raw, list):
        raise ValueError('conditions must be a list of '
                         '{"id": <CDR Condition id>, "version_id": <version id>}')
    out = []
    for i, c in enumerate(raw):
        if not isinstance(c, dict):
            raise ValueError(f'conditions[{i}] must be an object')
        cid = c.get('id')
        vid = c.get('version_id', c.get('versionId'))
        if isinstance(vid, int) and not isinstance(vid, bool):
            vid = str(vid)
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError(f'conditions[{i}].id is required (CDR Condition id)')
        if not isinstance(vid, str) or not vid.strip():
            raise ValueError(f'conditions[{i}].version_id is required '
                             f'(the CDR version written)')
        out.append({'id': cid.strip(), 'version_id': vid.strip()})
    return out


def _complete_diagnosis_review(sr, source, cdr_conditions, ip_address):
    from app.services import diagnosis_review

    if source != diagnosis_review.COMPLETING_SERVICE:
        log_event(action='service_request.diagnosis_review.complete.refused',
                  resource_type='ServiceRequest', resource_guid=sr.guid,
                  data_subject_guid=sr.patient_guid,
                  details={'reason': 'wrong_caller', 'source': source},
                  ip_address=ip_address)
        return {'code': 'caller_not_icd11',
                'message': 'A diagnosis-review ServiceRequest is completed '
                           'only by icd11.pdhc'}, 403
    try:
        conditions = normalise_cdr_conditions(cdr_conditions)
    except ValueError as e:
        return {'code': 'invalid_conditions', 'message': str(e)}, 400

    key = sorted((c['id'], c['version_id']) for c in conditions)
    if sr.status == 'completed':
        prior = (sr.completion_record or {}).get('conditions') or []
        if sorted((c['id'], c['version_id']) for c in prior) == key:
            return {'status': 'completed', 'service_request_guid': sr.guid,
                    'already_completed': True,
                    'completion_record': sr.completion_record}, 200
        return {'code': 'already_completed_with_other_conditions',
                'message': 'This diagnosis review was already completed with '
                           'a different set of CDR Condition versions',
                'completion_record': sr.completion_record}, 409
    if sr.status != 'active':
        return {'code': 'service_request_not_active',
                'message': f'ServiceRequest is {sr.status}, not active'}, 409

    now = datetime.now(timezone.utc)
    from app.services.versioning import note_change
    note_change(sr, None, f'diagnosis review completed by {source}',
                'diagnosis_review.complete')
    sr.status = 'completed'
    sr.completion_record = {'source': source, 'completed_at': now.isoformat(),
                            'conditions': conditions}
    sr.fhir_resource = diagnosis_review.build_fhir_resource(sr)
    db.session.commit()
    log_event(action='service_request.diagnosis_review.completed',
              resource_type='ServiceRequest', resource_guid=sr.guid,
              data_subject_guid=sr.patient_guid,
              details={'source': source, 'conditions': conditions,
                       'based_on': sr.based_on_guid},
              ip_address=ip_address)
    return {'status': 'completed', 'service_request_guid': sr.guid,
            'already_completed': False,
            'completion_record': sr.completion_record}, 200
