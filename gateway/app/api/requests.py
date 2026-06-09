"""API endpoints for the provider subscription feed.

These endpoints are consumed by provider.pdhc instances polling
for dispatched requests addressed to them."""

import bleach
from flask import Blueprint, jsonify, request
from app.middleware.auth_middleware import requires_auth
from app.services import request_feed_service
from app.services.audit_service import audit_read, log_event

requests_bp = Blueprint('requests_api', __name__)


@requests_bp.route('/requests', methods=['GET'])
@requires_auth
@audit_read('request.list', resource_type='ServiceRequest')
def list_requests():
    """List dispatched requests for a provider.

    Query params:
        provider_guid (required): The provider to filter on.
        since: ISO-8601 datetime — only return requests updated after this.
        cursor: Opaque cursor for pagination.
        status: Filter by dispatch status.
        _count: Max results (default 100).
    """
    provider_guid = request.args.get('provider_guid')
    if not provider_guid:
        return jsonify({
            'code': 'bad_request',
            'message': 'provider_guid query parameter is required',
        }), 400

    provider_guid = bleach.clean(provider_guid)
    since = request.args.get('since')
    cursor = request.args.get('cursor')
    status = request.args.get('status')
    limit = min(int(request.args.get('_count', 100)), 500)

    data = request_feed_service.list_requests_for_provider(
        provider_guid=provider_guid,
        since=since,
        cursor=cursor,
        status=status,
        limit=limit,
    )

    return jsonify(data), 200


@requests_bp.route('/requests/<request_guid>', methods=['GET'])
@requires_auth
@audit_read('request.read', resource_type='ServiceRequest', guid_arg='request_guid')
def get_request(request_guid):
    """Get a single dispatched request by GUID."""
    request_guid = bleach.clean(request_guid)
    data, status = request_feed_service.get_single_request(request_guid)
    return jsonify(data), status


@requests_bp.route('/requests/<request_guid>/status', methods=['PUT'])
@requires_auth
def update_request_status(request_guid):
    """Update the provider-side status on a dispatched request.

    Body:
        provider_guid (required): Must match the request's provider.
        status (required): One of: acknowledged, in_progress, completed, rejected.
    """
    request_guid = bleach.clean(request_guid)
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'code': 'bad_request', 'message': 'Request body required'}), 400

    provider_guid = payload.get('provider_guid')
    new_status = payload.get('status')

    if not provider_guid or not new_status:
        return jsonify({
            'code': 'bad_request',
            'message': 'provider_guid and status are required',
        }), 400

    provider_guid = bleach.clean(provider_guid)
    new_status = bleach.clean(new_status)

    data, status_code = request_feed_service.update_provider_status(
        request_guid=request_guid,
        provider_guid=provider_guid,
        new_status=new_status,
    )

    if status_code == 200:
        log_event(
            user_guid=provider_guid,
            action='request.status_update',
            resource_type='DispatchRequest',
            resource_guid=request_guid,
            details={'new_status': new_status, 'provider_guid': provider_guid},
            ip_address=request.remote_addr,
        )

    return jsonify(data), status_code
