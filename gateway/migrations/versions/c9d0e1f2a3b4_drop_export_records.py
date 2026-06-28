"""#320 (2026-06-28): drop export_records (legacy dead-code cleanup).

The export_records table was written by the /CarePlan/<guid>/export/csv
endpoint, which proxied a plan.pdhc URL that never existed. Every
call returned 502 upstream_error before reaching the INSERT, so the
table accumulated 0 rows in production over its entire lifetime.

#320 deletes the dead-code cluster (api/export.py, routes/export.py,
services/parse_service.py, services/csv_service.py, services/
careplan_service.py, api/careplans.py, routes/careplans.py,
models/export_models.py, plus the careplans/ and export/ template
dirs and their three test files). This migration removes the
matching DB table.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b4'
down_revision = 'b8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'export_records' in inspector.get_table_names():
        op.drop_table('export_records')


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'export_records' in inspector.get_table_names():
        return
    op.create_table(
        'export_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('guid', sa.String(36), unique=True, nullable=False),
        sa.Column('plan_definition_guid', sa.String(36), nullable=False),
        sa.Column('user_guid', sa.String(36), nullable=True),
        sa.Column('export_type', sa.String(20), nullable=False, server_default='csv'),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('file_name', sa.String(255), nullable=True),
        sa.Column('schema_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )
