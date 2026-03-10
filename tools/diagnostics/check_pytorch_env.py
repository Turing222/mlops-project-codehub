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
        from sentence_transformers import SentenceTransformer

        SentenceTransformer("BAAI/bge-base-zh-v1.5", device=device)
        print("Sentence-Transformers: loaded")
    except Exception as exc:
        print(f"Sentence-Transformers failed: {exc}")

    try:
        from docling.document_converter import DocumentConverter

        DocumentConverter()
        print("Docling: initialized")
    except Exception as exc:
        print(f"Docling failed: {exc}")


if __name__ == "__main__":
    check_env()
