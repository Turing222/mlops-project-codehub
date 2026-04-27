from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def _project_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _prepare_local_environment() -> None:
    original_env_keys = set(os.environ)
    env_values = _read_env_file(PROJECT_ROOT / ".env")
    smoke_env_values = _read_env_file(PROJECT_ROOT / ".env.smoke")

    for key, value in env_values.items():
        os.environ.setdefault(key, value)
    for key, value in smoke_env_values.items():
        os.environ.setdefault(key, value)

    secret_file_defaults = {
        "SECRET_KEY_FILE": smoke_env_values.get(
            "SMOKE_SECRET_KEY_FILE",
            "./secrets/smoke/secret_key.txt",
        ),
        "POSTGRES_PASSWORD_FILE": smoke_env_values.get(
            "SMOKE_POSTGRES_PASSWORD_FILE",
            "./secrets/smoke/postgres_password.txt",
        ),
        "REDIS_PASSWORD_FILE": smoke_env_values.get(
            "SMOKE_REDIS_PASSWORD_FILE",
            "./secrets/smoke/redis_password.txt",
        ),
    }
    for env_name, default_path in secret_file_defaults.items():
        if env_name in os.environ:
            continue
        secret_path = _project_path(default_path)
        if secret_path.exists():
            os.environ[env_name] = str(secret_path)

    if (
        "POSTGRES_SERVER" not in original_env_keys
        and os.getenv("POSTGRES_SERVER") == "postgres"
    ):
        os.environ["POSTGRES_SERVER"] = "localhost"

    if "SECRET_KEY" not in os.environ and "SECRET_KEY_FILE" not in os.environ:
        os.environ["SECRET_KEY"] = "dev-seed-local-secret"


_prepare_local_environment()

from backend.core.database import create_db_assets  # noqa: E402
from backend.core.security import get_password_hash  # noqa: E402
from backend.models.orm.access import (  # noqa: E402
    AuditEvent,
    AuditOutcome,
    UserWorkspaceRole,
    Workspace,
    WorkspaceRole,
)
from backend.models.orm.chat import (  # noqa: E402
    ChatMessage,
    ChatSession,
    MessageStatus,
)
from backend.models.orm.user import User  # noqa: E402

SEED_PASSWORD = "SeedPass123!"

USER_SEEDS = [
    {
        "username": "seed_admin",
        "email": "seed_admin@example.com",
        "is_superuser": True,
        "is_active": True,
        "max_tokens": 200000,
        "used_tokens": 1200,
    },
    {
        "username": "seed_workspace_admin",
        "email": "seed_workspace_admin@example.com",
        "is_superuser": False,
        "is_active": True,
        "max_tokens": 120000,
        "used_tokens": 800,
    },
    {
        "username": "seed_member",
        "email": "seed_member@example.com",
        "is_superuser": False,
        "is_active": True,
        "max_tokens": 80000,
        "used_tokens": 300,
    },
    {
        "username": "seed_viewer",
        "email": "seed_viewer@example.com",
        "is_superuser": False,
        "is_active": True,
        "max_tokens": 50000,
        "used_tokens": 50,
    },
    {
        "username": "seed_inactive",
        "email": "seed_inactive@example.com",
        "is_superuser": False,
        "is_active": False,
        "max_tokens": 10000,
        "used_tokens": 0,
    },
]

WORKSPACE_SEEDS = [
    {
        "slug": "seed-default",
        "name": "Seed Default Workspace",
        "owner_username": "seed_admin",
    },
    {
        "slug": "seed-ops",
        "name": "Seed Ops Workspace",
        "owner_username": "seed_workspace_admin",
    },
    {
        "slug": "seed-analytics",
        "name": "Seed Analytics Workspace",
        "owner_username": "seed_admin",
    },
    {
        "slug": "seed-sandbox",
        "name": "Seed Sandbox Workspace",
        "owner_username": "seed_member",
    },
    {
        "slug": "seed-archive",
        "name": "Seed Archive Workspace",
        "owner_username": "seed_admin",
    },
]

ROLE_SEEDS = [
    ("seed_admin", "seed-default", WorkspaceRole.OWNER),
    ("seed_workspace_admin", "seed-ops", WorkspaceRole.ADMIN),
    ("seed_member", "seed-analytics", WorkspaceRole.MEMBER),
    ("seed_viewer", "seed-sandbox", WorkspaceRole.VIEWER),
    ("seed_inactive", "seed-archive", WorkspaceRole.VIEWER),
]

