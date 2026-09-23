"""Ticket #598 — HTTP forms of the `flask provider …` CLI, for onboard.pdhc.

onboard.pdhc runs in its own container and cannot shell into
request_pdhc_app, so OB-8 (mint the secret and show it once) and OB-10
(verify with the new secret, then the go-live gate) need these over HTTP.

The rules the ticket set: raw secrets in the response body once and never
logged, an audit row per call (the wrapped service layer writes it), and a
403 for a non-SU caller.
"""
import os  # noqa: E402
import uuid
from unittest.mock import patch

# Signing secrets are Fernet-encrypted at rest and secret_crypto refuses to
# operate without a key. setdefault (not assignment) so conftest's canonical
# test env keeps priority — see the #380 note in test_sandbox_dispatch.py.
from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault('WEBHOOK_SECRETS_KEY', Fernet.generate_key().decode())

import pytest  # noqa: E402

from app import db  # noqa: E402
from app.services.pat_service import issue_pat
from app.services import webhook_secret_service


ORG = str(uuid.uuid4())
CONTRACT = str(uuid.uuid4())


@pytest.fixture()
def client(app):
    return app.test_client()


def _issue_pat(app, org=None, contract=None, **kw):
    with app.app_context():
        data, status = issue_pat(
            provider_org_guid=org or str(uuid.uuid4()),
            contract_guid=contract or str(uuid.uuid4()),
            created_by_user_guid='test',
            **kw,
        )
        assert status == 201, data
        return data


def _issue_secret(app, org):
    with app.app_context():
        data, status = webhook_secret_service.register_secret(
            provider_org_guid=org, created_by_user_guid='test',
        )
        assert status == 201, data
        return data


# ── PAT rotation over HTTP ────────────────────────────────────────────

class TestRotatePat:

    def test_rotate_returns_a_new_raw_token(self, app, client):
        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        first = _issue_pat(app, org, contract)

        r = client.post(f'/api/v1/admin/provider-tokens/{first["guid"]}/rotate',
                        json={})
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert body['raw_token']
        assert body['guid'] != first['guid']
        assert body['raw_token'] != first['raw_token']

    def test_old_token_is_deprecated_not_revoked(self, app, client):
        """The grace window is the point — a provider must be able to swap
        without an outage."""
        from app.models.security_models import ProviderAccessToken

        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        first = _issue_pat(app, org, contract)
        client.post(f'/api/v1/admin/provider-tokens/{first["guid"]}/rotate',
                    json={})

        with app.app_context():
            old = ProviderAccessToken.query.filter_by(guid=first['guid']).first()
            assert old.status == 'deprecated'
            assert old.revoked is False
            assert old.rotated_to_guid is not None

    def test_expires_days_is_honoured(self, app, client):
        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        first = _issue_pat(app, org, contract)
        r = client.post(f'/api/v1/admin/provider-tokens/{first["guid"]}/rotate',
                        json={'expires_days': 90})
        assert r.status_code == 201
        assert r.get_json()['expires_at']

    def test_unknown_guid_is_404(self, client):
        r = client.post(f'/api/v1/admin/provider-tokens/{uuid.uuid4()}/rotate',
                        json={})
        assert r.status_code == 404


# ── signing secrets over HTTP ─────────────────────────────────────────

class TestSigningSecrets:

    def test_issue_returns_plaintext_once(self, client):
        org = str(uuid.uuid4())
        r = client.post('/api/v1/admin/signing-secrets',
                        json={'provider_org_guid': org})
        assert r.status_code == 201, r.get_json()
        assert r.get_json()['secret_plaintext']

    def test_issue_requires_the_org(self, client):
        r = client.post('/api/v1/admin/signing-secrets', json={})
        assert r.status_code == 400

    def test_list_never_leaks_secret_material(self, app, client):
        """The listing is for an operator UI; it must be safe to render."""
        org = str(uuid.uuid4())
        _issue_secret(app, org)
        r = client.get(f'/api/v1/admin/signing-secrets?provider_org_guid={org}')
        assert r.status_code == 200
        body = r.get_json()
        assert body['total'] == 1
        serialised = str(body)
        assert 'secret_plaintext' not in serialised
        assert 'secret_encrypted' not in serialised

    def test_list_requires_the_org(self, client):
        r = client.get('/api/v1/admin/signing-secrets')
        assert r.status_code == 400

    def test_rotate_returns_new_plaintext(self, app, client):
        org = str(uuid.uuid4())
        first = _issue_secret(app, org)
        r = client.post(f'/api/v1/admin/signing-secrets/{first["guid"]}/rotate',
                        json={})
        assert r.status_code == 201, r.get_json()
        assert r.get_json()['secret_plaintext'] != first['secret_plaintext']

    def test_rotate_unknown_guid_is_404(self, client):
        r = client.post(f'/api/v1/admin/signing-secrets/{uuid.uuid4()}/rotate',
                        json={})
        assert r.status_code == 404

    def test_revoke_reports_every_guid_it_revoked(self, app, client):
        """The route is addressed by one guid but revokes the whole org's
        set — the response must say so rather than imply a single delete."""
        org = str(uuid.uuid4())
        first = _issue_secret(app, org)
        with app.app_context():
            webhook_secret_service.rotate_secret(
                provider_org_guid=org, created_by_user_guid='test',
            )
        r = client.delete(f'/api/v1/admin/signing-secrets/{first["guid"]}')
        assert r.status_code == 200
        assert len(r.get_json()['revoked_guids']) == 2

    def test_revoke_unknown_guid_is_404(self, client):
        r = client.delete(f'/api/v1/admin/signing-secrets/{uuid.uuid4()}')
        assert r.status_code == 404


