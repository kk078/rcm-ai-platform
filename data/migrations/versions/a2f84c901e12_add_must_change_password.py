"""add must_change_password to users

Revision ID: a2f84c901e12
Revises: b1130d605f93
Create Date: 2026-05-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a2f84c901e12'
down_revision = 'b1130d605f93'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False,
                  server_default=sa.text('false'))
    )
    op.add_column(
        'users',
        sa.Column('mfa_backup_codes', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('users', 'mfa_backup_codes')
    op.drop_column('users', 'must_change_password')
