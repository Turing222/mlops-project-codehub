from types import SimpleNamespace

import pytest

from backend.ai.providers.embedding.rag_embedding import (
    OpenAICompatibleEmbedder,
    RAGEmbedderFactory,
)
from backend.core.exceptions import ServiceError


def test_factory_returns_openai_compatible_embedder():
    embedder = RAGEmbedderFactory.create(
        provider="openai-compatible",
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=768,
    )

    assert isinstance(embedder, OpenAICompatibleEmbedder)


def test_factory_rejects_sentence_transformers():
    with pytest.raises(ValueError):
        RAGEmbedderFactory.create(
            provider="sentence-transformers",
            model_name="BAAI/bge-base-zh-v1.5",
            base_url="http://example.com/v1",
            api_key="test-key",
        )


def test_openai_embedder_encode_query_success(monkeypatch):
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

    vector = embedder.encode_query("hello")
    assert vector == [0.1, 0.2, 0.3]


def test_openai_embedder_encode_query_dim_mismatch(monkeypatch):
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

    with pytest.raises(ServiceError):
        embedder.encode_query("hello")


def test_openai_embedder_rejects_empty_text():
    embedder = OpenAICompatibleEmbedder(
        model_name="text-embedding-3-small",
        base_url="http://example.com/v1",
        api_key="test-key",
        dimensions=3,
    )

    with pytest.raises(ServiceError):
        embedder.encode_query("   ")
