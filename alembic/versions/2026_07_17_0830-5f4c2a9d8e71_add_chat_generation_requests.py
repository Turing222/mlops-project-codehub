"""Add durable Chat generation requests.

Revision ID: 5f4c2a9d8e71
Revises: 7e4a9d2c1b60
Create Date: 2026-07-17 08:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5f4c2a9d8e71"
down_revision: str | Sequence[str] | None = "7e4a9d2c1b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the additive request state table without switching Chat traffic."""
    op.create_table(
        "chat_generation_requests",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_message_id", sa.UUID(), nullable=True),
        sa.Column("assistant_message_id", sa.UUID(), nullable=True),
        sa.Column(
            "client_request_id",
            sa.String(length=64),
            nullable=False,
            comment="Actor-scoped idempotency identity supplied by the client",
        ),
        sa.Column(
            "task_id",
            sa.String(length=128),
            nullable=True,
            comment="Latest broker task identity for the current attempt",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'prepared'"),
            nullable=False,
        ),
        sa.Column(
            "attempt",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column(
            "reserved_credits",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "retryable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Sanitized terminal message; never store raw provider payloads",
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="基于ULID生成的唯一标识",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="最后更新时间",
        ),
        sa.CheckConstraint(
            "length(btrim(client_request_id)) > 0",
            name=op.f(
                "ck_chat_generation_requests_client_request_id_not_blank"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_chat_generation_requests_status_values"),
        ),
        sa.CheckConstraint(
            "attempt >= 1",
            name=op.f("ck_chat_generation_requests_attempt_positive"),
        ),
        sa.CheckConstraint(
            "reserved_credits >= 0",
            name=op.f(
                "ck_chat_generation_requests_reserved_credits_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "status = 'failed' OR retryable = false",
            name=op.f(
                "ck_chat_generation_requests_retryable_only_when_failed"
            ),
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed') AND finished_at IS NOT NULL) "
            "OR (status NOT IN ('succeeded', 'failed') AND finished_at IS NULL)",
            name=op.f("ck_chat_generation_requests_terminal_finished_at"),
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR length(btrim(error_code)) > 0",
            name=op.f("ck_chat_generation_requests_failed_error_code"),
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR assistant_message_id IS NOT NULL",
            name=op.f(
                "ck_chat_generation_requests_succeeded_assistant_message"
            ),
        ),
        sa.CheckConstraint(
            "status NOT IN ('queued', 'running') "
            "OR (length(btrim(task_id)) > 0 "
            "AND length(btrim(lease_token)) > 0)",
            name=op.f("ck_chat_generation_requests_active_attempt_fence"),
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"],
            ["chat_messages.id"],
            name=op.f(
                "fk_chat_generation_requests_assistant_message_id_chat_messages"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_generation_requests_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_generation_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"],
            ["chat_messages.id"],
            name=op.f(
                "fk_chat_generation_requests_user_message_id_chat_messages"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_chat_generation_requests_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("chat_generation_requests_pkey"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "client_request_id",
            name="uq_chat_generation_requests_user_client_request",
        ),
    )
    op.create_index(
        op.f("ix_chat_generation_requests_workspace_id"),
        "chat_generation_requests",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_chat_generation_requests_user_message",
        "chat_generation_requests",
        ["user_message_id"],
        unique=True,
        postgresql_where=sa.text("user_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_chat_generation_requests_assistant_message",
        "chat_generation_requests",
        ["assistant_message_id"],
        unique=True,
        postgresql_where=sa.text("assistant_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_chat_generation_requests_task",
        "chat_generation_requests",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )
    op.create_index(
        "ix_chat_generation_requests_session_created",
        "chat_generation_requests",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chat_generation_requests_recovery_due",
        "chat_generation_requests",
        ["status", "recovery_due_at"],
        unique=False,
        postgresql_where=sa.text("recovery_due_at IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove the additive request table; existing Chat rows are untouched."""
    op.drop_index(
        "ix_chat_generation_requests_recovery_due",
        table_name="chat_generation_requests",
        postgresql_where=sa.text("recovery_due_at IS NOT NULL"),
    )
    op.drop_index(
        "ix_chat_generation_requests_session_created",
        table_name="chat_generation_requests",
    )
    op.drop_index(
        "uq_chat_generation_requests_task",
        table_name="chat_generation_requests",
        postgresql_where=sa.text("task_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_chat_generation_requests_assistant_message",
        table_name="chat_generation_requests",
        postgresql_where=sa.text("assistant_message_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_chat_generation_requests_user_message",
        table_name="chat_generation_requests",
        postgresql_where=sa.text("user_message_id IS NOT NULL"),
    )
    op.drop_index(
        op.f("ix_chat_generation_requests_workspace_id"),
        table_name="chat_generation_requests",
    )
    op.drop_table("chat_generation_requests")
