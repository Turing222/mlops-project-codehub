"""
import gc

import torch

from backend.core.docling_models import AIModelFactory


class IngestionService:
    def __init__(self, uow):
        self.uow = uow

    async def process_file(self, file_path: str, file_id: int):
        converter = AIModelFactory.get_docling_converter()
        embed_model = AIModelFactory.get_embed_model()

        # 1. 解析 (CPU/GPU 密集)
        result = converter.convert(file_path)
        md_content = result.document.export_to_markdown()

        # 2. 分块并向量化
        chunks = md_content.split("\n\n")  # 简单演示，建议根据 Markdown 标题分
        to_db = []
        for text in chunks:
            if len(text.strip()) < 10:
                continue
            # 向量化
            embedding = embed_model.encode(text, normalize_embeddings=True).tolist()
            to_db.append({"file_id": file_id, "content": text, "embedding": embedding})

        # 3. 入库

        await self.uow.knowledge.add_chunks(to_db)
        await self.uow.commit()

        # 4. 💡 16G 内存保命操作：手动清理
        del chunks
        del to_db
        torch.cuda.empty_cache()  # 清理显存碎片
        gc.collect()  # 清理系统内存
"""
