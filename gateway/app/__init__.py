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
    login_manager.login_view = 'auth.login'
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
    from app.models import dispatch_models, audit_models, export_models, service_request_models, security_models  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id):
        from app.models.dispatch_models import LocalUser
        return LocalUser.query.get(int(user_id))

    # Register API blueprints
    from app.api.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')

    from app.api.patients import patients_bp
    app.register_blueprint(patients_bp, url_prefix='/api/v1')

    from app.api.dispatch import dispatch_bp
    app.register_blueprint(dispatch_bp, url_prefix='/api/v1')

    from app.api.providers import providers_bp
    app.register_blueprint(providers_bp, url_prefix='/api/v1')

    from app.api.export import export_bp
    app.register_blueprint(export_bp, url_prefix='/api/v1')

    from app.api.requests import requests_bp
    app.register_blueprint(requests_bp, url_prefix='/api/v1')

    from app.api.service_requests import service_requests_bp
    app.register_blueprint(service_requests_bp, url_prefix='/api/v1')

    from app.api.capability import capability_bp
    app.register_blueprint(capability_bp, url_prefix='/api/v1')

    from app.api.provider import provider_bp
    app.register_blueprint(provider_bp, url_prefix='/api/v1')

    from app.api.admin_tokens import admin_tokens_bp
    app.register_blueprint(admin_tokens_bp, url_prefix='/api/v1')

    from app.api.internal import internal_bp
    app.register_blueprint(internal_bp, url_prefix='/api/v1')

    # Register web UI blueprints
    from app.routes.main import main_bp
    app.register_blueprint(main_bp)

    from app.routes.patients import patients_web_bp
    app.register_blueprint(patients_web_bp)

    from app.routes.dispatch import dispatch_web_bp
    app.register_blueprint(dispatch_web_bp)

    from app.routes.export import export_web_bp
    app.register_blueprint(export_web_bp)

    from app.routes.service_requests import service_requests_web_bp
    app.register_blueprint(service_requests_web_bp)

    from app.routes.docs import docs_bp
    app.register_blueprint(docs_bp)

    from app.routes.api_docs import api_docs_bp
    app.register_blueprint(api_docs_bp)

    # Health endpoint
    @app.route('/api/health')
    def health():
        from flask import jsonify
        from sqlalchemy import text
        db_ok = False
        try:
            db.session.execute(text('SELECT 1'))
            db_ok = True
        except Exception:
            pass
        status = 'ok' if db_ok else 'degraded'
        code = 200 if db_ok else 503
        resp = jsonify({
            'status': status,
            'database': 'connected' if db_ok else 'unavailable',
            'service': 'request.pdhc',
        })
        # Ticket #70 / CLAUDE.md §10: let www.pdhc.se/services.html read the
        # JSON body cross-origin so it can drive real status/DB dots. Specific
        # origin + Vary: Origin (not "*") keeps future Allow-Credentials
        # spec-compliant.
        resp.headers['Access-Control-Allow-Origin'] = 'https://www.pdhc.se'
        resp.headers['Access-Control-Allow-Methods'] = 'GET'
        resp.headers['Vary'] = 'Origin'
        resp.headers['Cache-Control'] = 'no-store'
        return resp, code

    # JSON error handlers for API routes
    @app.errorhandler(400)
    def bad_request(e):
        from flask import jsonify, request
        if request.path.startswith('/api/'):
            return jsonify({'code': 'bad_request', 'message': str(e)}), 400
        return e

    @app.errorhandler(401)
    def unauthorized(e):
        from flask import jsonify, request, redirect, url_for
        if request.path.startswith('/api/'):
            return jsonify({'code': 'unauthenticated', 'message': 'Authentication required'}), 401
        return redirect(url_for('auth.login', next=request.url))

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

    # CLI commands — provider lifecycle (ticket #136)
    _register_provider_cli(app)

    @app.cli.command('seed-1177-pat')
    def seed_1177_pat():
        """Issue a push PAT for 1177.pdhc.se webhook delivery."""
        from app.services.pat_service import issue_pat
        data, status = issue_pat(
            provider_org_guid='14b25a1f-63b4-4369-810b-15388d22947b',
            contract_guid='df1e2436-4fb8-4a31-a06b-d89f9efc1800',
            scopes='read,write',
            delivery_mode='push',
            push_endpoint_url='https://1177.pdhc.se/api/webhook/inbound',
            push_auth_key='da0469ff-9ec2-4e31-b210-69550753297f',
            created_by_user_guid='system',
        )
        if status == 201:
            print(f'PAT issued for 1177: guid={data["guid"]}')
            print(f'Raw token (save this): {data["raw_token"]}')
        else:
            print(f'Error: {data}')

    return app


