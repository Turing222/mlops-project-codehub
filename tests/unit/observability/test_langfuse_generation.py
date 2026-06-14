"""Tests for langfuse_generation context manager and _LangfuseGenerationRecorder."""

from unittest.mock import MagicMock, patch

import pytest

from backend.observability import langfuse_utils
from backend.observability.langfuse_utils import langfuse_generation


def _mock_langfuse_context():
    """构建 mock Langfuse generation context manager。"""
    mock_generation = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_generation)
    mock_cm.__exit__ = MagicMock(return_value=False)
    mock_client = MagicMock()
    mock_client.start_as_current_generation.return_value = mock_cm
    return mock_client, mock_generation


def test_langfuse_generation_yields_recorder():
    mock_client, mock_generation = _mock_langfuse_context()
    with (
        patch("langfuse.get_client", return_value=mock_client),
        langfuse_generation(name="test", input_payload="hello") as recorder,
    ):
        recorder.record(
            output="world",
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
            model="gemini-2.0-flash",
        )
    mock_generation.update.assert_called_once_with(
        output="world",
        usage_details={
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
        model="gemini-2.0-flash",
    )


def test_langfuse_generation_records_error_on_exception():
    mock_client, mock_generation = _mock_langfuse_context()
    with (
        patch("langfuse.get_client", return_value=mock_client),
        pytest.raises(ValueError, match="boom"),
        langfuse_generation(name="test") as _recorder,
    ):
        raise ValueError("boom")
    mock_generation.update.assert_called_once_with(
        status_message="boom",
        level="ERROR",
    )


def test_langfuse_generation_passes_model_and_metadata():
    mock_client, mock_generation = _mock_langfuse_context()
    with (
        patch("langfuse.get_client", return_value=mock_client),
        langfuse_generation(
            name="test", model="gpt-4", metadata={"key": "value"}
        ) as _recorder,
    ):
        pass
    mock_client.start_as_current_generation.assert_called_once_with(
        name="test", model="gpt-4", metadata={"key": "value"}
    )


def test_langfuse_generation_record_noop():
    mock_client, mock_generation = _mock_langfuse_context()
    with (
        patch("langfuse.get_client", return_value=mock_client),
        langfuse_generation(name="test") as recorder,
    ):
        recorder.record()
    mock_generation.update.assert_not_called()


def test_init_langfuse_client_can_retry_after_client_init_failure(monkeypatch):
    class FailingLangfuse:
        def __init__(self, **kwargs):
            raise RuntimeError("missing key")

    monkeypatch.setattr(langfuse_utils, "_langfuse_filter_installed", False)

    with patch("langfuse.Langfuse", FailingLangfuse):
        langfuse_utils.init_langfuse_client()

    assert langfuse_utils._langfuse_filter_installed is False
