import os
from unittest.mock import patch

import pytest
import requests

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
def _no_real_ips_calls(request):
    """No test in this repo may reach ips.pdhc over the network.

    Found twice in one session, both times by accident. A test that patched the
    wrong function name left the real lookup in place and it called
    `https://ips.pdhc.se/api/v1/patients/<guid>/clinics`, which answered 401:

    * `test_service_request_create_authz` after #779 moved the gate to a new
      helper — the tests failed, so nothing passed silently;
    * `test_dispatch_trigger`'s `stubs` fixture never stubbed the lookup at all,
      and was saved only by the 401 being *tolerated* — the resolver returned
      None and the ServiceRequest was created anyway. The 2026-10-07 refusal
      decision turned that into a failure, which is how it was noticed.

    A unit run must not depend on a production service being reachable, and a
    wrong patch target should say so rather than look like an upstream 502. So
    the module's `requests.get` raises here, naming the URL.

    It raises `requests.ConnectionError` — the same thing a genuinely
    unreachable ips raises — rather than a louder custom error, on purpose.
    Several older modules are written to tolerate the upstream being down
    (`test_patients.py`: "upstream calls are expected to fail in test
    environment, which is acceptable", asserting `status in (200, 502)`), and
    they were only ever passing *because* production answered 401. Simulating
    the outage keeps them meaningful while cutting the network dependency.

    Those tolerant assertions are weak — they pass whether ips answers or not —
    but tightening them is a separate job from cutting the network call.

    Loudness where it matters comes from the code instead: since the 2026-10-07
    decision an unresolvable organisation REFUSES, so a create path that forgot
    to stub ips now fails its own assertion rather than quietly writing NULL.

    Opt out with `@pytest.mark.allow_ips_network` for a test that deliberately
    exercises the HTTP layer against a local stub.
    """
    if request.node.get_closest_marker("allow_ips_network"):
        yield
        return

    def _unreachable(url, *a, **kw):
        raise requests.ConnectionError(
            f"ips is not reachable from the test suite ({url}) — patch "
            f"patient_service.get_patient_clinic_orgs (or get_patient) if this "
            f"test needs an answer")

    with patch("app.services.patient_service.requests.get",
               side_effect=_unreachable):
        yield


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
