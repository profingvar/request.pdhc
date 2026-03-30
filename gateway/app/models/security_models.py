"""Security models — Provider Access Tokens and Data Exchange Grants.

ProviderAccessToken: binds a hashed token to a provider org + contract.
DataExchangeGrant: HMAC-signed composite key for patient data exchange.
"""
import uuid
from datetime import datetime, timezone

import bcrypt

from app import db


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
    created_by_user_guid = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    @staticmethod
    def hash_token(raw_token):
        return bcrypt.hashpw(raw_token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def verify_token(self, raw_token):
        return bcrypt.checkpw(raw_token.encode('utf-8'), self.token_hash.encode('utf-8'))

    def is_valid(self):
        if self.revoked:
            return False
        if self.expires_at:
            exp = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
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
