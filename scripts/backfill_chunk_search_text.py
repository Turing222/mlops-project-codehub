"""Backfill document chunk search text.

职责：按批次重建 document_chunks.search_text，触发数据库自动刷新 search_vector。
边界：本脚本不修改 content、embedding 或业务状态；需要在已完成迁移后执行。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill document_chunks.search_text in batches."
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=1_000_000)
    return parser.parse_args()


async def backfill(batch_size: int, max_batches: int) -> int:
    from backend.infra.database import create_db_assets
    from backend.models.orm.chunk import DocumentChunk
    from backend.utils.search_text import build_search_texts

    engine, session_factory = create_db_assets()
    processed = 0
    last_id: uuid.UUID | None = None

    try:
        for _batch_index in range(max_batches):
            async with session_factory() as session:
                stmt = (
                    select(DocumentChunk.id, DocumentChunk.content)
                    .order_by(DocumentChunk.id.asc())
                    .limit(batch_size)
                )
                if last_id is not None:
                    stmt = stmt.where(DocumentChunk.id > last_id)

                rows = (await session.execute(stmt)).all()
                if not rows:
                    break

                search_texts = await asyncio.to_thread(
                    build_search_texts,
                    [row.content for row in rows],
                )
                params = [
                    {
                        "chunk_id": row.id,
                        "search_text": search_text,
                    }
                    for row, search_text in zip(rows, search_texts, strict=True)
                ]
                await session.execute(
                    text(
                        """
                        UPDATE document_chunks
                        SET search_text = :search_text
                        WHERE id = :chunk_id
                        """
                    ),
                    params,
                )
                await session.commit()

                processed += len(rows)
                last_id = rows[-1].id
                print(f"processed={processed}")
        else:
            raise RuntimeError(
                "backfill exceeded max_batches before reaching an empty page"
            )
    finally:
        await engine.dispose()

    return processed


async def main() -> None:
    args = parse_args()
    batch_size = max(1, args.batch_size)
    max_batches = max(1, args.max_batches)
    processed = await backfill(batch_size=batch_size, max_batches=max_batches)
    print(f"done processed={processed}")


if __name__ == "__main__":
    asyncio.run(main())
