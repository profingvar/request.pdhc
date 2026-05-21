import requests
from flask import current_app, session
from app import db
from app.models.dispatch_models import LocalUser


def create_dev_user():
    """Create or fetch a local dev user for AUTH_DISABLED mode."""
    try:
        user = LocalUser.query.filter_by(role='admin').first()
        if not user:
            user = LocalUser(
                display_name='Dev Admin',
                email='dev@localhost',
                role='admin',
                is_active=True,
                access_blob={
                    'user_guid': 'dev-admin-guid',
                    'email': 'dev@localhost',
                    'user_type': 'professional',
                    'is_su_admin': True,
                    'effective_phases': ['planning', 'active', 'review'],
                    'organization_ids': [],
                    'groups': [],
                },
            )
            db.session.add(user)
            db.session.commit()
        return user
    except Exception:
        return None


def initiate_sso_login(next_url, state):
    """Build SSO login redirect URL."""
    sso_base = current_app.config['SSO_BASE_URL']
    callback = current_app.config['SSO_CALLBACK_URL']
    return f"{sso_base}/login?next={callback}&state={state}"


def validate_sso_token(token):
    """Validate a token against SSO and return the access blob."""
    sso_base = current_app.config['SSO_BASE_URL']
    try:
        resp = requests.get(
            f"{sso_base}/api/auth/me/service",
            headers={
                'Authorization': f'Bearer {token}',
                'X-SSO-Client-Id': current_app.config['SSO_CLIENT_ID'],
                'X-SSO-Client-Secret': current_app.config['SSO_CLIENT_SECRET'],
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def _clear_sso_session():
    """Drop all SSO state and log out the Flask-Login user.

    Called when SSO rejects a previously valid token (session flush,
    password reset, expiry, etc.). Next request will see an
    unauthenticated user and be redirected to /login.
    """
    session.pop('sso_token', None)
    session.pop('access_blob', None)
    try:
        from flask_login import logout_user
        logout_user()
    except Exception:
        pass


def get_current_access_blob():
    """Get the SSO access blob, re-validated against SSO on every call.

    Ticket #50: no caching. `session['access_blob']` is retained only as a
    display-side convenience and refreshed from each fresh /me/service
    response. All authorisation decisions MUST flow through this function
    so that SSO-side session flushes (SSO ticket #44) and forced password
    resets (SSO ticket #43) take effect immediately.

    Returns the blob on success, or None if the token is missing, expired,
    or revoked (in which case the local session is wiped).
    """
    if current_app.config.get('AUTH_DISABLED'):
        return {
            'user_guid': 'dev-admin-guid',
            'email': 'dev@localhost',
            'user_type': 'professional',
            'is_su_admin': True,
            'effective_phases': ['planning', 'active', 'review'],
            'organization_ids': [],
            'groups': [],
        }
    token = session.get('sso_token')
    if not token:
        return None
    blob = validate_sso_token(token)
    if blob is None:
        _clear_sso_session()
        return None
    # Display-only refresh; never trusted for authz.
    session['access_blob'] = blob
    return blob


def get_current_user_guid():
    """Get the current user's GUID."""
    blob = get_current_access_blob()
    if blob:
        return blob.get('user_guid')
    return None


def get_upstream_token():
    """Get the SSO token for forwarding to upstream services."""
    if current_app.config.get('AUTH_DISABLED'):
        return None
    return session.get('sso_token')


def map_role(access_blob):
    """Map SSO access blob to local role string."""
    if not access_blob:
        return 'read_only'
    if access_blob.get('is_su_admin'):
        return 'admin'
    if access_blob.get('user_type') == 'professional' and access_blob.get('effective_phases'):
        return 'read_write'
    return 'read_only'


def validate_api_key(api_key):
    """Validate an X-API-Key against SSO and return the access blob.

    Provider portals use this for service-to-service authentication.
    The key is validated by calling SSO's /api/auth/me with Bearer token.
    """
    if not api_key:
        return None
    sso_base = current_app.config['SSO_BASE_URL']
    try:
        resp = requests.get(
            f"{sso_base}/api/auth/me/service",
            headers={
                'Authorization': f'Bearer {api_key}',
                'X-SSO-Client-Id': current_app.config['SSO_CLIENT_ID'],
                'X-SSO-Client-Secret': current_app.config['SSO_CLIENT_SECRET'],
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def logout_sso(token):
    """Call SSO logout endpoint."""
    sso_base = current_app.config['SSO_BASE_URL']
    try:
        requests.post(
            f"{sso_base}/api/auth/logout",
            headers={'Authorization': f'Bearer {token}'},
            timeout=10,
        )
    except requests.RequestException:
        pass
