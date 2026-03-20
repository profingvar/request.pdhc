import os
from datetime import timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)


def create_app(testing=False):
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

    app = Flask(__name__)
    app.config.from_object('app.config.Config')

    if testing:
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = app.config.get(
            'TEST_DATABASE_URL', app.config['SQLALCHEMY_DATABASE_URI']
        )

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    limiter.init_app(app)

    app.permanent_session_lifetime = timedelta(hours=8)

    # Auto-login for local dev when AUTH_DISABLED
    if app.config.get('AUTH_DISABLED'):
        @app.before_request
        def _auto_login():
            from flask_login import login_user, current_user
            from flask import session
            if not current_user.is_authenticated:
                session.permanent = True
                # Create a mock user object for dev
                from app.services.auth_service import create_dev_user
                user = create_dev_user()
                if user:
                    login_user(user)

    # Import models so they are registered with SQLAlchemy
    from app.models import dispatch_models, audit_models, export_models  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.dispatch_models import LocalUser
        return LocalUser.query.get(int(user_id))

    # Register API blueprints
    from app.api.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')

    from app.api.patients import patients_bp
    app.register_blueprint(patients_bp, url_prefix='/api/v1')

    from app.api.careplans import careplans_bp
    app.register_blueprint(careplans_bp, url_prefix='/api/v1')

    from app.api.dispatch import dispatch_bp
    app.register_blueprint(dispatch_bp, url_prefix='/api/v1')

    from app.api.providers import providers_bp
    app.register_blueprint(providers_bp, url_prefix='/api/v1')

    from app.api.export import export_bp
    app.register_blueprint(export_bp, url_prefix='/api/v1')

    from app.api.capability import capability_bp
    app.register_blueprint(capability_bp, url_prefix='/api/v1')

    # Register web UI blueprints
    from app.routes.main import main_bp
    app.register_blueprint(main_bp)

    from app.routes.patients import patients_web_bp
    app.register_blueprint(patients_web_bp)

    from app.routes.careplans import careplans_web_bp
    app.register_blueprint(careplans_web_bp)

    from app.routes.dispatch import dispatch_web_bp
    app.register_blueprint(dispatch_web_bp)

    from app.routes.export import export_web_bp
    app.register_blueprint(export_web_bp)

    # Health endpoint
    @app.route('/api/health')
    def health():
        from flask import jsonify
        return jsonify({'status': 'ok'}), 200

    # JSON error handlers for API routes
    @app.errorhandler(400)
    def bad_request(e):
        from flask import jsonify, request
        if request.path.startswith('/api/'):
            return jsonify({'code': 'bad_request', 'message': str(e)}), 400
        return e

    @app.errorhandler(401)
    def unauthorized(e):
        from flask import jsonify, request
        if request.path.startswith('/api/'):
            return jsonify({'code': 'unauthenticated', 'message': 'Authentication required'}), 401
        return e

    @app.errorhandler(403)
    def forbidden(e):
        from flask import jsonify, request
        if request.path.startswith('/api/'):
            return jsonify({'code': 'unauthorized', 'message': 'Insufficient permissions'}), 403
        return e

    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify, request
        if request.path.startswith('/api/'):
            return jsonify({'code': 'not_found', 'message': 'Resource not found'}), 404
        return e

    @app.errorhandler(500)
    def internal_error(e):
        from flask import jsonify, request
        if request.path.startswith('/api/'):
            return jsonify({'code': 'internal_error', 'message': 'Internal server error'}), 500
        return e

    return app
