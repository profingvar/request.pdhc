"""add requester name columns

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-30 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('service_requests', sa.Column('requester_user_name', sa.String(length=255), nullable=True))
    op.add_column('service_requests', sa.Column('requester_org_name', sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column('service_requests', 'requester_org_name')
    op.drop_column('service_requests', 'requester_user_name')
