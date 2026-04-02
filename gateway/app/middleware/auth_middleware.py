from functools import wraps
from flask import current_app, request, jsonify, abort, g
from flask_login import current_user
from app.services.auth_service import get_current_access_blob, map_role, validate_api_key


def _check_provider_token():
    """Check for X-Provider-Token header and validate against PAT store.
    Sets g.provider_pat, g.provider_org_guid, g.provider_contract_guid.
    Returns True if valid PAT found, False otherwise."""
    raw_token = request.headers.get('X-Provider-Token')
    if not raw_token:
        return False
    from app.services.pat_service import validate_pat
    pat = validate_pat(raw_token)
    if not pat:
        return False
    g.provider_pat = pat
    g.provider_org_guid = pat.provider_org_guid
    g.provider_contract_guid = pat.contract_guid
    g.provider_delivery_mode = pat.delivery_mode
    from app.services.audit_service import log_event
    log_event(
        action='pat.validated',
        resource_type='ProviderAccessToken',
        resource_guid=pat.guid,
        details={
            'provider_org_guid': pat.provider_org_guid,
            'endpoint': request.path,
        },
        ip_address=request.remote_addr,
    )
    return True


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
            'effective_phases': ['active'],
            'organization_ids': [],
            'groups': [],
        }
    return validate_api_key(api_key)


def requires_auth(f):
    """Require authentication. Accepts session, Bearer token, X-API-Key, or X-Provider-Token.
    In AUTH_DISABLED mode, passes through."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_app.config.get('AUTH_DISABLED'):
            return f(*args, **kwargs)

        # Check X-Provider-Token first (provider org auth)
        if _check_provider_token():
            return f(*args, **kwargs)

        # Check X-API-Key (service-to-service via SSO)
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


def requires_provider_token(scope='read'):
    """Require a valid Provider Access Token with the given scope.
    Sets g.provider_org_guid from the token record (never from request params)."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if current_app.config.get('AUTH_DISABLED'):
                # Dev bypass — use fixed dev identities, never from request params
                g.provider_org_guid = 'dev-org-00000000'
                g.provider_contract_guid = 'dev-contract-00000000'
                g.provider_delivery_mode = 'poll'
                return f(*args, **kwargs)

            if not _check_provider_token():
                from app.services.audit_service import log_event
                log_event(
                    action='pat.rejected',
                    details={'endpoint': request.path, 'reason': 'invalid_or_missing_token'},
                    ip_address=request.remote_addr,
                )
                return jsonify({
                    'code': 'unauthenticated',
                    'message': 'Valid X-Provider-Token header required',
                }), 401

            pat = g.provider_pat
            if not pat.has_scope(scope):
                return jsonify({
                    'code': 'unauthorized',
                    'message': f'Token missing required scope: {scope}',
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


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
