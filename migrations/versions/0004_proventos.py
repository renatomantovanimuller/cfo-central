"""proventos e desdobramentos por ativo (asset_events)

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('asset_events',
        sa.Column('symbol', sa.String(length=30), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('symbol', 'date', 'kind'))


def downgrade() -> None:
    op.drop_table('asset_events')
