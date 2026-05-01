from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from backend.models.orm.knowledge import KnowledgeBase
    from backend.models.orm.user import User


def _default_database_url() -> str:
    explicit = os.getenv("SMOKE_DATABASE_URL")
    if explicit:
        return explicit

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("SMOKE_DB_HOST") or os.getenv("POSTGRES_SERVER", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "postgres")

    if host == "postgres":
        # .env.smoke is used both inside docker and on the host.
        # When this script runs on the host, service DNS names are not resolvable.
        host = "localhost"

    auth = (
        f"{quote(user, safe='')}:{quote(password, safe='')}@"
        if password
        else f"{quote(user, safe='')}@"
    )
    return f"postgresql+asyncpg://{auth}{host}:{port}/{database}"


async def _create_kb(
    *,
    database_url: str,
    username: str | None,
    email: str | None,
    name: str,
    description: str | None,
) -> tuple[KnowledgeBase, User]:
    from backend.models.orm.knowledge import KnowledgeBase
    from backend.models.orm.user import User

    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    try:
        async with session_factory() as session:
            stmt = select(User)
            if username:
                stmt = stmt.where(User.username == username)
            elif email:
                stmt = stmt.where(User.email == email)
            else:
                raise ValueError("username or email is required")

            result = await session.execute(stmt)
            user = result.scalars().first()
            if user is None:
                identity = username or email or "<unknown>"
                raise SystemExit(
                    f"User not found: {identity}. Register/login the user first, then rerun this command."
                )

            kb = KnowledgeBase(
                name=name,
                description=description,
                user_id=user.id,
            )
            session.add(kb)
            await session.commit()
            await session.refresh(kb)
            return kb, user
    finally:
        await engine.dispose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a smoke/manual knowledge base for an existing user."
    )
    parser.add_argument("--username", help="Existing username to bind the KB to.")
    parser.add_argument("--email", help="Existing email to bind the KB to.")
    parser.add_argument(
        "--name",
        help="Knowledge base name. Defaults to a generated smoke name.",
    )
    parser.add_argument(
        "--description",
        default="Manual smoke knowledge base",
        help="Optional knowledge base description.",
    )
    parser.add_argument(
        "--database-url",
        default=_default_database_url(),
        help="Override the database URL. Defaults to SMOKE_DATABASE_URL or POSTGRES_* env vars.",
    )
    return parser


async def _main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.username and not args.email:
        parser.error("one of --username or --email is required")

    kb_name = args.name or f"manual_smoke_kb_{uuid.uuid4().hex[:8]}"
    kb, user = await _create_kb(
        database_url=args.database_url,
        username=args.username,
        email=args.email,
        name=kb_name,
        description=args.description,
    )

    print(f"user_id={user.id}")
    print(f"username={user.username}")
    print(f"kb_id={kb.id}")
    print(f"kb_name={kb.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
