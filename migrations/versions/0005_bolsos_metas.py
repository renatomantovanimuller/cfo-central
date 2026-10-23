"""bolsos (finalidade do dinheiro) e metas com tipo e prioridade

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('financial_goals', sa.Column('kind', sa.String(length=20), nullable=False, server_default='prazo'))
    op.add_column('financial_goals', sa.Column('priority', sa.Integer(), nullable=False, server_default='100'))
    op.create_table('buckets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('goal_id', sa.Integer(), nullable=True),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['financial_goals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('goal_id'))
    op.create_table('bucket_allocations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('bucket_id', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=12), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('pct', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['bucket_id'], ['buckets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('bucket_id', 'source_type', 'source_id'))
    op.create_index('ix_bucket_allocations_bucket_id', 'bucket_allocations', ['bucket_id'])


def downgrade() -> None:
    op.drop_index('ix_bucket_allocations_bucket_id', table_name='bucket_allocations')
    op.drop_table('bucket_allocations')
    op.drop_table('buckets')
    op.drop_column('financial_goals', 'priority')
    op.drop_column('financial_goals', 'kind')
