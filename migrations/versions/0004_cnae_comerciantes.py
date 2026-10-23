"""CNAE dos comerciantes (descrição, origem e data da consulta do CNPJ)

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
    op.add_column('merchants', sa.Column('cnae_desc', sa.String(length=200), nullable=True))
    op.add_column('merchants', sa.Column('cnae_source', sa.String(length=10), nullable=True))
    op.add_column('merchants', sa.Column('enriched_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('merchants', 'enriched_at')
    op.drop_column('merchants', 'cnae_source')
    op.drop_column('merchants', 'cnae_desc')
