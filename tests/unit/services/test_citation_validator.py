"""Citation validator unit tests.

职责：验证 validate_citations、extract_valid_ref_ids 和 StreamingCitationFilter 的
正则提取、无效标记移除、search_context 遍历和流式 chunk 过滤逻辑；
边界：不测试 workflow 集成（由 test_worker_generation_workflow.py 覆盖）。
"""

from backend.services.citation_validator import (
    StreamingCitationFilter,
    extract_valid_ref_ids,
    validate_citations,
)

# ── validate_citations ────────────────────────────────────────────


class TestValidateCitations:
    def test_no_citations_returns_unchanged(self) -> None:
        result = validate_citations("hello world", {"R1.1"})
        assert result.cleaned_content == "hello world"
        assert result.total_citations == 0
        assert result.removed_count == 0

    def test_all_citations_valid_returns_unchanged(self) -> None:
        content = "text [R1.1] more [R2.1] end"
        valid = {"R1.1", "R2.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == content
        assert result.total_citations == 2
        assert result.removed_count == 0

    def test_removes_invalid_citation(self) -> None:
        content = "text [R1.1] more [R9.1] end"
        valid = {"R1.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == "text [R1.1] more  end"
        assert result.total_citations == 2
        assert result.removed_count == 1

    def test_removes_all_citations_when_none_valid(self) -> None:
        content = "text [R1.1] more [R2.1] end"
        valid = {"R5.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == "text  more  end"
        assert result.total_citations == 2
        assert result.removed_count == 2

    def test_empty_content_returns_empty(self) -> None:
        result = validate_citations("", {"R1.1"})
        assert result.cleaned_content == ""
        assert result.total_citations == 0
        assert result.removed_count == 0

    def test_empty_valid_ref_ids_returns_unchanged(self) -> None:
        content = "text [R1.1] more"
        result = validate_citations(content, set())
        assert result.cleaned_content == content
        assert result.total_citations == 0
        assert result.removed_count == 0

    def test_adjacent_invalid_markers_removed_cleanly(self) -> None:
        content = "text [R9.1][R9.2] end"
        valid = {"R1.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == "text  end"

    def test_group_level_marker_validated(self) -> None:
        content = "summary [R1] and detail [R1.1]"
        valid = {"R1", "R1.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == content
        assert result.total_citations == 2
        assert result.removed_count == 0

    def test_group_level_marker_removed_when_invalid(self) -> None:
        content = "summary [R5] and detail [R1.1]"
        valid = {"R1.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == "summary  and detail [R1.1]"
        assert result.removed_count == 1

    def test_mixed_valid_invalid_in_same_sentence(self) -> None:
        content = "a [R1.1] b [R9.1] c [R2.1] d [R8.1] e"
        valid = {"R1.1", "R2.1"}
        result = validate_citations(content, valid)
        assert result.cleaned_content == "a [R1.1] b  c [R2.1] d  e"
        assert result.total_citations == 4
        assert result.removed_count == 2

    def test_valid_ref_ids_preserved_in_result(self) -> None:
        valid = {"R1.1", "R2.1"}
        result = validate_citations("text [R1.1]", valid)
        assert result.valid_ref_ids == frozenset(valid)

    def test_web_marker_validated(self) -> None:
        content = "fresh fact [W1] stale fact [W9]"
        result = validate_citations(content, {"W1"})
        assert result.cleaned_content == "fresh fact [W1] stale fact "
        assert result.total_citations == 2
        assert result.removed_count == 1


# ── extract_valid_ref_ids ─────────────────────────────────────────


class TestExtractValidRefIds:
    def test_extracts_from_refs_and_chunks(self) -> None:
        search_context = {
            "refs": [
                {
                    "ref_id": "R1",
                    "chunks": [
                        {"ref_id": "R1.1"},
                        {"ref_id": "R1.2"},
                    ],
                },
                {
                    "ref_id": "R2",
                    "chunks": [
                        {"ref_id": "R2.1"},
                    ],
                },
                {
                    "ref_id": "W1",
                    "chunks": [
                        {"ref_id": "W1"},
                    ],
                },
            ],
            "chunks": [
                {"ref_id": "R1.1"},
                {"ref_id": "R1.2"},
                {"ref_id": "R2.1"},
                {"ref_id": "W1"},
            ],
        }
        result = extract_valid_ref_ids(search_context)
        assert result == {"R1", "R1.1", "R1.2", "R2", "R2.1", "W1"}

    def test_empty_refs_returns_empty(self) -> None:
        search_context = {"refs": [], "chunks": []}
        result = extract_valid_ref_ids(search_context)
        assert result == set()

    def test_missing_chunks_key_still_works(self) -> None:
        search_context = {
            "refs": [
                {"ref_id": "R1", "chunks": [{"ref_id": "R1.1"}]},
            ],
        }
        result = extract_valid_ref_ids(search_context)
        assert result == {"R1", "R1.1"}

    def test_missing_refs_key_still_works(self) -> None:
        search_context = {
            "chunks": [
                {"ref_id": "R1.1"},
            ],
        }
        result = extract_valid_ref_ids(search_context)
        assert result == {"R1.1"}

    def test_missing_ref_id_fields_handled_gracefully(self) -> None:
        search_context = {
            "refs": [
                {"chunks": [{"ref_id": "R1.1"}, {"other": "val"}]},
                {"ref_id": None},
            ],
            "chunks": [{"ref_id": None}],
        }
        result = extract_valid_ref_ids(search_context)
        assert result == {"R1.1"}


# ── StreamingCitationFilter ────────────────────────────────────────


class TestStreamingCitationFilter:
    def _collect(self, chunks: list[str], valid: set[str]) -> list[str]:
        """Push all chunks through the filter and return list of published strings."""
        filt = StreamingCitationFilter(valid)
        published: list[str] = []
        for chunk in chunks:
            result = filt.push(chunk)
            if result is not None:
                published.append(result)
        remaining = filt.flush()
        if remaining:
            published.append(remaining)
        return published

    def test_simple_chunk_passes_through(self) -> None:
        result = self._collect(["hello world"], {"R1.1"})
        assert result == ["hello world"]

    def test_invalid_marker_removed_from_single_chunk(self) -> None:
        result = self._collect(["text [R9.1] end"], {"R1.1"})
        assert result == ["text  end"]

    def test_valid_marker_kept_in_single_chunk(self) -> None:
        result = self._collect(["text [R1.1] end"], {"R1.1"})
        assert result == ["text [R1.1] end"]

    def test_multiple_chunks_each_cleaned(self) -> None:
        result = self._collect(["text [R1.1] ", "more [R9.1] end"], {"R1.1"})
        assert result == ["text [R1.1] ", "more  end"]

    def test_split_marker_buffered_then_released(self) -> None:
        """[R1.1] split as '[R1.' + '1]' — first chunk buffered, second completes it."""
        result = self._collect(["text [R1.", "1] end"], {"R1.1"})
        assert "".join(result) == "text [R1.1] end"

    def test_split_invalid_marker_removed(self) -> None:
        """[R9.1] split as '[R9.' + '1]' — invalid, should be removed."""
        result = self._collect(["text [R9.", "1] end"], {"R1.1"})
        assert "".join(result) == "text  end"

    def test_non_citation_bracket_not_buffered(self) -> None:
        """'[hello]' is not a citation pattern — should not be buffered."""
        result = self._collect(["text [hello", "] world"], {"R1.1"})
        assert result == ["text [hello", "] world"]

    def test_empty_valid_ref_ids_passes_through(self) -> None:
        result = self._collect(["text [R1.1] end"], set())
        assert result == ["text [R1.1] end"]

    def test_flush_releases_remaining_buffer(self) -> None:
        """Stream ends mid-marker — flush should release the buffered text as-is."""
        filt = StreamingCitationFilter({"R1.1"})
        out = filt.push("text [R1.")
        assert out == "text "
        remaining = filt.flush()
        assert remaining == "[R1."

    def test_multiple_markers_in_one_chunk(self) -> None:
        result = self._collect(["[R1.1] and [R9.1]"], {"R1.1"})
        assert result == ["[R1.1] and "]

    def test_group_level_marker_in_stream(self) -> None:
        result = self._collect(["summary [R1] detail [R1.1]"], {"R1", "R1.1"})
        assert result == ["summary [R1] detail [R1.1]"]

    def test_web_marker_in_stream(self) -> None:
        result = self._collect(["fresh [W1] stale [W9]"], {"W1"})
        assert result == ["fresh [W1] stale "]
