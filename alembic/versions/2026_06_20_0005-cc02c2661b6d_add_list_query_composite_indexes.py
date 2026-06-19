"""add list query composite indexes

Revision ID: cc02c2661b6d
Revises: fc496fdd17b6
Create Date: 2026-06-20 00:05:39.029762

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'cc02c2661b6d'
down_revision: Union[str, Sequence[str], None] = 'fc496fdd17b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 覆盖 get_user_sessions 的 where user_id + order by updated_at。
    op.create_index(
        "ix_chat_sessions_user_updated",
        "chat_sessions",
        ["user_id", "updated_at"],
    )
    # 覆盖 list_transactions 的 where account_id + order by created_at。
    op.create_index(
        "ix_credit_transactions_account_created",
        "credit_transactions",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_credit_transactions_account_created",
        table_name="credit_transactions",
    )
    op.drop_index(
        "ix_chat_sessions_user_updated",
        table_name="chat_sessions",
    )
