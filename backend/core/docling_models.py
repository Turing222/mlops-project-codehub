from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docling.chunking import HierarchicalChunker
    from docling.document_converter import DocumentConverter


class DoclingModelFactory:
    """Lazily-initialized Docling runtime models."""

    _converter: DocumentConverter | None = None
    _chunker: HierarchicalChunker | None = None

    @classmethod
    def get_converter(cls) -> DocumentConverter:
        if cls._converter is None:
            from docling.document_converter import DocumentConverter

            cls._converter = DocumentConverter()
        return cls._converter

    @classmethod
    def get_hierarchical_chunker(cls) -> HierarchicalChunker:
        if cls._chunker is None:
            from docling.chunking import HierarchicalChunker

            cls._chunker = HierarchicalChunker()
        return cls._chunker
