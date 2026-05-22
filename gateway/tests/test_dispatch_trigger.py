"""Ticket #152: webhook dispatch trigger on ServiceRequest creation.

create_service_request must enqueue a WebhookDelivery row for every
active push-mode PAT on the contract, and must do so best-effort
(failures here don't roll back the SR commit).
"""
import json
import os

os.environ['AUTH_DISABLED'] = 'false'
os.environ['FLASK_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['HMAC_SECRET'] = 'test-hmac-secret-min-32-chars-for-test'
os.environ['INTERNAL_SERVICE_KEY'] = 'test-internal-key'
os.environ['FLASK_SECRET_KEY'] = 'test-flask-secret'
os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'

from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault('WEBHOOK_SECRETS_KEY', Fernet.generate_key().decode())

import pytest  # noqa: E402

from app import db as _db  # noqa: E402
from app.models.security_models import (  # noqa: E402
    ProviderAccessToken, WebhookDelivery, WebhookSigningSecret,
)
from app.models.service_request_models import ServiceRequest  # noqa: E402
from app.services import service_request_service, scope_service  # noqa: E402
from app.services import webhook_secret_service  # noqa: E402
from app.services.pat_service import issue_pat  # noqa: E402


CONTRACT = 'contract-152'
ORG_A = 'org-a-152'
ORG_B = 'org-b-152'
WEBHOOK_A = 'https://provider-a.example/webhook'
WEBHOOK_B = 'https://provider-b.example/webhook'


@pytest.fixture(autouse=True)
def _clean(app):
    with app.app_context():
        WebhookDelivery.query.delete()
        WebhookSigningSecret.query.delete()
        ProviderAccessToken.query.delete()
        ServiceRequest.query.delete()
        _db.session.commit()
        yield
        _db.session.rollback()


@pytest.fixture
def stubs(monkeypatch):
    """Stub the upstream service calls so create_service_request can
    succeed without IPS/Plan running. Also stub scope_service so
    the trigger fires through the happy path."""
    monkeypatch.setattr(
        'app.services.service_request_service.patient_service.get_patient',
        lambda p_guid: ({'id': p_guid}, 200),
    )
    monkeypatch.setattr(
        'app.services.service_request_service.plan_definition_service.get_plan_definition',
        lambda pd_guid: ({'id': pd_guid, 'activities': []}, 200),
    )
    monkeypatch.setattr(
        'app.services.service_request_service.build_patient_excerpt',
        lambda data: {},
    )
    # No contract scope defined → allow path
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda guid: None)


def _register_provider(app, org_guid, webhook_url):
    """Set up signing secret + active push PAT for an org."""
    with app.app_context():
        webhook_secret_service.register_secret(
            provider_org_guid=org_guid, created_by_user_guid='test',
        )
        issue_pat(
            provider_org_guid=org_guid, contract_guid=CONTRACT,
            scopes='read,write', delivery_mode='push',
            push_endpoint_url=webhook_url, created_by_user_guid='test',
        )


def _create_sr(app, contract_guid=CONTRACT):
    with app.app_context():
        return service_request_service.create_service_request(
            patient_guid='pat-152',
            plan_definition_guid='pd-152',
            user_guid='user-152',
            contract_guid=contract_guid,
        )


# ── Tests ─────────────────────────────────────────────────────────────


def test_creating_sr_enqueues_one_delivery_per_active_push_pat(app, stubs):
    """Two push providers on the same contract → two WebhookDelivery rows."""
    _register_provider(app, ORG_A, WEBHOOK_A)
    _register_provider(app, ORG_B, WEBHOOK_B)

    result, status = _create_sr(app)
    assert status == 201
    sr_guid = result['guid']

    with app.app_context():
        deliveries = WebhookDelivery.query.filter_by(
            service_request_guid=sr_guid,
        ).all()
        assert len(deliveries) == 2
        urls = {d.webhook_url for d in deliveries}
        assert urls == {WEBHOOK_A, WEBHOOK_B}
        # Every row should be signed and pending (not DLQ — they have
        # active signing secrets).
        for d in deliveries:
            assert d.status == WebhookDelivery.STATUS_PENDING
            assert d.signature and d.signature.startswith('sha256=')
            assert d.event_type == 'service_request.dispatched'
            payload = json.loads(d.payload_json)
            assert payload['service_request_guid'] == sr_guid
            assert payload['contract_guid'] == CONTRACT


