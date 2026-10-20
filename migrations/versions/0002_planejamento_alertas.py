"""planejamento (preferências, política de alocação) e log de notificações

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('app_settings',
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('value', JSON, nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'))
    op.create_table('allocation_targets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asset_class', sa.String(length=60), nullable=False),
        sa.Column('target_pct', sa.Float(), nullable=False),
        sa.Column('min_pct', sa.Float(), nullable=True),
        sa.Column('max_pct', sa.Float(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_class'))
    op.create_table('notification_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('fingerprint', sa.String(length=200), nullable=False),
        sa.Column('subject', sa.String(length=300), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_notification_log_fingerprint', 'notification_log', ['fingerprint'])


def downgrade() -> None:
    op.drop_index('ix_notification_log_fingerprint', table_name='notification_log')
    op.drop_table('notification_log')
    op.drop_table('allocation_targets')
    op.drop_table('app_settings')
