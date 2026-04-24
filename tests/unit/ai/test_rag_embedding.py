from types import SimpleNamespace

import pytest

from backend.ai.providers.embedding.rag_embedding import (
    GoogleGenAIEmbedder,
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


def test_factory_returns_google_embedder():
    embedder = RAGEmbedderFactory.create(
        provider="google",
        model_name="gemini-embedding-001",
        api_key="test-key",
        dimensions=768,
    )

    assert isinstance(embedder, GoogleGenAIEmbedder)


def test_factory_rejects_local_embedding_provider():
    with pytest.raises(ValueError):
        RAGEmbedderFactory.create(
            provider="local-model",
            model_name="local-embedding",
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


def test_google_embedder_uses_query_and_document_task_types(monkeypatch):
    calls = []
    fake_response = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])]
    )

    class FakeModels:
        def embed_content(self, **kwargs):
            calls.append(kwargs)
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

    assert embedder.encode_query("hello") == [0.1, 0.2, 0.3]
    assert embedder.encode_document("doc") == [0.1, 0.2, 0.3]

    assert calls[0]["model"] == "gemini-embedding-001"
    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    assert calls[0]["config"].output_dimensionality == 3
    assert calls[1]["config"].task_type == "RETRIEVAL_DOCUMENT"


def test_google_embedder_encode_query_dim_mismatch(monkeypatch):
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

    with pytest.raises(ServiceError):
        embedder.encode_query("hello")