def test_creating_sr_without_contract_does_not_enqueue(app, stubs):
    """No contract_guid → no webhook fan-out."""
    _register_provider(app, ORG_A, WEBHOOK_A)
    result, status = _create_sr(app, contract_guid=None)
    assert status == 201
    with app.app_context():
        assert WebhookDelivery.query.count() == 0


def test_poll_mode_pats_are_skipped(app, stubs):
    """Only push-mode + active PATs are dispatched to."""
    with app.app_context():
        webhook_secret_service.register_secret(
            provider_org_guid=ORG_A, created_by_user_guid='test',
        )
        # Poll mode — should be ignored
        issue_pat(
            provider_org_guid=ORG_A, contract_guid=CONTRACT,
            scopes='read', delivery_mode='poll',
            created_by_user_guid='test',
        )
    _create_sr(app)
    with app.app_context():
        assert WebhookDelivery.query.count() == 0


def test_revoked_pat_is_skipped(app, stubs):
    """A revoked PAT must not get the SR webhook."""
    _register_provider(app, ORG_A, WEBHOOK_A)
    with app.app_context():
        pat = ProviderAccessToken.query.filter_by(
            provider_org_guid=ORG_A,
        ).first()
        pat.status = 'revoked'
        pat.revoked = True
        _db.session.commit()
    _create_sr(app)
    with app.app_context():
        assert WebhookDelivery.query.count() == 0


def test_enqueue_failure_does_not_roll_back_sr(app, stubs, monkeypatch):
    """If enqueue raises, the SR must still exist (best-effort fan-out)."""
    _register_provider(app, ORG_A, WEBHOOK_A)

    def boom(*a, **kw):
        raise RuntimeError('dispatcher offline')

    monkeypatch.setattr(
        'app.services.webhook_dispatcher.enqueue_service_request_dispatched',
        boom,
    )

    result, status = _create_sr(app)
    assert status == 201
    with app.app_context():
        assert ServiceRequest.query.filter_by(guid=result['guid']).first() is not None
        assert WebhookDelivery.query.count() == 0  # no enqueue happened


def test_provider_without_signing_secret_dead_letters(app, stubs):
    """If the provider has a PAT but no active signing secret, the
    enqueue should still create a row — going straight to DLQ per
    webhook_dispatcher.enqueue. Operator gets a ticket from the
    dispatcher. SR is still created."""
    with app.app_context():
        issue_pat(
            provider_org_guid=ORG_A, contract_guid=CONTRACT,
            scopes='read,write', delivery_mode='push',
            push_endpoint_url=WEBHOOK_A, created_by_user_guid='test',
        )
        # Note: NO register_secret() — provider has no signing key

    # Patch the DLQ ticket emission so the test doesn't hit the real API.
    import app.services.webhook_dispatcher as wd
    original = wd._file_dead_letter_ticket
    wd._file_dead_letter_ticket = lambda row, reason: None
    try:
        result, status = _create_sr(app)
    finally:
        wd._file_dead_letter_ticket = original

    assert status == 201
    with app.app_context():
        rows = WebhookDelivery.query.filter_by(
            provider_org_guid=ORG_A,
        ).all()
        assert len(rows) == 1
        assert rows[0].status == WebhookDelivery.STATUS_DEAD_LETTER
        assert ServiceRequest.query.filter_by(guid=result['guid']).first() is not None
