from sqlalchemy import insert

from app.models.orm.knowledge import FileChunk


class KnowledgeRepository:
    def __init__(self, session):
        self.session = session

    async def add_chunks(self, chunks_data: list[dict]):
        # chunks_data 包含 content 和 embedding(list)
        if not chunks_data:
            return
        stmt = insert(FileChunk).values(chunks_data)
        await self.session.execute(stmt)

    async def vector_search(self, query_vector: list[float], limit=5):
        # 利用 pgvector 的 <=> 符号进行余弦相似度搜索
        from sqlalchemy import select

        stmt = (
            select(FileChunk)
            .order_by(FileChunk.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
