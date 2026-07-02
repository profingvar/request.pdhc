"""Outbound webhook dispatcher tests (ticket #140)."""
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone, timedelta

# Ticket #380 (rollup #348) — every env write here is `setdefault` so
# conftest.py's canonical test env wins when pytest imports this
# module during collection. Previously these were brute overrides
# that polluted the session-scoped app fixture's config: sibling
# tests (test_internal_api, test_care_plans, ...) run after this
# module is imported and saw the wrong INTERNAL_SERVICE_KEY /
# AUTH_DISABLED values.
os.environ.setdefault('AUTH_DISABLED', 'false')
os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('HMAC_SECRET', 'test-hmac-secret-min-32-chars-for-test')
os.environ.setdefault('INTERNAL_SERVICE_KEY', 'test-internal-key')
os.environ.setdefault('FLASK_SECRET_KEY', 'test-flask-secret')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret')

from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault('WEBHOOK_SECRETS_KEY', Fernet.generate_key().decode())
os.environ.setdefault('TICKET_API_KEY', 'test-ticket-key')

import pytest  # noqa: E402

from app import db as _db  # noqa: E402
from app.models.security_models import (  # noqa: E402
    WebhookDelivery, WebhookSigningSecret,
)
from app.services import webhook_dispatcher, webhook_secret_service  # noqa: E402


ORG = 'org-1140'
SR_GUID = 'sr-1140'
URL = 'https://provider.example/webhook'


@pytest.fixture(autouse=True)
def _clean(app):
    with app.app_context():
        WebhookDelivery.query.delete()
        WebhookSigningSecret.query.delete()
        _db.session.commit()
        yield
        _db.session.rollback()


@pytest.fixture
def secret(app):
    """Register a signing secret for ORG and return its plaintext."""
    with app.app_context():
        data, status = webhook_secret_service.register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        assert status == 201
        return data['secret_plaintext']


# ── Signing ────────────────────────────────────────────────────────────


def test_signature_matches_provider_side_hmac():
    body = b'{"event":"x"}'
    s = 'super-secret'
    expected = 'sha256=' + hmac.new(
        s.encode(), body, hashlib.sha256,
    ).hexdigest()
    assert webhook_dispatcher.compute_signature(s, body) == expected


# ── Enqueue ────────────────────────────────────────────────────────────


def test_enqueue_creates_pending_row_with_signature(app, secret):
    with app.app_context():
        row = webhook_dispatcher.enqueue(
            event_type='service_request.dispatched',
            provider_org_guid=ORG,
            service_request_guid=SR_GUID,
            webhook_url=URL,
            payload={'event': 'service_request.dispatched',
                     'service_request_guid': SR_GUID},
        )
        assert row.status == WebhookDelivery.STATUS_PENDING
        assert row.signature is not None
        assert row.signature.startswith('sha256=')
        assert row.attempt_count == 0


def test_enqueue_dead_letters_when_no_signing_secret(app, monkeypatch):
    """Without a signing secret we cannot sign — fail fast as DLQ.

    Patch _file_dead_letter_ticket so the test doesn't hit a real
    ticket API.
    """
    called = {}

    def fake_file(row, reason):
        called['row'] = row
        called['reason'] = reason

    monkeypatch.setattr(webhook_dispatcher, '_file_dead_letter_ticket',
                        fake_file)

    with app.app_context():
        row = webhook_dispatcher.enqueue(
            event_type='service_request.dispatched',
            provider_org_guid=ORG,
            service_request_guid=SR_GUID,
            webhook_url=URL,
            payload={'event': 'x'},
        )
        assert row.status == WebhookDelivery.STATUS_DEAD_LETTER
    assert called['reason'] == 'no_signing_secret'


# ── Tick / retry ───────────────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text


def test_tick_success_marks_succeeded(app, secret, monkeypatch):
    posts = []

    def fake_post(url, data, headers, timeout):
        posts.append({'url': url, 'data': data, 'headers': headers})
        return _FakeResp(200, 'ok')

    monkeypatch.setattr(webhook_dispatcher.http_requests, 'post', fake_post)

    with app.app_context():
        row = webhook_dispatcher.enqueue(
            event_type='service_request.dispatched',
            provider_org_guid=ORG, service_request_guid=SR_GUID,
            webhook_url=URL,
            payload={'event': 'service_request.dispatched',
                     'service_request_guid': SR_GUID},
        )
        counts = webhook_dispatcher.tick(limit=10)
        assert counts == {'attempted': 1, 'succeeded': 1,
                          'rescheduled': 0, 'dead_lettered': 0}
        refreshed = WebhookDelivery.query.filter_by(guid=row.guid).first()
        assert refreshed.status == WebhookDelivery.STATUS_SUCCEEDED
        assert refreshed.last_response_code == 200

    # Provider receives the right headers
    assert posts[0]['headers']['X-PDHC-Signature'].startswith('sha256=')
    assert posts[0]['headers']['X-PDHC-Event-Type'] == 'service_request.dispatched'
    body = posts[0]['data'].decode('utf-8')
    parsed = json.loads(body)
    assert parsed['service_request_guid'] == SR_GUID


