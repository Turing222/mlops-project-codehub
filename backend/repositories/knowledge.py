from sqlalchemy import insert

from backend.models.orm.chunk import DocumentChunk


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
