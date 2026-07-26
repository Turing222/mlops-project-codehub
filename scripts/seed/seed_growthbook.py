"""Seed GrowthBook feature flags from code definitions.

职责：将代码中的 flag 定义同步到 GrowthBook 实例，确保代码与面板一致。
边界：只创建不存在的 flag；--force 时同步脚本生成的环境默认规则并保留人工规则。
失败处理：API 请求失败时逐个报错并继续，不中断整个批次。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.feature_flag_service import (  # noqa: E402
    _AI_SYSTEM_FLAG_DEFAULTS,
)

# ---------------------------------------------------------------------------
# Flag definitions — single source of truth from code
# ---------------------------------------------------------------------------

_SYSTEM_FLAGS: dict[str, bool] = {
    "enable-public-registration": True,
    "enable-closed-beta-login": False,
    "enable-password-login": False,
}

_USER_FLAGS: dict[str, bool] = {
    "enable-pixel-avatar": True,
    # enable-credits and enable-agent-trace have dynamic defaults
    # (bool(user.is_superuser)); we seed them as False here and let
    # GrowthBook rules / code fallback handle the real logic.
    "enable-credits": False,
    "enable-agent-trace": False,
}

ALL_FLAGS: dict[str, bool] = {
    **_SYSTEM_FLAGS,
    **_AI_SYSTEM_FLAG_DEFAULTS,
    **_USER_FLAGS,
}

FLAG_DESCRIPTIONS: dict[str, str] = {
    # system
    "enable-public-registration": "Allow anyone to register a new account.",
    "enable-closed-beta-login": "Restrict login to beta whitelist users.",
    "enable-password-login": "Show username/password login on the auth modal.",
    # AI
    "enable-external-context": "Enable external context retrieval (Tavily) during RAG.",
    "enable-rag-rerank": "Enable reranking step in RAG pipeline.",
    "enable-rag-planner": "Enable RAG query planner before retrieval.",
    "enable-rag-planner-routing": "Enable planner-driven routing/refusal decisions.",
    "enable-rag-refusal": "Enable refusal when RAG evidence is insufficient.",
    "enable-llm-model-routing": "Enable multi-model routing based on query confidence.",
    # user
    "enable-pixel-avatar": "Enable pixel avatar feature for users.",
    "enable-credits": "Enable credits system (dynamic default: is_superuser).",
    "enable-agent-trace": "Enable agent trace visibility (dynamic default: is_superuser).",
}

FLAG_TAGS: dict[str, list[str]] = {
    "enable-public-registration": ["auth"],
    "enable-closed-beta-login": ["auth"],
    "enable-password-login": ["auth"],
    "enable-external-context": ["ai", "rag"],
    "enable-rag-rerank": ["ai", "rag"],
    "enable-rag-planner": ["ai", "rag"],
    "enable-rag-planner-routing": ["ai", "rag"],
    "enable-rag-refusal": ["ai", "rag"],
    "enable-llm-model-routing": ["ai", "llm"],
    "enable-pixel-avatar": ["user"],
    "enable-credits": ["user", "billing"],
    "enable-agent-trace": ["user", "observability"],
}

# ---------------------------------------------------------------------------
# YAML environment overrides
# ---------------------------------------------------------------------------

DEFAULT_FLAGS_YAML = PROJECT_ROOT / "configs" / "growthbook" / "flags.yaml"


def _load_env_overrides(path: Path | None) -> dict[str, dict[str, bool]]:
    """Load per-environment flag overrides from YAML.

    Returns: {"local": {"enable-rag-rerank": True}, ...}
    """
    if path is None:
        path = DEFAULT_FLAGS_YAML
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("environments", {})


def _resolve_default_value(
    flag_id: str,
    code_default: bool,
    env_overrides: dict[str, dict[str, bool]],
) -> dict[str, bool]:
    """Resolve defaultValue per environment.

    env_overrides structure: {"local": {"enable-rag-rerank": True}, ...}
    If an override exists for an environment, use it; otherwise use the code default.
    Returns: {"local": False, "prod": True, ...}
    """
    result: dict[str, bool] = {}
    for env_name, env_flags in env_overrides.items():
        override = env_flags.get(flag_id)
        result[env_name] = override if override is not None else code_default
    return result


# ---------------------------------------------------------------------------
# GrowthBook API client
# ---------------------------------------------------------------------------

API_TIMEOUT = 10.0
GENERATED_RULE_ID_PREFIX = "env-override-"


def _build_flag_payload(
    flag_id: str,
    code_default: bool,
    env_overrides: dict[str, dict[str, bool]],
    project_id: str,
    owner: str,
    environments: list[str],
) -> dict:
    """Build the POST /v2/features request body."""
    env_defaults = _resolve_default_value(flag_id, code_default, env_overrides)

    env_enabled: dict[str, dict] = {}
    for env_name in environments:
        env_enabled[env_name] = {"enabled": True}

    for env_name, env_default in env_defaults.items():
        if env_default != code_default:
            env_enabled.setdefault(env_name, {"enabled": True}).setdefault(
                "rules", []
            ).append(
                {
                    "description": f"Override for {env_name}",
                    "condition": json.dumps({"env": env_name}),
                    "id": f"env-override-{env_name}",
                    "enabled": True,
                    "type": "force",
                    "value": str(env_default).lower(),
                }
            )

    payload = {
        "id": flag_id,
        "owner": owner,
        "project": project_id,
        "valueType": "boolean",
        "defaultValue": str(code_default).lower(),
    }
    if FLAG_DESCRIPTIONS.get(flag_id):
        payload["description"] = FLAG_DESCRIPTIONS[flag_id]
    if FLAG_TAGS.get(flag_id):
        payload["tags"] = FLAG_TAGS[flag_id]
    if env_enabled:
        payload["environments"] = env_enabled
    return payload


def _merge_generated_rules(
    existing_rules: list[dict],
    generated_rules: list[dict],
) -> list[dict]:
    """Replace generated env override rules while preserving manual rules."""
    manual_rules = [
        rule
        for rule in existing_rules
        if not str(rule.get("id", "")).startswith(GENERATED_RULE_ID_PREFIX)
    ]
    return [*manual_rules, *generated_rules]


def _merge_generated_environment_rules(
    existing_environments: dict,
    generated_environments: dict,
    target_environments: list[str],
) -> dict:
    """Replace generated rules per environment while preserving manual settings."""
    merged_environments = {
        env_name: dict(env_settings)
        for env_name, env_settings in existing_environments.items()
        if isinstance(env_settings, dict)
    }
    for env_name in target_environments:
        existing_env = merged_environments.get(env_name, {})
        generated_env = generated_environments.get(env_name, {})
        existing_rules = existing_env.get("rules", [])
        if not isinstance(existing_rules, list):
            existing_rules = []
        generated_rules = generated_env.get("rules", [])
        if not isinstance(generated_rules, list):
            generated_rules = []

        next_env = {**existing_env, **generated_env, "enabled": True}
        next_rules = _merge_generated_rules(existing_rules, generated_rules)
        if next_rules:
            next_env["rules"] = next_rules
        else:
            next_env.pop("rules", None)
        merged_environments[env_name] = next_env
    return merged_environments


def _sync_flags(
    *,
    api_base: str,
    api_key: str,
    project_id: str,
    owner: str,
    environments: list[str],
    env_overrides: dict[str, dict[str, bool]],
    force: bool,
    dry_run: bool,
) -> int:
    """Sync all flags to GrowthBook. Returns exit code."""
    client = httpx.Client(
        base_url=api_base,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=API_TIMEOUT,
    )

    created = 0
    skipped = 0
    updated = 0
    failed = 0

    try:
        # Pre-fetch existing flag IDs to avoid repeated list queries
        existing_features: dict[str, dict] = {}
        list_resp = client.get("/api/v2/features")
        if list_resp.status_code == 200:
            for f in list_resp.json().get("features", []):
                existing_features[f.get("id")] = f

        for flag_id, code_default in ALL_FLAGS.items():
            payload = _build_flag_payload(
                flag_id, code_default, env_overrides, project_id, owner, environments
            )

            if dry_run:
                print(f"[DRY-RUN] Would create: {flag_id} (default={code_default})")
                for env_name, env_payload in payload.get("environments", {}).items():
                    for rule in env_payload.get("rules", []):
                        print(f"           {env_name}: {rule['id']} -> {rule['value']}")
                created += 1
                continue

            if flag_id in existing_features:
                if force:
                    existing_feature = existing_features[flag_id]
                    existing_environments = existing_feature.get("environments", {})
                    if not isinstance(existing_environments, dict):
                        existing_environments = {}
                    merged_environments = _merge_generated_environment_rules(
                        existing_environments,
                        payload.get("environments", {}),
                        environments,
                    )
                    update_payload = {
                        "defaultValue": str(code_default).lower(),
                        "environments": merged_environments,
                    }
                    resp = client.post(
                        f"/api/v2/features/{flag_id}",
                        json=update_payload,
                    )
                    if resp.status_code in (200, 201):
                        print(f"[UPDATED] {flag_id} (defaults and env rules)")
                        for env_name, env_payload in payload.get(
                            "environments", {}
                        ).items():
                            for rule in env_payload.get("rules", []):
                                print(
                                    f"           {env_name}: {rule['id']} -> "
                                    f"{rule['value']}"
                                )
                        updated += 1
                    else:
                        print(f"[FAILED]  {flag_id}: {resp.status_code}")
                        try:
                            err_body = resp.json()
                            print(
                                f"           detail: "
                                f"{json.dumps(err_body, ensure_ascii=False)[:500]}"
                            )
                        except Exception:
                            print(f"           body: {resp.text[:500]}")
                        failed += 1
                else:
                    print(
                        f"[SKIPPED] {flag_id} (already exists, use --force to update)"
                    )
                    skipped += 1
                continue

            # Flag does not exist — create it
            resp = client.post("/api/v2/features", json=payload)
            if resp.status_code in (200, 201):
                print(f"[CREATED] {flag_id} (default={code_default})")
                for env_name, env_payload in payload.get("environments", {}).items():
                    for rule in env_payload.get("rules", []):
                        print(f"           {env_name}: {rule['id']} -> {rule['value']}")
                created += 1
            else:
                print(f"[FAILED]  {flag_id}: {resp.status_code}")
                try:
                    err_body = resp.json()
                    print(
                        f"           detail: "
                        f"{json.dumps(err_body, ensure_ascii=False)[:500]}"
                    )
                except Exception:
                    print(f"           body: {resp.text[:500]}")
                failed += 1
    finally:
        client.close()

    mode = "dry_run" if dry_run else "synced"
    print(f"\n--- {mode} ---")
    print(f"created={created}  skipped={skipped}  updated={updated}  failed={failed}")
    print(f"total={len(ALL_FLAGS)}")

    return 1 if failed > 0 else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed feature flags from code definitions into GrowthBook.",
    )
    parser.add_argument(
        "--api-base",
        default="https://api.growthbook.io",
        help="GrowthBook API base URL (default: https://api.growthbook.io).",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="GrowthBook API Secret Key (Bearer token).",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="GrowthBook project ID (e.g. prj_xxx).",
    )
    parser.add_argument(
        "--owner",
        default="devops@dewflow.com",
        help="Owner email for created flags.",
    )
    parser.add_argument(
        "--environments",
        default="local,smoke,prod",
        help="Comma-separated environment names (default: local,smoke,prod).",
    )
    parser.add_argument(
        "--env-overrides",
        default=None,
        help="Path to flags.yaml with per-environment overrides "
        "(default: configs/growthbook/flags.yaml).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Update defaultValue of existing flags (preserves rules).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making API calls.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    environments = [e.strip() for e in args.environments.split(",") if e.strip()]
    env_overrides = _load_env_overrides(
        Path(args.env_overrides) if args.env_overrides else None,
    )

    return _sync_flags(
        api_base=args.api_base,
        api_key=args.api_key,
        project_id=args.project,
        owner=args.owner,
        environments=environments,
        env_overrides=env_overrides,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
