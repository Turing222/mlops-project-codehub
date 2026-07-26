"""Add bounded Chat broker dispatch accounting.

Revision ID: 8c1d7e4a9b20
Revises: 5f4c2a9d8e71
Create Date: 2026-07-17 09:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8c1d7e4a9b20"
down_revision: str | Sequence[str] | None = "5f4c2a9d8e71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add per-attempt accounting and the durable redispatch context."""
    op.add_column(
        "chat_generation_requests",
        sa.Column(
            "dispatch_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Broker dispatch reservations for the current business attempt",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE chat_generation_requests "
            "SET dispatch_attempts = 1 "
            "WHERE task_id IS NOT NULL"
        )
    )
    op.add_column(
        "chat_generation_requests",
        sa.Column(
            "dispatch_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Validated Worker inputs for durable redispatch; no secrets",
        ),
    )
    op.create_check_constraint(
        op.f("ck_chat_generation_requests_dispatch_attempts_non_negative"),
        "chat_generation_requests",
        "dispatch_attempts >= 0",
    )


def downgrade() -> None:
    """Remove only the additive broker dispatch accounting field."""
    op.drop_constraint(
        op.f("ck_chat_generation_requests_dispatch_attempts_non_negative"),
        "chat_generation_requests",
        type_="check",
    )
    op.drop_column("chat_generation_requests", "dispatch_context")
    op.drop_column("chat_generation_requests", "dispatch_attempts")
