"""Webhook deliveries table (ticket #140)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-22 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guid', sa.String(length=36), nullable=False),
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('provider_org_guid', sa.String(length=36), nullable=False),
        sa.Column('service_request_guid', sa.String(length=36), nullable=True),
        sa.Column('webhook_url', sa.String(length=1024), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.Column('signature', sa.String(length=128), nullable=True),
        sa.Column('signing_secret_guid', sa.String(length=36), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False,
                  server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        sa.Column('last_response_code', sa.Integer(), nullable=True),
        sa.Column('last_response_body_excerpt', sa.String(length=1024),
                  nullable=True),
        sa.Column('last_error', sa.String(length=512), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('succeeded_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guid'),
        sa.UniqueConstraint('event_id'),
    )
    op.create_index('ix_webhook_deliveries_provider_org_guid',
                    'webhook_deliveries', ['provider_org_guid'], unique=False)
    op.create_index('ix_webhook_deliveries_service_request_guid',
                    'webhook_deliveries', ['service_request_guid'], unique=False)
    op.create_index('ix_webhook_deliveries_status',
                    'webhook_deliveries', ['status'], unique=False)
    op.create_index('ix_webhook_deliveries_next_attempt_at',
                    'webhook_deliveries', ['next_attempt_at'], unique=False)


def downgrade():
    op.drop_index('ix_webhook_deliveries_next_attempt_at',
                  table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_status',
                  table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_service_request_guid',
                  table_name='webhook_deliveries')
    op.drop_index('ix_webhook_deliveries_provider_org_guid',
                  table_name='webhook_deliveries')
    op.drop_table('webhook_deliveries')