CHAT_SESSION_SEEDS = [
    ("seed-session-001", "seed_admin", "seed-default", "Seed Admin Overview"),
    ("seed-session-002", "seed_workspace_admin", "seed-ops", "Seed Ops Review"),
    ("seed-session-003", "seed_member", "seed-analytics", "Seed Analytics Notes"),
    ("seed-session-004", "seed_viewer", "seed-sandbox", "Seed Read Only Check"),
    ("seed-session-005", "seed_inactive", "seed-archive", "Seed Inactive User Check"),
]
SESSION_USER_BY_KEY = {
    seed_key: username for seed_key, username, _, _ in CHAT_SESSION_SEEDS
}

CHAT_MESSAGE_SEEDS = [
    (
        "seed-msg-001",
        "seed-session-001",
        "user",
        "请确认管理员后台概览可用。",
        MessageStatus.SUCCESS,
        12,
        0,
    ),
    (
        "seed-msg-002",
        "seed-session-002",
        "assistant",
        "Ops 工作区权限检查数据已准备。",
        MessageStatus.SUCCESS,
        18,
        24,
    ),
    (
        "seed-msg-003",
        "seed-session-003",
        "user",
        "成员用户尝试创建普通后台资源。",
        MessageStatus.SUCCESS,
        15,
        0,
    ),
    (
        "seed-msg-004",
        "seed-session-004",
        "assistant",
        "Viewer 用户应只能读取，不能修改。",
        MessageStatus.SUCCESS,
        16,
        21,
    ),
    (
        "seed-msg-005",
        "seed-session-005",
        "system",
        "Inactive user fixture for auth and permission tests.",
        MessageStatus.FAILED,
        8,
        0,
    ),
]

AUDIT_EVENT_SEEDS = [
    (
        "seed-audit-001",
        "seed_admin",
        "seed-default",
        "workspace.seed",
        "workspace",
        AuditOutcome.SUCCESS,
    ),
    (
        "seed-audit-002",
        "seed_workspace_admin",
        "seed-ops",
        "role.assign",
        "user_workspace_role",
        AuditOutcome.SUCCESS,
    ),
    (
        "seed-audit-003",
        "seed_member",
        "seed-analytics",
        "chat.create",
        "chat_session",
        AuditOutcome.SUCCESS,
    ),
    (
        "seed-audit-004",
        "seed_viewer",
        "seed-sandbox",
        "workspace.update",
        "workspace",
        AuditOutcome.DENIED,
    ),
    (
        "seed-audit-005",
        "seed_inactive",
        "seed-archive",
        "auth.login",
        "user",
        AuditOutcome.FAILED,
    ),
]


async def _one_or_none_by(
    session: AsyncSession, model: type[Any], **filters: Any
) -> Any | None:
    stmt = select(model)
    for column_name, value in filters.items():
        stmt = stmt.where(getattr(model, column_name) == value)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _seed_users(session: AsyncSession) -> dict[str, User]:
    password_hash = await get_password_hash(SEED_PASSWORD)
    users: dict[str, User] = {}

    for seed in USER_SEEDS:
        user = await _one_or_none_by(session, User, username=seed["username"])
        if user is None:
            user = User(
                username=seed["username"],
                email=seed["email"],
                hashed_password=password_hash,
            )
            session.add(user)

        user.email = seed["email"]
        user.hashed_password = password_hash
        user.is_superuser = seed["is_superuser"]
        user.is_active = seed["is_active"]
        user.max_tokens = seed["max_tokens"]
        user.used_tokens = seed["used_tokens"]
        users[user.username] = user

    await session.flush()
    return users


async def _seed_workspaces(
    session: AsyncSession,
    users: dict[str, User],
) -> dict[str, Workspace]:
    workspaces: dict[str, Workspace] = {}

    for seed in WORKSPACE_SEEDS:
        workspace = await _one_or_none_by(session, Workspace, slug=seed["slug"])
        owner = users[seed["owner_username"]]
        if workspace is None:
            workspace = Workspace(
                slug=seed["slug"],
                name=seed["name"],
                owner_id=owner.id,
            )
            session.add(workspace)

        workspace.name = seed["name"]
        workspace.owner_id = owner.id
        workspaces[workspace.slug] = workspace

    await session.flush()
    return workspaces


async def _seed_roles(
    session: AsyncSession,
    users: dict[str, User],
    workspaces: dict[str, Workspace],
) -> list[UserWorkspaceRole]:
    roles: list[UserWorkspaceRole] = []

    for username, workspace_slug, role_value in ROLE_SEEDS:
        user = users[username]
        workspace = workspaces[workspace_slug]
        role = await _one_or_none_by(
            session,
            UserWorkspaceRole,
            user_id=user.id,
            workspace_id=workspace.id,
        )
        if role is None:
            role = UserWorkspaceRole(
                user_id=user.id,
                workspace_id=workspace.id,
            )
            session.add(role)

        role.role = role_value
        roles.append(role)

    await session.flush()
    return roles


