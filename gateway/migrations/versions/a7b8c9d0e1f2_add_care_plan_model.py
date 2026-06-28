"""add care_plans table + ServiceRequest.care_plan_guid (#310)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-28 21:00:00.000000

Phase 2 of the clinical-context harmonisation (#294 RFC decision A1).

Adds the patient-specific CarePlan instance model that the platform
has been missing — until now "CarePlan" was used as a URL-level
misnomer for PlanDefinition. The new model gives Observations a
proper patient-scoped provenance hook.

Also adds care_plan_guid to ServiceRequest as an optional FK (Option
X in the ticket). New SRs derived from a CarePlan reference it; SRs
issued directly against a PlanDefinition leave it NULL — backwards
compatible.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'care_plans',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('guid', sa.String(36), unique=True, nullable=False),
        sa.Column('patient_guid', sa.String(36), nullable=False),
        sa.Column('plan_definition_guid', sa.String(36), nullable=False),
        sa.Column('status', sa.String(20), nullable=False,
                  server_default='draft'),
        sa.Column('intent', sa.String(20), nullable=False,
                  server_default='plan'),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('plan_definition_snapshot', sa.JSON, nullable=True),
        sa.Column('goals', sa.JSON, nullable=True),
        sa.Column('care_team_user_guids', sa.JSON, nullable=True),
        sa.Column('created_by_user_guid', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('ix_care_plans_patient',
                    'care_plans', ['patient_guid'])
    op.create_index('ix_care_plans_plan_definition',
                    'care_plans', ['plan_definition_guid'])
    op.create_index('ix_care_plans_status',
                    'care_plans', ['status'])

    # Add care_plan_guid to service_requests. NULL when SR is issued
    # directly against a PlanDefinition (legacy / direct workflow).
    with op.batch_alter_table('service_requests', schema=None) as batch:
        batch.add_column(sa.Column('care_plan_guid',
                                    sa.String(36), nullable=True))
    op.create_index('ix_service_requests_care_plan',
                    'service_requests', ['care_plan_guid'])


def downgrade():
    op.drop_index('ix_service_requests_care_plan',
                  table_name='service_requests')
    with op.batch_alter_table('service_requests', schema=None) as batch:
        batch.drop_column('care_plan_guid')

    op.drop_index('ix_care_plans_status', table_name='care_plans')
    op.drop_index('ix_care_plans_plan_definition', table_name='care_plans')
    op.drop_index('ix_care_plans_patient', table_name='care_plans')
    op.drop_table('care_plans')