def _register_provider_cli(app):
    """flask provider … subcommands (ticket #136)."""
    import click

    @app.cli.group('provider')
    def provider_group():
        """Provider lifecycle: PATs and webhook signing secrets."""

    @provider_group.command('register-pat')
    @click.option('--org-guid', required=True)
    @click.option('--contract-guid', required=True)
    @click.option('--scopes', default='read,write')
    @click.option('--delivery-mode', type=click.Choice(['push', 'poll']),
                  default='poll')
    @click.option('--push-endpoint-url', default=None)
    @click.option('--expires-days', type=int, default=None)
    def cmd_register_pat(org_guid, contract_guid, scopes, delivery_mode,
                         push_endpoint_url, expires_days):
        """Issue a new PAT for a provider org+contract. Prints raw token once."""
        from app.services.pat_service import issue_pat
        data, status = issue_pat(
            provider_org_guid=org_guid,
            contract_guid=contract_guid,
            scopes=scopes,
            delivery_mode=delivery_mode,
            push_endpoint_url=push_endpoint_url,
            expires_days=expires_days,
            created_by_user_guid='cli',
        )
        if status != 201:
            click.echo(f'error: {data}', err=True)
            raise SystemExit(1)
        click.echo(f'pat_guid: {data["guid"]}')
        click.echo(f'raw_token (save this — shown only once): {data["raw_token"]}')

    @provider_group.command('rotate-pat')
    @click.option('--org-guid', required=True)
    @click.option('--contract-guid', required=True)
    @click.option('--expires-days', type=int, default=None)
    def cmd_rotate_pat(org_guid, contract_guid, expires_days):
        """Rotate a PAT: issue new active, mark old as deprecated (14d grace)."""
        from app.services.pat_service import rotate_pat
        data, status = rotate_pat(
            provider_org_guid=org_guid,
            contract_guid=contract_guid,
            expires_days=expires_days,
            created_by_user_guid='cli',
        )
        if status != 201:
            click.echo(f'error: {data}', err=True)
            raise SystemExit(1)
        click.echo(f'new_pat_guid: {data["guid"]}')
        click.echo(f'raw_token (save this — shown only once): {data["raw_token"]}')

    @provider_group.command('revoke-pat')
    @click.option('--pat-guid', required=True)
    def cmd_revoke_pat(pat_guid):
        """Revoke a PAT by its guid. Takes effect immediately."""
        from app.services.pat_service import revoke_pat
        data, status = revoke_pat(pat_guid, user_guid='cli')
        if status != 200:
            click.echo(f'error: {data}', err=True)
            raise SystemExit(1)
        click.echo(f'revoked: {data["guid"]}')

    @provider_group.command('register-signing-secret')
    @click.option('--org-guid', required=True)
    def cmd_register_secret(org_guid):
        """Issue a webhook signing secret for an org. Prints plaintext once."""
        from app.services.webhook_secret_service import register_secret
        data, status = register_secret(
            provider_org_guid=org_guid, created_by_user_guid='cli',
        )
        if status != 201:
            click.echo(f'error: {data}', err=True)
            raise SystemExit(1)
        click.echo(f'secret_guid: {data["guid"]}')
        click.echo(f'secret_plaintext (save this — shown only once): '
                   f'{data["secret_plaintext"]}')

    @provider_group.command('rotate-signing-secret')
    @click.option('--org-guid', required=True)
    def cmd_rotate_secret(org_guid):
        """Rotate a webhook signing secret. 14d verification grace for the previous one."""
        from app.services.webhook_secret_service import rotate_secret
        data, status = rotate_secret(
            provider_org_guid=org_guid, created_by_user_guid='cli',
        )
        if status != 201:
            click.echo(f'error: {data}', err=True)
            raise SystemExit(1)
        click.echo(f'new_secret_guid: {data["guid"]}')
        click.echo(f'secret_plaintext (save this — shown only once): '
                   f'{data["secret_plaintext"]}')

    @provider_group.command('revoke-signing-secret')
    @click.option('--org-guid', required=True)
    def cmd_revoke_secret(org_guid):
        """Revoke every webhook signing secret (active + deprecated) for an org."""
        from app.services.webhook_secret_service import revoke_secret
        data, status = revoke_secret(
            provider_org_guid=org_guid, user_guid='cli',
        )
        if status != 200:
            click.echo(f'error: {data}', err=True)
            raise SystemExit(1)
        click.echo(f'revoked: {data["revoked_guids"]}')

    # ── Webhook dispatcher (ticket #140) ─────────────────────────

    @app.cli.group('webhook')
    def webhook_group():
        """Outbound webhook dispatcher controls."""

    @webhook_group.command('tick')
    @click.option('--limit', type=int, default=20)
    def cmd_webhook_tick(limit):
        """Process up to <limit> due deliveries and exit."""
        from app.services.webhook_dispatcher import tick
        counts = tick(limit=limit)
        click.echo(
            f'attempted={counts["attempted"]} '
            f'succeeded={counts["succeeded"]} '
            f'rescheduled={counts["rescheduled"]} '
            f'dead_lettered={counts["dead_lettered"]}'
        )

    @webhook_group.command('run-worker')
    @click.option('--interval', type=int, default=5,
                  help='Seconds between ticks (default 5).')
    @click.option('--limit', type=int, default=20,
                  help='Max deliveries per tick.')
    def cmd_webhook_worker(interval, limit):
        """Run the dispatcher loop until interrupted.

        Intended for start.sh invocation:
            flask webhook run-worker &
        """
        import time
        from app.services.webhook_dispatcher import tick
        click.echo(f'webhook worker starting; interval={interval}s')
        while True:
            try:
                counts = tick(limit=limit)
                if counts['attempted']:
                    click.echo(
                        f'tick: attempted={counts["attempted"]} '
                        f'succeeded={counts["succeeded"]} '
                        f'rescheduled={counts["rescheduled"]} '
                        f'dead_lettered={counts["dead_lettered"]}'
                    )
            except Exception as e:
                click.echo(f'tick error: {e}', err=True)
            time.sleep(interval)

    @webhook_group.command('list-pending')
    def cmd_webhook_list_pending():
        """Show pending + dead-lettered deliveries (for debugging)."""
        from app.models.security_models import WebhookDelivery
        rows = WebhookDelivery.query.filter(
            WebhookDelivery.status.in_(['pending', 'dead_letter'])
        ).order_by(WebhookDelivery.created_at.desc()).limit(50).all()
        for r in rows:
            click.echo(
                f'{r.guid}  {r.status}  attempts={r.attempt_count}  '
                f'{r.event_type}  org={r.provider_org_guid}  '
                f'next={r.next_attempt_at}'
            )

    @webhook_group.command('requeue')
    @click.option('--guid', required=True, help='WebhookDelivery guid')
    def cmd_webhook_requeue(guid):
        """Move a dead-lettered delivery back to pending with a fresh attempt window."""
        from datetime import datetime, timezone
        from app.models.security_models import WebhookDelivery
        row = WebhookDelivery.query.filter_by(guid=guid).first()
        if not row:
            click.echo('not found', err=True)
            raise SystemExit(1)
        row.status = WebhookDelivery.STATUS_PENDING
        row.attempt_count = 0
        row.next_attempt_at = datetime.now(timezone.utc)
        row.last_error = None
        db.session.commit()
        click.echo(f'requeued: {row.guid}')
