"""#774: record the patient's organisation on the ServiceRequest.

The organisation the patient was affiliated with in ips **at request time**
(#768). It cannot be reconstructed later: ips's `patient_clinic_assignments`
carries `assigned_at` and no end timestamp, so a lookup a year from now returns
today's answer for a year-old request. Captured at create time and stored.

Distinct from `requester_org_guid` on the same row, which is who ORDERED the
collection. Operator, 2026-10-06: "requesting clinic is not the same as the
patient affiliation clinic". All 27 existing ServiceRequests have one requesting
org (UAS); the patients' own clinics are a different fact.

Nullable: resolution returns None rather than guessing when the patient has no
clinic, has several resolving to different organisations, or the clinic carries
no organisation_guid.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""
from alembic import op
import sqlalchemy as sa

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("service_requests")}
    if "patient_org_guid" not in have:
        op.add_column("service_requests",
                      sa.Column("patient_org_guid", sa.String(36), nullable=True))
    if "ix_service_requests_patient_org" not in {
            i["name"] for i in insp.get_indexes("service_requests")}:
        op.create_index("ix_service_requests_patient_org", "service_requests",
                        ["patient_org_guid"])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if "ix_service_requests_patient_org" in {
            i["name"] for i in insp.get_indexes("service_requests")}:
        op.drop_index("ix_service_requests_patient_org",
                      table_name="service_requests")
    if "patient_org_guid" in {c["name"] for c in insp.get_columns("service_requests")}:
        op.drop_column("service_requests", "patient_org_guid")
