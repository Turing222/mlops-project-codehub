"""Add durable Knowledge task identity, worker lease, and outbox.

Revision ID: 2a7c9e4d1b63
Revises: 8c1d7e4a9b20
Create Date: 2026-07-17 11:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2a7c9e4d1b63"
down_revision: str | Sequence[str] | None = "8c1d7e4a9b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add only nullable/backfilled TaskJob fields and the outbox table."""
    op.add_column(
        "task_jobs",
        sa.Column(
            "knowledge_file_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Structured Knowledge file identity; payload is compatibility only",
        ),
    )
    op.add_column(
        "task_jobs",
        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "task_jobs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Worker claims for this durable job",
        ),
    )
    op.add_column(
        "task_jobs",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Current worker heartbeat",
        ),
    )
    op.add_column(
        "task_jobs",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Current worker claim expiry",
        ),
    )
    op.create_foreign_key(
        op.f("fk_task_jobs_knowledge_file_id_knowledge_files"),
        "task_jobs",
        "knowledge_files",
        ["knowledge_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_task_jobs_knowledge_base_id_knowledge_bases"),
        "task_jobs",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_task_jobs_knowledge_file_id"),
        "task_jobs",
        ["knowledge_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_jobs_knowledge_base_id"),
        "task_jobs",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        "ix_task_jobs_kb_status_updated",
        "task_jobs",
        ["action_type", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_jobs_kb_lease",
        "task_jobs",
        ["action_type", "status", "lease_expires_at"],
        unique=False,
    )
    op.create_check_constraint(
        op.f("ck_task_jobs_status_values"),
        "task_jobs",
        "status IN ('pending', 'processing', 'completed', 'failed', 'canceled')",
    )
    op.create_check_constraint(
        op.f("ck_task_jobs_attempt_count_non_negative"),
        "task_jobs",
        "attempt_count >= 0",
    )

    # Backfill only through rows that still have valid referenced resources.
    op.execute(
        sa.text(
            "UPDATE task_jobs AS task "
            "SET knowledge_file_id = file.id, knowledge_base_id = file.kb_id "
            "FROM knowledge_files AS file "
            "WHERE task.action_type = 'KB_INGESTION' "
            "AND task.payload->>'file_id' = file.id::text"
        )
    )
    op.execute(
        sa.text(
            "UPDATE task_jobs SET attempt_count = 1 "
            "WHERE action_type = 'KB_INGESTION' "
            "AND status IN ('processing', 'completed')"
        )
    )
    op.create_index(
        "uq_task_jobs_active_knowledge_file",
        "task_jobs",
        ["knowledge_file_id"],
        unique=True,
        postgresql_where=sa.text(
            "knowledge_file_id IS NOT NULL "
            "AND action_type = 'KB_INGESTION' "
            "AND status IN ('pending', 'processing')"
        ),
    )

    op.create_table(
        "task_outbox",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
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
            "attempt_count >= 0",
            name=op.f("ck_task_outbox_attempt_count_non_negative"),
        ),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name=op.f("ck_task_outbox_published_has_timestamp"),
        ),
        sa.CheckConstraint(
            "status <> 'publishing' OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_task_outbox_publishing_has_lease"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'dead')",
            name=op.f("ck_task_outbox_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task_jobs.id"],
            name=op.f("fk_task_outbox_task_id_task_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("task_outbox_pkey")),
        sa.UniqueConstraint(
            "task_id",
            "event_type",
            name="uq_task_outbox_task_event",
        ),
    )
    op.create_index(
        "ix_task_outbox_claim",
        "task_outbox",
        ["status", "next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'publishing')"),
    )


def downgrade() -> None:
    """Remove WS4 schema; production rollback should prefer a forward fix."""
    op.drop_index("ix_task_outbox_claim", table_name="task_outbox")
    op.drop_table("task_outbox")
    op.drop_constraint(
        op.f("ck_task_jobs_attempt_count_non_negative"),
        "task_jobs",
        type_="check",
    )
    op.drop_index("uq_task_jobs_active_knowledge_file", table_name="task_jobs")
    op.drop_constraint(
        op.f("ck_task_jobs_status_values"),
        "task_jobs",
        type_="check",
    )
    op.drop_index("ix_task_jobs_kb_lease", table_name="task_jobs")
    op.drop_index("ix_task_jobs_kb_status_updated", table_name="task_jobs")
    op.drop_index(op.f("ix_task_jobs_knowledge_base_id"), table_name="task_jobs")
    op.drop_index(op.f("ix_task_jobs_knowledge_file_id"), table_name="task_jobs")
    op.drop_constraint(
        op.f("fk_task_jobs_knowledge_base_id_knowledge_bases"),
        "task_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_task_jobs_knowledge_file_id_knowledge_files"),
        "task_jobs",
        type_="foreignkey",
    )
    op.drop_column("task_jobs", "lease_expires_at")
    op.drop_column("task_jobs", "heartbeat_at")
    op.drop_column("task_jobs", "attempt_count")
    op.drop_column("task_jobs", "knowledge_base_id")
    op.drop_column("task_jobs", "knowledge_file_id")
