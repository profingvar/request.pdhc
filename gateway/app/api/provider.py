"""Provider API — feed, download, report endpoints.

All endpoints require X-Provider-Token (PAT) authentication.
Provider org identity is derived from the token, never from request params.
"""
from flask import Blueprint, request, jsonify, g

from app.middleware.auth_middleware import requires_provider_token
from app.services.audit_service import log_event
from app.services.secret_crypto import decrypt as decrypt_secret

provider_bp = Blueprint('provider', __name__)


@provider_bp.route('/provider/feed', methods=['GET'])
@requires_provider_token(scope='read')
def feed():
    """List ServiceRequests addressed to this provider (metadata only).

    No patient data in the listing — GDPR data minimization.
    Provider must download individual SRs to get the FHIR Bundle.
    """
    from app.services.provider_feed_service import list_for_provider

    since = request.args.get('since')
    limit = min(int(request.args.get('limit', 50)), 200)

    data, status = list_for_provider(
        provider_org_guid=g.provider_org_guid,
        since=since,
        limit=limit,
    )

    log_event(
        action='feed.accessed',
        resource_type='ServiceRequest',
        details={
            'provider_org_guid': g.provider_org_guid,
            'result_count': len(data.get('items', [])),
        },
        ip_address=request.remote_addr,
    )

    return jsonify(data), status


@provider_bp.route('/provider/download/<sr_guid>', methods=['GET'])
@requires_provider_token(scope='read')
def download(sr_guid):
    """Download the full FHIR Bundle for a specific ServiceRequest.

    Issues a DataExchangeGrant if none exists for this provider+SR.
    Returns the FHIR Bundle + grant_token for future report submission.
    """
    from app.services.provider_feed_service import download_bundle

    data, status = download_bundle(
        service_request_guid=sr_guid,
        provider_org_guid=g.provider_org_guid,
        contract_guid=g.provider_contract_guid,
        ip_address=request.remote_addr,
    )

    return jsonify(data), status


def _handle_status_update(sr_guid):
    """Shared handler for status-update submissions.

    NOTE on naming: this endpoint records ServiceRequest LIFECYCLE state
    (in-progress / completed / etc.) on request.pdhc — it is NOT for
    observation data. Observation data must be POSTed to
    `gateway.pdhc /api/v1/provider/report/<sr_guid>` which writes
    InboundObservation rows after PAT + grant + SR-context validation.

    A payload sent here is stored on the contract-match for audit but
    will NEVER reach inbound_observations. Providers that conflated the
    two endpoints have silently lost observation data — see the
    /provider/report alias below.
    """
    from app.services.report_service import submit_report

    body = request.get_json()
    if not body:
        return jsonify({'code': 'bad_request', 'message': 'JSON body required'}), 400

    # #294 / #306 phase 6: canonical wire key is `provider_org_guid`;
    # legacy alias `organisation_guid` still accepted. Required-set
    # check uses whichever is present.
    body_provider_org = (body.get('provider_org_guid')
                         or body.get('organisation_guid'))
    required = ['patient_guid', 'grant_token', 'contract_guid']
    missing = [f for f in required if not body.get(f)]
    if not body_provider_org:
        missing.append('provider_org_guid')
    if missing:
        return jsonify({
            'code': 'validation_error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    # Verify the org in the body matches the PAT
    if body_provider_org != g.provider_org_guid:
        log_event(
            action='report.rejected',
            details={
                'reason': 'org_mismatch',
                'token_org': g.provider_org_guid,
                'body_org': body_provider_org,
            },
            ip_address=request.remote_addr,
        )
        return jsonify({
            'code': 'unauthorized',
            'message': 'Organisation GUID does not match token',
        }), 403

    data, status = submit_report(
        service_request_guid=sr_guid,
        patient_guid=body['patient_guid'],
        provider_org_guid=g.provider_org_guid,
        contract_guid=body['contract_guid'],
        grant_token=body['grant_token'],
        report_status=body.get('status', 'completed'),
        report_payload=body.get('report_payload'),
        ip_address=request.remote_addr,
    )

    return jsonify(data), status


@provider_bp.route('/provider/status/<sr_guid>', methods=['POST'])
@requires_provider_token(scope='write')
def status_update(sr_guid):
    """Submit a lifecycle status update for a ServiceRequest (canonical path).

    Requires the composite key: patient_guid, contract_guid,
    organisation_guid, grant_token.

    For observation DATA, POST to `gateway.pdhc /api/v1/provider/report/<sr_guid>`
    instead — that path writes inbound_observations after full validation.
    """
    return _handle_status_update(sr_guid)


@provider_bp.route('/provider/report/<sr_guid>', methods=['POST'])
@requires_provider_token(scope='write')
def report_deprecated_alias(sr_guid):
    """DEPRECATED alias for /provider/status/<sr_guid>.

    Kept so existing provider integrations don't break, but the path is
    misnamed — this is a status-update endpoint, not an observation
    submission endpoint. The same URL on `gateway.pdhc` is the actual
    report endpoint. See `_handle_status_update`'s docstring.

    Logs a `report.deprecated_alias_used` audit event so we can spot
    providers still calling the old path before removing it.
    """
    log_event(
        action='report.deprecated_alias_used',
        resource_type='ServiceRequest',
        resource_guid=sr_guid,
        details={
            'provider_org_guid': g.provider_org_guid,
            'note': 'Provider POSTed to /provider/report; canonical path is '
                    '/provider/status (request.pdhc) or /provider/report '
                    '(gateway.pdhc) for observation data.',
        },
        ip_address=request.remote_addr,
    )
    return _handle_status_update(sr_guid)


@provider_bp.route('/provider/validate-token', methods=['POST'])
def validate_token():
    """Validate a raw Provider Access Token — called by gateway.pdhc.

    No authentication required on this endpoint (the token IS the credential).
    Returns provider identity if valid, 401 if not.
    """
    from app.services.pat_service import validate_pat

    body = request.get_json(silent=True) or {}
    raw_token = body.get('token', '')
    if not raw_token:
        return jsonify({'code': 'bad_request', 'message': 'token required'}), 400

    pat = validate_pat(raw_token)
    if not pat:
        return jsonify({'code': 'invalid_token', 'message': 'Token not found, expired, or revoked'}), 401

    return jsonify({
        'valid': True,
        'provider_org_guid': pat.provider_org_guid,
        'contract_guid': pat.contract_guid,
        'scopes': pat.scopes,
        'delivery_mode': pat.delivery_mode,
        # Gateway uses these to route receipts back to this specific
        # provider (instead of a global PROVIDER_SERVICE_URL). The
        # push_auth_key is the mutual secret the provider expects on
        # its receipt ingestion endpoint (same value used for X-Push-Secret
        # on inbound bundles).
        'push_endpoint_url': pat.push_endpoint_url,
        'push_auth_key': decrypt_secret(pat.push_auth_key_encrypted),  # #151: decrypt for the gateway
    }), 200


@provider_bp.route('/provider/receipt/<receipt_token>/ack', methods=['POST'])
@requires_provider_token(scope='write')
def ack_receipt(receipt_token):
    """Acknowledge a push delivery receipt."""
    from app.services.push_service import handle_provider_response

    body = request.get_json() or {}
    body.setdefault('status', 'acknowledged')

    data, status = handle_provider_response(
        receipt_token, body, provider_org_guid=g.provider_org_guid,
    )
    return jsonify(data), status
