"""Push delivery logic for ServiceRequests.

Sends finalized FHIR ServiceRequests to matched provider endpoints,
creates delivery receipts for tracking, and handles response callbacks.
"""

import base64
import json
import requests as http_requests
from datetime import datetime, timezone
from flask import current_app
from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch, ServiceRequestReceipt
)
from app.services.auth_service import get_upstream_token
from app.services.audit_service import log_event


def _headers():
    headers = {'Content-Type': 'application/fhir+json', 'Accept': 'application/fhir+json'}
    token = get_upstream_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def push_to_provider(match_guid, user_guid=None, ip_address=None):
    """Push a ServiceRequest to a matched provider.

    Sends the FHIR resource to the provider's endpoint,
    creates a receipt, and updates match status.

    Returns:
        tuple: (result_dict, status_code)
    """
    match = ServiceRequestContractMatch.query.filter_by(guid=match_guid).first()
    if not match:
        return {'code': 'not_found', 'message': 'Match not found'}, 404

    if match.status not in ('pending', 'sent'):
        return {'code': 'invalid_status',
                'message': f'Cannot push match in status: {match.status}'}, 400

    sr = ServiceRequest.query.filter_by(guid=match.service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404

    if sr.status != 'active':
        return {'code': 'invalid_status',
                'message': 'ServiceRequest must be active to push'}, 400

    if not sr.fhir_resource:
        return {'code': 'invalid_state',
                'message': 'ServiceRequest has no FHIR resource — finalize first'}, 400

    # Create receipt before push attempt
    receipt = ServiceRequestReceipt(
        service_request_guid=sr.guid,
        contract_match_guid=match.guid,
        delivery_method='push',
        delivery_status='pending',
        delivery_payload=sr.fhir_resource,
    )
    db.session.add(receipt)
    db.session.flush()

    # Build provider endpoint URL from PAT records
    provider_url, push_auth_key = _get_provider_endpoint(match.provider_org_guid)

    # Issue a DataExchangeGrant for this push
    from app.services.grant_service import issue_grant
    grant_data, _ = issue_grant(
        service_request_guid=sr.guid,
        patient_guid=sr.patient_guid,
        provider_org_guid=match.provider_org_guid,
        contract_guid=match.contract_guid,
    )

    if provider_url:
        try:
            push_entries = [{'resource': sr.fhir_resource}]

            # Add render-ready Binary entries for each attached form
            if hasattr(sr, 'forms'):
                for srf in sr.forms:
                    if srf.render_ready_snapshot:
                        rr_b64 = base64.b64encode(
                            json.dumps(srf.render_ready_snapshot).encode()
                        ).decode()
                        push_entries.append({
                            'resource': {
                                'resourceType': 'Binary',
                                'contentType': 'application/json',
                                'data': rr_b64,
                                'meta': {
                                    'tag': [
                                        {'system': 'https://pdhc.se/forms',
                                         'code': 'form_guid',
                                         'display': srf.form_guid},
                                        {'system': 'https://pdhc.se/forms',
                                         'code': 'render_ready',
                                         'display': srf.display_title or ''},
                                    ],
                                },
                            },
                        })

            push_payload = {
                'resourceType': 'Bundle',
                'type': 'message',
                'entry': push_entries,
                'meta': {
                    'tag': [
                        {'system': 'https://pdhc.se/delivery', 'code': 'receipt_token',
                         'display': receipt.receipt_token},
                        {'system': 'https://pdhc.se/delivery', 'code': 'grant_token',
                         'display': grant_data.get('grant_token', '')},
                        {'system': 'https://pdhc.se/delivery', 'code': 'expires_at',
                         'display': grant_data.get('expires_at', '')},
                        {'system': 'https://pdhc.se/delivery', 'code': 'organisation_guid',
                         'display': match.provider_org_guid},
                        {'system': 'https://pdhc.se/delivery', 'code': 'contract_guid',
                         'display': match.contract_guid},
                        {'system': 'https://pdhc.se/delivery', 'code': 'service_request_guid',
                         'display': sr.guid},
                        {'system': 'https://pdhc.se/delivery', 'code': 'patient_guid',
                         'display': sr.patient_guid},
                    ],
                },
            }

            push_headers = _headers()
            if push_auth_key:
                push_headers['X-API-Key'] = push_auth_key

            resp = http_requests.post(
                provider_url,
                headers=push_headers,
                json=push_payload,
                timeout=30,
            )

            if resp.status_code in (200, 201, 202):
                receipt.delivery_status = 'delivered'
                match.status = 'sent'
                match.sent_at = datetime.now(timezone.utc)
            else:
                receipt.delivery_status = 'failed'
                receipt.response_payload = {
                    'status_code': resp.status_code,
                    'body': resp.text[:1000],
                }
        except http_requests.RequestException as e:
            receipt.delivery_status = 'failed'
            receipt.response_payload = {'error': str(e)}
    else:
        # No endpoint configured — mark as sent (offer mode, provider polls)
        receipt.delivery_status = 'queued'
        match.status = 'sent'
        match.sent_at = datetime.now(timezone.utc)

    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='service_request.push',
        resource_type='ServiceRequestContractMatch',
        resource_guid=match.guid,
        details={
            'service_request_guid': sr.guid,
            'provider_org_guid': match.provider_org_guid,
            'delivery_status': receipt.delivery_status,
            'receipt_token': receipt.receipt_token,
        },
        ip_address=ip_address,
    )

    return {
        'match': match.to_dict(),
        'receipt': receipt.to_dict(),
        'delivery_status': receipt.delivery_status,
    }, 200


