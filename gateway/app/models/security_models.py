"""Security models — Provider Access Tokens, Webhook Signing Secrets,
and Data Exchange Grants.

ProviderAccessToken: binds a hashed token to a provider org + contract.
WebhookSigningSecret: per-org HMAC key for signing outbound webhook bodies.
DataExchangeGrant: HMAC-signed composite key for patient data exchange.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import bcrypt

from app import db

# How long a deprecated PAT remains accepted after rotation (ticket #136).
PAT_DEPRECATED_GRACE_DAYS = int(
    os.environ.get('PAT_DEPRECATED_GRACE_DAYS', '14')
)


class ProviderAccessToken(db.Model):
    """Binds an API token to a specific provider organisation and contract."""
    __tablename__ = 'provider_access_tokens'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    token_hash = db.Column(db.String(255), nullable=False)
    provider_org_guid = db.Column(db.String(36), nullable=False, index=True)
    contract_guid = db.Column(db.String(36), nullable=False, index=True)
    scopes = db.Column(db.String(255), nullable=False, default='read')
    delivery_mode = db.Column(db.String(20), nullable=False, default='poll')  # push | poll
    push_endpoint_url = db.Column(db.String(512), nullable=True)
    push_auth_key_encrypted = db.Column(db.String(512), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    # Three-state status (ticket #136). `revoked` boolean is preserved
    # for backward compat with consumers that haven't migrated yet.
    # Allowed values: 'active', 'deprecated', 'revoked'. A rotated PAT
    # is marked 'deprecated' and remains accepted for
    # PAT_DEPRECATED_GRACE_DAYS so providers can swap tokens at their
    # own pace.
    status = db.Column(db.String(20), nullable=False, default='active', index=True)
    deprecated_at = db.Column(db.DateTime, nullable=True)
    rotated_to_guid = db.Column(db.String(36), nullable=True)
    created_by_user_guid = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def hash_token(raw_token):
        return bcrypt.hashpw(raw_token.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')

    def verify_token(self, raw_token):
        return bcrypt.checkpw(raw_token.encode('utf-8'), self.token_hash.encode('utf-8'))

    def is_valid(self):
        """Active or grace-period deprecated PATs are accepted.

        Backward compatible: a PAT with `revoked=True` is still
        rejected regardless of `status`, in case a consumer flipped
        the bool but not the new column.
        """
        if self.revoked or self.status == 'revoked':
            return False
        if self.expires_at:
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return False
        if self.status == 'deprecated':
            if not self.deprecated_at:
                return False  # malformed — defensive
            dep = self.deprecated_at if self.deprecated_at.tzinfo \
                else self.deprecated_at.replace(tzinfo=timezone.utc)
            grace_until = dep + timedelta(days=PAT_DEPRECATED_GRACE_DAYS)
            if datetime.now(timezone.utc) > grace_until:
                return False
        return True

    def has_scope(self, scope):
        return scope in self.scopes.split(',')

    def to_dict(self):
        return {
            'guid': self.guid,
            'provider_org_guid': self.provider_org_guid,
            'contract_guid': self.contract_guid,
            'scopes': self.scopes,
            'delivery_mode': self.delivery_mode,
            'push_endpoint_url': self.push_endpoint_url,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'status': self.status,
            'deprecated_at': self.deprecated_at.isoformat() if self.deprecated_at else None,
            'rotated_to_guid': self.rotated_to_guid,
            'revoked': self.revoked,
            'created_by_user_guid': self.created_by_user_guid,
            'created_at': self.created_at.isoformat(),
        }


class DataExchangeGrant(db.Model):
    """HMAC-signed composite key authorizing data exchange for one ServiceRequest."""
    __tablename__ = 'data_exchange_grants'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    service_request_guid = db.Column(db.String(36), db.ForeignKey('service_requests.guid'), nullable=False)
    patient_guid = db.Column(db.String(36), nullable=False, index=True)
    provider_org_guid = db.Column(db.String(36), nullable=False, index=True)
    contract_guid = db.Column(db.String(36), nullable=False)
    grant_token = db.Column(db.String(128), nullable=False)
    grant_type = db.Column(db.String(20), nullable=False, default='bidirectional')  # download | upload | bidirectional
    expires_at = db.Column(db.DateTime, nullable=False)
    used_count = db.Column(db.Integer, nullable=False, default=0)
    max_uses = db.Column(db.Integer, nullable=True)  # NULL = unlimited
    revoked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def is_valid(self):
        if self.revoked:
            return False
        exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            return False
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False
        return True

    def record_use(self):
        self.used_count += 1

    def to_dict(self):
        return {
            'guid': self.guid,
            'service_request_guid': self.service_request_guid,
            'patient_guid': self.patient_guid,
            'provider_org_guid': self.provider_org_guid,
            'contract_guid': self.contract_guid,
            'grant_type': self.grant_type,
            'expires_at': self.expires_at.isoformat(),
            'used_count': self.used_count,
            'max_uses': self.max_uses,
            'revoked': self.revoked,
            'created_at': self.created_at.isoformat(),
        }


class WebhookSigningSecret(db.Model):
    """Per-provider HMAC key for signing outbound webhook bodies (ticket #136).

    Secrets are encrypted with Fernet (cryptography lib) using the
    application-wide key from env `WEBHOOK_SECRETS_KEY`. Fernet is
    AES-128-CBC + HMAC-SHA256 + URL-safe base64 — adequate for now;
    when KMS is available the secret_encrypted column gets re-keyed
    transparently because the row already isolates the ciphertext.

    Lifecycle mirrors PAT three-state: active / deprecated / revoked.
    On rotation the previous secret is kept as 'deprecated' so the
    dispatcher can keep verifying for the grace period; new bodies
    are signed only with the active secret.
    """
    __tablename__ = 'webhook_signing_secrets'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False,
                     default=lambda: str(uuid.uuid4()))
    provider_org_guid = db.Column(db.String(36), nullable=False, index=True)
    secret_encrypted = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='active', index=True)
    issued_at = db.Column(db.DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    deprecated_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    rotated_to_guid = db.Column(db.String(36), nullable=True)
    created_by_user_guid = db.Column(db.String(36), nullable=False)

    def is_valid_for_signing(self):
        """Only 'active' is used for new signatures (no grace period
        on signing — a rotated secret stops signing immediately)."""
        return self.status == 'active'

    def is_valid_for_verification(self):
        """Active and grace-period deprecated are accepted for verify."""
        if self.status == 'active':
            return True
        if self.status == 'deprecated' and self.deprecated_at:
            dep = self.deprecated_at if self.deprecated_at.tzinfo \
                else self.deprecated_at.replace(tzinfo=timezone.utc)
            grace_until = dep + timedelta(days=PAT_DEPRECATED_GRACE_DAYS)
            return datetime.now(timezone.utc) <= grace_until
        return False

    def to_dict(self):
        return {
            'guid': self.guid,
            'provider_org_guid': self.provider_org_guid,
            'status': self.status,
            'issued_at': self.issued_at.isoformat() if self.issued_at else None,
            'deprecated_at': self.deprecated_at.isoformat()
                if self.deprecated_at else None,
            'revoked_at': self.revoked_at.isoformat()
                if self.revoked_at else None,
            'rotated_to_guid': self.rotated_to_guid,
            'created_by_user_guid': self.created_by_user_guid,
        }
