"""Provider feed service — list and download ServiceRequests for a provider org.

The feed returns metadata only (no patient data). The provider must
call download_bundle() to get the full FHIR resource + exchange grant.
"""
from datetime import datetime, timezone

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch,
)
from app.services.grant_service import issue_grant, use_grant
from app.services.audit_service import log_event


def list_for_provider(provider_org_guid, since=None, limit=50):
    """List ServiceRequests matched to this provider org.

    Returns metadata only — no patient data (GDPR data minimization).

    Args:
        provider_org_guid: from validated PAT (never from request params)
        since: ISO datetime string, return only items updated after this
        limit: max items to return

    Returns:
        tuple: (result_dict, status_code)
    """
    query = db.session.query(
        ServiceRequestContractMatch, ServiceRequest
    ).join(
        ServiceRequest,
        ServiceRequest.guid == ServiceRequestContractMatch.service_request_guid,
    ).filter(
        ServiceRequestContractMatch.provider_org_guid == provider_org_guid,
        ServiceRequestContractMatch.status.in_(['pending', 'sent', 'accepted']),
        ServiceRequest.status == 'active',
    )

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            query = query.filter(ServiceRequestContractMatch.updated_at > since_dt)
        except (ValueError, TypeError):
            pass

    query = query.order_by(ServiceRequestContractMatch.created_at.desc())
    results = query.limit(limit).all()

    items = []
    for match, sr in results:
        snapshot = sr.plan_definition_snapshot or {}
        items.append({
            'service_request_guid': sr.guid,
            'match_guid': match.guid,
            'status': match.status,
            'title': snapshot.get('title', ''),
            'intent': sr.intent,
            'priority': sr.priority,
            'contract_guid': match.contract_guid,
            'created_at': sr.created_at.isoformat(),
            'updated_at': match.updated_at.isoformat(),
            'download_url': f'/api/v1/provider/download/{sr.guid}',
        })

    return {'items': items, 'total': len(items)}, 200


def download_bundle(service_request_guid, provider_org_guid, contract_guid,
                    ip_address=None):
    """Download the full FHIR Bundle for a ServiceRequest.

    Verifies the provider has a matching contract, issues a DataExchangeGrant
    if none exists, and returns the FHIR resource with the grant token.

    Returns:
        tuple: (result_dict, status_code)
    """
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404

    if sr.status != 'active':
        return {'code': 'invalid_status',
                'message': 'ServiceRequest is not active'}, 400

    # Verify match exists for this provider
    match = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid,
        provider_org_guid=provider_org_guid,
    ).first()

    if not match:
        return {'code': 'unauthorized',
                'message': 'No contract match for this provider'}, 403

    if not sr.fhir_resource:
        return {'code': 'not_ready',
                'message': 'FHIR resource not yet assembled'}, 400

    # Issue or retrieve grant
    grant_data, _ = issue_grant(
        service_request_guid=sr.guid,
        patient_guid=sr.patient_guid,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
    )

    # Record download in audit
    log_event(
        action='bundle.downloaded',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        details={
            'patient_guid': sr.patient_guid,
            'provider_org_guid': provider_org_guid,
            'contract_guid': contract_guid,
            'data_subject_guid': sr.patient_guid,
        },
        ip_address=ip_address,
    )

    return {
        'fhir_resource': sr.fhir_resource,
        'grant_token': grant_data['grant_token'],
        'service_request_guid': sr.guid,
        'patient_guid': sr.patient_guid,
        'contract_guid': contract_guid,
        'provider_org_guid': provider_org_guid,
    }, 200
