import uuid
from flask import Blueprint, jsonify, request, redirect, session, url_for, current_app
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

    if request.path.startswith('/api/'):
        return jsonify({'message': 'Logged out'}), 200
    return redirect(url_for('auth.login'))


@auth_bp.route('/me', methods=['GET'])
def me():
    """Return current user access blob."""
    blob = get_current_access_blob()
    if not blob:
        return jsonify({'code': 'unauthenticated', 'message': 'Not authenticated'}), 401
    return jsonify(blob), 200
