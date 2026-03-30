"""add service_request tables

Revision ID: a1b2c3d4e5f6
Revises: 837810485062
Create Date: 2026-03-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '837810485062'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('service_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guid', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('intent', sa.String(length=20), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=False),
        sa.Column('patient_guid', sa.String(length=36), nullable=False),
        sa.Column('patient_excerpt', sa.JSON(), nullable=True),
        sa.Column('plan_definition_guid', sa.String(length=36), nullable=False),
        sa.Column('plan_definition_snapshot', sa.JSON(), nullable=True),
        sa.Column('fhir_resource', sa.JSON(), nullable=True),
        sa.Column('contract_guid', sa.String(length=36), nullable=True),
        sa.Column('requester_user_guid', sa.String(length=36), nullable=False),
        sa.Column('requester_org_guid', sa.String(length=36), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('period_start', sa.DateTime(), nullable=True),
        sa.Column('period_end', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guid'),
    )
    op.create_index('ix_service_requests_patient_guid', 'service_requests', ['patient_guid'])
    op.create_index('ix_service_requests_contract_guid', 'service_requests', ['contract_guid'])
    op.create_index('ix_service_requests_requester_org_guid', 'service_requests', ['requester_org_guid'])

    op.create_table('service_request_contract_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guid', sa.String(length=36), nullable=False),
        sa.Column('service_request_guid', sa.String(length=36), nullable=False),
        sa.Column('contract_guid', sa.String(length=36), nullable=False),
        sa.Column('provider_org_guid', sa.String(length=36), nullable=False),
        sa.Column('provider_name', sa.String(length=255), nullable=True),
        sa.Column('match_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('response_at', sa.DateTime(), nullable=True),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['service_request_guid'], ['service_requests.guid']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guid'),
    )
    op.create_index('ix_service_request_contract_matches_provider_org_guid',
                     'service_request_contract_matches', ['provider_org_guid'])

    op.create_table('service_request_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guid', sa.String(length=36), nullable=False),
        sa.Column('service_request_guid', sa.String(length=36), nullable=False),
        sa.Column('contract_match_guid', sa.String(length=36), nullable=False),
        sa.Column('receipt_token', sa.String(length=255), nullable=False),
        sa.Column('delivery_method', sa.String(length=20), nullable=False),
        sa.Column('delivery_status', sa.String(length=30), nullable=False),
        sa.Column('delivery_payload', sa.JSON(), nullable=True),
        sa.Column('response_received', sa.Boolean(), nullable=True),
        sa.Column('response_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['service_request_guid'], ['service_requests.guid']),
        sa.ForeignKeyConstraint(['contract_match_guid'], ['service_request_contract_matches.guid']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guid'),
        sa.UniqueConstraint('receipt_token'),
    )


def downgrade():
    op.drop_table('service_request_receipts')
    op.drop_table('service_request_contract_matches')
    op.drop_index('ix_service_requests_requester_org_guid', 'service_requests')
    op.drop_index('ix_service_requests_contract_guid', 'service_requests')
    op.drop_index('ix_service_requests_patient_guid', 'service_requests')
    op.drop_table('service_requests')
