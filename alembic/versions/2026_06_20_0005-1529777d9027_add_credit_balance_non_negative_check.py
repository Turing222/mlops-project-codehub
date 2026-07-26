"""add credit balance non negative check

Revision ID: 1529777d9027
Revises: b7f8d9a2c3e4
Create Date: 2026-06-20 00:05:38.276574

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1529777d9027'
down_revision: Union[str, Sequence[str], None] = 'b7f8d9a2c3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        op.f("ck_credit_accounts_balance_non_negative"),
        "credit_accounts",
        "balance >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("ck_credit_accounts_balance_non_negative"),
        "credit_accounts",
        type_="check",
    )
