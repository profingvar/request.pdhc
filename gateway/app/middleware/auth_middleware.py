import hmac as hmac_mod
from functools import wraps
from flask import current_app, request, jsonify, abort, g, redirect
from app.services.auth_service import get_current_access_blob, map_role, validate_api_key


def _sso_change_password_url():
    base = current_app.config['SSO_BASE_URL'].rstrip('/')
    return f'{base}/change-password'


def _must_change_password_response(blob):
    """Uniform response when SSO flags `must_change_password=True`.
    JSON 403 for API paths; redirect to SSO /change-password for HTML.
    Returns None if no change required."""
    if not blob or not blob.get('must_change_password'):
        return None
    if request.path.startswith('/api/'):
        return jsonify({
            'code': 'password_change_required',
            'message': 'Password change required before further actions',
            'change_password_url': _sso_change_password_url(),
        }), 403
    return redirect(_sso_change_password_url())


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
            mcp = _must_change_password_response(api_blob)
            if mcp is not None:
                return mcp
            return f(*args, **kwargs)

        # Ticket #50: session-based SSO auth must re-validate every request.
        # Calling get_current_access_blob() hits SSO /me/service; on failure
        # it wipes the session and returns None, which flips Flask-Login's
        # current_user.is_authenticated to False on the next check.
        blob = get_current_access_blob()
        if blob is None:
            if request.path.startswith('/api/'):
                return jsonify({'code': 'unauthenticated', 'message': 'Authentication required'}), 401
            abort(401)

        # Ticket #43 gate.
        mcp = _must_change_password_response(blob)
        if mcp is not None:
            return mcp

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


def requires_service_key(f):
    """Require X-Service-Key header for internal service-to-service calls.
    Uses constant-time comparison. Generic error on failure."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = current_app.config.get('INTERNAL_SERVICE_KEY')
        if not key:
            return jsonify({'error': 'unauthorized'}), 401
        provided = request.headers.get('X-Service-Key', '')
        if not provided or not hmac_mod.compare_digest(provided, key):
            return jsonify({'error': 'unauthorized'}), 401
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

            # Ticket #50: re-validate with SSO every request. blob==None means
            # the stored bearer was rejected (expired/revoked/flushed) and the
            # local session has already been wiped inside get_current_access_blob.
            blob = get_current_access_blob()
            if blob is None:
                if request.path.startswith('/api/'):
                    return jsonify({'code': 'unauthenticated', 'message': 'Authentication required'}), 401
                abort(401)

            # Ticket #43 gate — must come before the role check so a user
            # flagged for password reset can't slip through with an admin role.
            mcp = _must_change_password_response(blob)
            if mcp is not None:
                return mcp

            user_role = map_role(blob)
            if role_levels.get(user_role, 0) < role_levels.get(role, 0):
                if request.path.startswith('/api/'):
                    return jsonify({'code': 'unauthorized', 'message': 'Insufficient permissions'}), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator
