from flask import Blueprint, jsonify, request
from app.middleware.auth_middleware import requires_auth
from app.services import provider_service

providers_bp = Blueprint('providers_api', __name__)


@providers_bp.route('/providers', methods=['GET'])
@requires_auth
def list_providers():
    """List providers (proxy to Plan backend)."""
    params = dict(request.args)
    data, status = provider_service.list_providers(params)
    return jsonify(data), status
