"""#984: diagnosis review as a PlanDefinition step — ServiceRequest columns.

A PlanDefinition action with definitionCanonical
https://icd11.pdhc.se/fhir/ActivityDefinition/diagnosis-review becomes its own
ServiceRequest (contract: plans/984_diagnosis_review_contract.md, section 2).
All columns nullable and additive; existing rows read as kind NULL = an
ordinary order ServiceRequest, behaviour unchanged.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("kind", sa.String(40)),
    ("instantiates_canonical", sa.String(255)),
    ("code_scope", sa.JSON()),
    ("performer_type", sa.String(40)),
    ("based_on_guid", sa.String(36)),
    ("completion_record", sa.JSON()),
)
_INDEXES = (
    ("ix_service_requests_kind", "kind"),
    ("ix_service_requests_based_on_guid", "based_on_guid"),
)


def upgrade():
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("service_requests")}
    for name, type_ in _COLUMNS:
        if name not in have:
            op.add_column("service_requests",
                          sa.Column(name, type_, nullable=True))
    have_ix = {i["name"] for i in insp.get_indexes("service_requests")}
    for ix, col in _INDEXES:
        if ix not in have_ix:
            op.create_index(ix, "service_requests", [col])


def downgrade():
    insp = sa.inspect(op.get_bind())
    have_ix = {i["name"] for i in insp.get_indexes("service_requests")}
    for ix, _ in _INDEXES:
        if ix in have_ix:
            op.drop_index(ix, table_name="service_requests")
    have = {c["name"] for c in insp.get_columns("service_requests")}
    for name, _ in reversed(_COLUMNS):
        if name in have:
            op.drop_column("service_requests", name)
