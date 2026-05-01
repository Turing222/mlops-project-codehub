from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    args = parse_args()
    print("--- AI environment check ---")

    llm_ok = check_llm(live=args.live, prompt=args.prompt)
    embedding_ok = check_embedding(live=args.live, text=args.embedding_text)
    langfuse_ok = check_langfuse(live=args.live)
    check_pdf_parser()

    if not all((llm_ok, embedding_ok, langfuse_ok)):
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate configured LLM, embedding, Langfuse, and parser wiring."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Perform real network calls to the configured AI providers.",
    )
    parser.add_argument(
        "--prompt",
        default="请只回复 OK。",
        help="Prompt used for the live LLM check.",
    )
    parser.add_argument(
        "--embedding-text",
        default="MLOps smoke embedding check",
        help="Text used for the live embedding check.",
    )
    return parser.parse_args()


def check_llm(*, live: bool, prompt: str) -> bool:
    from backend.config.llm import get_llm_model_config
    from backend.config.settings import settings

    try:
        profile = get_llm_model_config().resolve_profile(settings.LLM_PROVIDER)
        print(
            "LLM profile: resolved "
            f"(profile={profile.name}, provider={profile.provider}, model={profile.model})"
        )
        if profile.provider.strip().lower() != "mock" and not profile.resolve_api_key():
            raise RuntimeError(
                "missing API key; expected one of "
                f"{', '.join(profile.api_key_envs) or '(none configured)'}"
            )
        if live:
            result = asyncio.run(_run_llm_live_check(prompt))
            print(
                "LLM live call: ok "
                f"(chars={len(result.content)}, latency_ms={result.latency_ms})"
            )
        return True
    except Exception as exc:
        print(f"LLM config failed: {exc}")
        return False


async def _run_llm_live_check(prompt: str):
    from backend.ai.providers.llm.factory import LLMProviderFactory
    from backend.config.settings import settings
    from backend.models.schemas.chat_schema import LLMQueryDTO

    service = LLMProviderFactory.create(settings.LLM_PROVIDER)
    return await service.generate_response(
        LLMQueryDTO(
            session_id=uuid.uuid4(),
            query_text=prompt,
            conversation_history=[{"role": "user", "content": prompt}],
        )
    )


def check_embedding(*, live: bool, text: str) -> bool:
    from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
    from backend.config.llm import get_llm_model_config
    from backend.config.settings import settings

    try:
        profile = get_llm_model_config().resolve_embedding_profile(
            settings.RAG_EMBED_PROVIDER
        )
        print(
            "Embedding profile: resolved "
            f"(profile={profile.name}, provider={profile.provider}, "
            f"model={profile.model}, dimensions={profile.dimensions})"
        )
        if profile.provider.strip().lower() != "mock" and not profile.resolve_api_key():
            raise RuntimeError(
                "missing API key; expected one of "
                f"{', '.join(profile.api_key_envs) or '(none configured)'}"
            )

        embedder = RAGEmbedderFactory.create(
            provider=profile.provider,
            model_name=profile.model,
            base_url=profile.resolve_base_url(),
            api_key=profile.resolve_api_key(),
            dimensions=profile.dimensions,
        )
        if live:
            vector = embedder.encode_query(text)
            print(f"Embedding live call: ok (dim={len(vector)})")
        else:
            print("Embedding client: initialized")
        return True
    except Exception as exc:
        print(f"Embedding config failed: {exc}")
        return False


def check_langfuse(*, live: bool) -> bool:
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    base_url = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    if not public_key and not secret_key:
        print("Langfuse: not configured")
        return True
    if not public_key or not secret_key:
        print(
            "Langfuse config failed: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are both required"
        )
        return False

    print(f"Langfuse: configured (base_url={base_url})")
    if not live:
        return True

    try:
        from langfuse import get_client

        client = get_client()
        if not client.auth_check():
            raise RuntimeError("auth_check returned false")
        print("Langfuse live auth: ok")
        return True
    except Exception as exc:
        print(f"Langfuse live auth failed: {exc}")
        return False


def check_pdf_parser() -> None:
    try:
        import pypdfium2 as pdfium

        print(f"PDF parser: pypdfium2 {pdfium.version.PYPDFIUM_INFO}")
    except Exception as exc:
        print(f"PDF parser failed: {exc}")


if __name__ == "__main__":
    main()
