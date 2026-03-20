from functools import wraps
from flask import current_app, request, jsonify, abort
from flask_login import current_user
from app.services.auth_service import get_current_access_blob, map_role


def requires_auth(f):
    """Require authentication. In AUTH_DISABLED mode, passes through."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get('AUTH_DISABLED'):
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
