"""add patch columns to error_logs for AI auto-patcher

Revision ID: g8b04d925f33
Revises: e5f82b193d67
Create Date: 2026-05-27 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g8b04d925f33'
down_revision: Union[str, None] = 'f7a93c814e12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Auto-patcher result columns
    op.add_column('error_logs', sa.Column('patch_applied', sa.Boolean, nullable=False, server_default='false'))
    op.add_column('error_logs', sa.Column('patch_backup_path', sa.Text, nullable=True))
    op.add_column('error_logs', sa.Column('patch_diff', sa.Text, nullable=True))
    op.add_column('error_logs', sa.Column('patch_applied_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('error_logs', sa.Column('patch_error', sa.Text, nullable=True))

    # Index to quickly find patched errors in the dashboard
    op.create_index('idx_error_logs_patch_applied', 'error_logs', ['patch_applied'])


def downgrade() -> None:
    op.drop_index('idx_error_logs_patch_applied', table_name='error_logs')
    op.drop_column('error_logs', 'patch_error')
    op.drop_column('error_logs', 'patch_applied_at')
    op.drop_column('error_logs', 'patch_diff')
    op.drop_column('error_logs', 'patch_backup_path')
    op.drop_column('error_logs', 'patch_applied')
