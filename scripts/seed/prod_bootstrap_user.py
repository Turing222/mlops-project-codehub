"""Bootstrap a single production manual-test user with a personal workspace.

职责：幂等创建用于部署后手动验证的账号（用户名 + 密码 + 个人 workspace）。
边界：不灌 demo 聊天/审计数据；密码只从环境变量或 CLI 读取，不落盘、不写日志。
用法：
  BOOTSTRAP_PROD_PASSWORD='...' uv run python scripts/seed/prod_bootstrap_user.py \\
      --email you@example.com
  # 部署后请同时将 email 加入 BETA_USER_EMAIL_WHITELIST，并在 GrowthBook 临时开启
  # enable-password-login 以显示前端密码登录表单。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value

    return values


def _prepare_runtime_environment() -> None:
    env_values = _read_env_file(PROJECT_ROOT / ".env")
    for key, value in env_values.items():
        os.environ.setdefault(key, value)

    if "POSTGRES_SERVER" not in os.environ:
        os.environ.setdefault("POSTGRES_SERVER", "localhost")


_prepare_runtime_environment()

from backend.core.security import get_password_hash  # noqa: E402
from backend.infra.database import create_db_assets  # noqa: E402
from backend.models.enums import WorkspaceRole  # noqa: E402
from backend.models.orm.access import UserWorkspaceRole, Workspace  # noqa: E402
from backend.models.orm.user import User  # noqa: E402

DEFAULT_USERNAME = "prod_manual_tester"
MIN_PASSWORD_LENGTH = 12


async def _one_or_none_by(
    session: AsyncSession, model: type[object], **filters: object
) -> object | None:
    stmt = select(model)
    for column_name, value in filters.items():
        stmt = stmt.where(getattr(model, column_name) == value)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _ensure_personal_workspace(session: AsyncSession, user: User) -> Workspace:
    existing_role = await _one_or_none_by(
        session,
        UserWorkspaceRole,
        user_id=user.id,
        role=WorkspaceRole.OWNER.value,
    )
    if existing_role is not None:
        workspace = await _one_or_none_by(
            session,
            Workspace,
            id=existing_role.workspace_id,
        )
        if workspace is not None:
            return workspace

    workspace_slug = f"{user.username}-{user.id.hex[:8]}"
    workspace = await _one_or_none_by(session, Workspace, slug=workspace_slug)
    if workspace is None:
        workspace = Workspace(
            slug=workspace_slug,
            name=f"{user.username}'s Workspace",
            owner_id=user.id,
        )
        session.add(workspace)
        await session.flush()

    role = await _one_or_none_by(
        session,
        UserWorkspaceRole,
        user_id=user.id,
        workspace_id=workspace.id,
    )
    if role is None:
        session.add(
            UserWorkspaceRole(
                user_id=user.id,
                workspace_id=workspace.id,
                role=WorkspaceRole.OWNER.value,
            )
        )

    await session.flush()
    return workspace


async def bootstrap_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    is_superuser: bool,
) -> tuple[User, Workspace, bool]:
    """Create or update the bootstrap user. Returns (user, workspace, created)."""
    password_hash = await get_password_hash(password)
    user = await _one_or_none_by(session, User, username=username)
    created = user is None
    if user is None:
        user = User(
            username=username,
            email=email,
            hashed_password=password_hash,
            auth_provider="local",
        )
        session.add(user)

    user.email = email
    user.hashed_password = password_hash
    user.is_active = True
    user.is_superuser = is_superuser
    user.auth_provider = "local"
    await session.flush()

    workspace = await _ensure_personal_workspace(session, user)
    return user, workspace, created


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap one idempotent manual-test user for deployed environments."
        )
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USERNAME,
        help=f"Login username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="User email; add to BETA_USER_EMAIL_WHITELIST before closed-beta login.",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("BOOTSTRAP_PROD_PASSWORD", ""),
        help="Password (prefer BOOTSTRAP_PROD_PASSWORD env var).",
    )
    parser.add_argument(
        "--superuser",
        action="store_true",
        help="Grant is_superuser (bypasses closed-beta whitelist).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and roll back instead of committing.",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if not args.password or len(args.password) < MIN_PASSWORD_LENGTH:
        msg = (
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters. "
            "Set BOOTSTRAP_PROD_PASSWORD or pass --password."
        )
        raise SystemExit(msg)


async def _main() -> int:
    args = _build_parser().parse_args()
    _validate_args(args)

    engine, session_factory = create_db_assets()
    try:
        async with session_factory() as session:
            user, workspace, created = await bootstrap_user(
                session,
                username=args.username,
                email=args.email,
                password=args.password,
                is_superuser=args.superuser,
            )

            if args.dry_run:
                await session.rollback()
                mode = "dry_run"
            else:
                await session.commit()
                mode = "committed"

            print(f"bootstrap_status={mode}")
            print(f"bootstrap_created={'true' if created else 'false'}")
            print(f"bootstrap_username={user.username}")
            print(f"bootstrap_email={user.email}")
            print(f"bootstrap_workspace_slug={workspace.slug}")
            print(
                "bootstrap_next_steps="
                "add email to BETA_USER_EMAIL_WHITELIST; "
                "enable enable-password-login in GrowthBook while testing"
            )
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
