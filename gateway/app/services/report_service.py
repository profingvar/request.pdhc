"""Report service — handle provider report submissions with composite key validation."""
from datetime import datetime, timezone

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch,
)
from app.services.grant_service import validate_grant, use_grant
from app.services.audit_service import log_event


def submit_report(service_request_guid, patient_guid, provider_org_guid,
                  contract_guid, grant_token, report_status='completed',
                  report_payload=None, ip_address=None):
    """Validate composite key and store a provider's report.

    Validation chain (defense in depth):
    1. ServiceRequest exists with matching patient_guid
    2. Contract match exists linking SR to this org
    3. DataExchangeGrant validates (HMAC, expiry, revocation)
    4. All audit logged with data_subject_guid

    Returns:
        tuple: (result_dict, status_code)
    """
    # 1. Verify ServiceRequest exists and patient matches
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404

    if sr.patient_guid != patient_guid:
        log_event(
            action='report.rejected',
            resource_type='ServiceRequest',
            resource_guid=service_request_guid,
            details={
                'reason': 'patient_mismatch',
                'provider_org_guid': provider_org_guid,
                'data_subject_guid': patient_guid,
            },
            ip_address=ip_address,
        )
        return {'code': 'validation_error',
                'message': 'Patient GUID does not match ServiceRequest'}, 400

    # 2. Verify contract match exists
    match = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
    ).first()

    if not match:
        log_event(
            action='report.rejected',
            resource_type='ServiceRequest',
            resource_guid=service_request_guid,
            details={
                'reason': 'no_match',
                'provider_org_guid': provider_org_guid,
                'contract_guid': contract_guid,
            },
            ip_address=ip_address,
        )
        return {'code': 'unauthorized',
                'message': 'No contract match for this provider and contract'}, 403

    # 3. Validate composite key (grant token)
    grant = validate_grant(
        service_request_guid=service_request_guid,
        patient_guid=patient_guid,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        grant_token=grant_token,
    )

    if not grant:
        log_event(
            action='report.rejected',
            resource_type='ServiceRequest',
            resource_guid=service_request_guid,
            details={
                'reason': 'invalid_grant',
                'provider_org_guid': provider_org_guid,
                'data_subject_guid': patient_guid,
            },
            ip_address=ip_address,
        )
        return {'code': 'unauthorized',
                'message': 'Invalid or expired grant token'}, 403

    # 4. Record the grant use
    use_grant(grant, action='report.grant_used', ip_address=ip_address)

    # 5. Update match status and store response
    match.status = report_status if report_status in ('completed', 'accepted', 'rejected') else 'acknowledged'
    match.response_at = datetime.now(timezone.utc)
    match.response_payload = {
        'status': report_status,
        'payload': report_payload,
        'received_at': datetime.now(timezone.utc).isoformat(),
    }
    db.session.commit()

    # 6. Audit
    log_event(
        action='report.received',
        resource_type='ServiceRequest',
        resource_guid=service_request_guid,
        details={
            'patient_guid': patient_guid,
            'provider_org_guid': provider_org_guid,
            'contract_guid': contract_guid,
            'report_status': report_status,
            'data_subject_guid': patient_guid,
        },
        ip_address=ip_address,
    )

    return {
        'status': 'recorded',
        'service_request_guid': service_request_guid,
        'match_status': match.status,
    }, 200
