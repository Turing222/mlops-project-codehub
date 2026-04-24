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


def test_extract_chunks_uses_lightweight_pdf_channel(monkeypatch, tmp_path):
    chunking = FakeChunkingService(chunk_size=10)
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.pdf"
    file_path.write_text("fake", encoding="utf-8")

    class FakeTextPage:
        def __init__(self, text: str):
            self.text = text

        def get_text_range(self) -> str:
            return self.text

        def close(self) -> None:
            pass

    class FakePage:
        def __init__(self, text: str):
            self.text = text

        def get_textpage(self) -> FakeTextPage:
            return FakeTextPage(self.text)

        def close(self) -> None:
            pass

    class FakePdfDocument:
        def __init__(self, _: object):
            self.pages = [FakePage("0123456789ABC"), FakePage("short")]

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def __len__(self) -> int:
            return len(self.pages)

        def __getitem__(self, index: int) -> FakePage:
            return self.pages[index]

    monkeypatch.setattr(
        "backend.workflow.knowledge_rag_workflow.pdfium.PdfDocument",
        FakePdfDocument,
    )

    chunks = workflow._extract_chunks(file_path)

    assert chunks == ["0123456789", "ABC\n\nshort"]
    assert chunking.split_calls == ["0123456789ABC\n\nshort"]


def test_extract_chunks_rejects_docx_without_structured_parser(tmp_path):
    chunking = FakeChunkingService()
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.docx"
    file_path.write_text("fake", encoding="utf-8")

    with pytest.raises(ValidationError):
        workflow._extract_chunks(file_path)


def test_extract_chunks_rejects_unsupported_file_suffix(tmp_path):
    chunking = FakeChunkingService()
    workflow = make_workflow(chunking)
    file_path = tmp_path / "demo.bin"
    file_path.write_text("fake", encoding="utf-8")

    with pytest.raises(ValidationError):
        workflow._extract_chunks(file_path)
