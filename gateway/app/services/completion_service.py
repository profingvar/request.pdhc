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
                                   ip_address=None):
    """Flip this SR's open provider contract-match(es) to 'completed'.

    Returns (result_dict, status_code):
      - 404 if the ServiceRequest is unknown (gateway tolerates this).
      - 200 otherwise, with `matches_updated` = number of matches flipped
        (0 if already completed, none present, or only terminal matches).
    Idempotent: re-calling on an already-completed SR is a 200 no-op.
    """
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if sr is None:
        return {'code': 'not_found',
                'message': 'ServiceRequest not found'}, 404

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