def push_all_matches(service_request_guid, user_guid=None, ip_address=None):
    """Push to all pending matches for a ServiceRequest.

    Also pushes directly to 1177 if the SR has forms attached.

    Returns:
        tuple: (result_dict, status_code)
    """
    sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
    if not sr:
        return {'code': 'not_found', 'message': 'ServiceRequest not found'}, 404

    matches = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid,
        status='pending',
    ).all()

    results = []
    for match in matches:
        result, _ = push_to_provider(match.guid, user_guid=user_guid, ip_address=ip_address)
        results.append(result)

    # Always push forms to 1177 when SR has forms with Questionnaire snapshots
    forms_result = None
    has_forms = hasattr(sr, 'forms') and any(f.form_snapshot for f in sr.forms)
    if has_forms:
        forms_result = _push_forms_to_1177(sr, user_guid=user_guid, ip_address=ip_address)

    if not matches and not has_forms:
        return {'code': 'no_matches', 'message': 'No pending matches and no forms to push'}, 400

    return {
        'service_request_guid': service_request_guid,
        'pushed': len(results),
        'results': results,
        'forms_1177': forms_result,
    }, 200


def _push_forms_to_1177(sr, user_guid=None, ip_address=None):
    """Push the SR bundle with form Binaries directly to 1177.pdhc webhook.

    Returns a status dict (not a tuple).
    """
    webhook_url = current_app.config.get('FORMS_1177_WEBHOOK_URL', '')
    api_key = current_app.config.get('FORMS_1177_API_KEY', '')
    org_guid = current_app.config.get('FORMS_1177_ORG_GUID', '')

    if not webhook_url or not api_key:
        return {'status': 'skipped', 'reason': 'FORMS_1177_WEBHOOK_URL or FORMS_1177_API_KEY not configured'}

    if not sr.fhir_resource:
        return {'status': 'skipped', 'reason': 'No FHIR resource on SR'}

    forms_with_questionnaire = [f for f in sr.forms if f.form_snapshot]
    if not forms_with_questionnaire:
        return {'status': 'skipped', 'reason': 'No forms with Questionnaire snapshot'}

    # Issue a grant for 1177 delivery
    from app.services.grant_service import issue_grant
    grant_data, _ = issue_grant(
        service_request_guid=sr.guid,
        patient_guid=sr.patient_guid,
        provider_org_guid=org_guid,
        contract_guid=sr.contract_guid or '',
    )

    push_entries = [{'resource': sr.fhir_resource}]
    for srf in forms_with_questionnaire:
        if not srf.render_ready_snapshot:
            continue
        rr_b64 = base64.b64encode(
            json.dumps(srf.render_ready_snapshot).encode()
        ).decode()
        push_entries.append({
            'resource': {
                'resourceType': 'Binary',
                'contentType': 'application/json',
                'data': rr_b64,
                'meta': {
                    'tag': [
                        {'system': 'https://pdhc.se/forms', 'code': 'form_guid',
                         'display': srf.form_guid},
                        {'system': 'https://pdhc.se/forms', 'code': 'render_ready',
                         'display': srf.display_title or ''},
                    ],
                },
            },
        })

    push_payload = {
        'resourceType': 'Bundle',
        'type': 'message',
        'entry': push_entries,
        'meta': {
            'tag': [
                {'system': 'https://pdhc.se/delivery', 'code': 'grant_token',
                 'display': grant_data.get('grant_token', '')},
                {'system': 'https://pdhc.se/delivery', 'code': 'expires_at',
                 'display': grant_data.get('expires_at', '')},
                {'system': 'https://pdhc.se/delivery', 'code': 'organisation_guid',
                 'display': org_guid},
                {'system': 'https://pdhc.se/delivery', 'code': 'contract_guid',
                 'display': sr.contract_guid or ''},
                {'system': 'https://pdhc.se/delivery', 'code': 'service_request_guid',
                 'display': sr.guid},
                {'system': 'https://pdhc.se/delivery', 'code': 'patient_guid',
                 'display': sr.patient_guid},
            ],
        },
    }

    try:
        resp = http_requests.post(
            webhook_url,
            headers={
                'Content-Type': 'application/fhir+json',
                'X-API-Key': api_key,
            },
            json=push_payload,
            timeout=current_app.config.get('PUSH_TIMEOUT_SECONDS', 30),
        )
        status = 'delivered' if resp.status_code in (200, 201, 202) else 'failed'
        result = {'status': status, 'http_status': resp.status_code}
        if status == 'failed':
            result['body'] = resp.text[:500]
    except http_requests.RequestException as e:
        result = {'status': 'failed', 'error': str(e)}

    log_event(
        user_guid=user_guid,
        action='service_request.push_forms_1177',
        resource_type='ServiceRequest',
        resource_guid=sr.guid,
        details={'forms_count': len(forms_with_questionnaire), 'result': result.get('status')},
        ip_address=ip_address,
    )

    return result


