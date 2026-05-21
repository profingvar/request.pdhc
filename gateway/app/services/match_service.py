"""Contract matching and offer/push logic for ServiceRequests."""

from datetime import datetime, timezone
from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestReceipt
)
from app.services import contract_service
from app.services.audit_service import log_event


def _extract_provider(contract):
    """Extract provider org GUID and name from a FHIR Contract resource."""
    parties = contract.get('party', [])
    for p in parties:
        roles = p.get('role', [])
        is_provider = any(
            c.get('code') == 'provider'
            for r in roles for c in r.get('coding', [])
        )
        if is_provider:
            for ref_obj in p.get('reference', []):
                ref = ref_obj.get('reference', '')
                if ref.startswith('Organization/'):
                    return ref.replace('Organization/', ''), ref_obj.get('display', '')
    return '', ''


def find_eligible_providers(service_request_guid):
    """Find providers eligible for a ServiceRequest (read-only, no DB writes).

    Returns a list of dicts with contract and provider info.
    """
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'active':
        return {'code': 'invalid_status', 'message': 'ServiceRequest must be active to match'}, 400

    # Contracts may reference the PlanDefinition's database guid or its fhir_id.
    snap = sr.plan_definition_snapshot or {}
    pd_fhir_id = snap.get('fhir_id') or (snap.get('fhir_data') or {}).get('id')
    contracts, status = contract_service.find_matching_contracts(
        plan_definition_guid=sr.plan_definition_guid,
        plan_definition_fhir_id=pd_fhir_id,
    )
    if status != 200:
        return contracts, status

    # Filter out providers that already have a match for this SR
    existing_pairs = {
        (m.contract_guid, m.provider_org_guid)
        for m in ServiceRequestContractMatch.query.filter_by(
            service_request_guid=service_request_guid
        ).all()
    }

    eligible = []
    for contract in contracts:
        contract_guid = contract.get('id', '')
        contract_title = contract.get('title', contract.get('name', ''))
        provider_org_guid, provider_name = _extract_provider(contract)
        if not provider_org_guid:
            continue
        if (contract_guid, provider_org_guid) in existing_pairs:
            continue
        eligible.append({
            'contract_guid': contract_guid,
            'contract_title': contract_title,
            'provider_org_guid': provider_org_guid,
            'provider_name': provider_name,
        })

    return {'eligible': eligible}, 200


def dispatch_to_provider(service_request_guid, contract_guid, provider_org_guid,
                         provider_name='', user_guid=None, ip_address=None):
    """Create a match for a single chosen provider and push the SR to them."""
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'active':
        return {'code': 'invalid_status', 'message': 'ServiceRequest must be active'}, 400

    # Prevent duplicate
    existing = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid,
        contract_guid=contract_guid,
        provider_org_guid=provider_org_guid,
    ).first()
    if existing:
        return {'code': 'duplicate', 'message': 'Provider already matched'}, 409

    match = ServiceRequestContractMatch(
        service_request_guid=service_request_guid,
        contract_guid=contract_guid,
        provider_org_guid=provider_org_guid,
        provider_name=provider_name,
        match_type='offer',
        status='pending',
    )
    db.session.add(match)

    # Set contract on the SR if not already set
    if not sr.contract_guid:
        sr.contract_guid = contract_guid

    # Rebuild FHIR resource with contract reference
    from app.services.fhir_builder_service import build_service_request_resource
    try:
        sr.fhir_resource = build_service_request_resource(sr)
    except Exception:
        pass

    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.dispatch',
        resource_type='ServiceRequest',
        resource_guid=service_request_guid,
        details={
            'contract_guid': contract_guid,
            'provider_org_guid': provider_org_guid,
            'provider_name': provider_name,
        },
        ip_address=ip_address,
    )

    # Push to the provider
    from app.services.push_service import push_to_provider
    push_result, push_status = push_to_provider(
        match.guid, user_guid=user_guid, ip_address=ip_address,
    )

    return {
        'match': match.to_dict(),
        'push': push_result,
    }, 200


def find_and_create_matches(service_request_guid, user_guid=None, ip_address=None):
    """Find matching contracts and create match records (legacy — creates all)."""
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404
    if sr.status != 'active':
        return {'code': 'invalid_status', 'message': 'ServiceRequest must be active to match'}, 400

    # Contracts may reference the PlanDefinition's database guid or its fhir_id.
    snap = sr.plan_definition_snapshot or {}
    pd_fhir_id = snap.get('fhir_id') or (snap.get('fhir_data') or {}).get('id')
    contracts, status = contract_service.find_matching_contracts(
        plan_definition_guid=sr.plan_definition_guid,
        plan_definition_fhir_id=pd_fhir_id,
    )
    if status != 200:
        return contracts, status

    created = []
    for contract in contracts:
        contract_guid = contract.get('id', '')
        existing = ServiceRequestContractMatch.query.filter_by(
            service_request_guid=service_request_guid,
            contract_guid=contract_guid,
        ).first()
        if existing:
            continue

        provider_org_guid, provider_name = _extract_provider(contract)
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
        if not sr.contract_guid:
            sr.contract_guid = created[0].contract_guid
        from app.services.fhir_builder_service import build_service_request_resource
        try:
            sr.fhir_resource = build_service_request_resource(sr)
        except Exception:
            pass
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
