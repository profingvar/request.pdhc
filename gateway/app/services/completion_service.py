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

    if updated:
        db.session.commit()

    log_event(
        action='report.auto_completed',
        resource_type='ServiceRequest',
        resource_guid=service_request_guid,
        details={
            'source': source,
            'matches_updated': updated,
            'data_subject_guid': sr.patient_guid,
        },
        ip_address=ip_address,
    )

    return {
        'status': 'completed',
        'service_request_guid': service_request_guid,
        'matches_updated': updated,
    }, 200
