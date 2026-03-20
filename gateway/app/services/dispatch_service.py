import requests
from flask import current_app
from app import db
from app.models.dispatch_models import DispatchRequest, DispatchReceipt
from app.services.auth_service import get_upstream_token
from app.services.audit_service import log_event


def _headers():
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    token = get_upstream_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def create_dispatch(careplan_guid, provider_guid, assigned_user_guid=None,
                    notes=None, idempotency_key=None, user_guid=None, ip_address=None):
    """Create and submit a dispatch request.

    Returns:
        tuple: (result_dict, status_code)
    """
    # Check idempotency — return existing if duplicate
    existing = DispatchRequest.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        receipt = DispatchReceipt.query.filter_by(dispatch_request_guid=existing.guid).first()
        return {
            'message': 'Duplicate dispatch — returning existing receipt',
            'dispatch_request': existing.to_dict(),
            'receipt': receipt.to_dict() if receipt else None,
        }, 200

    # Create local dispatch request record
    dispatch_req = DispatchRequest(
        careplan_guid=careplan_guid,
        provider_guid=provider_guid,
        assigned_user_guid=assigned_user_guid,
        dispatch_notes=notes,
        status='pending',
        idempotency_key=idempotency_key,
    )
    db.session.add(dispatch_req)
    db.session.flush()

    # Submit to upstream
    plan_base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    upstream_url = f"{plan_base}/api/v1/CarePlan/{careplan_guid}/dispatch"

    upstream_payload = {
        'provider_guid': provider_guid,
        'assigned_user_guid': assigned_user_guid,
        'notes': notes,
    }

    try:
        resp = requests.post(upstream_url, headers=_headers(), json=upstream_payload, timeout=15)

        if resp.status_code in (200, 201):
            dispatch_req.status = 'submitted'
            response_data = resp.json()
            receipt = DispatchReceipt(
                dispatch_request_guid=dispatch_req.guid,
                status='accepted',
                response_payload=response_data,
            )
        elif resp.status_code == 404:
            dispatch_req.status = 'failed'
            receipt = DispatchReceipt(
                dispatch_request_guid=dispatch_req.guid,
                status='error',
                response_payload={'error': 'CarePlan or provider not found upstream'},
            )
        else:
            dispatch_req.status = 'failed'
            receipt = DispatchReceipt(
                dispatch_request_guid=dispatch_req.guid,
                status='error',
                response_payload={'error': f'Upstream returned {resp.status_code}', 'body': resp.text[:500]},
            )
    except requests.RequestException as e:
        dispatch_req.status = 'failed'
        receipt = DispatchReceipt(
            dispatch_request_guid=dispatch_req.guid,
            status='error',
            response_payload={'error': f'Upstream connection failed: {str(e)}'},
        )

    db.session.add(receipt)
    db.session.commit()

    # Audit
    log_event(
        user_guid=user_guid,
        action='careplan.dispatch',
        resource_type='CarePlan',
        resource_guid=careplan_guid,
        details={
            'provider_guid': provider_guid,
            'dispatch_guid': dispatch_req.guid,
            'receipt_token': receipt.receipt_token,
            'status': receipt.status,
        },
        ip_address=ip_address,
    )

    status_code = 201 if receipt.status == 'accepted' else 502
    return {
        'dispatch_request': dispatch_req.to_dict(),
        'receipt': receipt.to_dict(),
    }, status_code


def get_dispatch_status(receipt_token):
    """Look up a dispatch receipt by token.

    Returns:
        tuple: (result_dict, status_code)
    """
    receipt = DispatchReceipt.query.filter_by(receipt_token=receipt_token).first()
    if not receipt:
        return {'code': 'not_found', 'message': 'Dispatch receipt not found'}, 404

    dispatch_req = DispatchRequest.query.filter_by(guid=receipt.dispatch_request_guid).first()
    return {
        'dispatch_request': dispatch_req.to_dict() if dispatch_req else None,
        'receipt': receipt.to_dict(),
    }, 200
