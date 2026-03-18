import uuid
from unittest.mock import MagicMock

from backend.core.config import settings
from backend.workflow.chat_nonstream_workflow import ChatNonStreamWorkflow


def _build_workflow() -> ChatNonStreamWorkflow:
    return ChatNonStreamWorkflow(
        uow=MagicMock(),
        llm_service=MagicMock(),
    )


def test_prepare_memory_context_excludes_current_query(monkeypatch):
    workflow = _build_workflow()
    monkeypatch.setattr(settings, "CHAT_MEMORY_RECENT_ROUNDS", 6)

    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我在。"},
        {"role": "user", "content": "本轮问题"},
    ]

    recent_history, summary_text = workflow._prepare_memory_context(
        history,
        current_query="本轮问题",
    )

    assert summary_text == ""
    assert recent_history == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，我在。"},
    ]


def test_prepare_memory_context_splits_recent_rounds_and_summary(monkeypatch):
    workflow = _build_workflow()
    monkeypatch.setattr(settings, "CHAT_MEMORY_RECENT_ROUNDS", 1)
    monkeypatch.setattr(settings, "CHAT_MEMORY_SNIPPET_CHARS", 60)
    monkeypatch.setattr(settings, "CHAT_MEMORY_SUMMARY_MAX_CHARS", 1000)

    history = [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "user", "content": "第二轮问题"},
        {"role": "assistant", "content": "第二轮回答"},
        {"role": "user", "content": "第三轮问题"},
    ]

    recent_history, summary_text = workflow._prepare_memory_context(
        history,
        current_query="第三轮问题",
    )

    assert recent_history == [
        {"role": "user", "content": "第二轮问题"},
        {"role": "assistant", "content": "第二轮回答"},
    ]
    assert "第一轮问题" in summary_text
    assert "第一轮回答" in summary_text
    assert "第二轮问题" not in summary_text


def test_build_rounds_summary_respects_max_chars(monkeypatch):
    workflow = _build_workflow()
    monkeypatch.setattr(settings, "CHAT_MEMORY_SNIPPET_CHARS", 200)
    monkeypatch.setattr(settings, "CHAT_MEMORY_SUMMARY_MAX_CHARS", 80)

    rounds = [
        [
            {"role": "user", "content": f"U{i}-{uuid.uuid4()}"},
            {"role": "assistant", "content": f"A{i}-{uuid.uuid4()}"},
        ]
        for i in range(4)
    ]

    summary_text = workflow._build_rounds_summary(rounds)

    assert len(summary_text) <= 80
    assert summary_text != ""
