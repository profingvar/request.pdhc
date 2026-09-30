"""sandbox-dispatch CLI tests (ticket #141)."""
import os

# Ticket #380 (rollup #348) — every env write here is `setdefault` so
# conftest.py's canonical test env wins when pytest imports this
# module during collection. Previously these were brute overrides
# that polluted the session-scoped app fixture's config.
os.environ.setdefault('AUTH_DISABLED', 'false')
os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('HMAC_SECRET', 'test-hmac-secret-min-32-chars-for-test')
os.environ.setdefault('INTERNAL_SERVICE_KEY', 'test-internal-key')
os.environ.setdefault('FLASK_SECRET_KEY', 'test-flask-secret')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret')

from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault('WEBHOOK_SECRETS_KEY', Fernet.generate_key().decode())

import pytest  # noqa: E402

from app import db as _db  # noqa: E402
from app.models.security_models import (  # noqa: E402
    ProviderAccessToken, WebhookDelivery, WebhookSigningSecret,
)
from app.services import webhook_dispatcher, webhook_secret_service  # noqa: E402
from app.services.pat_service import issue_pat  # noqa: E402


ORG = 'org-sandbox'
CONTRACT = 'contract-sandbox'
URL = 'https://provider.example/webhook'


@pytest.fixture(autouse=True)
def _clean(app):
    with app.app_context():
        WebhookDelivery.query.delete()
        WebhookSigningSecret.query.delete()
        ProviderAccessToken.query.delete()
        _db.session.commit()
        yield


@pytest.fixture
def stubbed_provider(monkeypatch):
    """Pretend the provider responds 200 to every webhook POST."""
    calls = []

    class _Resp:
        status_code = 200
        text = 'ok'

    def fake_post(url, data, headers, timeout):
        calls.append({'url': url, 'headers': dict(headers), 'body': data})
        return _Resp()

    monkeypatch.setattr(webhook_dispatcher.http_requests, 'post', fake_post)
    return calls


def test_sandbox_dispatch_pass_path(app, stubbed_provider):
    """Full happy-path: register signing secret + PAT, then run the CLI."""
    with app.app_context():
        webhook_secret_service.register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            scopes='read,write', delivery_mode='push',
            push_endpoint_url=URL, created_by_user_guid='test',
        )

    runner = app.test_cli_runner()
    result = runner.invoke(args=[
        'provider', 'sandbox-dispatch',
        '--org-guid', ORG,
        '--contract-guid', CONTRACT,
        '--concept-guid', 'concept-A',
    ])
    assert result.exit_code == 0, result.output
    assert 'PASS' in result.output

    # Provider received two posts with the SAME X-PDHC-Event-Id
    assert len(stubbed_provider) == 2
    eids = {c['headers']['X-PDHC-Event-Id'] for c in stubbed_provider}
    assert len(eids) == 1, f'expected same event id, got {eids}'


def test_sandbox_dispatch_no_pat_errors_helpfully(app, stubbed_provider):
    """Without an active PAT and no --webhook-url override, exit non-zero."""
    runner = app.test_cli_runner()
    result = runner.invoke(args=[
        'provider', 'sandbox-dispatch',
        '--org-guid', ORG,
        '--contract-guid', CONTRACT,
    ])
    assert result.exit_code != 0
    assert 'no active PAT' in result.output


def test_sandbox_sign_emits_valid_signature(app, tmp_path):
    """sandbox-sign output should round-trip through compute_signature."""
    payload = b'{"event":"x"}'
    f = tmp_path / 'payload.json'
    f.write_bytes(payload)

    with app.app_context():
        data, _ = webhook_secret_service.register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        secret = data['secret_plaintext']

    runner = app.test_cli_runner()
    result = runner.invoke(args=[
        'provider', 'sandbox-sign',
        '--org-guid', ORG,
        '--payload-file', str(f),
    ])
    assert result.exit_code == 0

    sig_line = next(
        line for line in result.output.splitlines()
        if line.startswith('X-PDHC-Signature:')
    )
    sig = sig_line.split(': ', 1)[1].strip()
    expected = webhook_dispatcher.compute_signature(secret, payload)
    assert sig == expected


class TestTheSandboxGuidFitsItsColumn:
    """#720 — the sandbox dispatch built ``f'sandbox-{uuid4}'``: 44 characters
    into ``webhook_deliveries.service_request_guid``, which is varchar(36)
    like every other service_request_guid column on the platform, because a
    guid IS 36 characters.

    Every push-mode sandbox dispatch therefore died with
    ``StringDataRightTruncation`` and returned a 500 — and that endpoint is
    the go-live gate for a push provider, so no push onboarding could ever
    complete.

    **These tests exist because the three above passed throughout.** They run
    on SQLite, which does not enforce VARCHAR length; Postgres does. A backend
    that silently accepts an over-long value cannot catch a column overflow,
    so the length is asserted directly here rather than left to the database.
    """

    def _column_limit(self):
        from app.models.security_models import WebhookDelivery
        return WebhookDelivery.__table__.c.service_request_guid.type.length

    def test_the_generated_guid_fits(self, app):
        import re
        from app.services import sandbox_service
        src = __import__("inspect").getsource(sandbox_service)
        m = re.search(r"sr_guid\s*=\s*(.+)", src)
        assert m, "could not find the guid construction"
        assert "sandbox-" not in m.group(1), (
            "the 'sandbox-' prefix is back; it does not fit varchar(36)")

    def test_a_uuid_is_exactly_the_column_width(self, app):
        import uuid
        assert len(str(uuid.uuid4())) == self._column_limit() == 36

    def test_the_old_prefixed_form_would_not_have_fit(self, app):
        """Kept as the record of the defect: 44 was not near the limit, it
        was 8 characters over it."""
        import uuid
        assert len(f"sandbox-{uuid.uuid4()}") > self._column_limit()

    def test_every_service_request_guid_column_is_the_same_width(self, app):
        """The reason the fix is to drop the prefix rather than widen one
        column: they all hold the same kind of value."""
        from app import db
        widths = {}
        for table in db.metadata.tables.values():
            col = table.c.get("service_request_guid")
            if col is not None and getattr(col.type, "length", None):
                widths[table.name] = col.type.length
        assert widths, "expected service_request_guid columns"
        assert set(widths.values()) == {36}, f"inconsistent widths: {widths}"
