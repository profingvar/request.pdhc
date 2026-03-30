import uuid
from datetime import datetime, timezone
from app import db


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    correlation_id = db.Column(db.String(255), nullable=True)
    user_guid = db.Column(db.String(36), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(50), nullable=True)
    resource_guid = db.Column(db.String(36), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    data_subject_guid = db.Column(db.String(36), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'correlation_id': self.correlation_id,
            'user_guid': self.user_guid,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_guid': self.resource_guid,
            'details': self.details,
            'ip_address': self.ip_address,
            'data_subject_guid': self.data_subject_guid,
            'created_at': self.created_at.isoformat(),
        }