def handle_provider_response(receipt_token, response_payload):
    """Handle a provider's response via receipt token.

    Called when a provider sends back an acceptance/rejection
    using the receipt_token from the push bundle.

    Returns:
        tuple: (result_dict, status_code)
    """
    receipt = ServiceRequestReceipt.query.filter_by(receipt_token=receipt_token).first()
    if not receipt:
        return {'code': 'not_found', 'message': 'Receipt not found'}, 404

    if receipt.response_received:
        return {'code': 'already_responded', 'message': 'Response already recorded'}, 400

    receipt.response_received = True
    receipt.response_payload = response_payload

    # Update match status based on response
    match = ServiceRequestContractMatch.query.filter_by(guid=receipt.contract_match_guid).first()
    if match:
        status = response_payload.get('status', 'acknowledged')
        if status in ('accepted', 'rejected', 'acknowledged'):
            match.status = status
            match.response_at = datetime.now(timezone.utc)
            match.response_payload = response_payload

    db.session.commit()

    log_event(
        action='service_request.provider_response',
        resource_type='ServiceRequestReceipt',
        resource_guid=receipt.guid,
        details={
            'receipt_token': receipt_token,
            'response_status': response_payload.get('status'),
            'service_request_guid': receipt.service_request_guid,
        },
    )

    # Auto-archive when fulfilled: all matches resolved and at least one accepted
    if match and match.status == 'accepted':
        _check_auto_archive_on_fulfillment(receipt.service_request_guid)

    return {
        'receipt_token': receipt_token,
        'status': 'recorded',
        'match_status': match.status if match else None,
    }, 200


def _check_auto_archive_on_fulfillment(service_request_guid):
    """Auto-archive a ServiceRequest when all matches are resolved with at least one accepted."""
    from app.models.service_request_models import ServiceRequest

    all_matches = ServiceRequestContractMatch.query.filter_by(
        service_request_guid=service_request_guid
    ).all()
    if not all_matches:
        return

    resolved = all(m.status in ('accepted', 'rejected') for m in all_matches)
    has_accepted = any(m.status == 'accepted' for m in all_matches)

    if resolved and has_accepted:
        sr = ServiceRequest.query.filter_by(guid=service_request_guid).first()
        if sr and sr.status == 'active':
            sr.status = 'archived'
            db.session.commit()
            log_event(
                action='service_request.auto_archive',
                resource_type='ServiceRequest',
                resource_guid=service_request_guid,
                details={'reason': 'all_matches_resolved'},
            )


def get_receipt(receipt_token):
    """Look up a delivery receipt by token.

    Returns:
        tuple: (result_dict, status_code)
    """
    receipt = ServiceRequestReceipt.query.filter_by(receipt_token=receipt_token).first()
    if not receipt:
        return {'code': 'not_found', 'message': 'Receipt not found'}, 404
    return receipt.to_dict(), 200


def list_receipts_for_request(service_request_guid):
    """List all delivery receipts for a ServiceRequest.

    Returns:
        tuple: (result_dict, status_code)
    """
    receipts = ServiceRequestReceipt.query.filter_by(
        service_request_guid=service_request_guid
    ).order_by(ServiceRequestReceipt.created_at.desc()).all()

    return {
        'service_request_guid': service_request_guid,
        'receipts': [r.to_dict() for r in receipts],
    }, 200


def _get_provider_endpoint(provider_org_guid):
    """Look up the push endpoint for a provider organisation.

    Resolves from ProviderAccessToken records with delivery_mode=push.
    Returns (url, push_auth_key) or (None, None).
    """
    from app.models.security_models import ProviderAccessToken
    pat = ProviderAccessToken.query.filter_by(
        provider_org_guid=provider_org_guid,
        delivery_mode='push',
        revoked=False,
    ).first()
    if pat and pat.is_valid() and pat.push_endpoint_url:
        return pat.push_endpoint_url, pat.push_auth_key_encrypted
    return None, None
