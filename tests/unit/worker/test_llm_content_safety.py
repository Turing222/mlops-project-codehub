"""Worker LLM telemetry content-safety tests.

职责：验证实际 worker task 不把 generation query/history/output 交给 tracing recorder。
边界：mock generation workflow 与 Langfuse context，不连接 provider、Redis 或 DB。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest

from backend.models.schemas.chat.payloads import (
    GenerationResult,
    LLMTaskPayload,
    StreamGenerationResult,
)
from backend.worker.tasks import llm_tasks


@contextmanager
def _noop_context(*_args: object, **_kwargs: object):
    yield


async def test_nonstream_task_telemetry_omits_synthetic_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_marker = "query-secret-AKIA1111111111111111"
    history_marker = "history-pii-13812345678"
    output_marker = "ordinary-output-secret-value"
    generation_calls: list[dict[str, object]] = []
    recorder_calls: list[dict[str, object]] = []

    class FakeRecorder:
        def record(self, **kwargs: object) -> None:
            recorder_calls.append(kwargs)

    @contextmanager
    def fake_generation(**kwargs: object):
        generation_calls.append(kwargs)
        yield FakeRecorder()

    monkeypatch.setattr(llm_tasks, "use_trace_context", _noop_context)
    monkeypatch.setattr(llm_tasks, "set_langfuse_trace_metadata", _noop_context)
    monkeypatch.setattr(llm_tasks, "langfuse_generation", fake_generation)
    monkeypatch.setattr(
        llm_tasks,
        "_generate_llm_nonstream_task",
        AsyncMock(
            return_value=GenerationResult(
                success=True,
                content=output_marker,
                tokens_input=4,
                tokens_output=5,
                model_name="safe-model",
            )
        ),
    )
    task_payload = LLMTaskPayload(
        generation_payload={
            "session_id": str(uuid.uuid4()),
            "query_text": query_marker,
            "conversation_history": [
                {"role": "user", "content": history_marker},
            ],
        }
    )

    result = await llm_tasks.generate_llm_nonstream_task.original_func(
        task_payload.model_dump(mode="json")
    )

    telemetry_arguments = repr((generation_calls, recorder_calls))
    assert result.content == output_marker
    assert query_marker not in telemetry_arguments
    assert history_marker not in telemetry_arguments
    assert output_marker not in telemetry_arguments
    assert set(generation_calls[0]) == {"name", "model", "metadata"}
    assert "output" not in recorder_calls[0]


async def test_stream_task_telemetry_omits_synthetic_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query_marker = "stream-query-secret-AKIA1111111111111111"
    history_marker = "stream-history-pii-13812345678"
    output_marker = "stream-output-secret-value"
    generation_calls: list[dict[str, object]] = []
    recorder_calls: list[dict[str, object]] = []

    class FakeRecorder:
        def record(self, **kwargs: object) -> None:
            recorder_calls.append(kwargs)

    @contextmanager
    def fake_generation(**kwargs: object):
        generation_calls.append(kwargs)
        yield FakeRecorder()

    monkeypatch.setattr(llm_tasks, "use_trace_context", _noop_context)
    monkeypatch.setattr(llm_tasks, "set_langfuse_trace_metadata", _noop_context)
    monkeypatch.setattr(llm_tasks, "langfuse_generation", fake_generation)
    monkeypatch.setattr(
        llm_tasks,
        "_generate_llm_stream_task",
        AsyncMock(
            return_value=StreamGenerationResult(
                success=True,
                output=output_marker,
                tokens_input=4,
                tokens_output=5,
                model_name="safe-model",
            )
        ),
    )
    task_payload = LLMTaskPayload(
        generation_payload={
            "session_id": str(uuid.uuid4()),
            "query_text": query_marker,
            "conversation_history": [
                {"role": "user", "content": history_marker},
            ],
        },
        channel="stream:content-safety",
    )

    await llm_tasks.generate_llm_stream_task.original_func(
        task_payload.model_dump(mode="json")
    )

    telemetry_arguments = repr((generation_calls, recorder_calls))
    assert query_marker not in telemetry_arguments
    assert history_marker not in telemetry_arguments
    assert output_marker not in telemetry_arguments
    assert set(generation_calls[0]) == {"name", "model", "metadata"}
    assert "output" not in recorder_calls[0]
