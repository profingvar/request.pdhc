"""sandbox-dispatch CLI tests (ticket #141)."""
import os

# Env preamble (see test_webhook_dispatcher.py for why this is needed).
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
