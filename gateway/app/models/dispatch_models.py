import uuid
from datetime import datetime, timezone
from flask_login import UserMixin
from app import db


class LocalUser(UserMixin, db.Model):
    """Minimal local user for Flask-Login session management.
    Real auth is handled by SSO. This stores the session state."""
    __tablename__ = 'local_users'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    sso_user_guid = db.Column(db.String(36), unique=True, nullable=True)
    email = db.Column(db.String(255), nullable=True)
    display_name = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default='read_only')
    is_active = db.Column(db.Boolean, default=True)
    access_blob = db.Column(db.JSON, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class DispatchRequest(db.Model):
    __tablename__ = 'dispatch_requests'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    careplan_guid = db.Column(db.String(36), nullable=False)
    provider_guid = db.Column(db.String(36), nullable=False)
    assigned_user_guid = db.Column(db.String(36), nullable=True)
    dispatch_notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    idempotency_key = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    receipts = db.relationship('DispatchReceipt', backref='dispatch_request', lazy=True)

    def to_dict(self):
        return {
            'guid': self.guid,
            'careplan_guid': self.careplan_guid,
            'provider_guid': self.provider_guid,
            'assigned_user_guid': self.assigned_user_guid,
            'dispatch_notes': self.dispatch_notes,
            'status': self.status,
            'idempotency_key': self.idempotency_key,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class DispatchReceipt(db.Model):
    __tablename__ = 'dispatch_receipts'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    dispatch_request_guid = db.Column(db.String(36), db.ForeignKey('dispatch_requests.guid'), nullable=False)
    receipt_token = db.Column(db.String(255), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    status = db.Column(db.String(20), nullable=False, default='accepted')
    response_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'dispatch_request_guid': self.dispatch_request_guid,
            'receipt_token': self.receipt_token,
            'status': self.status,
            'response_payload': self.response_payload,
            'created_at': self.created_at.isoformat(),
        }
