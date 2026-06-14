"""Citation marker validation and cleaning.

职责：从 LLM 输出中提取引用标记、校验其是否存在于合法 ref_id 集合，移除非法标记。
边界：本模块只做正则提取与字符串替换，不查询数据库、不调用 LLM、不修改 search_context。
风险：正则仅匹配 [R\\d+(\\.\\d+)?] / [W\\d+(\\.\\d+)?] 格式；其他引用格式不会被处理。
"""

import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[([RW])(\d+)(?:\.(\d+))?\]")


@dataclass(frozen=True, slots=True)
class CitationResult:
    """Citation validation result."""

    cleaned_content: str
    total_citations: int
    removed_count: int
    valid_ref_ids: frozenset[str]


def extract_valid_ref_ids(search_context: dict) -> set[str]:
    """Extract all valid ref_ids from a search_context dict."""
    ref_ids: set[str] = set()
    for group in search_context.get("refs", []):
        group_ref = group.get("ref_id")
        if group_ref:
            ref_ids.add(group_ref)
        for chunk in group.get("chunks", []):
            chunk_ref = chunk.get("ref_id")
            if chunk_ref:
                ref_ids.add(chunk_ref)
    for chunk in search_context.get("chunks", []):
        chunk_ref = chunk.get("ref_id")
        if chunk_ref:
            ref_ids.add(chunk_ref)
    return ref_ids


def _match_to_ref_id(match: re.Match[str]) -> str:
    """Convert a regex match like [R1.1] or [W1] to a ref_id string."""
    ref_id = f"{match.group(1)}{match.group(2)}"
    if match.group(3) is not None:
        ref_id = f"{ref_id}.{match.group(3)}"
    return ref_id


def _clean_markers(text: str, valid_ref_ids: set[str]) -> str:
    """Remove invalid citation markers from text with only complete markers."""
    if not text:
        return text
    matches = list(_CITATION_RE.finditer(text))
    if not matches:
        return text
    segments: list[str] = []
    last_end = 0
    for match in matches:
        segments.append(text[last_end : match.start()])
        if _match_to_ref_id(match) in valid_ref_ids:
            segments.append(match.group(0))
        last_end = match.end()
    segments.append(text[last_end:])
    return "".join(segments)


def validate_citations(content: str, valid_ref_ids: set[str]) -> CitationResult:
    """Remove citation markers from content that are not in valid_ref_ids."""
    if not content or not valid_ref_ids:
        return CitationResult(
            cleaned_content=content,
            total_citations=0,
            removed_count=0,
            valid_ref_ids=frozenset(valid_ref_ids),
        )

    matches = list(_CITATION_RE.finditer(content))
    if not matches:
        return CitationResult(
            cleaned_content=content,
            total_citations=0,
            removed_count=0,
            valid_ref_ids=frozenset(valid_ref_ids),
        )

    total = len(matches)
    segments: list[str] = []
    last_end = 0
    removed = 0
    for match in matches:
        segments.append(content[last_end : match.start()])
        if _match_to_ref_id(match) in valid_ref_ids:
            segments.append(match.group(0))
        else:
            removed += 1
        last_end = match.end()
    segments.append(content[last_end:])

    return CitationResult(
        cleaned_content="".join(segments),
        total_citations=total,
        removed_count=removed,
        valid_ref_ids=frozenset(valid_ref_ids),
    )


class StreamingCitationFilter:
    """Chunk-by-chunk citation filter with a short buffer for split markers."""

    _MAX_BRACKET_LEN = 10  # len("[R99.99]") = 8, add margin
    _PARTIAL_PREFIX_RE = re.compile(r"^\[[RW]\d*(?:\.\d*)?$")

    def __init__(self, valid_ref_ids: set[str]) -> None:
        self._valid = valid_ref_ids
        self._buffer = ""

    def push(self, chunk: str) -> str | None:
        """Process an incoming chunk; return cleaned text ready to publish.

        Returns None when the chunk is absorbed into the buffer (waiting for
        the rest of a split marker). Otherwise returns the cleaned text.
        """
        if not self._valid:
            return chunk

        combined = self._buffer + chunk
        self._buffer = ""

        split_pos = self._find_potential_split(combined)
        if split_pos is not None:
            ready_part = combined[:split_pos]
            self._buffer = combined[split_pos:]
            return _clean_markers(ready_part, self._valid) if ready_part else None

        return _clean_markers(combined, self._valid)

    def flush(self) -> str:
        """Flush any remaining buffered text. Call after the last chunk."""
        if not self._buffer:
            return ""
        remaining = self._buffer
        self._buffer = ""
        return _clean_markers(remaining, self._valid)

    def _find_potential_split(self, text: str) -> int | None:
        """Return start position of a potential incomplete marker at text tail.

        An incomplete marker is a trailing substring starting with '[' that
        could become [R\\d+(\\.\\d+)?] when more chunks arrive.
        Returns None if the tail looks complete.
        """
        bracket_pos = text.rfind("[")
        if bracket_pos == -1:
            return None
        tail = text[bracket_pos:]
        tail_len = len(tail)

        if tail_len > self._MAX_BRACKET_LEN:
            return None

        if "]" in tail:
            return None

        if self._PARTIAL_PREFIX_RE.match(tail):
            return bracket_pos

        return None
