"""Contract matching and offer/push logic for ServiceRequests."""

from datetime import datetime, timezone
from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestReceipt
)
from app.services import contract_service
from app.services.audit_service import log_event


def find_and_create_matches(service_request_guid, user_guid=None, ip_address=None):
    """Find matching contracts and create match records."""
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'active':
        return {'code': 'invalid_status', 'message': 'ServiceRequest must be active to match'}, 400

    contracts, status = contract_service.find_matching_contracts(sr.plan_definition_guid)
    if status != 200:
        return contracts, status

    created = []
    for contract in contracts:
        contract_guid = contract.get('id', '')
        # Skip if match already exists
        existing = ServiceRequestContractMatch.query.filter_by(
            service_request_guid=service_request_guid,
            contract_guid=contract_guid,
        ).first()
        if existing:
            continue

        # Extract provider from contract party with role "provider"
        parties = contract.get('party', [])
        provider_org_guid = ''
        provider_name = ''
        for p in parties:
            roles = p.get('role', [])
            is_provider = any(
                c.get('code') == 'provider'
                for r in roles for c in r.get('coding', [])
            )
            if is_provider:
                refs = p.get('reference', [])
                for ref_obj in refs:
                    ref = ref_obj.get('reference', '')
                    if ref.startswith('Organization/'):
                        provider_org_guid = ref.replace('Organization/', '')
                        provider_name = ref_obj.get('display', '')
                        break
            if provider_org_guid:
                break

        if not provider_org_guid:
            provider_org_guid = contract_guid
            provider_name = contract.get('name', contract.get('title', 'Unknown'))

        match = ServiceRequestContractMatch(
            service_request_guid=service_request_guid,
            contract_guid=contract_guid,
            provider_org_guid=provider_org_guid,
            provider_name=provider_name,
            match_type='offer',
            status='pending',
        )
        db.session.add(match)
        created.append(match)

    if created:
        # Set contract_guid on the SR from the first match (if not already set)
        if not sr.contract_guid:
            sr.contract_guid = created[0].contract_guid

        # Rebuild FHIR resource so basedOn includes the contract reference
        from app.services.fhir_builder_service import build_service_request_resource
        try:
            sr.fhir_resource = build_service_request_resource(sr)
        except Exception:
            pass  # Non-fatal — FHIR rebuild failure shouldn't block matching

        db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.match',
        resource_type='ServiceRequest',
        resource_guid=service_request_guid,
        details={'matches_created': len(created)},
        ip_address=ip_address,
    )

    return {
        'service_request_guid': service_request_guid,
        'matches_created': len(created),
        'matches': [m.to_dict() for m in created],
    }, 200


def list_matches_for_request(service_request_guid):
    """List all contract matches for a ServiceRequest."""
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404

    matches = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid
    ).order_by(ServiceRequestContractMatch.created_at.desc()).all()

    return {
        'service_request_guid': service_request_guid,
        'matches': [m.to_dict() for m in matches],
    }, 200


def update_match_status(match_guid, new_status, user_guid=None, ip_address=None):
    """Update match status (accept/reject)."""
    match = ServiceRequestContractMatch.query.filter_by(guid=match_guid).first()
    if not match:
        return {'code': 'not_found', 'message': 'Match not found'}, 404

    valid = ('pending', 'sent', 'accepted', 'rejected')
    if new_status not in valid:
        return {'code': 'bad_request', 'message': f'Status must be one of: {", ".join(valid)}'}, 400

    match.status = new_status
    if new_status in ('accepted', 'rejected'):
        match.response_at = datetime.now(timezone.utc)
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.match_status',
        resource_type='ServiceRequestContractMatch',
        resource_guid=match_guid,
        details={'new_status': new_status},
        ip_address=ip_address,
    )

    return match.to_dict(), 200
