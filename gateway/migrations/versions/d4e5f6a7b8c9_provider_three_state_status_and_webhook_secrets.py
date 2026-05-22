"""Provider three-state status + webhook signing secrets (ticket #136)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-22 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # provider_access_tokens: add status / deprecated_at / rotated_to_guid
    with op.batch_alter_table('provider_access_tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20),
                                      nullable=False, server_default='active'))
        batch_op.add_column(sa.Column('deprecated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('rotated_to_guid', sa.String(length=36),
                                      nullable=True))
        batch_op.create_index(batch_op.f('ix_provider_access_tokens_status'),
                              ['status'], unique=False)

    # Backfill: any existing PAT with revoked=True gets status='revoked'.
    # This keeps the new column consistent with the legacy boolean for
    # callers that haven't migrated yet.
    op.execute(
        "UPDATE provider_access_tokens SET status = 'revoked' WHERE revoked = TRUE"
    )

    # New table: webhook_signing_secrets
    op.create_table(
        'webhook_signing_secrets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guid', sa.String(length=36), nullable=False),
        sa.Column('provider_org_guid', sa.String(length=36), nullable=False),
        sa.Column('secret_encrypted', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='active'),
        sa.Column('issued_at', sa.DateTime(), nullable=False),
        sa.Column('deprecated_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('rotated_to_guid', sa.String(length=36), nullable=True),
        sa.Column('created_by_user_guid', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guid'),
    )
    op.create_index('ix_webhook_signing_secrets_provider_org_guid',
                    'webhook_signing_secrets', ['provider_org_guid'],
                    unique=False)
    op.create_index('ix_webhook_signing_secrets_status',
                    'webhook_signing_secrets', ['status'], unique=False)


def downgrade():
    op.drop_index('ix_webhook_signing_secrets_status',
                  table_name='webhook_signing_secrets')
    op.drop_index('ix_webhook_signing_secrets_provider_org_guid',
                  table_name='webhook_signing_secrets')
    op.drop_table('webhook_signing_secrets')

    with op.batch_alter_table('provider_access_tokens', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_provider_access_tokens_status'))
        batch_op.drop_column('rotated_to_guid')
        batch_op.drop_column('deprecated_at')
        batch_op.drop_column('status')
