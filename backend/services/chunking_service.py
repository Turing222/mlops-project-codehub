class ChunkingService:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 120):
        self.chunk_size = max(200, chunk_size)
        self.chunk_overlap = max(0, min(chunk_overlap, self.chunk_size // 2))

    def split_text(self, text: str) -> list[str]:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(normalized)

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            if end < text_len:
                candidates = [
                    normalized.rfind("\n\n", start, end),
                    normalized.rfind("\n", start, end),
                    normalized.rfind("。", start, end),
                    normalized.rfind(".", start, end),
                    normalized.rfind(" ", start, end),
                ]
                boundary = max(candidates)
                if boundary > start + self.chunk_size // 2:
                    end = boundary + 1

            piece = normalized[start:end].strip()
            if piece:
                chunks.append(piece)

            if end >= text_len:
                break
            next_start = max(0, end - self.chunk_overlap)
            if next_start <= start:
                next_start = end
            start = next_start

        return chunks
