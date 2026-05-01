import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from backend.models.orm.chunk import DocumentChunk
from backend.models.orm.knowledge import File, FileStatus, FileVisibility, KnowledgeBase


class KnowledgeRepository:
    """知识库聚合仓储（多模型组合，不继承 CRUDBase）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_kb(self, kb_id: uuid.UUID) -> KnowledgeBase | None:
        return await self.session.get(KnowledgeBase, kb_id)

    async def get_kb_for_user(
        self,
        kb_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_kb_by_name_for_user(
        self,
        *,
        name: str,
        user_id: uuid.UUID,
    ) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(
            KnowledgeBase.name == name,
            KnowledgeBase.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_kb(
        self,
        *,
        name: str,
        description: str | None,
        user_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> KnowledgeBase:
        kb = KnowledgeBase(
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        self.session.add(kb)
        await self.session.flush()
        await self.session.refresh(kb)
        return kb

    async def create_file(
        self,
        kb_id: uuid.UUID,
        filename: str,
        file_path: str,
        file_size: int,
        status: FileStatus = FileStatus.UPLOADED,
        owner_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        visibility: FileVisibility = FileVisibility.WORKSPACE,
        storage_backend: str = "local",
        storage_bucket: str | None = None,
        storage_key: str | None = None,
        content_sha256: str | None = None,
    ) -> File:
        knowledge_file = File(
            kb_id=kb_id,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            status=status,
            owner_id=owner_id,
            workspace_id=workspace_id,
            visibility=visibility,
            storage_backend=storage_backend,
            storage_bucket=storage_bucket,
            storage_key=storage_key,
            content_sha256=content_sha256,
        )
        self.session.add(knowledge_file)
        await self.session.flush()
        await self.session.refresh(knowledge_file)
        return knowledge_file

    async def get_file(self, file_id: uuid.UUID) -> File | None:
        return await self.session.get(File, file_id)

    async def get_ready_file_by_hash(
        self,
        *,
        kb_id: uuid.UUID,
        content_sha256: str,
    ) -> File | None:
        stmt = (
            select(File)
            .where(File.kb_id == kb_id)
            .where(File.content_sha256 == content_sha256)
            .where(File.status == FileStatus.READY)
            .order_by(File.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_file_status(
        self,
        file_id: uuid.UUID,
        status: FileStatus,
    ) -> File | None:
        knowledge_file = await self.get_file(file_id)
        if not knowledge_file:
            return None
        knowledge_file.status = status
        self.session.add(knowledge_file)
        await self.session.flush()
        await self.session.refresh(knowledge_file)
        return knowledge_file

    async def delete_chunks_for_file(self, file_id: uuid.UUID) -> None:
        stmt = delete(DocumentChunk).where(DocumentChunk.file_id == file_id)
        await self.session.execute(stmt)

    async def add_chunks(self, chunks_data: list[dict]) -> None:
        # chunks_data 包含 content 和 embedding(list)
        if not chunks_data:
            return
        stmt = insert(DocumentChunk).values(chunks_data)
        await self.session.execute(stmt)

    async def vector_search(
        self,
        query_vector: list[float],
        limit: int = 5,
    ) -> Sequence[DocumentChunk]:
        # 利用 pgvector 的 <=> 符号进行余弦相似度搜索
        from sqlalchemy import select

        stmt = (
            select(DocumentChunk)
            .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def search_chunks_for_kb(
        self,
        query_vector: list[float],
        kb_id: uuid.UUID,
        limit: int = 5,
    ) -> list[tuple[DocumentChunk, float]]:
        """在指定知识库内做向量检索，返回 (chunk, distance)。"""
        from sqlalchemy import select

        distance = DocumentChunk.embedding.cosine_distance(query_vector).label(
            "distance"
        )
        stmt = (
            select(DocumentChunk, distance)
            .join(File, DocumentChunk.file_id == File.id)
            .options(contains_eager(DocumentChunk.file))
            .where(File.kb_id == kb_id)
            .order_by(distance)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]

    async def search_chunks_for_kb_fulltext(
        self,
        *,
        query_text: str,
        kb_id: uuid.UUID,
        limit: int = 5,
    ) -> list[tuple[DocumentChunk, float]]:
        """在指定知识库内做全文检索，返回 (chunk, distance)。"""
        if not query_text.strip() or limit <= 0:
            return []

        normalized_query = query_text.strip()
        ts_vector = func.to_tsvector("simple", DocumentChunk.content)
        ts_query = func.plainto_tsquery("simple", normalized_query)
        rank = func.ts_rank_cd(ts_vector, ts_query).label("rank")
        stmt = (
            select(DocumentChunk, rank)
            .join(File, DocumentChunk.file_id == File.id)
            .options(contains_eager(DocumentChunk.file))
            .where(File.kb_id == kb_id)
            .where(ts_vector.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            (
                row[0],
                self._rank_to_distance(float(row[1]) if row[1] is not None else 0.0),
            )
            for row in rows
        ]

    @staticmethod
    def _rank_to_distance(rank: float) -> float:
        # 与向量检索保持同方向：值越小越相关
        safe_rank = max(0.0, rank)
        return 1.0 / (1.0 + safe_rank)
