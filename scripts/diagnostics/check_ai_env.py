from backend.core.config import settings


def check_env() -> None:
    print("--- AI environment check ---")

    try:
        if settings.RAG_EMBED_PROVIDER.strip().lower() in {
            "google",
            "gemini",
            "google-genai",
        }:
            from google import genai

            api_key = (
                settings.RAG_EMBED_API_KEY
                or settings.GEMINI_API_KEY
                or settings.GOOGLE_API_KEY
            )
            if not api_key:
                raise RuntimeError(
                    "missing RAG_EMBED_API_KEY/GEMINI_API_KEY/GOOGLE_API_KEY"
                )
            genai.Client(api_key=api_key)
        else:
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
        import pypdfium2 as pdfium

        print(f"PDF parser: pypdfium2 {pdfium.version.PYPDFIUM_INFO}")
    except Exception as exc:
        print(f"PDF parser failed: {exc}")


if __name__ == "__main__":
    check_env()