async def _seed_chat_sessions(
    session: AsyncSession,
    users: dict[str, User],
    workspaces: dict[str, Workspace],
) -> dict[str, ChatSession]:
    sessions: dict[str, ChatSession] = {}

    for key, username, workspace_slug, title in CHAT_SESSION_SEEDS:
        user = users[username]
        workspace = workspaces[workspace_slug]
        session_row = await _one_or_none_by(session, ChatSession, title=title)
        if session_row is None:
            session_row = ChatSession(
                title=title,
                user_id=user.id,
                kb_id=None,
                workspace_id=workspace.id,
            )
            session.add(session_row)

        session_row.user_id = user.id
        session_row.kb_id = None
        session_row.workspace_id = workspace.id
        session_row.llm_config = {
            "seed_key": key,
            "model": "seed-mock",
            "temperature": 0,
        }
        sessions[key] = session_row

    await session.flush()
    return sessions


async def _seed_chat_messages(
    session: AsyncSession,
    users: dict[str, User],
    sessions: dict[str, ChatSession],
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []

    for (
        seed_key,
        session_key,
        role,
        content,
        status,
        tokens_input,
        tokens_output,
    ) in CHAT_MESSAGE_SEEDS:
        session_row = sessions[session_key]
        user = users[SESSION_USER_BY_KEY[session_key]]
        message = await _one_or_none_by(
            session,
            ChatMessage,
            client_request_id=seed_key,
        )
        if message is None:
            message = ChatMessage(
                session_id=session_row.id,
                role=role,
                content=content,
                client_request_id=seed_key,
            )
            session.add(message)

        message.session_id = session_row.id
        message.role = role
        message.content = content
        message.user_id = user.id
        message.status = status
        message.search_context = None
        message.message_metadata = {"seed": True, "key": seed_key}
        message.tokens_input = tokens_input
        message.tokens_output = tokens_output
        message.latency_ms = 120 if tokens_output else None
        messages.append(message)

    await session.flush()
    return messages


async def _seed_audit_events(
    session: AsyncSession,
    users: dict[str, User],
    workspaces: dict[str, Workspace],
) -> list[AuditEvent]:
    events: list[AuditEvent] = []

    for (
        request_id,
        username,
        workspace_slug,
        action,
        resource_type,
        outcome,
    ) in AUDIT_EVENT_SEEDS:
        user = users[username]
        workspace = workspaces[workspace_slug]
        event = await _one_or_none_by(session, AuditEvent, request_id=request_id)
        if event is None:
            event = AuditEvent(
                request_id=request_id,
                action=action,
                resource_type=resource_type,
            )
            session.add(event)

        event.actor_user_id = user.id
        event.workspace_id = workspace.id
        event.action = action
        event.resource_type = resource_type
        event.resource_id = workspace.id
        event.outcome = outcome
        event.ip = "127.0.0.1"
        event.user_agent = "dev-seed"
        event.event_metadata = {
            "seed": True,
            "username": username,
            "workspace_slug": workspace_slug,
        }
        events.append(event)

    await session.flush()
    return events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed a small fixed dataset for local admin and permission testing."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the seed data and roll the transaction back.",
    )
    return parser


def _print_summary(
    *,
    users: dict[str, User],
    workspaces: dict[str, Workspace],
    roles: Sequence[UserWorkspaceRole],
    sessions: dict[str, ChatSession],
    messages: Sequence[ChatMessage],
    events: Sequence[AuditEvent],
    dry_run: bool,
) -> None:
    mode = "dry_run" if dry_run else "committed"
    print(f"seed_status={mode}")
    print(f"seed_password={SEED_PASSWORD}")
    print(f"users={len(users)}")
    print(f"workspaces={len(workspaces)}")
    print(f"user_workspace_roles={len(roles)}")
    print(f"chat_sessions={len(sessions)}")
    print(f"chat_messages={len(messages)}")
    print(f"audit_events={len(events)}")
    print("seed_usernames=" + ",".join(sorted(users)))
    print("workspace_slugs=" + ",".join(sorted(workspaces)))


async def _main() -> int:
    args = _build_parser().parse_args()
    engine, session_factory = create_db_assets()

    try:
        async with session_factory() as session:
            users = await _seed_users(session)
            workspaces = await _seed_workspaces(session, users)
            roles = await _seed_roles(session, users, workspaces)
            sessions = await _seed_chat_sessions(session, users, workspaces)
            messages = await _seed_chat_messages(session, users, sessions)
            events = await _seed_audit_events(session, users, workspaces)

            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()

            _print_summary(
                users=users,
                workspaces=workspaces,
                roles=roles,
                sessions=sessions,
                messages=messages,
                events=events,
                dry_run=args.dry_run,
            )
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
