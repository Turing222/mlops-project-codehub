"""Worker dependencies unit tests.

职责：验证 WorkerContainer 关闭清理和 wrapper 函数委托行为；边界：使用 DummyEngine/DummyContainer 替身，不连接真实基础设施；副作用：无。
"""

from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def reset_worker_container() -> None:
    from backend.worker import dependencies

    dependencies.set_worker_container(None)
    yield
    dependencies.set_worker_container(None)


class DummyEngine:
    def __init__(self) -> None:
        self.dispose = AsyncMock()


class DummyContainer:
    def __init__(self) -> None:
        self.session_factory = object()
        self.llm_service = object()
        self.embedder = object()
        self.rerank_service = object()
        self.rag_service = object()
        self.rag_planning_service = object()
        self.external_context_provider = object()
        self.object_storage = object()
        self.close = AsyncMock()

    def get_session_factory(self) -> object:
        return self.session_factory

    def get_llm_service(self) -> object:
        return self.llm_service

    def get_llm_service_for_provider(self, provider: str | None) -> object:
        return self.llm_service

    def get_embedder(self) -> object:
        return self.embedder

    def get_rerank_service(self) -> object:
        return self.rerank_service

    def get_rag_service(self) -> object:
        return self.rag_service

    def get_rag_planning_service(self) -> object:
        return self.rag_planning_service

    def get_external_context_provider(self) -> object:
        return self.external_context_provider

    def get_object_storage(self) -> object:
        return self.object_storage


@pytest.mark.asyncio
async def test_worker_container_close_disposes_engine_and_clears_refs() -> None:
    from backend.worker.dependencies import WorkerContainer

    container = WorkerContainer()
    engine = DummyEngine()
    llm_service = AsyncMock()
    embedder = AsyncMock()
    external_context_provider = AsyncMock()
    container._engine = engine
    container._session_factory = object()
    container._llm_service = llm_service
    container._embedder = embedder
    rerank_service = AsyncMock()
    container._rerank_service = rerank_service
    container._rag_service = object()
    container._rag_planning_service = object()
    container._external_context_provider = external_context_provider
    container._object_storage = object()

    await container.close()

    engine.dispose.assert_awaited_once()
    llm_service.close.assert_awaited_once()
    embedder.close.assert_awaited_once()
    rerank_service.close.assert_awaited_once()
    external_context_provider.close.assert_awaited_once()
    assert container._engine is None
    assert container._session_factory is None
    assert container._llm_service is None
    assert container._embedder is None
    assert container._rerank_service is None
    assert container._rag_service is None
    assert container._rag_planning_service is None
    assert container._external_context_provider is None
    assert container._object_storage is None


def test_wrapper_functions_delegate_to_container_return_services() -> None:
    from backend.worker import dependencies

    container = DummyContainer()
    dependencies.set_worker_container(container)

    assert dependencies.get_worker_session_factory() is container.session_factory
    assert dependencies.get_worker_llm_service() is container.llm_service
    assert (
        dependencies.get_worker_llm_service_for_provider("fast")
        is container.llm_service
    )
    assert dependencies.get_worker_embedder() is container.embedder
    assert dependencies.get_worker_rag_service() is container.rag_service
    assert (
        dependencies.get_worker_rag_planning_service() is container.rag_planning_service
    )
    assert (
        dependencies.get_worker_external_context_provider()
        is container.external_context_provider
    )
    assert dependencies.get_worker_object_storage() is container.object_storage


