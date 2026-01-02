"""add_telegram_chat_id_to_groups

Revision ID: a1b2c3d4e5f6
Revises: 1dfa14ced14f
Create Date: 2025-01-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '1dfa14ced14f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add telegram_chat_id column to groups table."""
    op.add_column('groups', 
        sa.Column('telegram_chat_id', sa.BigInteger(), nullable=False,
                  comment='Telegram chat ID of the group chat where this expense group is created')
    )
    # Add index for faster lookups by telegram_chat_id
    op.create_index('ix_groups_telegram_chat_id', 'groups', ['telegram_chat_id'])


def downgrade() -> None:
    """Remove telegram_chat_id column from groups table."""
    op.drop_index('ix_groups_telegram_chat_id', table_name='groups')
    op.drop_column('groups', 'telegram_chat_id')

