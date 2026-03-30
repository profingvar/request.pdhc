"""add service_request_forms table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-26 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('service_request_forms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('guid', sa.String(length=36), nullable=False),
        sa.Column('service_request_guid', sa.String(length=36), nullable=False),
        sa.Column('form_guid', sa.String(length=36), nullable=False),
        sa.Column('form_version', sa.String(length=50), nullable=True),
        sa.Column('form_snapshot', sa.JSON(), nullable=True),
        sa.Column('render_ready_snapshot', sa.JSON(), nullable=True),
        sa.Column('display_title', sa.String(length=255), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['service_request_guid'], ['service_requests.guid']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guid'),
        sa.UniqueConstraint('service_request_guid', 'form_guid', name='uq_sr_form'),
    )


def downgrade():
    op.drop_table('service_request_forms')
