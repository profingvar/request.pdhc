"""#318 (2026-06-28): rename `careplan_guid` -> `plan_definition_guid`
on dispatch_requests and export_records.

Pre-#310 the platform used "CarePlan" as a URL-level misnomer for
PlanDefinition. Both columns always held a PlanDefinition guid; only
the name was wrong.

Both tables are empty at the time of writing (0 dispatch_requests,
0 export_records) — the rename is data-safe with no transformation
needed.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8c9d0e1f2a3'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'dispatch_requests' in tables:
        cols = {c['name'] for c in inspector.get_columns('dispatch_requests')}
        if 'careplan_guid' in cols and 'plan_definition_guid' not in cols:
            op.alter_column(
                'dispatch_requests', 'careplan_guid',
                new_column_name='plan_definition_guid',
            )

    if 'export_records' in tables:
        cols = {c['name'] for c in inspector.get_columns('export_records')}
        if 'careplan_guid' in cols and 'plan_definition_guid' not in cols:
            op.alter_column(
                'export_records', 'careplan_guid',
                new_column_name='plan_definition_guid',
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'dispatch_requests' in tables:
        cols = {c['name'] for c in inspector.get_columns('dispatch_requests')}
        if 'plan_definition_guid' in cols and 'careplan_guid' not in cols:
            op.alter_column(
                'dispatch_requests', 'plan_definition_guid',
                new_column_name='careplan_guid',
            )

    if 'export_records' in tables:
        cols = {c['name'] for c in inspector.get_columns('export_records')}
        if 'plan_definition_guid' in cols and 'careplan_guid' not in cols:
            op.alter_column(
                'export_records', 'plan_definition_guid',
                new_column_name='careplan_guid',
            )
