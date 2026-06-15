"""add error_logs table for AI error intelligence

Revision ID: e5f82b193d67
Revises: c3d91e7f2a45
Create Date: 2026-05-19 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = 'e5f82b193d67'
down_revision: Union[str, None] = 'c3d91e7f2a45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'error_logs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),

        # Error details
        sa.Column('error_type', sa.String(200), nullable=False),
        sa.Column('message', sa.Text, nullable=False),
        sa.Column('stack_trace', sa.Text, nullable=True),
        sa.Column('status_code', sa.Integer, nullable=True),

        # Request context
        sa.Column('request_path', sa.String(500), nullable=True),
        sa.Column('request_method', sa.String(10), nullable=True),
        sa.Column('user_id', UUID(as_uuid=True), nullable=True),

        # Sentry cross-reference
        sa.Column('sentry_event_id', sa.String(100), nullable=True),

        # AI analysis
        sa.Column('severity', sa.String(20), nullable=False, server_default='unknown'),
        sa.Column('analysis_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('ai_analysis', JSONB, nullable=True),

        # Resolution
        sa.Column('resolved', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('resolved_at', sa.DateTime, nullable=True),
        sa.Column('resolved_by', UUID(as_uuid=True), nullable=True),

        # Deduplication / frequency
        sa.Column('occurrence_count', sa.Integer, nullable=False, server_default='1'),

        # Timestamps
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
    )

    # Indexes for common dashboard queries
    op.create_index('idx_error_logs_severity', 'error_logs', ['severity'])
    op.create_index('idx_error_logs_resolved', 'error_logs', ['resolved'])
    op.create_index('idx_error_logs_created', 'error_logs', ['created_at'])
    op.create_index('idx_error_logs_type', 'error_logs', ['error_type'])
    op.create_index('idx_error_logs_analysis_status', 'error_logs', ['analysis_status'])


def downgrade() -> None:
    op.drop_index('idx_error_logs_analysis_status', table_name='error_logs')
    op.drop_index('idx_error_logs_type', table_name='error_logs')
    op.drop_index('idx_error_logs_created', table_name='error_logs')
    op.drop_index('idx_error_logs_resolved', table_name='error_logs')
    op.drop_index('idx_error_logs_severity', table_name='error_logs')
    op.drop_table('error_logs')
