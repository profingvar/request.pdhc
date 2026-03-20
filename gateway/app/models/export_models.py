import uuid
from datetime import datetime, timezone
from app import db


class ExportRecord(db.Model):
    __tablename__ = 'export_records'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    careplan_guid = db.Column(db.String(36), nullable=False)
    user_guid = db.Column(db.String(36), nullable=True)
    export_type = db.Column(db.String(20), nullable=False, default='csv')
    row_count = db.Column(db.Integer, nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    schema_version = db.Column(db.String(20), nullable=False, default='1.0.0')
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'careplan_guid': self.careplan_guid,
            'user_guid': self.user_guid,
            'export_type': self.export_type,
            'row_count': self.row_count,
            'file_name': self.file_name,
            'schema_version': self.schema_version,
            'created_at': self.created_at.isoformat(),
        }
