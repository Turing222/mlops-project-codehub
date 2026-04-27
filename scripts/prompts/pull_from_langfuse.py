from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from langfuse import get_client

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backend.core.secret_env  # noqa: E402,F401
from backend.config.llm import PromptConfig, load_prompt_config  # noqa: E402


def main() -> None:
    args = parse_args()
    prompt_config = load_prompt_config(config_dir=args.config_dir)
    label = args.label or prompt_config.source.label
    output_path = resolve_path(args.output or prompt_config.source.cache_path)
    ttl_seconds = args.ttl_seconds
    if ttl_seconds is None:
        ttl_seconds = prompt_config.source.ttl_seconds

    if should_skip(output_path, ttl_seconds=ttl_seconds, force=args.force):
        age_seconds = int(time.time() - output_path.stat().st_mtime)
        print(
            f"Prompt cache is fresh: {output_path} "
            f"(age={age_seconds}s, ttl={ttl_seconds}s)"
        )
        return

    payload = fetch_langfuse_prompts(prompt_config=prompt_config, label=label)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_path, payload)
    print(f"Synced Langfuse prompts to {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull text prompts from Langfuse into the local prompt cache."
    )
    parser.add_argument("--label", help="Langfuse label to pull, e.g. production")
    parser.add_argument(
        "--config-dir",
        help="Config directory containing llm/prompts.yaml. Defaults to CONFIG_DIR/configs.",
    )
    parser.add_argument(
        "--output",
        help="Cache file to write. Defaults to source.cache_path in prompts.yaml.",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        help="Skip pull when output file is newer than this many seconds.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch even when the local cache is still fresh.",
    )
    return parser.parse_args()


def should_skip(path: Path, *, ttl_seconds: int, force: bool) -> bool:
    if force or ttl_seconds <= 0 or not path.exists():
        return False
    return time.time() - path.stat().st_mtime < ttl_seconds


def fetch_langfuse_prompts(
    *,
    prompt_config: PromptConfig,
    label: str,
) -> dict[str, Any]:
    if not prompt_config.langfuse_templates:
        raise RuntimeError("No Langfuse prompt mappings configured in prompts.yaml")

    client = get_client()
    templates: dict[str, dict[str, str]] = {}
    langfuse_templates: dict[str, dict[str, Any]] = {}

    for template_name, ref in prompt_config.langfuse_templates.items():
        if ref.type != "text":
            raise RuntimeError(
                f"Only text prompts are supported for YAML cache sync: {template_name}"
            )

        prompt = client.get_prompt(
            ref.name,
            label=label,
            type="text",
            cache_ttl_seconds=0,
        )
        content = getattr(prompt, "prompt", None)
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"Langfuse prompt is empty or not text: {ref.name}")

        templates[template_name] = {"content": content}
        langfuse_templates[template_name] = {
            "name": ref.name,
            "type": ref.type,
            "version": getattr(prompt, "version", None),
        }

    return {
        "version": prompt_config.version,
        "source": {
            "provider": "langfuse_cache",
            "label": label,
            "ttl_seconds": prompt_config.source.ttl_seconds,
            "cache_path": prompt_config.source.cache_path,
            "fallback": prompt_config.source.fallback,
            "synced_at": datetime.now(UTC).isoformat(),
        },
        "langfuse": {"templates": langfuse_templates},
        "defaults": {"variables": prompt_config.default_variables},
        "templates": templates,
    }


def atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            payload,
            f,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )
    temp_path.replace(path)


def resolve_path(path: str | Path) -> Path:
    resolved = Path(path)
    if resolved.is_absolute():
        return resolved
    return REPO_ROOT / resolved


if __name__ == "__main__":
    main()