def test_tick_failure_reschedules_with_backoff(app, secret, monkeypatch):
    monkeypatch.setattr(webhook_dispatcher.http_requests, 'post',
                        lambda url, data, headers, timeout: _FakeResp(500, 'boom'))

    with app.app_context():
        row = webhook_dispatcher.enqueue(
            event_type='x', provider_org_guid=ORG,
            service_request_guid=SR_GUID, webhook_url=URL,
            payload={'event': 'x'},
        )
        before = datetime.now(timezone.utc)
        counts = webhook_dispatcher.tick(limit=10)
        assert counts['rescheduled'] == 1

        row = WebhookDelivery.query.filter_by(guid=row.guid).first()
        assert row.status == WebhookDelivery.STATUS_PENDING
        assert row.attempt_count == 1
        assert row.last_response_code == 500
        # First retry should be ~5 seconds out (BACKOFF_SECONDS[0]).
        delta = (row.next_attempt_at.replace(tzinfo=timezone.utc)
                 - before).total_seconds()
        assert 4 < delta < 8


def test_tick_dead_letters_after_max_attempts(app, secret, monkeypatch):
    """Force 6 consecutive 500s — the 6th should dead-letter."""
    monkeypatch.setattr(webhook_dispatcher.http_requests, 'post',
                        lambda url, data, headers, timeout: _FakeResp(500))

    files = []
    monkeypatch.setattr(webhook_dispatcher, '_file_dead_letter_ticket',
                        lambda row, reason: files.append(reason))

    with app.app_context():
        row = webhook_dispatcher.enqueue(
            event_type='x', provider_org_guid=ORG,
            service_request_guid=SR_GUID, webhook_url=URL,
            payload={'event': 'x'},
        )
        # Drive the row to dead-letter by forcing each tick window
        # by backdating next_attempt_at after each failure.
        for _ in range(webhook_dispatcher.MAX_ATTEMPTS):
            r = WebhookDelivery.query.filter_by(guid=row.guid).first()
            if r.status == WebhookDelivery.STATUS_DEAD_LETTER:
                break
            r.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            _db.session.commit()
            webhook_dispatcher.tick(limit=10)

        final = WebhookDelivery.query.filter_by(guid=row.guid).first()
        assert final.status == WebhookDelivery.STATUS_DEAD_LETTER
        assert final.attempt_count == webhook_dispatcher.MAX_ATTEMPTS
        assert files == ['retries_exhausted']


def test_tick_transport_error_counts_as_failure(app, secret, monkeypatch):
    def boom(url, data, headers, timeout):
        raise webhook_dispatcher.http_requests.ConnectionError('net down')

    monkeypatch.setattr(webhook_dispatcher.http_requests, 'post', boom)

    with app.app_context():
        row = webhook_dispatcher.enqueue(
            event_type='x', provider_org_guid=ORG,
            service_request_guid=SR_GUID, webhook_url=URL,
            payload={'event': 'x'},
        )
        webhook_dispatcher.tick(limit=10)
        r = WebhookDelivery.query.filter_by(guid=row.guid).first()
        assert r.status == WebhookDelivery.STATUS_PENDING
        assert r.attempt_count == 1
        assert 'net down' in (r.last_error or '')


def test_dispatcher_verifies_signature_against_active_secret(app, secret,
                                                              monkeypatch):
    """Provider-side verification: take the body + signature and
    recompute the HMAC with the active secret — must match."""
    captured = {}

    def fake_post(url, data, headers, timeout):
        captured['data'] = data
        captured['sig'] = headers['X-PDHC-Signature']
        return _FakeResp(200, '')

    monkeypatch.setattr(webhook_dispatcher.http_requests, 'post', fake_post)

    with app.app_context():
        webhook_dispatcher.enqueue(
            event_type='x', provider_org_guid=ORG,
            service_request_guid=SR_GUID, webhook_url=URL,
            payload={'event': 'service_request.dispatched',
                     'service_request_guid': SR_GUID},
        )
        webhook_dispatcher.tick(limit=10)

    # Provider does:
    recomputed = webhook_dispatcher.compute_signature(secret, captured['data'])
    assert recomputed == captured['sig']
