"""PAT three-state status + webhook signing secret tests (ticket #136).

Standalone — does NOT depend on the package conftest (broken; #149).
Builds a minimal Flask app + SQLite memory DB so the lifecycle paths
run end-to-end.
"""
import os
import sys
from datetime import datetime, timezone, timedelta

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
os.environ.setdefault('PAT_DEPRECATED_GRACE_DAYS', '14')

# Generate a Fernet key for tests
from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault('WEBHOOK_SECRETS_KEY', Fernet.generate_key().decode('utf-8'))

import pytest  # noqa: E402

from app import db as _db  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_security_tables(app):
    """Each test starts with empty PAT + signing-secret tables.

    `app` is the session-scope fixture from tests/conftest.py.
    """
    with app.app_context():
        from app.models.security_models import (
            ProviderAccessToken, WebhookSigningSecret,
        )
        ProviderAccessToken.query.delete()
        WebhookSigningSecret.query.delete()
        _db.session.commit()
        yield
        _db.session.rollback()


# ── PAT three-state ────────────────────────────────────────────────────


ORG = 'org-1111'
CONTRACT = 'contract-1111'


def test_issue_pat_starts_as_active(app):
    from app.services.pat_service import issue_pat
    with app.app_context():
        data, status = issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        assert status == 201
        assert data['status'] == 'active'
        assert data['raw_token']


def test_validate_pat_accepts_active(app):
    from app.services.pat_service import issue_pat, validate_pat
    with app.app_context():
        data, _ = issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        pat = validate_pat(data['raw_token'])
        assert pat is not None
        assert pat.status == 'active'


def test_rotate_pat_marks_old_deprecated_new_active(app):
    from app.services.pat_service import issue_pat, rotate_pat, validate_pat
    from app.models.security_models import ProviderAccessToken
    with app.app_context():
        old, _ = issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        new, status = rotate_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        assert status == 201

        # Both tokens validate during the grace period.
        old_pat = validate_pat(old['raw_token'])
        new_pat = validate_pat(new['raw_token'])
        assert old_pat is not None
        assert new_pat is not None
        assert old_pat.status == 'deprecated'
        assert new_pat.status == 'active'
        assert old_pat.rotated_to_guid == new_pat.guid


def test_deprecated_pat_expires_after_grace(app):
    from app.services.pat_service import issue_pat, rotate_pat, validate_pat
    from app.models.security_models import ProviderAccessToken
    with app.app_context():
        old, _ = issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        rotate_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        # Backdate the deprecation past the 14-day grace.
        old_pat = ProviderAccessToken.query.filter_by(guid=old['guid']).first()
        old_pat.deprecated_at = datetime.now(timezone.utc) - timedelta(days=20)
        _db.session.commit()

        assert validate_pat(old['raw_token']) is None


def test_revoke_pat_immediately_rejects(app):
    from app.services.pat_service import issue_pat, revoke_pat, validate_pat
    with app.app_context():
        data, _ = issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        revoke_pat(data['guid'], user_guid='test')
        assert validate_pat(data['raw_token']) is None


def test_validate_rejects_legacy_revoked_bool(app):
    """A PAT with revoked=True must be rejected even if status='active'
    (covers DB rows mutated by older code)."""
    from app.services.pat_service import issue_pat, validate_pat
    from app.models.security_models import ProviderAccessToken
    with app.app_context():
        data, _ = issue_pat(
            provider_org_guid=ORG, contract_guid=CONTRACT,
            created_by_user_guid='test',
        )
        pat = ProviderAccessToken.query.filter_by(guid=data['guid']).first()
        pat.revoked = True  # legacy bool only
        _db.session.commit()
        assert validate_pat(data['raw_token']) is None


# ── Webhook signing secrets ────────────────────────────────────────────


def test_register_secret_returns_plaintext_once(app):
    from app.services.webhook_secret_service import register_secret
    with app.app_context():
        data, status = register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        assert status == 201
        assert data['status'] == 'active'
        assert data['secret_plaintext']
        # Saved row exposes status but NOT the plaintext
        assert 'secret_plaintext' not in data.get('encrypted_form', {})


def test_register_twice_returns_409(app):
    from app.services.webhook_secret_service import register_secret
    with app.app_context():
        register_secret(provider_org_guid=ORG, created_by_user_guid='test')
        data, status = register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        assert status == 409
        assert data['code'] == 'already_exists'


def test_rotate_secret_deprecates_old_returns_new(app):
    from app.services.webhook_secret_service import (
        register_secret, rotate_secret, get_signing_secret,
        get_verification_secrets,
    )
    with app.app_context():
        first, _ = register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        second, _ = rotate_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )

        # Active secret = the new one
        signing = get_signing_secret(ORG)
        assert signing == second['secret_plaintext']
        assert signing != first['secret_plaintext']

        # Verification accepts BOTH during grace
        verify_set = set(get_verification_secrets(ORG))
        assert first['secret_plaintext'] in verify_set
        assert second['secret_plaintext'] in verify_set


def test_revoke_secret_kills_all(app):
    from app.services.webhook_secret_service import (
        register_secret, rotate_secret, revoke_secret,
        get_signing_secret, get_verification_secrets,
    )
    with app.app_context():
        register_secret(provider_org_guid=ORG, created_by_user_guid='test')
        rotate_secret(provider_org_guid=ORG, created_by_user_guid='test')

        data, status = revoke_secret(provider_org_guid=ORG, user_guid='test')
        assert status == 200
        assert len(data['revoked_guids']) == 2  # active + deprecated

        assert get_signing_secret(ORG) is None
        assert get_verification_secrets(ORG) == []


def test_decrypt_roundtrip_works(app):
    """Sanity: a registered secret decrypts back to the same plaintext."""
    from app.services.webhook_secret_service import (
        register_secret, get_signing_secret,
    )
    with app.app_context():
        data, _ = register_secret(
            provider_org_guid=ORG, created_by_user_guid='test',
        )
        assert get_signing_secret(ORG) == data['secret_plaintext']
