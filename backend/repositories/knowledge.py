import uuid

from sqlalchemy import insert

from backend.models.orm.chunk import DocumentChunk
from backend.models.orm.knowledge import File


class KnowledgeRepository:
    def __init__(self, session):
        self.session = session

    async def add_chunks(self, chunks_data: list[dict]):
        # chunks_data 包含 content 和 embedding(list)
        if not chunks_data:
            return
        stmt = insert(DocumentChunk).values(chunks_data)
        await self.session.execute(stmt)

    async def vector_search(self, query_vector: list[float], limit=5):
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
            .where(File.kb_id == kb_id)
            .order_by(distance)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]