# ── sandbox over HTTP ─────────────────────────────────────────────────

class TestSandboxRoutes:

    def test_dispatch_requires_org_and_contract(self, client):
        r = client.post('/api/v1/admin/sandbox-dispatch',
                        json={'provider_org_guid': ORG})
        assert r.status_code == 400

    def test_dispatch_without_a_push_url_is_400(self, app, client):
        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        _issue_pat(app, org, contract)      # poll mode, no push_endpoint_url
        r = client.post('/api/v1/admin/sandbox-dispatch',
                        json={'provider_org_guid': org,
                              'contract_guid': contract})
        assert r.status_code == 400
        assert r.get_json()['code'] == 'no_webhook_url'

    def test_dispatch_reports_pass_when_the_provider_behaves(self, app, client):
        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        url = 'https://provider.example.se/hook'
        _issue_secret(app, org)
        _issue_pat(app, org, contract, delivery_mode='push',
                   push_endpoint_url=url, scopes='read,write')

        class _Resp:
            status_code = 200
            text = 'ok'

        from app.services import webhook_dispatcher
        with patch.object(webhook_dispatcher.http_requests, 'post',
                          return_value=_Resp()):
            r = client.post('/api/v1/admin/sandbox-dispatch',
                            json={'provider_org_guid': org,
                                  'contract_guid': contract,
                                  'concept_guids': ['concept-A']})
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['result'] == 'PASS'
        assert body['replay']['event_id'] == body['delivery']['event_id']

    def test_a_failing_provider_is_a_200_with_result_fail(self, app, client):
        """A provider-side failure is a successful test run reporting bad
        news, not a server error — onboard.pdhc's go-live gate reads the
        body, not the status code."""
        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        url = 'https://provider.example.se/hook'
        _issue_secret(app, org)
        _issue_pat(app, org, contract, delivery_mode='push',
                   push_endpoint_url=url, scopes='read,write')

        class _Resp:
            status_code = 500
            text = 'boom'

        from app.services import webhook_dispatcher
        with patch.object(webhook_dispatcher.http_requests, 'post',
                          return_value=_Resp()):
            r = client.post('/api/v1/admin/sandbox-dispatch',
                            json={'provider_org_guid': org,
                                  'contract_guid': contract})
        assert r.status_code == 200
        body = r.get_json()
        assert body['result'] == 'FAIL'
        assert body['stage'] == 'first_delivery'

    def test_sign_returns_the_four_pdhc_headers(self, app, client):
        org = str(uuid.uuid4())
        _issue_secret(app, org)
        r = client.post('/api/v1/admin/sandbox-sign',
                        json={'provider_org_guid': org,
                              'payload': {'event': 'x'}})
        assert r.status_code == 200, r.get_json()
        headers = r.get_json()['headers']
        for h in ('X-PDHC-Event-Id', 'X-PDHC-Event-Type',
                  'X-PDHC-Timestamp', 'X-PDHC-Signature'):
            assert headers[h]

    def test_sign_matches_compute_signature(self, app, client):
        """The whole point: a provider engineer checks their HMAC against
        ours, so ours had better be the real one."""
        import json as _json

        org = str(uuid.uuid4())
        data = _issue_secret(app, org)
        payload = {'event': 'x'}
        r = client.post('/api/v1/admin/sandbox-sign',
                        json={'provider_org_guid': org, 'payload': payload})

        from app.services import webhook_dispatcher
        body_bytes = _json.dumps(payload, separators=(',', ':'),
                                 sort_keys=True).encode('utf-8')
        with app.app_context():
            expected = webhook_dispatcher.compute_signature(
                data['secret_plaintext'], body_bytes,
            )
        assert r.get_json()['headers']['X-PDHC-Signature'] == expected

    def test_sign_without_a_secret_is_404(self, client):
        r = client.post('/api/v1/admin/sandbox-sign',
                        json={'provider_org_guid': str(uuid.uuid4()),
                              'payload': {'a': 1}})
        assert r.status_code == 404

    def test_sign_requires_org_and_payload(self, client):
        r = client.post('/api/v1/admin/sandbox-sign',
                        json={'provider_org_guid': ORG})
        assert r.status_code == 400


# ── X-Skip-Auto-Provision on the internal route ───────────────────────

class TestSkipAutoProvision:

    _KEY = {'X-Service-Key': 'test-internal-service-key-12345'}

    def test_header_skips_provisioning(self, app, client):
        from app.models.security_models import ProviderAccessToken

        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        r = client.post('/api/v1/internal/auto-provision-pat',
                        json={'provider_org_guid': org,
                              'contract_guid': contract},
                        headers={**self._KEY, 'X-Skip-Auto-Provision': '1'})
        assert r.status_code == 200
        assert r.get_json()['status'] == 'skipped'
        with app.app_context():
            assert ProviderAccessToken.query.filter_by(
                provider_org_guid=org, contract_guid=contract,
            ).count() == 0

    def test_without_the_header_a_pat_is_created(self, app, client):
        from app.models.security_models import ProviderAccessToken

        org, contract = str(uuid.uuid4()), str(uuid.uuid4())
        r = client.post('/api/v1/internal/auto-provision-pat',
                        json={'provider_org_guid': org,
                              'contract_guid': contract},
                        headers=self._KEY)
        assert r.status_code in (200, 201), r.get_json()
        with app.app_context():
            assert ProviderAccessToken.query.filter_by(
                provider_org_guid=org, contract_guid=contract,
            ).count() == 1
