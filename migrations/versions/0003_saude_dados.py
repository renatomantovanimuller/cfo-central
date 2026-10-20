"""saúde dos dados (health_runs)

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('health_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('summary', JSON, nullable=True),
        sa.Column('results', JSON, nullable=True),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_health_runs_at', 'health_runs', ['at'])


def downgrade() -> None:
    op.drop_index('ix_health_runs_at', table_name='health_runs')
    op.drop_table('health_runs')
