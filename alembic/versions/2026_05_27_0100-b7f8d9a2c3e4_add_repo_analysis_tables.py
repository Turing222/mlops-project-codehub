"""add_repo_analysis_tables

Revision ID: b7f8d9a2c3e4
Revises: ee8c06050a97
Create Date: 2026-05-27 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7f8d9a2c3e4"
down_revision: str | Sequence[str] | None = "ee8c06050a97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "repo_analysis_runs",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="提交分析的用户ID",
        ),
        sa.Column(
            "task_id",
            sa.UUID(),
            nullable=True,
            comment="关联 TaskJob ID",
        ),
        sa.Column("repo_url", sa.String(length=500), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column("repo", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rubric_version", sa.String(length=80), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            ["task_id"],
            ["task_jobs.id"],
            name=op.f("fk_repo_analysis_runs_task_id_task_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_repo_analysis_runs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("repo_analysis_runs_pkey")),
    )
    op.create_index(
        op.f("ix_repo_analysis_runs_owner"),
        "repo_analysis_runs",
        ["owner"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repo_analysis_runs_repo"),
        "repo_analysis_runs",
        ["repo"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repo_analysis_runs_status"),
        "repo_analysis_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repo_analysis_runs_task_id"),
        "repo_analysis_runs",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_repo_analysis_runs_user_id"),
        "repo_analysis_runs",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "repo_analysis_results",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column(
            "subject",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "structured_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("markdown_report", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=40), nullable=False),
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
            ["run_id"],
            ["repo_analysis_runs.id"],
            name=op.f("fk_repo_analysis_results_run_id_repo_analysis_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("repo_analysis_results_pkey")),
    )
    op.create_index(
        op.f("ix_repo_analysis_results_run_id"),
        "repo_analysis_results",
        ["run_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_repo_analysis_results_run_id"),
        table_name="repo_analysis_results",
    )
    op.drop_table("repo_analysis_results")
    op.drop_index(op.f("ix_repo_analysis_runs_user_id"), table_name="repo_analysis_runs")
    op.drop_index(op.f("ix_repo_analysis_runs_task_id"), table_name="repo_analysis_runs")
    op.drop_index(op.f("ix_repo_analysis_runs_status"), table_name="repo_analysis_runs")
    op.drop_index(op.f("ix_repo_analysis_runs_repo"), table_name="repo_analysis_runs")
    op.drop_index(op.f("ix_repo_analysis_runs_owner"), table_name="repo_analysis_runs")
    op.drop_table("repo_analysis_runs")
