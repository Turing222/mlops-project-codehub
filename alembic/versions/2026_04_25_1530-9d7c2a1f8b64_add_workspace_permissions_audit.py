"""Add workspace permissions and audit tables

Revision ID: 9d7c2a1f8b64
Revises: 678e5c0abf31
Create Date: 2026-04-25 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9d7c2a1f8b64"
down_revision: Union[str, Sequence[str], None] = "678e5c0abf31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "workspaces",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_workspaces_owner_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workspaces_pkey")),
    )
    op.create_index(op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"])
    op.create_index(op.f("ix_workspaces_slug"), "workspaces", ["slug"], unique=True)

    op.create_table(
        "user_workspace_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="member", nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_workspace_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_user_workspace_roles_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("user_workspace_roles_pkey")),
        sa.UniqueConstraint(
            "user_id",
            "workspace_id",
            name="uq_user_workspace_roles_user_workspace",
        ),
    )
    op.create_index(
        op.f("ix_user_workspace_roles_user_id"),
        "user_workspace_roles",
        ["user_id"],
    )
    op.create_index(
        op.f("ix_user_workspace_roles_workspace_id"),
        "user_workspace_roles",
        ["workspace_id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.String(length=20), server_default="success", nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_audit_events_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("audit_events_pkey")),
    )
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"])
    op.create_index(
        op.f("ix_audit_events_actor_user_id"),
        "audit_events",
        ["actor_user_id"],
    )
    op.create_index(
        "idx_audit_events_actor_created",
        "audit_events",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        op.f("ix_audit_events_request_id"),
        "audit_events",
        ["request_id"],
    )
    op.create_index(
        op.f("ix_audit_events_resource_id"),
        "audit_events",
        ["resource_id"],
    )
    op.create_index(
        op.f("ix_audit_events_workspace_id"),
        "audit_events",
        ["workspace_id"],
    )
    op.create_index(
        "idx_audit_events_workspace_created",
        "audit_events",
        ["workspace_id", "created_at"],
    )

    op.add_column("knowledge_bases", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_knowledge_bases_workspace_id"),
        "knowledge_bases",
        ["workspace_id"],
    )
    op.create_foreign_key(
        op.f("fk_knowledge_bases_workspace_id_workspaces"),
        "knowledge_bases",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("knowledge_files", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.add_column("knowledge_files", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.add_column(
        "knowledge_files",
        sa.Column("visibility", sa.String(length=20), server_default="workspace", nullable=False),
    )
    op.create_index(op.f("ix_knowledge_files_owner_id"), "knowledge_files", ["owner_id"])
    op.create_index(
        op.f("ix_knowledge_files_workspace_id"),
        "knowledge_files",
        ["workspace_id"],
    )
    op.create_foreign_key(
        op.f("fk_knowledge_files_owner_id_users"),
        "knowledge_files",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_knowledge_files_workspace_id_workspaces"),
        "knowledge_files",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("chat_sessions", sa.Column("workspace_id", sa.UUID(), nullable=True))
    op.create_index(op.f("ix_chat_sessions_workspace_id"), "chat_sessions", ["workspace_id"])
    op.create_foreign_key(
        op.f("fk_chat_sessions_workspace_id_workspaces"),
        "chat_sessions",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("chat_messages", sa.Column("user_id", sa.UUID(), nullable=True))
    op.add_column(
        "chat_messages",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_chat_messages_user_id"), "chat_messages", ["user_id"])
    op.create_foreign_key(
        op.f("fk_chat_messages_user_id_users"),
        "chat_messages",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_chat_messages_user_id_users"),
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_chat_messages_user_id"), table_name="chat_messages")
    op.drop_column("chat_messages", "metadata")
    op.drop_column("chat_messages", "user_id")

    op.drop_constraint(
        op.f("fk_chat_sessions_workspace_id_workspaces"),
        "chat_sessions",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_chat_sessions_workspace_id"), table_name="chat_sessions")
    op.drop_column("chat_sessions", "workspace_id")

    op.drop_constraint(
        op.f("fk_knowledge_files_workspace_id_workspaces"),
        "knowledge_files",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_knowledge_files_owner_id_users"),
        "knowledge_files",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_knowledge_files_workspace_id"), table_name="knowledge_files")
    op.drop_index(op.f("ix_knowledge_files_owner_id"), table_name="knowledge_files")
    op.drop_column("knowledge_files", "visibility")
    op.drop_column("knowledge_files", "workspace_id")
    op.drop_column("knowledge_files", "owner_id")

    op.drop_constraint(
        op.f("fk_knowledge_bases_workspace_id_workspaces"),
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_knowledge_bases_workspace_id"), table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "workspace_id")

    op.drop_index("idx_audit_events_workspace_created", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_workspace_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_resource_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_request_id"), table_name="audit_events")
    op.drop_index("idx_audit_events_actor_created", table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_user_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_action"), table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(
        op.f("ix_user_workspace_roles_workspace_id"),
        table_name="user_workspace_roles",
    )
    op.drop_index(
        op.f("ix_user_workspace_roles_user_id"),
        table_name="user_workspace_roles",
    )
    op.drop_table("user_workspace_roles")

    op.drop_index(op.f("ix_workspaces_slug"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.drop_table("workspaces")
