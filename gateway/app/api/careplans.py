import bleach
from flask import Blueprint, jsonify, request
from app.middleware.auth_middleware import requires_auth
from app.services import careplan_service
from app.services.audit_service import audit_read, log_event
from app.services.auth_service import get_current_user_guid

careplans_bp = Blueprint('careplans_api', __name__)


@careplans_bp.route('/CarePlan', methods=['GET'])
@requires_auth
@audit_read('careplan.list', resource_type='CarePlan')
def list_careplans():
    """List/search careplans (proxy to Plan)."""
    params = dict(request.args)
    data, status = careplan_service.list_careplans(params)
    return jsonify(data), status


@careplans_bp.route('/CarePlan/<guid>', methods=['GET'])
@requires_auth
def get_careplan(guid):
    """Read a single careplan by GUID.

    Uses inline ``log_event`` (not ``@audit_read``) because the
    existing ``careplan.view`` action and shape pre-date #227 and
    callers may already filter on it.
    """
    guid = bleach.clean(guid)
    data, status = careplan_service.get_careplan(guid)

    if status == 200:
        log_event(
            user_guid=get_current_user_guid(),
            action='careplan.view',
            resource_type='CarePlan',
            resource_guid=guid,
            ip_address=request.remote_addr,
        )

    return jsonify(data), status
