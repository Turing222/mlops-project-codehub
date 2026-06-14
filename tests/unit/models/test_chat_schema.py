"""Chat schema unit tests.

职责：验证 QuerySentRequest extra_body 字段的接受和拒绝行为；边界：直接调用 Pydantic model_validate，不启动 FastAPI；副作用：无。
"""

import pytest
from pydantic import ValidationError

from backend.models.schemas.chat.api import QuerySentRequest


def test_extra_body_accepts_thinking_mode() -> None:
    request = QuerySentRequest.model_validate(
        {
            "query": "你好",
            "extra_body": {"thinking": {"type": "disabled"}},
        }
    )

    assert request.extra_body is not None
    assert request.extra_body.to_provider_dict() == {"thinking": {"type": "disabled"}}


def test_extra_body_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        QuerySentRequest.model_validate(
            {
                "query": "你好",
                "extra_body": {"temperature": 0.7},
            }
        )


def test_context_mode_accepts_known_values() -> None:
    request = QuerySentRequest.model_validate(
        {
            "query": "需要最新资料吗",
            "context_mode": "auto",
        }
    )

    assert request.context_mode == "auto"


def test_context_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        QuerySentRequest.model_validate(
            {
                "query": "你好",
                "context_mode": "everything",
            }
        )
