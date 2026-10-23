"""histórico de valores, data de aquisição e atualização anual dos itens manuais

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('manual_assets', sa.Column('acquired_at', sa.Date(), nullable=True))
    op.add_column('manual_assets', sa.Column('growth_aa', sa.Float(), nullable=True))
    op.create_table('manual_asset_values',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('manual_asset_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['manual_asset_id'], ['manual_assets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('manual_asset_id', 'date'))
    op.create_index('ix_manual_asset_values_manual_asset_id', 'manual_asset_values', ['manual_asset_id'])
    # o valor atual de cada item vira o primeiro ponto do histórico
    op.execute("INSERT INTO manual_asset_values (manual_asset_id, date, value) "
               "SELECT id, as_of, value FROM manual_assets WHERE as_of IS NOT NULL")


def downgrade() -> None:
    op.drop_index('ix_manual_asset_values_manual_asset_id', table_name='manual_asset_values')
    op.drop_table('manual_asset_values')
    op.drop_column('manual_assets', 'growth_aa')
    op.drop_column('manual_assets', 'acquired_at')
