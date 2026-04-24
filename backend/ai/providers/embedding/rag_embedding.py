import logging

import openai
from google import genai
from google.genai import types

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


class GoogleGenAIEmbedder(AbstractRAGEmbedder):
    """基于 Google GenAI embeddings API 的向量化实现。"""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        dimensions: int | None = None,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.dimensions = dimensions
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def encode_query(self, text: str) -> list[float]:
        return self._embed(text, task_type="RETRIEVAL_QUERY")

    def encode_document(self, text: str) -> list[float]:
        return self._embed(text, task_type="RETRIEVAL_DOCUMENT")

    def _embed(self, text: str, *, task_type: str) -> list[float]:
        payload = text.strip()
        if not payload:
            raise ServiceError("RAG embedding 输入不能为空")

        config_kwargs: dict = {"task_type": task_type}
        if self.dimensions is not None:
            config_kwargs["output_dimensionality"] = self.dimensions

        try:
            response = self._get_client().models.embed_content(
                model=self.model_name,
                contents=payload,
                config=types.EmbedContentConfig(**config_kwargs),
            )
            if not response.embeddings or not response.embeddings[0].values:
                raise ServiceError("Google embedding 服务未返回向量数据")

            embedding = response.embeddings[0].values
            if self.dimensions is not None and len(embedding) != self.dimensions:
                raise ServiceError(
                    "Google embedding 维度不匹配",
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
            logger.error("Google embedding API 调用失败: %s", exc, exc_info=True)
            raise ServiceError(
                "Google embedding API 调用失败",
                details={
                    "model": self.model_name,
                    "task_type": task_type,
                    "error": str(exc),
                },
            ) from exc


class RAGEmbedderFactory:
    """负责选择并构建 RAG 向量化模型。"""

    @staticmethod
    def create(
        provider: str,
        model_name: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> AbstractRAGEmbedder:
        normalized = provider.strip().lower()
        resolved_dimensions = (
            dimensions if dimensions is not None else settings.RAG_EMBED_DIM
        )

        if normalized in {"google", "gemini", "google-genai"}:
            resolved_api_key = (
                api_key
                or settings.RAG_EMBED_API_KEY
                or settings.GEMINI_API_KEY
                or settings.GOOGLE_API_KEY
            )
            if not resolved_api_key:
                raise ValueError(
                    "Google RAG embedding API Key 未配置，请检查 "
                    "RAG_EMBED_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY"
                )
            return GoogleGenAIEmbedder(
                model_name=model_name,
                api_key=resolved_api_key,
                dimensions=resolved_dimensions,
            )

        if normalized in {"openai", "openai-compatible", "api", "external-api"}:
            resolved_base_url = (
                base_url or settings.RAG_EMBED_BASE_URL or settings.LLM_BASE_URL
            )
            resolved_api_key = api_key or settings.RAG_EMBED_API_KEY or settings.LLM_API_KEY
            if not resolved_base_url or not resolved_api_key:
                raise ValueError("RAG embedding API 配置不完整，请检查 BASE_URL/API_KEY")
            return OpenAICompatibleEmbedder(
                model_name=model_name,
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                dimensions=resolved_dimensions,
            )
        raise ValueError(
            f"Unsupported RAG embedding provider: {provider}. "
            "Supported providers: google/gemini, openai-compatible."
        )
