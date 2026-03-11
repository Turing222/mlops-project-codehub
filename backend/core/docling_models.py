from docling.chunking import HierarchicalChunker
from docling.document_converter import DocumentConverter


class DoclingModelFactory:
    """Lazily-initialized Docling runtime models."""

    _converter: DocumentConverter | None = None
    _chunker: HierarchicalChunker | None = None

    @classmethod
    def get_converter(cls) -> DocumentConverter:
        if cls._converter is None:
            cls._converter = DocumentConverter()
        return cls._converter

    @classmethod
    def get_hierarchical_chunker(cls) -> HierarchicalChunker:
        if cls._chunker is None:
            cls._chunker = HierarchicalChunker()
        return cls._chunker
