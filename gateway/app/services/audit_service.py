import uuid
from flask import current_app
from app import db
from app.models.audit_models import AuditLog


def log_event(user_guid=None, action='', resource_type=None, resource_guid=None,
              details=None, correlation_id=None, ip_address=None):
    """Log an audit event to the database."""
    try:
        entry = AuditLog(
            correlation_id=correlation_id or str(uuid.uuid4()),
            user_guid=user_guid,
            action=action,
            resource_type=resource_type,
            resource_guid=resource_guid,
            details=details,
            ip_address=ip_address,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Audit log failed: {e}")
        db.session.rollback()
