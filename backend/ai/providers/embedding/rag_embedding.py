"""RAG embedding providers.

职责：封装 OpenAI-compatible、Google GenAI 和本地 mock 的向量化调用。
边界：本模块只返回向量，不写入索引；索引替换由 VectorIndexService 负责。
失败处理：空输入、空响应和维度不匹配都会转换为统一业务错误。
"""

import logging

import openai
from google import genai
from google.genai import types

from backend.core.config import settings
from backend.core.exceptions import AppException, app_service_error
from backend.core.trace_utils import set_span_attributes, trace_span
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
    ) -> None:
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
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")

        return self._create_embeddings([payload])[0]

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        payloads = [text.strip() for text in texts]
        if not payloads or any(not payload for payload in payloads):
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")
        return self._create_embeddings(payloads)

    def _create_embeddings(self, payloads: list[str]) -> list[list[float]]:
        if not payloads:
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")

        request_kwargs: dict = {}
        if self.dimensions is not None:
            request_kwargs["dimensions"] = self.dimensions

        try:
            with trace_span(
                "embedding.openai_compatible.encode",
                {
                    "gen_ai.system": "openai-compatible",
                    "gen_ai.operation.name": "embeddings",
                    "gen_ai.request.model": self.model_name,
                    "embedding.base_url": self.base_url,
                    "embedding.input.count": len(payloads),
                    "embedding.input.char_count": sum(
                        len(payload) for payload in payloads
                    ),
                    "embedding.expected_dim": self.dimensions,
                },
            ) as span:
                response = self._get_client().embeddings.create(
                    model=self.model_name,
                    input=payloads,
                    **request_kwargs,
                )
                if not response.data or len(response.data) != len(payloads):
                    raise app_service_error(
                        "RAG embedding 服务未返回向量数据",
                        code="RAG_EMBEDDING_EMPTY_RESPONSE",
                    )

                data = sorted(
                    response.data,
                    key=lambda item: getattr(item, "index", 0),
                )
                embeddings: list[list[float]] = []
                for item in data:
                    embedding = item.embedding
                    if (
                        self.dimensions is not None
                        and len(embedding) != self.dimensions
                    ):
                        raise app_service_error(
                            "RAG embedding 维度不匹配",
                            code="RAG_EMBEDDING_DIMENSION_MISMATCH",
                            details={
                                "expected_dim": self.dimensions,
                                "actual_dim": len(embedding),
                                "model": self.model_name,
                            },
                        )
                    embeddings.append([float(value) for value in embedding])
                set_span_attributes(
                    span,
                    {
                        "embedding.output.count": len(embeddings),
                        "embedding.output_dim": len(embeddings[0])
                        if embeddings
                        else None,
                    },
                )
            return embeddings
        except AppException:
            raise
        except Exception as exc:
            logger.error("RAG embedding API 调用失败: %s", exc, exc_info=True)
            raise app_service_error(
                "RAG embedding API 调用失败",
                code="RAG_EMBEDDING_API_ERROR",
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
    ) -> None:
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
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")

        config_kwargs: dict = {"task_type": task_type}
        if self.dimensions is not None:
            config_kwargs["output_dimensionality"] = self.dimensions

        try:
            with trace_span(
                "embedding.google_genai.encode",
                {
                    "gen_ai.system": "google-genai",
                    "gen_ai.operation.name": "embeddings",
                    "gen_ai.request.model": self.model_name,
                    "embedding.task_type": task_type,
                    "embedding.input.char_count": len(payload),
                    "embedding.expected_dim": self.dimensions,
                },
            ) as span:
                response = self._get_client().models.embed_content(
                    model=self.model_name,
                    contents=payload,
                    config=types.EmbedContentConfig(**config_kwargs),
                )
                if not response.embeddings or not response.embeddings[0].values:
                    raise app_service_error(
                        "Google embedding 服务未返回向量数据",
                        code="GOOGLE_EMBEDDING_EMPTY_RESPONSE",
                    )

                embedding = response.embeddings[0].values
                set_span_attributes(
                    span,
                    {
                        "embedding.output_dim": len(embedding),
                    },
                )
                if self.dimensions is not None and len(embedding) != self.dimensions:
                    raise app_service_error(
                        "Google embedding 维度不匹配",
                        code="GOOGLE_EMBEDDING_DIMENSION_MISMATCH",
                        details={
                            "expected_dim": self.dimensions,
                            "actual_dim": len(embedding),
                            "model": self.model_name,
                        },
                    )
            return [float(value) for value in embedding]
        except AppException:
            raise
        except Exception as exc:
            logger.error("Google embedding API 调用失败: %s", exc, exc_info=True)
            raise app_service_error(
                "Google embedding API 调用失败",
                code="GOOGLE_EMBEDDING_API_ERROR",
                details={
                    "model": self.model_name,
                    "task_type": task_type,
                    "error": str(exc),
                },
            ) from exc


class MockRAGEmbedder(AbstractRAGEmbedder):
    """Deterministic local embedder for smoke tests and offline development."""

    def __init__(self, *, dimensions: int = 768) -> None:
        self.dimensions = max(1, dimensions)

    def encode_query(self, text: str) -> list[float]:
        payload = text.strip()
        if not payload:
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")
        return self._vector()

    def encode_document(self, text: str) -> list[float]:
        payload = text.strip()
        if not payload:
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")
        return self._vector()

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        payloads = [text.strip() for text in texts]
        if not payloads or any(not payload for payload in payloads):
            raise app_service_error("RAG embedding 输入不能为空", code="RAG_EMBEDDING_INPUT_EMPTY")
        return [self._vector() for _ in payloads]

    def _vector(self) -> list[float]:
        return [1.0, *([0.0] * (self.dimensions - 1))]


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

        if normalized in {"mock", "fake", "deterministic"}:
            return MockRAGEmbedder(dimensions=resolved_dimensions)

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
            resolved_api_key = (
                api_key or settings.RAG_EMBED_API_KEY or settings.LLM_API_KEY
            )
            if not resolved_base_url or not resolved_api_key:
                raise ValueError(
                    "RAG embedding API 配置不完整，请检查 BASE_URL/API_KEY"
                )
            return OpenAICompatibleEmbedder(
                model_name=model_name,
                base_url=resolved_base_url,
                api_key=resolved_api_key,
                dimensions=resolved_dimensions,
            )
        raise ValueError(
            f"Unsupported RAG embedding provider: {provider}. "
            "Supported providers: mock, google/gemini, openai-compatible."
        )
