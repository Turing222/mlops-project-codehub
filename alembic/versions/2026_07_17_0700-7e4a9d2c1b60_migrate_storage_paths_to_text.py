"""Migrate knowledge file storage path columns to Text.

Revision ID: 7e4a9d2c1b60
Revises: 91a39c0c190c
Create Date: 2026-07-17 07:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7e4a9d2c1b60"
down_revision: str | Sequence[str] | None = "91a39c0c190c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade storage path columns without changing nullability."""
    op.alter_column(
        "knowledge_files",
        "file_path",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "knowledge_files",
        "storage_key",
        existing_type=sa.String(length=1024),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Restore bounded columns only when all existing values fit."""
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM knowledge_files
                    WHERE char_length(file_path) > 1024
                       OR char_length(storage_key) > 1024
                ) THEN
                    RAISE EXCEPTION
                        'Cannot downgrade storage paths: values exceed 1024 characters';
                END IF;
            END
            $$
            """
        )
    )
    op.alter_column(
        "knowledge_files",
        "storage_key",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=True,
    )
    op.alter_column(
        "knowledge_files",
        "file_path",
        existing_type=sa.Text(),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
