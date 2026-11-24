"""#1054: append-only version history of ServiceRequests and CarePlans.

record.pdhc points at an order by VERSION (`ServiceRequest/<guid>/_history/n`,
plan §2.2), and such a reference is worthless if the version can be rewritten.
Before #1054 an order was changed in place and its earlier states were gone.

Each row is ONE EARLIER VERSION, written when it was superseded:

  * `version`, `status`, `row` (every column of the main table as it was,
    except `fhir_resource`), `fhir_resource` (as it was);
  * `version_recorded_at` / `version_author_guid`: when that version came into
    being and who made it (copied from the main row as it was);
  * `changed_at` / `changed_by_user_guid` / `change_reason` / `change_action`:
    the change that ENDED this version.

The current version is the main row itself (`version` there is current).
Written by app/services/versioning.py in a before_flush hook, so no code path
can change an order without leaving the old state here. Guarded against UPDATE
and DELETE by app/services/history_guard.py (ORM event + database trigger).
"""
import uuid
from datetime import datetime, timezone

from app import db


def _now():
    return datetime.now(timezone.utc)


class ServiceRequestHistory(db.Model):
    __tablename__ = 'service_request_history'
    __table_args__ = (
        db.UniqueConstraint('service_request_guid', 'version', name='uq_sr_history_version'),
    )

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    # no FK: the history must outlive anything done to the main row
    service_request_guid = db.Column(db.String(36), nullable=False, index=True)
    patient_guid = db.Column(db.String(36), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False)
    row = db.Column(db.JSON, nullable=False)
    fhir_resource = db.Column(db.JSON, nullable=True)
    version_recorded_at = db.Column(db.DateTime, nullable=True)
    version_author_guid = db.Column(db.String(36), nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=_now)
    changed_by_user_guid = db.Column(db.String(36), nullable=True)
    change_reason = db.Column(db.Text, nullable=True)
    change_action = db.Column(db.String(80), nullable=True)


class CarePlanHistory(db.Model):
    __tablename__ = 'care_plan_history'
    __table_args__ = (
        db.UniqueConstraint('care_plan_guid', 'version', name='uq_cp_history_version'),
    )

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    care_plan_guid = db.Column(db.String(36), nullable=False, index=True)
    patient_guid = db.Column(db.String(36), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    row = db.Column(db.JSON, nullable=False)
    version_recorded_at = db.Column(db.DateTime, nullable=True)
    version_author_guid = db.Column(db.String(36), nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=_now)
    changed_by_user_guid = db.Column(db.String(36), nullable=True)
    change_reason = db.Column(db.Text, nullable=True)
    change_action = db.Column(db.String(80), nullable=True)
