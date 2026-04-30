"""Add file storage metadata

Revision ID: 4f7c9b2d1a3e
Revises: 9d7c2a1f8b64
Create Date: 2026-04-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4f7c9b2d1a3e"
down_revision: Union[str, Sequence[str], None] = "9d7c2a1f8b64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "knowledge_files",
        "file_path",
        existing_type=sa.String(length=512),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
    op.add_column(
        "knowledge_files",
        sa.Column(
            "storage_backend",
            sa.String(length=20),
            server_default="local",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_files",
        sa.Column("storage_bucket", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_files",
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
    )
    op.create_check_constraint(
        "ck_knowledge_files_storage_backend",
        "knowledge_files",
        "storage_backend IN ('local', 's3')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_knowledge_files_storage_backend",
        "knowledge_files",
        type_="check",
    )
    op.drop_column("knowledge_files", "storage_key")
    op.drop_column("knowledge_files", "storage_bucket")
    op.drop_column("knowledge_files", "storage_backend")
    op.alter_column(
        "knowledge_files",
        "file_path",
        existing_type=sa.String(length=1024),
        type_=sa.String(length=512),
        existing_nullable=False,
    )
