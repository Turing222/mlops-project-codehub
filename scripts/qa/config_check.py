#!/usr/bin/env python3
"""Validate application config and environment for a given deployment context.

Checks:
  1. Settings instantiation (pydantic validation)
  2. Referenced *_FILE secrets exist and are non-empty
  3. YAML config files are valid and parseable
  4. Context-specific requirements (auth keys for web, provider keys for worker)

Usage:
  uv run python scripts/qa/config_check.py              # all contexts
  uv run python scripts/qa/config_check.py --context web
  uv run python scripts/qa/config_check.py --context worker

Exit 1 on any violation, 0 if clean.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config.loader import (  # noqa: E402
    ConfigurationError,
    get_config_dir,
    load_yaml_config,
)
from backend.core.secret_env import SECRET_ENV_NAMES  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════
# Rule framework
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Context:
    name: str
    desc: str
    settings_factory: Callable[[], object] | None = None
    extra_checks: list[Callable[[], CheckResult]] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
# Check helpers
# ═══════════════════════════════════════════════════════════════════════


def _check_secret_files() -> CheckResult:
    """Verify referenced Docker secret *_FILE paths exist and are non-empty."""
    missing: list[str] = []
    empty: list[str] = []

    for name in sorted(SECRET_ENV_NAMES):
        env_name = f"{name}_FILE"
        file_path = os.environ.get(env_name)
        if not file_path:
            continue
        path = Path(file_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            missing.append(f"{env_name}={file_path}")
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            missing.append(f"{env_name}={file_path} (unreadable)")
            continue
        if not content:
            empty.append(f"{env_name}={file_path}")

    parts: list[str] = []
    if missing:
        parts.append(f"Missing: {', '.join(missing)}")
    if empty:
        parts.append(f"Empty: {', '.join(empty)}")

    return CheckResult(
        name="Secret file references",
        ok=not (missing or empty),
        detail="; ".join(parts)
        if parts
        else "All referenced secret files present and non-empty",
    )


def _check_yaml_app_config() -> CheckResult:
    """Validate app YAML configs are parseable and are mappings.

    Note: The app/ directory is considered required for the application to run.
    If it is missing, this check will fail.
    """
    try:
        config_dir = get_config_dir()
    except Exception:
        return CheckResult(
            name="YAML app config", ok=False, detail="Cannot resolve CONFIG_DIR"
        )

    app_dir = config_dir / "app"
    if not app_dir.is_dir():
        return CheckResult(
            name="YAML app config",
            ok=False,
            detail=f"App config directory not found: {app_dir}",
        )

    errors: list[str] = []
    for yaml_file in sorted(app_dir.glob("*.yaml")):
        try:
            load_yaml_config(f"app/{yaml_file.name}", config_dir=config_dir)
        except ConfigurationError as exc:
            errors.append(str(exc))

    return CheckResult(
        name="YAML app config",
        ok=not errors,
        detail="; ".join(errors)
        if errors
        else f"All YAML configs valid ({config_dir / 'app'})",
    )


def _check_yaml_llm_config() -> CheckResult:
    """Validate LLM provider YAML configs are parseable.

    Note: The llm/ directory is optional. If missing, default LLM settings are used.
    """
    try:
        config_dir = get_config_dir()
    except Exception:
        return CheckResult(
            name="YAML LLM config", ok=False, detail="Cannot resolve CONFIG_DIR"
        )

    llm_dir = config_dir / "llm"
    if not llm_dir.is_dir():
        return CheckResult(
            name="YAML LLM config",
            ok=True,
            detail=f"No LLM config directory ({llm_dir}), using defaults",
        )

    errors: list[str] = []
    for yaml_file in sorted(llm_dir.glob("*.yaml")):
        try:
            load_yaml_config(f"llm/{yaml_file.name}", config_dir=config_dir)
        except ConfigurationError as exc:
            errors.append(str(exc))

    return CheckResult(
        name="YAML LLM config",
        ok=not errors,
        detail="; ".join(errors)
        if errors
        else f"All LLM YAML configs valid ({llm_dir})",
    )


def _check_yaml_access_config() -> CheckResult:
    """Validate access control YAML configs are parseable.

    Note: The access/ directory is optional. If missing, default access settings are used.
    """
    try:
        config_dir = get_config_dir()
    except Exception:
        return CheckResult(
            name="YAML access config", ok=False, detail="Cannot resolve CONFIG_DIR"
        )

    access_dir = config_dir / "access"
    if not access_dir.is_dir():
        return CheckResult(
            name="YAML access config",
            ok=True,
            detail=f"No access config directory ({access_dir}), using defaults",
        )

    errors: list[str] = []
    for yaml_file in sorted(access_dir.glob("*.yaml")):
        try:
            load_yaml_config(f"access/{yaml_file.name}", config_dir=config_dir)
        except ConfigurationError as exc:
            errors.append(str(exc))

    return CheckResult(
        name="YAML access config",
        ok=not errors,
        detail="; ".join(errors)
        if errors
        else f"All access YAML configs valid ({access_dir})",
    )


# ═══════════════════════════════════════════════════════════════════════
# Context-specific settings validation
# ═══════════════════════════════════════════════════════════════════════


def _validate_settings(factory: Callable[[], object], label: str) -> CheckResult:
    try:
        factory()
    except Exception as exc:
        return CheckResult(
            name=label, ok=False, detail=f"Failed to load settings: {exc}"
        )
    return CheckResult(name=label, ok=True, detail="Settings loaded successfully")


def _check_web_requirements() -> CheckResult:
    """Web-specific: SECRET_KEY must be set and non-trivial in non-local env."""
    from backend.config.web_settings import (
        DEFAULT_SECRET_KEY,
        MIN_NON_LOCAL_SECRET_KEY_LENGTH,
        get_web_settings,
        is_local_app_env,
    )

    try:
        settings = get_web_settings()
    except Exception as exc:
        return CheckResult(name="Web requirements", ok=False, detail=str(exc))

    errors: list[str] = []
    warnings: list[str] = []
    app_env = settings.APP_ENV

    if not is_local_app_env(app_env):
        secret_key = settings.SECRET_KEY.strip()
        if not secret_key:
            errors.append("SECRET_KEY must be set for non-local web environments")
        elif secret_key == DEFAULT_SECRET_KEY:
            errors.append("SECRET_KEY must not use the local default outside local")
        elif len(secret_key) < MIN_NON_LOCAL_SECRET_KEY_LENGTH:
            errors.append(
                f"SECRET_KEY is short ({len(secret_key)} chars); "
                f"use >={MIN_NON_LOCAL_SECRET_KEY_LENGTH} chars for non-local "
                "environments"
            )
        if settings.ACCESS_TOKEN_EXPIRE_MINUTES > 60:
            warnings.append(
                f"ACCESS_TOKEN_EXPIRE_MINUTES={settings.ACCESS_TOKEN_EXPIRE_MINUTES} is high for {app_env}"
            )

    if errors:
        return CheckResult(
            name="Web requirements",
            ok=False,
            detail="; ".join(errors),
        )
    if warnings:
        return CheckResult(
            name="Web requirements",
            ok=True,
            detail="Warnings: " + "; ".join(warnings),
        )
    return CheckResult(name="Web requirements", ok=True, detail="Web requirements met")


def _check_worker_requirements() -> CheckResult:
    """Worker-specific: at least one LLM provider should be configured or mock is fine."""
    from backend.config.ai_settings import get_ai_settings

    try:
        settings = get_ai_settings()
    except Exception as exc:
        return CheckResult(name="Worker requirements", ok=False, detail=str(exc))

    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "mock":
        return CheckResult(
            name="Worker requirements",
            ok=True,
            detail="LLM_PROVIDER=mock (no external API keys needed)",
        )

    api_key_map = {
        "openai": ("OPENAI_API_KEY", settings.OPENAI_API_KEY),
        "google": ("GOOGLE_API_KEY", settings.GOOGLE_API_KEY),
        "gemini": ("GEMINI_API_KEY", settings.GEMINI_API_KEY),
        "deepseek": ("DEEPSEEK_API_KEY", settings.DEEPSEEK_API_KEY),
        # Note: Local providers like 'ollama' do not require API keys and
        # will safely pass through the 'no specific key check' branch below.
    }

    key_name, key_value = api_key_map.get(provider, (None, None))
    if key_name is None:
        return CheckResult(
            name="Worker requirements",
            ok=True,
            detail=f"LLM_PROVIDER={provider} (no specific key check implemented)",
        )

    if not key_value:
        return CheckResult(
            name="Worker requirements",
            ok=False,
            detail=f"LLM_PROVIDER={provider} but {key_name} is not set",
        )

    return CheckResult(
        name="Worker requirements",
        ok=True,
        detail=f"LLM_PROVIDER={provider} configured",
    )


# ═══════════════════════════════════════════════════════════════════════
# Context definitions
# ═══════════════════════════════════════════════════════════════════════

CONTEXTS: dict[str, Context] = {
    "web": Context(
        name="web",
        desc="Web/HTTP API",
        settings_factory=lambda: _lazy_import(
            "backend.config.web_settings", "get_web_settings"
        )(),
        extra_checks=[_check_web_requirements],
    ),
    "worker": Context(
        name="worker",
        desc="Worker + AI",
        settings_factory=lambda: _lazy_import(
            "backend.config.ai_settings", "get_ai_settings"
        )(),
        extra_checks=[_check_worker_requirements],
    ),
    "all": Context(
        name="all",
        desc="Full application",
        settings_factory=lambda: _lazy_import(
            "backend.config.settings", "get_settings"
        )(),
        extra_checks=[_check_web_requirements, _check_worker_requirements],
    ),
}


def _lazy_import(module: str, attr: str) -> Callable[..., object]:
    import importlib

    return getattr(importlib.import_module(module), attr)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════


def run_checks(context_name: str) -> int:
    context = CONTEXTS.get(context_name)
    if context is None:
        print(f"Unknown context: {context_name}")
        print(f"Valid contexts: {', '.join(CONTEXTS)}")
        return 2

    print(f"Context: {context.desc} ({context.name})")
    print(f"APP_ENV={os.getenv('APP_ENV', 'local')}")
    print(f"CONFIG_DIR={os.getenv('CONFIG_DIR', get_config_dir())}")
    print()

    results: list[CheckResult] = []

    # 1. Settings validation
    if context.settings_factory:
        results.append(_validate_settings(context.settings_factory, "Settings init"))

    # 2. Secret file check
    results.append(_check_secret_files())

    # 3. YAML config checks
    results.append(_check_yaml_app_config())
    results.append(_check_yaml_llm_config())
    results.append(_check_yaml_access_config())

    # 4. Context-specific checks
    for check_fn in context.extra_checks:
        results.append(check_fn())

    # Print results
    failed = 0
    for r in results:
        status = "OK" if r.ok else "FAIL"
        print(f"  [{status}] {r.name}")
        if r.detail:
            print(f"         {r.detail}")
        if not r.ok:
            failed += 1

    print()
    if failed:
        print(f"{failed} check(s) failed.")
        return 1
    print(f"All {len(results)} checks passed for context '{context.name}'.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate application config and environment"
    )
    parser.add_argument(
        "--context",
        choices=list(CONTEXTS),
        default="all",
        help="Deployment context to validate against (default: all)",
    )
    args = parser.parse_args()
    return run_checks(args.context)


if __name__ == "__main__":
    raise SystemExit(main())
