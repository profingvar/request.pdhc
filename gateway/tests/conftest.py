import os
import pytest

# Force test configuration before any imports
os.environ['AUTH_DISABLED'] = 'true'
# AUTH_DISABLED=true requires FLASK_ENV=development per app/config.py
# (guard added in commit 1967608). Tests are dev-bypass; using
# 'development' here keeps the guard satisfied without changing the
# production-safety semantics.
os.environ['FLASK_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite:///test_request_pdhc.db'
os.environ['HMAC_SECRET'] = 'test-hmac-secret-for-pytest-minimum-32-chars'
os.environ['INTERNAL_SERVICE_KEY'] = 'test-internal-service-key-12345'
os.environ.setdefault('FLASK_SECRET_KEY', 'test-secret-key')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-key')

from app import create_app, db as _db


@pytest.fixture(scope='session')
def app():
    """Create application for testing."""
    app = create_app(testing=True)
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test_request_pdhc.db'
    return app


@pytest.fixture(scope='session', autouse=True)
def _database(app):
    """Set up the database once for the test session."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.drop_all()
        # Clean up sqlite file
        db_path = os.path.join(app.instance_path, 'test_request_pdhc.db')
        if os.path.exists(db_path):
            os.unlink(db_path)


@pytest.fixture(autouse=True)
def _pin_auth_disabled(app):
    """Ticket #380 (rollup #348) — reset app.config['AUTH_DISABLED']
    to True before every test.

    Sibling test modules (test_dispatch_trigger, test_provider_lifecycle,
    test_sandbox_dispatch, test_webhook_dispatcher) historically set
    os.environ['AUTH_DISABLED'] = 'false' at import time to exercise
    real auth paths. Pytest imports all test modules during collection
    (regardless of run order), so those import-time env writes could
    leak into every subsequent test — the app fixture is session-scoped
    and its config was read once from the polluted env.

    This autouse fixture pins app.config['AUTH_DISABLED']=True before
    each test runs, so the polluters' import-time env writes no longer
    affect anyone. Tests that specifically need auth ON monkeypatch
    or set app.config['AUTH_DISABLED']=False themselves (see
    test_service_request_create_authz.py for the precedent).
    """
    prev = app.config.get('AUTH_DISABLED')
    app.config['AUTH_DISABLED'] = True
    yield
    app.config['AUTH_DISABLED'] = prev


@pytest.fixture(autouse=True)
def db_session(app, _database):
    """Provide a clean session for each test."""
    with app.app_context():
        yield _database.session
        _database.session.rollback()


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Flask CLI test runner."""
    return app.test_cli_runner()
