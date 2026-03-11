import logging

import openai

from backend.core.config import settings
from backend.core.exceptions import ServiceError
from backend.domain.interfaces import AbstractRAGEmbedder

logger = logging.getLogger(__name__)


class OpenAICompatibleEmbedder(AbstractRAGEmbedder):
    """基于 OpenAI-compatible embeddings API 的向量化实现。"""

    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: str,
        dimensions: int | None = None,
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.dimensions = dimensions
        self._client: openai.OpenAI | None = None

    def _get_client(self) -> openai.OpenAI:
        if self._client is None:
            self._client = openai.OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        return self._client

    def encode_query(self, text: str) -> list[float]:
        payload = text.strip()
        if not payload:
            raise ServiceError("RAG embedding 输入不能为空")

        request_kwargs: dict = {}
        if self.dimensions is not None:
            request_kwargs["dimensions"] = self.dimensions

        try:
            response = self._get_client().embeddings.create(
                model=self.model_name,
                input=payload,
                **request_kwargs,
            )
            if not response.data:
                raise ServiceError("RAG embedding 服务未返回向量数据")

            embedding = response.data[0].embedding
            if self.dimensions is not None and len(embedding) != self.dimensions:
                raise ServiceError(
                    "RAG embedding 维度不匹配",
                    details={
                        "expected_dim": self.dimensions,
                        "actual_dim": len(embedding),
                        "model": self.model_name,
                    },
                )
            return [float(value) for value in embedding]
        except ServiceError:
            raise
        except Exception as exc:
            logger.error("RAG embedding API 调用失败: %s", exc, exc_info=True)
            raise ServiceError(
                "RAG embedding API 调用失败",
                details={
                    "model": self.model_name,
                    "base_url": self.base_url,
                    "error": str(exc),
                },
            ) from exc


class RAGEmbedderFactory:
    """负责选择并构建 RAG 向量化模型。"""

    @staticmethod
    def create(
        provider: str,
        model_name: str,
        device: str = "cpu",
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> AbstractRAGEmbedder:
        _ = device  # 保留参数签名兼容旧调用点
        normalized = provider.strip().lower()
        if normalized in {"openai", "openai-compatible", "api", "external-api"}:
            resolved_base_url = base_url or settings.RAG_EMBED_BASE_URL or settings.LLM_BASE_URL
            resolved_api_key = api_key or settings.RAG_EMBED_API_KEY or settings.LLM_API_KEY
            if not resolved_base_url or not resolved_api_key:
                raise ValueError("RAG embedding API 配置不完整，请检查 BASE_URL/API_KEY")
            return OpenAICompatibleEmbedder(
                model_name=model_name,
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                dimensions=dimensions if dimensions is not None else settings.RAG_EMBED_DIM,
            )
        if normalized in {"sentence-transformers", "st"}:
            raise ValueError(
                "sentence-transformers 本地向量化已禁用，请改用 openai-compatible provider"
            )
        raise ValueError(f"Unsupported RAG embedding provider: {provider}")
