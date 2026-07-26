"""add task job user id and timing columns

Revision ID: 91a39c0c190c
Revises: cc02c2661b6d
Create Date: 2026-06-20 00:05:39.405689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '91a39c0c190c'
down_revision: Union[str, Sequence[str], None] = 'cc02c2661b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "task_jobs",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="提交任务的用户ID",
        ),
    )
    op.add_column(
        "task_jobs",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="任务开始执行时间",
        ),
    )
    op.add_column(
        "task_jobs",
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="任务结束时间（完成或失败）",
        ),
    )
    # 回填 user_id：仅写入格式合法且用户仍存在的值，跳过缺失/非法/孤儿数据，
    # 否则后续 ADD FOREIGN KEY 会因孤儿引用整体失败。
    op.execute(
        """
        UPDATE task_jobs
        SET user_id = (payload->>'user_id')::uuid
        WHERE user_id IS NULL
          AND payload->>'user_id' ~
            '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
          AND EXISTS (
              SELECT 1 FROM users
              WHERE users.id = (payload->>'user_id')::uuid
          )
        """
    )
    op.create_index(
        op.f("ix_task_jobs_user_id"), "task_jobs", ["user_id"], unique=False
    )
    op.create_foreign_key(
        "fk_task_jobs_user_id_users",
        "task_jobs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_task_jobs_user_id_users", "task_jobs", type_="foreignkey")
    op.drop_index(op.f("ix_task_jobs_user_id"), table_name="task_jobs")
    op.drop_column("task_jobs", "finished_at")
    op.drop_column("task_jobs", "started_at")
    op.drop_column("task_jobs", "user_id")