@pytest.mark.asyncio
async def test_get_external_context_provider_lazy_init(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    fake_provider = AsyncMock()
    monkeypatch.setattr(
        "backend.worker.dependencies.create_external_context_provider",
        lambda **kw: fake_provider,
    )

    container = WorkerContainer()
    assert container._external_context_provider is None

    result1 = container.get_external_context_provider()
    assert result1 is fake_provider
    assert container._external_context_provider is fake_provider

    result2 = container.get_external_context_provider()
    assert result2 is fake_provider


@pytest.mark.asyncio
async def test_get_rerank_service_lazy_init(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    fake_reranker = AsyncMock()
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_PROVIDER", "dashscope"
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.RerankProviderFactory.create",
        lambda *args, **kwargs: fake_reranker,
    )

    container = WorkerContainer()
    assert container._rerank_service is None

    result1 = container.get_rerank_service()
    assert result1 is fake_reranker
    assert container._rerank_service is fake_reranker

    result2 = container.get_rerank_service()
    assert result2 is fake_reranker


def test_get_rerank_service_returns_none_when_no_provider(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_PROVIDER", None
    )

    container = WorkerContainer()
    assert container.get_rerank_service() is None


def test_get_rerank_service_degrades_to_none_on_create_failure(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """构造失败（如缺少 provider key）时降级为 None，而不是把异常抛给生成任务。"""
    from backend.worker import dependencies
    from backend.worker.dependencies import WorkerContainer

    create_calls = 0

    def _raise_create(*args: object, **kwargs: object) -> object:
        nonlocal create_calls
        create_calls += 1
        raise ValueError("DashScope rerank 配置不完整，请检查 DASHSCOPE_API_KEY")

    caplog.set_level("WARNING", logger=dependencies.__name__)
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_PROVIDER", "dashscope"
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.RerankProviderFactory.create",
        _raise_create,
    )

    container = WorkerContainer()
    assert container.get_rerank_service() is None
    assert container._rerank_service is None
    assert container._rerank_init_failed is True

    assert container.get_rerank_service() is None
    assert create_calls == 1

    records = [
        item
        for item in caplog.records
        if getattr(item, "event", None) == "worker_rerank_init_degraded"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.rerank_provider == "dashscope"
    assert record.degradation_mode == "disabled"
    assert record.error == "DashScope rerank 配置不完整，请检查 DASHSCOPE_API_KEY"
    assert (
        record.getMessage()
        == "Worker rerank initialization degraded; rerank disabled for this worker process"
    )


def test_get_llm_service_for_provider_caches_services(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    created: list[str | None] = []

    def fake_create(provider: str | None = None) -> object:
        created.append(provider)
        return object()

    monkeypatch.setattr(
        "backend.worker.dependencies.LLMProviderFactory.create",
        fake_create,
    )

    container = WorkerContainer()
    first = container.get_llm_service_for_provider("fast")
    second = container.get_llm_service_for_provider("fast")

    assert first is second
    assert created == ["fast"]


def test_get_llm_service_for_provider_caches_create_errors(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    created: list[str | None] = []

    def fake_create(provider: str | None = None) -> object:
        created.append(provider)
        raise RuntimeError("bad provider")

    monkeypatch.setattr(
        "backend.worker.dependencies.LLMProviderFactory.create",
        fake_create,
    )

    container = WorkerContainer()
    with pytest.raises(RuntimeError, match="bad provider"):
        container.get_llm_service_for_provider("missing")
    with pytest.raises(RuntimeError, match="bad provider"):
        container.get_llm_service_for_provider("missing")

    assert created == ["missing"]


def test_get_rerank_service_returns_none_when_provider_is_mock(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_PROVIDER", "mock"
    )

    container = WorkerContainer()
    assert container.get_rerank_service() is None
    assert container._rerank_init_failed is False


@pytest.mark.asyncio
async def test_get_rag_service_succeeds_when_rerank_provider_is_mock(
    monkeypatch,
) -> None:
    from backend.worker.dependencies import WorkerContainer

    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_PROVIDER", "mock"
    )
    monkeypatch.setattr("backend.worker.dependencies.ai_settings.RAG_TOP_K", 4)
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_CANDIDATE_COUNT", 20
    )
    monkeypatch.setattr("backend.worker.dependencies.ai_settings.RAG_RERANK_TOP_K", 4)
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_EMBED_BATCH_SIZE", 10
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.SQLAlchemyUnitOfWork",
        lambda sf: object(),
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.VectorIndexService",
        lambda **kw: object(),
    )

    container = WorkerContainer()
    container._session_factory = object()
    container._embedder = AsyncMock()

    rag_service = container.get_rag_service()

    assert rag_service.reranker is None


@pytest.mark.asyncio
async def test_get_rag_service_uses_native_reranker_without_initializing_llm(
    monkeypatch,
) -> None:
    from backend.worker.dependencies import WorkerContainer

    fake_reranker = AsyncMock()
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_PROVIDER", "dashscope"
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.RerankProviderFactory.create",
        lambda *args, **kwargs: fake_reranker,
    )
    monkeypatch.setattr("backend.worker.dependencies.ai_settings.RAG_TOP_K", 4)
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_RERANK_CANDIDATE_COUNT", 20
    )
    monkeypatch.setattr("backend.worker.dependencies.ai_settings.RAG_RERANK_TOP_K", 4)
    monkeypatch.setattr(
        "backend.worker.dependencies.ai_settings.RAG_EMBED_BATCH_SIZE", 10
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.SQLAlchemyUnitOfWork",
        lambda sf: object(),
    )
    monkeypatch.setattr(
        "backend.worker.dependencies.VectorIndexService",
        lambda **kw: object(),
    )

    container = WorkerContainer()
    container._session_factory = object()
    container._embedder = AsyncMock()

    rag_service = container.get_rag_service()
    assert rag_service.reranker is fake_reranker
    assert container._llm_service is None
