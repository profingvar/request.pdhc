"""Admin API for Provider Access Token management.

All endpoints require SU admin authentication.
"""
from flask import Blueprint, request, jsonify

from app.middleware.auth_middleware import requires_auth, requires_role
from app.services.auth_service import get_current_user_guid

admin_tokens_bp = Blueprint('admin_tokens', __name__)


@admin_tokens_bp.route('/admin/provider-tokens', methods=['POST'])
@requires_auth
@requires_role('admin')
def issue_token():
    """Issue a new Provider Access Token."""
    from app.services.pat_service import issue_pat

    body = request.get_json()
    if not body:
        return jsonify({'code': 'bad_request', 'message': 'JSON body required'}), 400

    required = ['provider_org_guid', 'contract_guid']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({
            'code': 'validation_error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    data, status = issue_pat(
        provider_org_guid=body['provider_org_guid'],
        contract_guid=body['contract_guid'],
        scopes=body.get('scopes', 'read'),
        delivery_mode=body.get('delivery_mode', 'poll'),
        push_endpoint_url=body.get('push_endpoint_url'),
        push_auth_key=body.get('push_auth_key'),
        expires_days=body.get('expires_days'),
        created_by_user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )

    return jsonify(data), status


@admin_tokens_bp.route('/admin/provider-tokens', methods=['GET'])
@requires_auth
@requires_role('admin')
def list_tokens():
    """List Provider Access Tokens."""
    from app.services.pat_service import list_pats

    provider_org_guid = request.args.get('provider_org_guid')
    include_revoked = request.args.get('include_revoked', 'false').lower() == 'true'

    data, status = list_pats(
        provider_org_guid=provider_org_guid,
        include_revoked=include_revoked,
    )

    return jsonify(data), status


@admin_tokens_bp.route('/admin/provider-tokens/<guid>', methods=['DELETE'])
@requires_auth
@requires_role('admin')
def revoke_token(guid):
    """Revoke a Provider Access Token."""
    from app.services.pat_service import revoke_pat

    data, status = revoke_pat(
        pat_guid=guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )

    return jsonify(data), status
