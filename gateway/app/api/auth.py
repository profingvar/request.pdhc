import uuid
from flask import (
    Blueprint, jsonify, request, redirect, session, url_for, current_app,
    render_template_string,
)
from flask_login import login_user, logout_user, current_user
from app import db
from app.models.dispatch_models import LocalUser
from app.services.auth_service import (
    initiate_sso_login, validate_sso_token, map_role, logout_sso, get_current_access_blob
)
from app.services.audit_service import log_event

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET'])
def login():
    """Initiate SSO login handshake."""
    if current_app.config.get('AUTH_DISABLED'):
        return redirect(url_for('main.dashboard'))

    next_url = request.args.get('next', url_for('main.dashboard'))
    state = str(uuid.uuid4())
    session['sso_state'] = state
    session['sso_next'] = next_url
    return redirect(initiate_sso_login(next_url, state))


@auth_bp.route('/callback', methods=['GET'])
def callback():
    """Handle SSO callback with token."""
    token = request.args.get('token')
    state = request.args.get('state')

    if not token:
        return jsonify({'code': 'auth_error', 'message': 'No token received from SSO'}), 400

    expected_state = session.pop('sso_state', None)
    if state != expected_state:
        return jsonify({'code': 'auth_error', 'message': 'Invalid state parameter'}), 400

    access_blob = validate_sso_token(token)
    if not access_blob:
        return jsonify({'code': 'auth_error', 'message': 'Token validation failed'}), 401

    # Store token and blob in session
    session['sso_token'] = token
    session['access_blob'] = access_blob
    session.permanent = True

    # Create or update local user record
    sso_guid = access_blob.get('user_guid')
    user = LocalUser.query.filter_by(sso_user_guid=sso_guid).first()
    if not user:
        user = LocalUser(
            sso_user_guid=sso_guid,
            email=access_blob.get('email'),
            display_name=access_blob.get('display_name', access_blob.get('email', '')),
            role=map_role(access_blob),
            access_blob=access_blob,
        )
        db.session.add(user)
    else:
        user.role = map_role(access_blob)
        user.access_blob = access_blob

    from datetime import datetime, timezone
    user.last_login = datetime.now(timezone.utc)
    db.session.commit()

    login_user(user)

    log_event(
        user_guid=sso_guid,
        action='auth.login',
        ip_address=request.remote_addr,
    )

    next_url = session.pop('sso_next', url_for('main.dashboard'))
    return redirect(next_url)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout: clear local session and call SSO logout."""
    token = session.get('sso_token')
    user_guid = None
    blob = get_current_access_blob()
    if blob:
        user_guid = blob.get('user_guid')

    logout_user()
    if token:
        logout_sso(token)
    session.clear()

    log_event(
        user_guid=user_guid,
        action='auth.logout',
        ip_address=request.remote_addr,
    )

    # The route lives under /api/, so a path prefix can't tell a browser
    # form POST from a programmatic caller — use content negotiation. JSON/
    # API clients get JSON; a browser gets a logged-out page that ALSO kills
    # the SSO browser session, so the next login re-authenticates fresh
    # (picking up any affiliation/blob changes).
    if request.is_json or not request.accept_mimetypes.accept_html:
        return jsonify({'message': 'Logged out'}), 200
    return redirect(url_for('auth.logged_out'))


@auth_bp.route('/logged-out', methods=['GET'])
def logged_out():
    """Post-logout landing page. Auto-submits a hidden POST to the SSO
    browser /logout endpoint so the sso.pdhc session cookie is terminated
    too — without this the next 'login' silently re-authenticates from the
    surviving SSO session and the user appears never to have logged out."""
    base = (current_app.config.get('SSO_BASE_URL') or '').rstrip('/')
    sso_logout_url = f"{base}/logout" if base else ''
    return render_template_string(
        LOGGED_OUT_PAGE, sso_logout_url=sso_logout_url,
        login_url=url_for('auth.login'))


LOGGED_OUT_PAGE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Logged out — request.pdhc</title>
<style>
  body { font-family: system-ui, sans-serif; display: flex; justify-content: center;
         align-items: center; min-height: 100vh; margin: 0; background: #f5f5f5; }
  .box { text-align: center; background: white; padding: 2rem 3rem; border-radius: 8px;
         box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  a { color: #2563eb; text-decoration: none; font-weight: 600; }
</style>
</head>
<body>
<div class="box">
  <h2>You have been logged out</h2>
  <p><a href="{{ login_url }}">Log in again</a></p>
</div>
{% if sso_logout_url %}
<iframe name="sso_frame" style="display:none;"></iframe>
<form id="ssoLogout" method="post" action="{{ sso_logout_url }}" target="sso_frame"></form>
<script>document.getElementById('ssoLogout').submit();</script>
{% endif %}
</body>
</html>
"""


@auth_bp.route('/me', methods=['GET'])
def me():
    """Return current user access blob."""
    blob = get_current_access_blob()
    if not blob:
        return jsonify({'code': 'unauthenticated', 'message': 'Not authenticated'}), 401
    return jsonify(blob), 200
