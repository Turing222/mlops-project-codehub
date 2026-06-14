"""add phone, auth_provider, google_sub; make email/hashed_password nullable

Revision ID: e5a1b2c3d4f5
Revises: d20ae3655f81
Create Date: 2026-05-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a1b2c3d4f5"
down_revision: str | Sequence[str] | None = "d20ae3655f81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: add phone/auth_provider/google_sub, relax email/password."""
    # 1. 新增列
    op.add_column(
        "users",
        sa.Column("phone", sa.String(20), nullable=True, comment="手机号（短信登录标识）"),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.String(20),
            nullable=True,
            server_default=sa.text("'local'"),
            comment="注册渠道: local/phone/google",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "google_sub",
            sa.String(255),
            nullable=True,
            comment="Google OAuth sub 声明",
        ),
    )

    # 2. 回填 auth_provider（现有用户都是 local 渠道）
    op.execute("UPDATE users SET auth_provider = 'local' WHERE auth_provider IS NULL")

    # 3. 放宽 email / hashed_password 为可空
    op.alter_column("users", "email", nullable=True)
    op.alter_column("users", "hashed_password", nullable=True)

    # 4. 删除原有 email 唯一索引，重建为 partial unique index（仅非 NULL 值唯一）
    op.execute("DROP INDEX IF EXISTS ix_users_email")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_email ON users (email) WHERE email IS NOT NULL"
    )

    # 5. 新建 phone partial unique index
    op.create_index(
        op.f("ix_users_phone"), "users", ["phone"], unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_users_phone ON users (phone) WHERE phone IS NOT NULL"
    )

    # 6. 新建 google_sub partial unique index
    op.create_index(
        op.f("ix_users_google_sub"), "users", ["google_sub"], unique=False,
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_users_google_sub ON users (google_sub) "
        "WHERE google_sub IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema: restore NOT NULL constraints and drop new columns."""
    # 1. 删除 partial unique indexes
    op.execute("DROP INDEX IF EXISTS uq_users_google_sub")
    op.execute("DROP INDEX IF EXISTS uq_users_phone")
    op.execute("DROP INDEX IF EXISTS uq_users_email")

    # 2. 恢复 email 唯一约束（要求所有 email 非空）
    op.execute(
        "UPDATE users SET email = '' WHERE email IS NULL"
    )
    op.execute(
        "UPDATE users SET hashed_password = '' WHERE hashed_password IS NULL"
    )
    op.alter_column("users", "hashed_password", nullable=False)
    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    # 3. 删除新增列
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_index(op.f("ix_users_phone"), table_name="users")
    op.drop_column("users", "google_sub")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "phone")
