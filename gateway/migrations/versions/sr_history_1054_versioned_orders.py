"""#1054: versioned ServiceRequests and CarePlans; JournalBestallning fields.

  * service_request_history, care_plan_history: append-only (a trigger
    refuses UPDATE, and DELETE unless the session sets
    request.allow_history_purge - app/services/history_guard.py);
  * service_requests: version, version_author_guid, version_reason, reason,
    encounter_guid, replaces, supporting_info, annotations (all nullable or
    defaulted - additive);
  * care_plans: version, version_author_guid, version_reason.

Existing rows become version 1 with version_reason marking that versioning
began here (their earlier changes were never recorded); the extract says so.

Revision ID: sr_history_1054
Revises: f2a3b4c5d6e7
"""
from alembic import op
import sqlalchemy as sa

revision = "sr_history_1054"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None

PRE = 'pre-1054: versioning began here; earlier changes were not recorded'
HISTORY_TABLES = ("service_request_history", "care_plan_history")


def _history_cols(fk, with_fhir):
    cols = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guid", sa.String(36), nullable=False, unique=True),
        sa.Column(fk, sa.String(36), nullable=False),
        sa.Column("patient_guid", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("row", sa.JSON(), nullable=False),
    ]
    if with_fhir:
        cols.append(sa.Column("fhir_resource", sa.JSON(), nullable=True))
    cols += [
        sa.Column("version_recorded_at", sa.DateTime(), nullable=True),
        sa.Column("version_author_guid", sa.String(36), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("changed_by_user_guid", sa.String(36), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("change_action", sa.String(80), nullable=True),
    ]
    return cols


def _add(table, have, col):
    if col.name not in have:
        op.add_column(table, col)


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "service_request_history" not in tables:
        op.create_table("service_request_history",
                        *_history_cols("service_request_guid", True),
                        sa.UniqueConstraint("service_request_guid", "version",
                                            name="uq_sr_history_version"))
        op.create_index("ix_service_request_history_service_request_guid",
                        "service_request_history", ["service_request_guid"])
        op.create_index("ix_service_request_history_patient_guid",
                        "service_request_history", ["patient_guid"])
    if "care_plan_history" not in tables:
        op.create_table("care_plan_history",
                        *_history_cols("care_plan_guid", False),
                        sa.UniqueConstraint("care_plan_guid", "version",
                                            name="uq_cp_history_version"))
        op.create_index("ix_care_plan_history_care_plan_guid",
                        "care_plan_history", ["care_plan_guid"])
        op.create_index("ix_care_plan_history_patient_guid",
                        "care_plan_history", ["patient_guid"])

    have = {c["name"] for c in insp.get_columns("service_requests")}
    for col in (
            sa.Column("reason", sa.JSON(), nullable=True),
            sa.Column("encounter_guid", sa.String(36), nullable=True),
            sa.Column("replaces", sa.JSON(), nullable=True),
            sa.Column("supporting_info", sa.JSON(), nullable=True),
            sa.Column("annotations", sa.JSON(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("version_author_guid", sa.String(36), nullable=True),
            sa.Column("version_reason", sa.Text(), nullable=True)):
        _add("service_requests", have, col)
    if "encounter_guid" not in have:
        op.create_index("ix_service_requests_encounter_guid", "service_requests",
                        ["encounter_guid"])

    have = {c["name"] for c in insp.get_columns("care_plans")}
    for col in (
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("version_author_guid", sa.String(36), nullable=True),
            sa.Column("version_reason", sa.Text(), nullable=True)):
        _add("care_plans", have, col)

    # existing rows: version 1, marked as the moment versioning began
    op.execute(sa.text("UPDATE service_requests SET version_reason = :r "
                       "WHERE version_reason IS NULL").bindparams(r=PRE))
    op.execute(sa.text("UPDATE care_plans SET version_reason = :r "
                       "WHERE version_reason IS NULL").bindparams(r=PRE))

    # append-only triggers (the same DDL create_all installs in tests)
    from app.services.history_guard import ddl_for
    for t in HISTORY_TABLES:
        for stmt in ddl_for(t, bind.dialect.name):
            op.execute(sa.text(stmt))


def downgrade():
    bind = op.get_bind()
    from app.services.history_guard import drop_ddl_for
    for t in HISTORY_TABLES:
        for stmt in drop_ddl_for(t, bind.dialect.name):
            op.execute(sa.text(stmt))
    for col in ("version_reason", "version_author_guid", "version"):
        op.drop_column("care_plans", col)
    op.drop_index("ix_service_requests_encounter_guid", table_name="service_requests")
    for col in ("version_reason", "version_author_guid", "version", "annotations",
                "supporting_info", "replaces", "encounter_guid", "reason"):
        op.drop_column("service_requests", col)
    op.drop_table("care_plan_history")
    op.drop_table("service_request_history")
