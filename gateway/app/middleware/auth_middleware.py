from functools import wraps
from flask import current_app, request, jsonify, abort, g
from flask_login import current_user
from app.services.auth_service import get_current_access_blob, map_role, validate_api_key


def _check_api_key():
    """Check for X-API-Key header and validate against SSO.
    Returns the access blob if valid, None otherwise.
    Used by provider portals for service-to-service auth."""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return None
    if current_app.config.get('AUTH_DISABLED'):
        return {
            'user_guid': 'api-key-dev',
            'email': 'apikey@localhost',
            'user_type': 'service',
            'is_su_admin': False,
            'provider_guid': request.args.get('provider_guid', ''),
            'effective_phases': ['active'],
            'organisation_ids': [],
            'groups': [],
        }
    return validate_api_key(api_key)


def requires_auth(f):
    """Require authentication. Accepts session, Bearer token, or X-API-Key.
    In AUTH_DISABLED mode, passes through."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get('AUTH_DISABLED'):
            return f(*args, **kwargs)

        # Check X-API-Key first (service-to-service)
        api_blob = _check_api_key()
        if api_blob:
            g.api_key_access_blob = api_blob
            return f(*args, **kwargs)

        if not current_user.is_authenticated:
            if request.path.startswith('/api/'):
                return jsonify({'code': 'unauthenticated', 'message': 'Authentication required'}), 401
            abort(401)
        return f(*args, **kwargs)
    return decorated


def requires_role(role):
    """Require a minimum role level: read_only < read_write < admin."""
    role_levels = {'read_only': 0, 'read_write': 1, 'admin': 2}

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if current_app.config.get('AUTH_DISABLED'):
                return f(*args, **kwargs)

            # API key auth — service accounts get read_write
            api_blob = getattr(g, 'api_key_access_blob', None)
            if api_blob:
                api_role = map_role(api_blob) if api_blob.get('user_type') != 'service' else 'read_write'
                if role_levels.get(api_role, 0) < role_levels.get(role, 0):
                    return jsonify({'code': 'unauthorized', 'message': 'Insufficient permissions'}), 403
                return f(*args, **kwargs)

            if not current_user.is_authenticated:
                if request.path.startswith('/api/'):
                    return jsonify({'code': 'unauthenticated', 'message': 'Authentication required'}), 401
                abort(401)

            blob = get_current_access_blob()
            user_role = map_role(blob)
            if role_levels.get(user_role, 0) < role_levels.get(role, 0):
                if request.path.startswith('/api/'):
                    return jsonify({'code': 'unauthorized', 'message': 'Insufficient permissions'}), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator
