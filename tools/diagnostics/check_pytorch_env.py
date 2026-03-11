from backend.core.config import settings


def check_env() -> None:
    print("--- Environment check ---")

    try:
        import torch
    except Exception as exc:
        print(f"torch import failed: {exc}")
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Detected device: {device}")

    try:
        import openai

        base_url = settings.RAG_EMBED_BASE_URL or settings.LLM_BASE_URL
        api_key = settings.RAG_EMBED_API_KEY or settings.LLM_API_KEY
        if not base_url or not api_key:
            raise RuntimeError("missing base_url/api_key")

        openai.OpenAI(base_url=base_url, api_key=api_key)
        print(
            "Embedding API client: initialized "
            f"(provider={settings.RAG_EMBED_PROVIDER}, model={settings.RAG_EMBED_MODEL_NAME})"
        )
    except Exception as exc:
        print(f"Embedding API config failed: {exc}")

    try:
        from docling.chunking import HierarchicalChunker
        from docling.document_converter import DocumentConverter

        DocumentConverter()
        HierarchicalChunker()
        print("Docling: converter + hierarchical chunker initialized")
    except Exception as exc:
        print(f"Docling failed: {exc}")


if __name__ == "__main__":
    check_env()
