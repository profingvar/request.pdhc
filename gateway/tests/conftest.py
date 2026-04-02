import os
import pytest

# Force test configuration before any imports
os.environ['AUTH_DISABLED'] = 'true'
os.environ['FLASK_ENV'] = 'testing'
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
