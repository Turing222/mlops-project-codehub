"""Add upload hash metadata

Revision ID: a8c4d3e9f021
Revises: 4f7c9b2d1a3e
Create Date: 2026-05-01 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8c4d3e9f021"
down_revision: Union[str, Sequence[str], None] = "4f7c9b2d1a3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "knowledge_files",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_knowledge_files_kb_content_sha256",
        "knowledge_files",
        ["kb_id", "content_sha256"],
        unique=False,
    )

    op.add_column(
        "document_chunks",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "chunking_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_chunks_file_content_hash",
        "document_chunks",
        ["file_id", "content_hash"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_document_chunks_file_content_hash",
        table_name="document_chunks",
    )
    op.drop_column("document_chunks", "chunking_version")
    op.drop_column("document_chunks", "content_hash")

    op.drop_index(
        "ix_knowledge_files_kb_content_sha256",
        table_name="knowledge_files",
    )
    op.drop_column("knowledge_files", "content_sha256")
