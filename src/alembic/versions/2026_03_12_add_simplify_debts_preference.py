"""add_simplify_debts_preference

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-12

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add simplify_debts preference to groups and users tables."""
    op.add_column('groups',
        sa.Column('simplify_debts', sa.Boolean(), nullable=False,
                  server_default=sa.true(),
                  comment='Whether to show simplified debts by default for this group')
    )
    op.add_column('users',
        sa.Column('simplify_debts', sa.Boolean(), nullable=False,
                  server_default=sa.true(),
                  comment='Whether the user prefers to see simplified debts by default')
    )


def downgrade() -> None:
    """Remove simplify_debts columns."""
    op.drop_column('groups', 'simplify_debts')
    op.drop_column('users', 'simplify_debts')
