"""Provider API — feed, download, report endpoints.

All endpoints require X-Provider-Token (PAT) authentication.
Provider org identity is derived from the token, never from request params.
"""
from flask import Blueprint, request, jsonify, g

from app.middleware.auth_middleware import requires_provider_token
from app.services.audit_service import log_event

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


@provider_bp.route('/provider/report/<sr_guid>', methods=['POST'])
@requires_provider_token(scope='write')
def report(sr_guid):
    """Submit a report/response for a ServiceRequest.

    Requires the composite key: patient_guid, contract_guid,
    organisation_guid, grant_token.
    """
    from app.services.report_service import submit_report

    body = request.get_json()
    if not body:
        return jsonify({'code': 'bad_request', 'message': 'JSON body required'}), 400

    required = ['patient_guid', 'organisation_guid', 'grant_token', 'contract_guid']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({
            'code': 'validation_error',
            'message': f'Missing required fields: {", ".join(missing)}',
        }), 400

    # Verify the org in the body matches the PAT
    if body['organisation_guid'] != g.provider_org_guid:
        log_event(
            action='report.rejected',
            details={
                'reason': 'org_mismatch',
                'token_org': g.provider_org_guid,
                'body_org': body['organisation_guid'],
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
