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


# ─────────────────────────────────────────────────────────────────────
# #598 — HTTP forms of the `flask provider …` CLI, for onboard.pdhc.
#
# onboard.pdhc runs in its own container and cannot shell into
# request_pdhc_app, so OB-8 (mint the secret) and OB-10 (verify + go-live
# gate) need these over HTTP. Same SU-admin gate as the routes above.
#
# Raw secrets appear in a response body exactly once, at creation or
# rotation, and are never logged. Every route audits through the service
# layer it wraps.
# ─────────────────────────────────────────────────────────────────────


@admin_tokens_bp.route('/admin/provider-tokens/<guid>/rotate', methods=['POST'])
@requires_auth
@requires_role('admin')
def rotate_token(guid):
    """Rotate a PAT: issue a new active one, deprecate the old.

    Addressed by the CURRENT token's guid, which is what a caller holding
    a provider record has. rotate_pat itself works on org+contract, so the
    guid is resolved to those first.

    The old token keeps working for PAT_DEPRECATED_GRACE_DAYS (14 by
    default) so the provider can swap without an outage.
    """
    from app.models.security_models import ProviderAccessToken
    from app.services.pat_service import rotate_pat

    pat = ProviderAccessToken.query.filter_by(guid=guid).first()
    if not pat:
        return jsonify({'code': 'not_found',
                        'message': 'Provider access token not found'}), 404

    body = request.get_json(silent=True) or {}
    data, status = rotate_pat(
        provider_org_guid=pat.provider_org_guid,
        contract_guid=pat.contract_guid,
        expires_days=body.get('expires_days'),
        created_by_user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@admin_tokens_bp.route('/admin/signing-secrets', methods=['POST'])
@requires_auth
@requires_role('admin')
def issue_signing_secret():
    """Issue a webhook signing secret. Plaintext returned once, here only."""
    from app.services.webhook_secret_service import register_secret

    body = request.get_json(silent=True) or {}
    org = body.get('provider_org_guid')
    if not org:
        return jsonify({'code': 'validation_error',
                        'message': 'Missing required field: provider_org_guid'}), 400

    data, status = register_secret(
        provider_org_guid=org,
        created_by_user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@admin_tokens_bp.route('/admin/signing-secrets', methods=['GET'])
@requires_auth
@requires_role('admin')
def list_signing_secrets():
    """List signing secrets for an org. Never returns secret material."""
    from app.models.security_models import WebhookSigningSecret

    org = request.args.get('provider_org_guid')
    if not org:
        return jsonify({'code': 'validation_error',
                        'message': 'provider_org_guid query parameter required'}), 400

    rows = (WebhookSigningSecret.query
            .filter_by(provider_org_guid=org)
            .order_by(WebhookSigningSecret.issued_at.desc())
            .all())
    return jsonify({
        'items': [{
            'guid': r.guid,
            'provider_org_guid': r.provider_org_guid,
            'status': r.status,
            'issued_at': r.issued_at.isoformat() if r.issued_at else None,
            'deprecated_at': (r.deprecated_at.isoformat()
                              if r.deprecated_at else None),
            'revoked_at': r.revoked_at.isoformat() if r.revoked_at else None,
            'rotated_to_guid': r.rotated_to_guid,
        } for r in rows],
        'total': len(rows),
    }), 200


@admin_tokens_bp.route('/admin/signing-secrets/<guid>/rotate', methods=['POST'])
@requires_auth
@requires_role('admin')
def rotate_signing_secret(guid):
    """Rotate an org's signing secret; the previous one stays valid for
    verification during the grace window. Plaintext returned once."""
    from app.models.security_models import WebhookSigningSecret
    from app.services.webhook_secret_service import rotate_secret

    row = WebhookSigningSecret.query.filter_by(guid=guid).first()
    if not row:
        return jsonify({'code': 'not_found',
                        'message': 'Signing secret not found'}), 404

    data, status = rotate_secret(
        provider_org_guid=row.provider_org_guid,
        created_by_user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@admin_tokens_bp.route('/admin/signing-secrets/<guid>', methods=['DELETE'])
@requires_auth
@requires_role('admin')
def revoke_signing_secret(guid):
    """Revoke signing secrets for the org this secret belongs to.

    NOTE the scope, which is wider than the URL suggests: the underlying
    revoke_secret revokes EVERY active and deprecated secret for the org,
    not just this one, because a half-revoked org would still verify
    bodies signed with the sibling secret. The response lists exactly
    which guids were revoked so the caller is not misled.
    """
    from app.models.security_models import WebhookSigningSecret
    from app.services.webhook_secret_service import revoke_secret

    row = WebhookSigningSecret.query.filter_by(guid=guid).first()
    if not row:
        return jsonify({'code': 'not_found',
                        'message': 'Signing secret not found'}), 404

    data, status = revoke_secret(
        provider_org_guid=row.provider_org_guid,
        user_guid=get_current_user_guid(),
        ip_address=request.remote_addr,
    )
    return jsonify(data), status


@admin_tokens_bp.route('/admin/sandbox-dispatch', methods=['POST'])
@requires_auth
@requires_role('admin')
def sandbox_dispatch():
    """Go-live rehearsal: deliver a synthetic event, then replay it with
    the same event id to verify the provider de-duplicates. Same logic as
    `flask provider sandbox-dispatch`, rendered as JSON.

    Returns 200 with result PASS or FAIL — a FAIL is a successful test run
    reporting a provider-side problem, not a server error.
    """
    from app.services import sandbox_service

    body = request.get_json(silent=True) or {}
    org = body.get('provider_org_guid')
    contract = body.get('contract_guid')
    if not org or not contract:
        return jsonify({
            'code': 'validation_error',
            'message': 'Missing required fields: provider_org_guid, contract_guid',
        }), 400

    data, status = sandbox_service.run_dispatch(
        provider_org_guid=org,
        contract_guid=contract,
        concept_guids=body.get('concept_guids'),
        webhook_url=body.get('webhook_url'),
        patient_guid=body.get('patient_guid', 'SANDBOX-PATIENT'),
        immediate=body.get('immediate', True),
    )
    return jsonify(data), status


@admin_tokens_bp.route('/admin/sandbox-sign', methods=['POST'])
@requires_auth
@requires_role('admin')
def sandbox_sign():
    """Return the four PDHC headers the dispatcher would send for a given
    payload, so a provider engineer can check their HMAC against ours."""
    import json as _json

    from app.services import sandbox_service

    body = request.get_json(silent=True) or {}
    org = body.get('provider_org_guid')
    if not org or 'payload' not in body:
        return jsonify({
            'code': 'validation_error',
            'message': 'Missing required fields: provider_org_guid, payload',
        }), 400

    payload = body['payload']
    # Sign exactly the bytes the dispatcher would send: a string payload is
    # signed as given, an object is canonicalised the way enqueue() does.
    if isinstance(payload, str):
        body_bytes = payload.encode('utf-8')
    else:
        body_bytes = _json.dumps(
            payload, separators=(',', ':'), sort_keys=True,
        ).encode('utf-8')

    data, status = sandbox_service.sign_payload(org, body_bytes)
    return jsonify(data), status
