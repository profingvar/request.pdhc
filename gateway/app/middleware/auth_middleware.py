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
        # #1045: get_current_access_blob trusts g.api_key_access_blob, so a
        # value left on `g` by an earlier request sharing the app context (the
        # test client inside a pushed context) must never carry over.
        g.pop('api_key_access_blob', None)
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

        # #996: request's WEB pages are for professionals and SU admins.
        # Before this, any SSO account that completed the login — a patient
        # included — reached every web page; only the care-unit filters
        # stood between it and the data. Same shape as ips's
        # admin_access_policy (#902). The API keeps its own per-route gates.
        if not request.path.startswith('/api/') and not web_user_allowed(blob):
            from app.services.audit_service import log_event
            log_event(user_guid=blob.get('user_guid'), action='web.access.denied',
                      ip_address=request.remote_addr,
                      details={'reason': 'not_professional_or_su',
                               'user_type': blob.get('user_type'), 'path': request.path})
            abort(403)

        return f(*args, **kwargs)
    return decorated


def web_user_allowed(blob):
    """Professional or SU admin (#996). Pure, so it can be tested alone."""
    if not blob:
        return False
    return bool(blob.get('is_su_admin')) or blob.get('user_type') == 'professional'


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


# ---------------------------------------------------------------------------
# #984 — NAMED service identities (X-Source-Service + X-Service-Key)
# ---------------------------------------------------------------------------
#
# `requires_service_key` above is one shared, anonymous key (gateway.pdhc and
# contract.pdhc both hold INTERNAL_SERVICE_KEY), so it cannot say WHO called.
# The diagnosis-review completion must refuse every caller but icd11.pdhc, so
# icd11.pdhc gets its own key and its own name — the header pair and the
# name -> env-var map used by cdr (KNOWN_FHIR_SERVICES) and plan (#931).
#
# READ-ONLY BY DEFAULT, as cdr's #760: an identity in
# READ_ONLY_SERVICE_SOURCES may use GET/HEAD/OPTIONS only, unless the ROUTE
# grants that identity a write explicitly (`write_grant=`). icd11.pdhc's only
# write grant is the diagnosis-review completion endpoint. These keys open
# nothing else: `requires_auth`/`requires_service_key` never read them.
KNOWN_SERVICE_KEYS = {
    'icd11.pdhc': 'ICD11_PDHC_SERVICE_KEY',
}
READ_ONLY_SERVICE_SOURCES = frozenset({'icd11.pdhc'})
_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


def named_service_outcome(source, key, method, allowed, write_grant=()):
    """Pure decision: (None, source) when admitted, else (body, status).

    Separated so the read-only rule can be tested without issuing a write
    (CLAUDE.md: never verify a write grant by writing).
    """
    source = (source or '').strip()
    key = (key or '').strip()
    want = ', '.join(sorted(allowed))
    if not source or not key:
        return {'code': 'unauthenticated',
                'message': f'X-Source-Service and X-Service-Key of {want} '
                           f'required'}, 401
    cfg_var = KNOWN_SERVICE_KEYS.get(source)
    expected = (current_app.config.get(cfg_var) or '').strip() if cfg_var else ''
    if not expected or not hmac_mod.compare_digest(key, expected):
        # Unknown name, unset key and wrong key look the same from outside.
        return {'code': 'unauthenticated',
                'message': f'X-Source-Service and X-Service-Key of {want} '
                           f'required'}, 401
    if source not in allowed:
        return {'code': 'service_not_permitted',
                'message': f'{source} may not call this endpoint; only {want}'}, 403
    if (source in READ_ONLY_SERVICE_SOURCES and method not in _SAFE_METHODS
            and source not in write_grant):
        return {'code': 'service_read_only',
                'message': f'{source} holds a read-only service key'}, 403
    return None, source


def requires_named_service(*allowed, write_grant=()):
    """Admit only the named service identities in `allowed` (see above).

    Never bypassed by AUTH_DISABLED: a machine identity is not a dev login.
    Sets g.source_service.
    """
    allowed = frozenset(allowed)
    write_grant = frozenset(write_grant)

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            body, outcome = named_service_outcome(
                request.headers.get('X-Source-Service'),
                request.headers.get('X-Service-Key'),
                request.method, allowed, write_grant)
            if body is not None:
                from app.services.audit_service import log_event
                log_event(action='service_key.rejected',
                          details={'endpoint': request.path,
                                   'source': (request.headers.get('X-Source-Service') or '')[:64],
                                   'code': body['code']},
                          ip_address=request.remote_addr)
                return jsonify(body), outcome
            g.source_service = outcome
            return f(*args, **kwargs)
        return decorated
    return decorator
