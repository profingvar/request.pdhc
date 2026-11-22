"""#1043: Questionnaire registry + canonical reference on an attached form.

A ServiceRequest may reference a FHIR Questionnaire by canonical url + version
(the patient app's form and EPS-form tasks). The Questionnaire JSON is held in
`questionnaires` and frozen onto `service_request_forms.form_snapshot` when
attached. Additive: a new table and two nullable columns.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "questionnaires" not in insp.get_table_names():
        op.create_table(
            "questionnaires",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("guid", sa.String(36), nullable=False, unique=True),
            sa.Column("url", sa.String(255), nullable=False),
            sa.Column("version", sa.String(50), nullable=False),
            sa.Column("title", sa.String(255), nullable=True),
            sa.Column("resource", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("url", "version",
                                name="uq_questionnaire_url_version"),
        )
        op.create_index("ix_questionnaires_url", "questionnaires", ["url"])
    have = {c["name"] for c in insp.get_columns("service_request_forms")}
    if "questionnaire_url" not in have:
        op.add_column("service_request_forms",
                      sa.Column("questionnaire_url", sa.String(255), nullable=True))
    if "questionnaire_version" not in have:
        op.add_column("service_request_forms",
                      sa.Column("questionnaire_version", sa.String(50), nullable=True))


def downgrade():
    op.drop_column("service_request_forms", "questionnaire_version")
    op.drop_column("service_request_forms", "questionnaire_url")
    op.drop_index("ix_questionnaires_url", table_name="questionnaires")
    op.drop_table("questionnaires")
