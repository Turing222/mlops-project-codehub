"""add workspaces slug partial unique index

Revision ID: fc496fdd17b6
Revises: 1529777d9027
Create Date: 2026-06-20 00:05:38.652779

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc496fdd17b6'
down_revision: Union[str, Sequence[str], None] = '1529777d9027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 先建活跃集合的部分唯一索引，再移除旧的全局唯一索引，全程保持唯一保护。
    op.create_index(
        "uq_workspaces_slug_active",
        "workspaces",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(op.f("ix_workspaces_slug"), table_name="workspaces")


def downgrade() -> None:
    """Downgrade schema."""
    # 回退到全局唯一：若已存在软删与活跃记录复用同一 slug，重建会失败（预期）。
    op.create_index(
        op.f("ix_workspaces_slug"), "workspaces", ["slug"], unique=True
    )
    op.drop_index("uq_workspaces_slug_active", table_name="workspaces")
