from typing import Any

from backend.domain.interfaces import AbstractRAGEmbedder


class SentenceTransformerEmbedder(AbstractRAGEmbedder):
    """基于 sentence-transformers 的本地向量化实现。"""

    def __init__(self, model_name: str, device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model: Any | None = None

    def encode_query(self, text: str) -> list[float]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()


class RAGEmbedderFactory:
    """负责选择并构建 RAG 向量化模型。"""

    @staticmethod
    def create(
        provider: str,
        model_name: str,
        device: str = "cpu",
    ) -> AbstractRAGEmbedder:
        normalized = provider.strip().lower()
        if normalized in {"sentence-transformers", "st"}:
            return SentenceTransformerEmbedder(model_name=model_name, device=device)
        raise ValueError(f"Unsupported RAG embedding provider: {provider}")
