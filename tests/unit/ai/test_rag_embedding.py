"""RAG embedding provider unit tests.

职责：验证 embedding provider factory、批处理和维度校验；边界：使用 fake SDK client，不访问真实 embedding 服务；副作用：无。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.ai.providers.embedding.rag_embedding import (
    GoogleGenAIEmbedder,
    MockRAGEmbedder,
    OpenAICompatibleEmbedder,
    RAGEmbedderFactory,
)
from backend.contracts.interfaces import AbstractRAGEmbedder
from backend.core.exceptions import AppException


def test_factory_returns_openai_compatible_embedder() -> None:
    embedder = RAGEmbedderFactory.create(
        provider="openai-compatible",
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=768,
    )

    assert isinstance(embedder, OpenAICompatibleEmbedder)


def test_factory_returns_google_embedder() -> None:
    embedder = RAGEmbedderFactory.create(
        provider="google",
        model_name="gemini-embedding-001",
        api_key="test-key",
        dimensions=768,
    )

    assert isinstance(embedder, GoogleGenAIEmbedder)


async def test_factory_returns_mock_embedder() -> None:
    embedder = RAGEmbedderFactory.create(
        provider="mock",
        model_name="unused",
        dimensions=4,
    )

    assert isinstance(embedder, MockRAGEmbedder)
    assert await embedder.encode_query("hello") == [1.0, 0.0, 0.0, 0.0]
    assert await embedder.encode_document("doc") == [1.0, 0.0, 0.0, 0.0]
    assert await embedder.encode_documents(["a", "b"]) == [
        [1.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0, 0.0],
    ]


def test_factory_rejects_local_embedding_provider() -> None:
    with pytest.raises(ValueError):
        RAGEmbedderFactory.create(
            provider="local-model",
            model_name="local-embedding",
            base_url="http://example.com/v1",
            api_key="test-key",
        )


async def test_default_encode_documents_is_bounded_and_ordered() -> None:
    class SlowEmbedder(AbstractRAGEmbedder):
        DEFAULT_ENCODE_DOCUMENTS_CONCURRENCY = 2

        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.max_active = 0

        async def encode_query(self, text: str) -> list[float]:
            return [float(text)]

        async def encode_document(self, text: str) -> list[float]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return [float(text)]

    embedder = SlowEmbedder()

    vectors = await embedder.encode_documents(["1", "2", "3", "4"])

    assert vectors == [[1.0], [2.0], [3.0], [4.0]]
    assert embedder.max_active == 2


async def test_default_encode_documents_propagates_errors() -> None:
    class FailingEmbedder(AbstractRAGEmbedder):
        async def encode_query(self, text: str) -> list[float]:
            return [float(text)]

        async def encode_document(self, text: str) -> list[float]:
            if text == "bad":
                raise RuntimeError("boom")
            return [float(text)]

    with pytest.raises(RuntimeError, match="boom"):
        await FailingEmbedder().encode_documents(["1", "bad", "3"])


async def test_openai_embedder_encode_query_success(monkeypatch) -> None:
    fake_response = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(create=lambda **_: fake_response)
    )
    monkeypatch.setattr(
        "backend.ai.providers.embedding.rag_embedding.openai.OpenAI",
        lambda **_: fake_client,
    )

    embedder = OpenAICompatibleEmbedder(
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=3,
    )

    vector = await embedder.encode_query("hello")
    assert vector == [0.1, 0.2, 0.3]


async def test_openai_embedder_encode_documents_batches_inputs(monkeypatch) -> None:
    calls = []
    fake_response = SimpleNamespace(
        data=[
            SimpleNamespace(index=0, embedding=[0.1, 0.2, 0.3]),
            SimpleNamespace(index=1, embedding=[0.4, 0.5, 0.6]),
        ]
    )

    def fake_create(**kwargs):
        calls.append(kwargs)
        return fake_response

    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(
        "backend.ai.providers.embedding.rag_embedding.openai.OpenAI",
        lambda **_: fake_client,
    )

    embedder = OpenAICompatibleEmbedder(
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=3,
    )

    vectors = await embedder.encode_documents([" first ", "second"])

    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert calls[0]["input"] == ["first", "second"]
    assert calls[0]["model"] == "text-embedding-3-small"
    assert calls[0]["dimensions"] == 3


async def test_openai_embedder_encode_query_dim_mismatch(monkeypatch) -> None:
    fake_response = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(create=lambda **_: fake_response)
    )
    monkeypatch.setattr(
        "backend.ai.providers.embedding.rag_embedding.openai.OpenAI",
        lambda **_: fake_client,
    )

    embedder = OpenAICompatibleEmbedder(
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=3,
    )

    with pytest.raises(AppException):
        await embedder.encode_query("hello")


async def test_openai_embedder_rejects_empty_text() -> None:
    embedder = OpenAICompatibleEmbedder(
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=3,
    )

    with pytest.raises(AppException):
        await embedder.encode_query("   ")


async def test_google_embedder_uses_query_and_document_task_types(monkeypatch) -> None:
    calls = []
    fake_response = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])]
    )

    class FakeModels:
        def embed_content(self, **kwargs):
            calls.append(kwargs)
            if isinstance(kwargs["contents"], list):
                return SimpleNamespace(
                    embeddings=[
                        SimpleNamespace(values=[0.1, 0.2, 0.3]),
                        SimpleNamespace(values=[0.1, 0.2, 0.3]),
                    ]
                )
            return fake_response

    fake_client = SimpleNamespace(models=FakeModels())
    monkeypatch.setattr(
        "backend.ai.providers.embedding.rag_embedding.genai.Client",
        lambda **_: fake_client,
    )

    embedder = GoogleGenAIEmbedder(
        model_name="gemini-embedding-001",
        api_key="test-key",
        dimensions=3,
    )

    assert await embedder.encode_query("hello") == [0.1, 0.2, 0.3]
    assert await embedder.encode_document("doc") == [0.1, 0.2, 0.3]
    assert await embedder.encode_documents(["doc 1", "doc 2"]) == [
        [0.1, 0.2, 0.3],
        [0.1, 0.2, 0.3],
    ]

    assert calls[0]["model"] == "gemini-embedding-001"
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    assert calls[0]["config"].output_dimensionality == 3
    assert calls[1]["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert calls[2]["contents"] == ["doc 1", "doc 2"]
    assert calls[2]["config"].task_type == "RETRIEVAL_DOCUMENT"


async def test_google_embedder_encode_query_dim_mismatch(monkeypatch) -> None:
    fake_response = SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])
    fake_client = SimpleNamespace(
        models=SimpleNamespace(embed_content=lambda **_: fake_response)
    )
    monkeypatch.setattr(
        "backend.ai.providers.embedding.rag_embedding.genai.Client",
        lambda **_: fake_client,
    )

    embedder = GoogleGenAIEmbedder(
        model_name="gemini-embedding-001",
        api_key="test-key",
        dimensions=3,
    )

    with pytest.raises(AppException):
        await embedder.encode_query("hello")
