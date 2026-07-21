"""add_is_archived_to_groups

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-13

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_archived column to groups table."""
    op.add_column('groups',
        sa.Column('is_archived', sa.Boolean(), nullable=False,
                  server_default=sa.false(),
                  comment='Whether this group has been archived by the owner')
    )


def downgrade() -> None:
    """Remove is_archived column from groups table."""
    op.drop_column('groups', 'is_archived')
