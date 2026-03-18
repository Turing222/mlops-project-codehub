from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.core.exceptions import ValidationError
from backend.workflow.knowledge_rag_workflow import KnowledgeRAGWorkflow


class FakeChunkingService:
    def __init__(self, chunk_size: int = 10):
        self.chunk_size = chunk_size
        self.split_calls: list[str] = []

    def split_text(self, text: str) -> list[str]:
        self.split_calls.append(text)
        if len(text) <= self.chunk_size:
            return [text]
        return [text[: self.chunk_size], text[self.chunk_size :]]


def make_workflow(chunking_service: FakeChunkingService) -> KnowledgeRAGWorkflow:
    return KnowledgeRAGWorkflow(
        knowledge_service=MagicMock(),
        chunking_service=chunking_service,
        vector_index_service=MagicMock(),
    )


def test_extract_chunks_uses_plain_text_channel(tmp_path):
    chunking = FakeChunkingService(chunk_size=10)
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.txt"
    file_path.write_text("plain content", encoding="utf-8")

    chunks = workflow._extract_chunks(file_path)

    assert chunks == ["plain cont", "ent"]
    assert chunking.split_calls == ["plain content"]


def test_extract_chunks_uses_docling_hierarchical_channel(monkeypatch, tmp_path):
    chunking = FakeChunkingService(chunk_size=10)
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.pdf"
    file_path.write_text("fake", encoding="utf-8")

    class FakeConverter:
        def convert(self, _: str):
            return SimpleNamespace(document=object())

    class FakeChunker:
        def chunk(self, *, dl_doc: object):
            _ = dl_doc
            return iter(["0123456789ABC", "short"])

        def contextualize(self, chunk: str) -> str:
            return chunk

    monkeypatch.setattr(
        "backend.workflow.knowledge_rag_workflow.DoclingModelFactory.get_converter",
        lambda: FakeConverter(),
    )
    monkeypatch.setattr(
        (
            "backend.workflow."
            "knowledge_rag_workflow.DoclingModelFactory.get_hierarchical_chunker"
        ),
        lambda: FakeChunker(),
    )

    chunks = workflow._extract_chunks(file_path)

    assert chunks == ["0123456789", "ABC", "short"]
    assert chunking.split_calls == ["0123456789ABC"]


def test_extract_chunks_docling_fallbacks_to_exported_text(monkeypatch, tmp_path):
    chunking = FakeChunkingService(chunk_size=20)
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.docx"
    file_path.write_text("fake", encoding="utf-8")

    class FakeDocument:
        def export_to_markdown(self) -> str:
            return "fallback markdown"

    class FakeConverter:
        def convert(self, _: str):
            return SimpleNamespace(document=FakeDocument())

    class FakeChunker:
        def chunk(self, *, dl_doc: object):
            _ = dl_doc
            return iter([])

        def contextualize(self, chunk: str) -> str:
            return chunk

    monkeypatch.setattr(
        "backend.workflow.knowledge_rag_workflow.DoclingModelFactory.get_converter",
        lambda: FakeConverter(),
    )
    monkeypatch.setattr(
        (
            "backend.workflow."
            "knowledge_rag_workflow.DoclingModelFactory.get_hierarchical_chunker"
        ),
        lambda: FakeChunker(),
    )

    chunks = workflow._extract_chunks(file_path)

    assert chunks == ["fallback markdown"]
    assert chunking.split_calls == ["fallback markdown"]


def test_extract_chunks_rejects_unsupported_file_suffix(tmp_path):
    chunking = FakeChunkingService()
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.bin"
    file_path.write_text("fake", encoding="utf-8")

    with pytest.raises(ValidationError):
        workflow._extract_chunks(file_path)
