from flask import Blueprint, render_template
from app.middleware.auth_middleware import requires_auth

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@requires_auth
def dashboard():
    """Dashboard overview page."""
    return render_template('dashboard.html')
