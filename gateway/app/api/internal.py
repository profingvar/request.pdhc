"""Internal API — service-to-service endpoints.

All endpoints require X-Service-Key header authentication.
Not exposed publicly, not accessible via PAT or SSO.
"""
import logging

import requests as http_requests
from flask import Blueprint, current_app, request, jsonify

from app.middleware.auth_middleware import requires_service_key

internal_bp = Blueprint('internal', __name__)

logger = logging.getLogger(__name__)


@internal_bp.route('/internal/service-request/<sr_guid>/context', methods=['GET'])
@requires_service_key
def get_sr_context(sr_guid):
    """Return pre-extracted SR context for gateway reconstruction.

    Gateway uses this to resolve transaction_guid → concept_guid,
    cross-check patient_guid, and enrich observations.
    """
    from app.services.context_service import get_sr_context as _get_context

    context = _get_context(sr_guid)
    if context is None:
        return jsonify({'error': 'not_found'}), 404

    return jsonify(context), 200


@internal_bp.route('/internal/grant/validate', methods=['POST'])
@requires_service_key
def validate_grant():
    """Validate a DataExchangeGrant token.

    Gateway calls this instead of validating HMAC locally,
    so the HMAC_SECRET never leaves request.pdhc.
    """
    from app.services.grant_service import validate_grant_detailed as _validate_detailed

    body = request.get_json(silent=True) or {}

    required = ['sr_guid', 'org_guid', 'patient_guid', 'grant_token']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({
            'valid': False,
            'error': f'Missing required fields: {", ".join(missing)}',
        }), 400

    grant, reason = _validate_detailed(
        service_request_guid=body['sr_guid'],
        patient_guid=body['patient_guid'],
        provider_org_guid=body['org_guid'],
        contract_guid=body.get('contract_guid', ''),
        grant_token=body['grant_token'],
    )

    if not grant:
        # Per provider integration guide Phase G #4-5: expired tokens
        # must be distinguishable from other invalid-grant cases so the
        # client can map them to GRANT_EXPIRED vs GRANT_TOKEN_INVALID.
        error_code = 'GRANT_EXPIRED' if reason == 'expired' else 'GRANT_TOKEN_INVALID'
        error_msg = {
            'expired': 'Grant token has expired',
            'revoked': 'Grant token has been revoked',
            'not_found': 'Grant not found',
            'patient_mismatch': 'Patient GUID does not match grant',
            'invalid_token': 'Invalid grant token',
        }.get(reason, 'Grant invalid, expired, or revoked')
        return jsonify({
            'valid': False,
            'error': error_msg,
            'error_code': error_code,
            'reason': reason,
        }), 200

    # Record usage
    from app.services.grant_service import use_grant
    use_grant(grant, action='grant.validated_by_gateway', ip_address=request.remote_addr)

    uses_remaining = None
    if grant.max_uses:
        uses_remaining = max(0, grant.max_uses - grant.used_count)

    return jsonify({
        'valid': True,
        'contract_guid': grant.contract_guid,
        'grant_type': grant.grant_type,
        'uses_remaining': uses_remaining,
    }), 200


@internal_bp.route('/internal/auto-provision-pat', methods=['POST'])
@requires_service_key
def auto_provision_pat():
    """Auto-provision a PAT for a provider org + contract.

    Called by contract.pdhc when a contract is created/updated.
    Fetches push config from SSO, creates PAT if none exists.
    """
    from app.models.security_models import ProviderAccessToken
    from app.services.pat_service import issue_pat

    body = request.get_json(silent=True) or {}
    provider_org_guid = body.get('provider_org_guid')
    contract_guid = body.get('contract_guid')

    if not provider_org_guid or not contract_guid:
        return jsonify({
            'error': 'provider_org_guid and contract_guid are required',
        }), 400

    # Check if a valid PAT already exists for this org+contract
    existing = ProviderAccessToken.query.filter_by(
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        revoked=False,
    ).first()

    if existing and existing.is_valid():
        return jsonify({
            'status': 'already_exists',
            'pat_guid': existing.guid,
            'delivery_mode': existing.delivery_mode,
        }), 200

    # Fetch push config from SSO (use internal URL to bypass nginx)
    sso_base = current_app.config.get('SSO_INTERNAL_URL', current_app.config['SSO_BASE_URL']).rstrip('/')
    service_key = current_app.config.get('INTERNAL_SERVICE_KEY', '')
    push_endpoint_url = None
    push_secret = None

    try:
        resp = http_requests.get(
            f"{sso_base}/internal/organisations/{provider_org_guid}/push-config",
            headers={'X-Service-Key': service_key},
            timeout=10,
        )
        if resp.status_code == 200:
            cfg = resp.json()
            push_endpoint_url = cfg.get('push_endpoint_url')
            push_secret = cfg.get('push_secret')
    except http_requests.RequestException as e:
        logger.warning("Failed to fetch push config from SSO: %s", e)

    # Determine delivery mode
    delivery_mode = 'push' if push_endpoint_url else 'poll'

    result, status = issue_pat(
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        scopes='read',
        delivery_mode=delivery_mode,
        push_endpoint_url=push_endpoint_url,
        push_auth_key=push_secret,
        created_by_user_guid='system:auto-provision',
        ip_address=request.remote_addr,
    )

    if status == 201:
        logger.info(
            "Auto-provisioned PAT for org=%s contract=%s mode=%s",
            provider_org_guid, contract_guid, delivery_mode,
        )
        # Don't leak the raw_token in the response — it's internal
        result.pop('raw_token', None)
        return jsonify({
            'status': 'provisioned',
            'pat_guid': result.get('guid'),
            'delivery_mode': delivery_mode,
        }), 201

    return jsonify({'error': 'pat_creation_failed', 'detail': result}), 500


@internal_bp.route('/internal/service-request/<sr_guid>/complete', methods=['POST'])
@requires_service_key
def mark_sr_complete(sr_guid):
    """Auto-close: flip this SR's provider contract-match to 'completed'.

    Called by gateway.pdhc once an accepted provider report marks the SR
    completed, so the provider feed reflects clinical completion rather than
    only the distribution status ('sent'). Idempotent; service-key
    authenticated. 404 if the SR is unknown (gateway tolerates it).
    """
    from app.services.completion_service import mark_service_request_completed

    result, code = mark_service_request_completed(
        sr_guid, source='gateway.pdhc', ip_address=request.remote_addr,
    )
    return jsonify(result), code
