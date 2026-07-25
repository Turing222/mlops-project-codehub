"""Provider reasoning removal at the Chat application boundary.

职责：在 provider 文本进入 SSE、普通持久化或 telemetry 前移除 `<think>` 区段。
边界：只处理 provider 文本协议，不记录或返回被移除的 reasoning。
副作用：无。
"""

from __future__ import annotations

_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"


def _trailing_tag_prefix_length(value: str, tag: str) -> int:
    lowered = value.lower()
    for size in range(min(len(value), len(tag) - 1), 0, -1):
        if lowered.endswith(tag[:size]):
            return size
    return 0


class StreamingReasoningFilter:
    """Strip `<think>...</think>` safely across arbitrary chunk boundaries."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_reasoning = False
        self.saw_reasoning = False

    @property
    def in_reasoning(self) -> bool:
        return self._in_reasoning

    def push(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buffer += chunk
        visible: list[str] = []

        while self._buffer:
            lowered = self._buffer.lower()
            if self._in_reasoning:
                close_at = lowered.find(_CLOSE_TAG)
                if close_at < 0:
                    keep = _trailing_tag_prefix_length(self._buffer, _CLOSE_TAG)
                    self._buffer = self._buffer[-keep:] if keep else ""
                    break
                self._buffer = self._buffer[close_at + len(_CLOSE_TAG) :]
                self._in_reasoning = False
                continue

            open_at = lowered.find(_OPEN_TAG)
            stray_close_at = lowered.find(_CLOSE_TAG)
            if stray_close_at >= 0 and (open_at < 0 or stray_close_at < open_at):
                visible.append(self._buffer[:stray_close_at])
                self._buffer = self._buffer[stray_close_at + len(_CLOSE_TAG) :]
                continue
            if open_at >= 0:
                visible.append(self._buffer[:open_at])
                self._buffer = self._buffer[open_at + len(_OPEN_TAG) :]
                self._in_reasoning = True
                self.saw_reasoning = True
                continue

            keep = max(
                _trailing_tag_prefix_length(self._buffer, _OPEN_TAG),
                _trailing_tag_prefix_length(self._buffer, _CLOSE_TAG),
            )
            if keep:
                visible.append(self._buffer[:-keep])
                self._buffer = self._buffer[-keep:]
            else:
                visible.append(self._buffer)
                self._buffer = ""
            break

        return "".join(visible)

    def finish(self) -> str:
        if self._in_reasoning:
            self._buffer = ""
            return ""
        visible = self._buffer
        self._buffer = ""
        return visible


def strip_provider_reasoning(content: str) -> str:
    reasoning_filter = StreamingReasoningFilter()
    return reasoning_filter.push(content) + reasoning_filter.finish()
