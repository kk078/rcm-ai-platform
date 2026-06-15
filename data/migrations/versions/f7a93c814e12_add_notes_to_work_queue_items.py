"""add notes column to work_queue_items for AI agent output

Revision ID: f7a93c814e12
Revises: e5f82b193d67
Create Date: 2026-05-26 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f7a93c814e12'
down_revision: Union[str, None] = 'e5f82b193d67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'work_queue_items',
        sa.Column('notes', sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('work_queue_items', 'notes')
