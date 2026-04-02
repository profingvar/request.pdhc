"""Internal API — service-to-service endpoints for gateway.pdhc.

All endpoints require X-Service-Key header authentication.
Not exposed publicly, not accessible via PAT or SSO.
"""
from flask import Blueprint, request, jsonify

from app.middleware.auth_middleware import requires_service_key

internal_bp = Blueprint('internal', __name__)


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
    from app.services.grant_service import validate_grant as _validate

    body = request.get_json(silent=True) or {}

    required = ['sr_guid', 'org_guid', 'patient_guid', 'grant_token']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({
            'valid': False,
            'error': f'Missing required fields: {", ".join(missing)}',
        }), 400

    grant = _validate(
        service_request_guid=body['sr_guid'],
        patient_guid=body['patient_guid'],
        provider_org_guid=body['org_guid'],
        contract_guid=body.get('contract_guid', ''),
        grant_token=body['grant_token'],
    )

    if not grant:
        return jsonify({
            'valid': False,
            'error': 'Grant invalid, expired, or revoked',
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
